"""WP2: messaging shadow bridge — flag-gated, fail-safe mirror of inbound/outbound
into the domain ledgers. In-memory SQLite; WP0 guard active.

Proves: flag OFF = zero writes; flag ON records CanonicalMessage + Inbox/Outbox
(but NO Request/Assignment); repeat inbound = no duplicates; a failure never raises
to the caller and logs no PII (phone/text)."""
import asyncio
import contextlib
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import flags
from app.domain import messaging_shadow
from app.domain.messaging import MessageService
from app.domain.models import (
    Assignment, CanonicalMessage, Contact, Dialog, InboxEvent, OutboxJob, Request,
)

PHONE = "0700123456"        # normalizes to 996700123456
BODY = "секретный текст клиента"


@contextlib.contextmanager
def capture_logs():
    lg = logging.getLogger("domain.messaging_shadow")
    prev = (lg.disabled, lg.level, lg.propagate)
    lg.disabled = False
    lg.setLevel(logging.WARNING)
    msgs: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            msgs.append(record.getMessage())

    handler = _H()
    lg.addHandler(handler)
    try:
        yield msgs
    finally:
        lg.removeHandler(handler)
        lg.disabled, lg.level, lg.propagate = prev


async def _prepare(engine):
    from app.domain.models import DomainBase
    async with engine.begin() as conn:
        await conn.run_sync(DomainBase.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _count(sm, model) -> int:
    async with sm() as s:
        return await s.scalar(select(func.count()).select_from(model))


def _run(body):
    async def _main():
        flags.reset()
        engine = create_async_engine("sqlite+aiosqlite://",
                                     connect_args={"check_same_thread": False},
                                     poolclass=StaticPool)
        sm = await _prepare(engine)
        try:
            await body(sm)
        finally:
            flags.reset()
            await engine.dispose()
    asyncio.run(_main())


def test_flag_off_writes_nothing():
    async def body(sm):
        await messaging_shadow.mirror_inbound_message(
            phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
            body=BODY, provider_msg_id="wamid-1", external_event_id="wamid-1",
            sessionmaker=sm)
        assert await _count(sm, Contact) == 0
        assert await _count(sm, CanonicalMessage) == 0
        assert await _count(sm, InboxEvent) == 0
    _run(body)


def test_flag_on_inbound_records_history_and_inbox_not_request_or_assignment():
    async def body(sm):
        await flags.set_flag(messaging_shadow.FLAG, True)
        await messaging_shadow.mirror_inbound_message(
            phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
            body=BODY, provider_msg_id="wamid-1", external_event_id="wamid-1",
            sessionmaker=sm)
        assert await _count(sm, Contact) == 1
        assert await _count(sm, Dialog) == 1
        assert await _count(sm, CanonicalMessage) == 1
        assert await _count(sm, InboxEvent) == 1
        # Messaging shadow does not open commercial requests or assign managers.
        assert await _count(sm, Request) == 0
        assert await _count(sm, Assignment) == 0
    _run(body)


def test_flag_on_outbound_records_history_and_outbox():
    async def body(sm):
        await flags.set_flag(messaging_shadow.FLAG, True)
        await messaging_shadow.mirror_outbound_message(
            phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
            body="ответ бота", idempotency_key="out-1", provider_msg_id="out-1",
            status="sent", sessionmaker=sm)
        assert await _count(sm, CanonicalMessage) == 1
        assert await _count(sm, OutboxJob) == 1
    _run(body)


def test_repeat_inbound_does_not_duplicate():
    async def body(sm):
        await flags.set_flag(messaging_shadow.FLAG, True)
        for _ in range(3):
            await messaging_shadow.mirror_inbound_message(
                phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
                body=BODY, provider_msg_id="wamid-1", external_event_id="wamid-1",
                sessionmaker=sm)
        assert await _count(sm, Contact) == 1
        assert await _count(sm, CanonicalMessage) == 1
        assert await _count(sm, InboxEvent) == 1
    _run(body)


def test_failure_is_swallowed_and_logs_no_pii(monkeypatch):
    async def body(sm):
        await flags.set_flag(messaging_shadow.FLAG, True)

        async def boom(*a, **k):
            raise RuntimeError("db exploded")
        monkeypatch.setattr(MessageService, "record_inbound", boom)

        with capture_logs() as msgs:
            await messaging_shadow.mirror_inbound_message(
                phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
                body=BODY, provider_msg_id="wamid-1", external_event_id="wamid-1",
                sessionmaker=sm)   # must NOT raise
        text = "\n".join(msgs)
        assert "RuntimeError" in text
        for pii in (PHONE, "996700123456", "700123456", BODY, "db exploded"):
            assert pii not in text
    _run(body)
