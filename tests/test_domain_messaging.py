"""WP2: messaging service — unified history + inbox/outbox ledgers with DB-level
dedup. In-memory SQLite; WP0 network guard active."""
import asyncio

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.messaging import MessageService
from app.domain.models import (
    CanonicalMessage, Contact, Dialog, InboxEvent, OutboxJob,
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


async def _seed_dialog(session) -> tuple[int, int]:
    c = Contact()
    session.add(c)
    await session.flush()
    d = Dialog(contact_id=c.id, channel="whatsapp", bot_id="getvisa",
               channel_key="996700123456")
    session.add(d)
    await session.flush()
    return c.id, d.id


# --- inbound ------------------------------------------------------------------

def test_record_inbound_creates_history_and_inbox_and_dedups():
    async def scenario(sm):
        async with sm() as s:
            cid, did = await _seed_dialog(s)
            m1 = await MessageService.record_inbound(
                s, dialog_id=did, contact_id=cid, channel="whatsapp", body="привет",
                provider="wappi", provider_msg_id="wamid-1", external_event_id="wamid-1")
            # Replayed webhook (same external_event_id) → same canonical, no duplicate.
            m2 = await MessageService.record_inbound(
                s, dialog_id=did, contact_id=cid, channel="whatsapp", body="привет",
                provider="wappi", provider_msg_id="wamid-1", external_event_id="wamid-1")
            await s.commit()
            assert m1.id == m2.id
            assert await _count(s, CanonicalMessage) == 1
            assert await _count(s, InboxEvent) == 1
    run_with_db(scenario)


# --- outbound -----------------------------------------------------------------

def test_record_outbound_creates_history_and_outbox_and_dedups():
    async def scenario(sm):
        async with sm() as s:
            cid, did = await _seed_dialog(s)
            m1 = await MessageService.record_outbound(
                s, dialog_id=did, contact_id=cid, channel="whatsapp", body="ответ",
                idempotency_key="idem-1", provider_msg_id="out-1", status="sent")
            m2 = await MessageService.record_outbound(
                s, dialog_id=did, contact_id=cid, channel="whatsapp", body="ответ",
                idempotency_key="idem-1", provider_msg_id="out-1", status="sent")
            await s.commit()
            assert m1.id == m2.id
            assert await _count(s, CanonicalMessage) == 1
            assert await _count(s, OutboxJob) == 1
    run_with_db(scenario)


def test_history_is_ordered():
    async def scenario(sm):
        async with sm() as s:
            cid, did = await _seed_dialog(s)
            await MessageService.record_inbound(
                s, dialog_id=did, contact_id=cid, channel="whatsapp", body="1",
                provider="wappi", external_event_id="e1")
            await MessageService.record_outbound(
                s, dialog_id=did, contact_id=cid, channel="whatsapp", body="2",
                idempotency_key="o1")
            await s.commit()
            hist = await MessageService.history(s, did)
            assert [m.body for m in hist] == ["1", "2"]
            assert [m.direction for m in hist] == ["inbound", "outbound"]
    run_with_db(scenario)


def test_empty_dedup_key_does_not_dedup():
    async def scenario(sm):
        async with sm() as s:
            cid, did = await _seed_dialog(s)
            # No external_event_id / provider_msg_id → dedup_key empty → no dedup.
            await MessageService.record_inbound(
                s, dialog_id=did, contact_id=cid, channel="whatsapp", body="a")
            await MessageService.record_inbound(
                s, dialog_id=did, contact_id=cid, channel="whatsapp", body="a")
            await s.commit()
            assert await _count(s, CanonicalMessage) == 2   # both kept
            assert await _count(s, InboxEvent) == 0         # no event id → no ledger row
    run_with_db(scenario)


# --- DB-level dedup (direct ORM proofs) ---------------------------------------

def test_db_rejects_duplicate_canonical_dedup_key():
    async def scenario(sm):
        async with sm() as s:
            cid, did = await _seed_dialog(s)
            s.add(CanonicalMessage(dialog_id=did, contact_id=cid, direction="inbound",
                                   sender_role="client", channel="whatsapp", body="x",
                                   provider_msg_id="p", dedup_key="k1"))
            s.add(CanonicalMessage(dialog_id=did, contact_id=cid, direction="inbound",
                                   sender_role="client", channel="whatsapp", body="y",
                                   provider_msg_id="p2", dedup_key="k1"))
            with pytest.raises(IntegrityError):
                await s.flush()
    run_with_db(scenario)


def test_db_rejects_duplicate_inbox_event_same_scope():
    async def scenario(sm):
        async with sm() as s:
            await _seed_dialog(s)
            s.add(InboxEvent(provider="telegram", account_scope="botA",
                             external_event_id="E1", status="received"))
            s.add(InboxEvent(provider="telegram", account_scope="botA",
                             external_event_id="E1", status="received"))
            with pytest.raises(IntegrityError):
                await s.flush()
    run_with_db(scenario)


def test_M1_same_external_id_different_account_scope_does_not_collide():
    """Telegram message ids repeat across bots — different account_scope must NOT dedup."""
    async def scenario(sm):
        async with sm() as s:
            await _seed_dialog(s)
            s.add(InboxEvent(provider="telegram", account_scope="botA",
                             external_event_id="12345", status="received"))
            s.add(InboxEvent(provider="telegram", account_scope="botB",
                             external_event_id="12345", status="received"))
            await s.flush()      # must NOT raise
            assert await _count(s, InboxEvent) == 2
    run_with_db(scenario)


def test_db_rejects_duplicate_outbox_same_scope_and_key():
    async def scenario(sm):
        async with sm() as s:
            _, did = await _seed_dialog(s)
            s.add(OutboxJob(dialog_id=did, channel="whatsapp", provider="wappi",
                            account_scope="botA", destination_scope="996700111",
                            idempotency_key="I1", provider_msg_id="", status="pending"))
            s.add(OutboxJob(dialog_id=did, channel="whatsapp", provider="wappi",
                            account_scope="botA", destination_scope="996700111",
                            idempotency_key="I1", provider_msg_id="", status="pending"))
            with pytest.raises(IntegrityError):
                await s.flush()
    run_with_db(scenario)


def test_M2_same_idempotency_key_different_destination_or_account_allowed():
    async def scenario(sm):
        async with sm() as s:
            _, did = await _seed_dialog(s)
            # same key, different destination → allowed
            s.add(OutboxJob(dialog_id=did, channel="whatsapp", provider="wappi",
                            account_scope="botA", destination_scope="996700111",
                            idempotency_key="K1", provider_msg_id="", status="pending"))
            s.add(OutboxJob(dialog_id=did, channel="whatsapp", provider="wappi",
                            account_scope="botA", destination_scope="996700222",
                            idempotency_key="K1", provider_msg_id="", status="pending"))
            # same key, different account → allowed
            s.add(OutboxJob(dialog_id=did, channel="whatsapp", provider="wappi",
                            account_scope="botB", destination_scope="996700111",
                            idempotency_key="K1", provider_msg_id="", status="pending"))
            await s.flush()      # must NOT raise
            assert await _count(s, OutboxJob) == 3
    run_with_db(scenario)
