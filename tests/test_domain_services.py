"""WP1B: domain service layer — find-or-create, race handling, Dialog idempotency,
Request lifecycle, assignment invariants, external references. In-memory SQLite;
WP0 network guard stays active (no external network touched)."""
import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.models import (
    Assignment, Contact, ContactIdentity, Dialog, DomainError, Request,
)
from app.domain.services import (
    AssignmentService, ContactService, DialogService, ExternalRefService,
    RequestService,
)


def run_with_db(scenario):
    async def _main():
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            from app.domain.models import DomainBase
            await conn.run_sync(DomainBase.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await scenario(sm)
        finally:
            await engine.dispose()

    asyncio.run(_main())


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


# --- Contact find-or-create + normalization -----------------------------------

def test_find_or_create_is_idempotent_and_normalizes():
    async def scenario(sm):
        async with sm() as s:
            c1 = await ContactService.find_or_create_by_identity(s, "phone", "0700123456")
            # Different surface form of the SAME number → same Contact, no duplicate.
            c2 = await ContactService.find_or_create_by_identity(s, "phone", "+996700123456")
            await s.commit()
            assert c1.id == c2.id
            assert await _count(s, Contact) == 1
            assert await _count(s, ContactIdentity) == 1
            ident = await s.scalar(select(ContactIdentity))
            assert ident.normalized_value == "996700123456"
            assert ident.provider_scope == ""     # cross-bot: no scope
    run_with_db(scenario)


def test_find_or_create_recovers_from_lost_race_via_savepoint(monkeypatch):
    """Simulate a lost race: the initial lookup misses, the INSERT trips the unique
    index, the SAVEPOINT rolls back (no orphan Contact, session still usable), and we
    return the row the 'concurrent' writer created."""
    async def scenario(sm):
        async with sm() as s:
            # Pre-create the committed winner.
            winner = await ContactService.find_or_create_by_identity(s, "phone", "996700123456")
            await s.commit()

            real_find = ContactService._find      # underlying staticmethod function
            state = {"n": 0}

            async def flaky_find(session, itype, norm, scope):
                state["n"] += 1
                if state["n"] == 1:
                    return None            # pretend we didn't see the winner yet
                return await real_find(session, itype, norm, scope)

            monkeypatch.setattr(ContactService, "_find", staticmethod(flaky_find))

            got = await ContactService.find_or_create_by_identity(s, "phone", "996700123456")
            assert got.id == winner.id                 # returned the existing winner
            assert await _count(s, Contact) == 1       # no orphan / no duplicate
            assert await _count(s, ContactIdentity) == 1
            # Session survived the IntegrityError → still queryable.
            assert (await s.scalar(select(func.count()).select_from(Contact))) == 1
    run_with_db(scenario)


def test_empty_identity_rejected():
    async def scenario(sm):
        async with sm() as s:
            with pytest.raises(DomainError):
                await ContactService.find_or_create_by_identity(s, "phone", "   ")
    run_with_db(scenario)


# --- Request lifecycle ---------------------------------------------------------

def test_open_close_reopen_request_history():
    async def scenario(sm):
        async with sm() as s:
            c = await ContactService.find_or_create_by_identity(s, "phone", "996700111222")
            r1 = await RequestService.open(s, c.id, "visa")
            with pytest.raises(DomainError):                # one active per direction
                await RequestService.open(s, c.id, "visa")
            await RequestService.close(s, r1, status="won")
            assert r1.closed_at is not None and r1.status == "won"
            r2 = await RequestService.open(s, c.id, "visa")  # allowed after close
            await s.commit()
            assert r2.id != r1.id
            assert await _count(s, Request) == 2
            assert (await s.scalar(select(func.count()).select_from(Request)
                                   .where(Request.closed_at.is_(None)))) == 1
    run_with_db(scenario)


# --- Dialog idempotency (service + DB constraint) ------------------------------

def test_dialog_get_or_create_is_idempotent():
    async def scenario(sm):
        async with sm() as s:
            c = await ContactService.find_or_create_by_identity(s, "phone", "996700333444")
            d1 = await DialogService.get_or_create(
                s, c.id, channel="whatsapp", bot_id="getvisa", channel_key="996700333444")
            d2 = await DialogService.get_or_create(
                s, c.id, channel="whatsapp", bot_id="getvisa", channel_key="996700333444")
            await s.commit()
            assert d1.id == d2.id
            assert await _count(s, Dialog) == 1
    run_with_db(scenario)


def test_duplicate_dialog_rejected_by_db_constraint():
    """Direct ORM proof that (channel, bot_id, channel_key) is unique at the DB level."""
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            s.add(Dialog(contact_id=c.id, channel="whatsapp", bot_id="getvisa",
                         channel_key="996700555666"))
            s.add(Dialog(contact_id=c.id, channel="whatsapp", bot_id="getvisa",
                         channel_key="996700555666"))
            with pytest.raises(IntegrityError):
                await s.flush()
    run_with_db(scenario)


def test_dialog_links_existing_active_request_but_never_creates_one():
    async def scenario(sm):
        async with sm() as s:
            c = await ContactService.find_or_create_by_identity(s, "phone", "996700777888")
            active = await RequestService.open(s, c.id, "visa")
            d = await DialogService.get_or_create(
                s, c.id, channel="whatsapp", bot_id="getvisa", channel_key="996700777888",
                link_active_request_direction="visa")
            await s.commit()
            assert d.request_id == active.id           # linked to the existing request
            assert await _count(s, Request) == 1       # no NEW request created
    run_with_db(scenario)


def test_dialog_without_active_request_stays_unlinked():
    async def scenario(sm):
        async with sm() as s:
            c = await ContactService.find_or_create_by_identity(s, "phone", "996700999000")
            d = await DialogService.get_or_create(
                s, c.id, channel="whatsapp", bot_id="getvisa", channel_key="996700999000",
                link_active_request_direction="visa")
            await s.commit()
            assert d.request_id is None
            assert await _count(s, Request) == 0       # linking never opens a request
    run_with_db(scenario)


# --- Assignment invariants via service ----------------------------------------

def test_assignment_peer_takeover_and_emergency_and_history():
    async def scenario(sm):
        async with sm() as s:
            c = await ContactService.find_or_create_by_identity(s, "phone", "996700121212")
            a1 = await AssignmentService.assign(s, c.id, "visa", "medina", assigned_by="system")
            assert a1.revision == 1 and a1.active is True
            with pytest.raises(DomainError):                       # peer takeover blocked
                await AssignmentService.assign(s, c.id, "visa", "eliza", assigned_by="eliza")
            a2 = await AssignmentService.assign(s, c.id, "visa", "eliza",
                                                assigned_by="admin", reason="vacation",
                                                allow_emergency=True)
            await s.commit()
            assert a2.revision == 2 and a2.active is True
            assert await _count(s, Assignment) == 2                # history kept
            active = await AssignmentService.active_for(s, c.id, "visa")
            assert active.manager_id == "eliza"
    run_with_db(scenario)


# --- External references via service ------------------------------------------

def test_external_reference_link_and_conflict():
    async def scenario(sm):
        async with sm() as s:
            c = await ContactService.find_or_create_by_identity(s, "phone", "996700343434")
            r1 = await RequestService.open(s, c.id, "tours")
            await RequestService.close(s, r1)
            r2 = await RequestService.open(s, c.id, "tours")
            await ExternalRefService.link(s, "bitrix", "deal", "D-100", r1, "tours")
            with pytest.raises(DomainError):
                await ExternalRefService.link(s, "bitrix", "deal", "D-100", r2, "tours")
    run_with_db(scenario)
