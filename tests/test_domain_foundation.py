"""WP1A: domain foundation (Contact / ContactIdentity / Request / Dialog /
Assignment / ExternalReference). In-memory SQLite only — the WP0 network guard
stays active (these tests never touch external network)."""
import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.models import (
    Assignment, Contact, ContactIdentity, Dialog, DomainBase, DomainError,
    ExternalReference, Request, add_identity, close_request, link_external,
    open_request, reassign_manager,
)


def run_with_db(scenario):
    """One-shot shared in-memory SQLite (StaticPool), build the domain schema, run."""
    async def _main():
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            await conn.run_sync(DomainBase.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await scenario(sm)
        finally:
            await engine.dispose()

    asyncio.run(_main())


# --- Contact / identities ------------------------------------------------------

def test_contact_is_independent_of_bot_id_and_status():
    async def scenario(sm):
        async with sm() as s:
            c = Contact()
            s.add(c)
            await s.flush()
            assert c.id is not None
            # Contact carries no bot mode, funnel stage or assignment.
            for forbidden in ("bot_id", "funnel", "stage", "status", "assigned_to", "intercepted"):
                assert not hasattr(c, forbidden), f"Contact must not hold {forbidden}"
    run_with_db(scenario)


def test_multiple_identities_belong_to_one_contact():
    async def scenario(sm):
        async with sm() as s:
            c = Contact()
            s.add(c)
            await s.flush()
            await add_identity(s, c.id, "phone", "996700111222")
            await add_identity(s, c.id, "telegram", "tg-42")
            await s.commit()
        async with sm() as s:
            ids = (await s.scalars(select(ContactIdentity).where(ContactIdentity.contact_id == c.id))).all()
            assert {i.identity_type for i in ids} == {"phone", "telegram"}
    run_with_db(scenario)


def test_duplicate_normalized_identity_rejected():
    async def scenario(sm):
        async with sm() as s:
            c = Contact()
            s.add(c)
            await s.flush()
            await add_identity(s, c.id, "phone", "996700111222")
            with pytest.raises(DomainError):
                await add_identity(s, c.id, "phone", "996700111222")
    run_with_db(scenario)


# --- Request -------------------------------------------------------------------

def test_one_active_request_per_contact_direction_app_level():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            await open_request(s, c.id, "tours")
            with pytest.raises(DomainError):
                await open_request(s, c.id, "tours")
    run_with_db(scenario)


def test_one_active_request_per_contact_direction_db_constraint():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            s.add(Request(contact_id=c.id, direction="tours"))
            s.add(Request(contact_id=c.id, direction="tours"))  # two active → partial unique index
            with pytest.raises(IntegrityError):
                await s.flush()
    run_with_db(scenario)


def test_tour_and_visa_requests_may_coexist():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            t = await open_request(s, c.id, "tours")
            v = await open_request(s, c.id, "visa")
            assert t.closed_at is None and v.closed_at is None
            active = (await s.scalars(select(Request).where(
                Request.contact_id == c.id, Request.closed_at.is_(None)))).all()
            assert {r.direction for r in active} == {"tours", "visa"}
    run_with_db(scenario)


def test_closed_request_stays_in_history_and_new_one_can_open():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            first = await open_request(s, c.id, "tours")
            first_pk = first.id
            await close_request(s, first)
            assert first.closed_at is not None
            # A new request of the same direction is allowed after closing.
            second = await open_request(s, c.id, "tours")
            assert second.id != first_pk
            await s.commit()
        async with sm() as s:
            rows = (await s.scalars(select(Request).where(Request.contact_id == c.id))).all()
            assert len(rows) == 2  # history preserved (old + new)
            assert sum(1 for r in rows if r.closed_at is None) == 1  # exactly one active
    run_with_db(scenario)


# --- Dialog --------------------------------------------------------------------

def test_dialog_carries_no_business_status_and_one_contact_many_dialogs():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            d1 = Dialog(contact_id=c.id, channel="whatsapp", bot_id="frunze_tours")
            d2 = Dialog(contact_id=c.id, channel="telegram", bot_id="getvisa_tg")
            s.add_all([d1, d2]); await s.flush()
            for forbidden in ("status", "outcome", "funnel", "stage"):
                assert not hasattr(d1, forbidden), f"Dialog must not hold business {forbidden}"
            dialogs = (await s.scalars(select(Dialog).where(Dialog.contact_id == c.id))).all()
            assert {d.channel for d in dialogs} == {"whatsapp", "telegram"}
    run_with_db(scenario)


# --- Assignment ----------------------------------------------------------------

def test_new_request_may_stay_unassigned():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            await open_request(s, c.id, "visa")
            n = await s.scalar(select(Assignment).where(Assignment.contact_id == c.id))
            assert n is None  # no auto-assignment / no "first responder"
    run_with_db(scenario)


def test_one_active_assignment_and_history_and_revision():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            a1 = await reassign_manager(s, c.id, "visa", "medina", assigned_by="system")
            assert a1.revision == 1 and a1.active is True
            # Peer takeover is refused without emergency authorization.
            with pytest.raises(DomainError):
                await reassign_manager(s, c.id, "visa", "eliza", assigned_by="eliza")
            # Emergency (full-admin) reassignment succeeds and bumps revision.
            a2 = await reassign_manager(s, c.id, "visa", "eliza",
                                        assigned_by="admin", reason="vacation",
                                        allow_emergency=True)
            assert a2.revision == 2 and a2.active is True
            await s.commit()
        async with sm() as s:
            rows = (await s.scalars(select(Assignment).where(Assignment.contact_id == c.id))).all()
            assert len(rows) == 2  # history not deleted
            assert sum(1 for a in rows if a.active) == 1  # exactly one active
            old = next(a for a in rows if a.revision == 1)
            assert old.active is False and old.ended_at is not None
    run_with_db(scenario)


def test_two_active_assignments_blocked_by_db_constraint():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            s.add(Assignment(contact_id=c.id, direction="tours", manager_id="ademi", active=True))
            s.add(Assignment(contact_id=c.id, direction="tours", manager_id="sezim", active=True))
            with pytest.raises(IntegrityError):
                await s.flush()
    run_with_db(scenario)


# --- External references -------------------------------------------------------

def test_one_external_deal_cannot_link_to_two_requests():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            r1 = await open_request(s, c.id, "tours")
            await close_request(s, r1)
            r2 = await open_request(s, c.id, "tours")
            await link_external(s, "bitrix", "deal", "D-100", r1, "tours")
            with pytest.raises(DomainError):
                await link_external(s, "bitrix", "deal", "D-100", r2, "tours")
    run_with_db(scenario)


def test_external_reference_survives_and_is_queryable():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            r = await open_request(s, c.id, "visa")
            ref = await link_external(s, "bitrix", "lead", "L-7", r, "visa")
            await s.commit()
        async with sm() as s:
            got = await s.scalar(select(ExternalReference).where(
                ExternalReference.external_id == "L-7"))
            assert got is not None and got.request_ref == r.id and got.provider == "bitrix"
    run_with_db(scenario)
