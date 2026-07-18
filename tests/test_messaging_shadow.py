"""WP2: messaging shadow bridge — gated by BOTH domain_shadow_enabled AND
messaging_shadow_enabled (M6), fail-safe, PII-free. In-memory SQLite; WP0 guard."""
import asyncio
import contextlib
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import flags
from app.domain import messaging_shadow, shadow_bridge
from app.domain.messaging import MessageService
from app.domain.models import (
    Assignment, CanonicalMessage, Contact, Dialog, InboxEvent, OutboxJob, Request,
)
from app.domain.services import ContactService, RequestService

PHONE = "0700123456"        # normalizes to 996700123456
CANON = "996700123456"
BODY = "секретный текст клиента"
DOMAIN = "domain_shadow_enabled"
MSG = "messaging_shadow_enabled"


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


async def _inbound_both_paths(sm):
    """Drive BOTH the WP1B contact/dialog shadow and the WP2 messaging shadow."""
    await shadow_bridge.mirror_inbound(
        phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
        sessionmaker=sm)
    await messaging_shadow.mirror_inbound_message(
        phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
        body=BODY, provider_msg_id="wamid-1", external_event_id="wamid-1",
        sessionmaker=sm)


# --- M6: four flag combinations ------------------------------------------------

def test_combo_1_both_off_is_noop():
    async def body(sm):
        await _inbound_both_paths(sm)                       # both flags default OFF
        assert await _count(sm, Contact) == 0
        assert await _count(sm, CanonicalMessage) == 0
    _run(body)


def test_combo_2_domain_on_messaging_off_dialog_only_no_message():
    async def body(sm):
        await flags.set_flag(DOMAIN, True)                  # domain ON, messaging OFF
        await _inbound_both_paths(sm)
        assert await _count(sm, Contact) == 1               # contact/dialog from WP1B shadow
        assert await _count(sm, Dialog) == 1
        assert await _count(sm, CanonicalMessage) == 0      # NO message row
        assert await _count(sm, InboxEvent) == 0
    _run(body)


def test_combo_3_domain_off_messaging_on_is_noop():
    async def body(sm):
        await flags.set_flag(MSG, True)                     # domain OFF, messaging ON
        await _inbound_both_paths(sm)
        assert await _count(sm, Contact) == 0               # full no-op
        assert await _count(sm, CanonicalMessage) == 0
    _run(body)


def test_combo_4_both_on_records_message_with_dialog_and_contact():
    async def body(sm):
        await flags.set_flag(DOMAIN, True)
        await flags.set_flag(MSG, True)
        await messaging_shadow.mirror_inbound_message(
            phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
            body=BODY, provider_msg_id="wamid-1", external_event_id="wamid-1",
            sessionmaker=sm)
        assert await _count(sm, Contact) == 1
        assert await _count(sm, Dialog) == 1
        assert await _count(sm, CanonicalMessage) == 1      # message never without dialog/contact
        assert await _count(sm, InboxEvent) == 1
        # No commercial side effects.
        assert await _count(sm, Request) == 0
        assert await _count(sm, Assignment) == 0
        async with sm() as s:
            cm = await s.scalar(select(CanonicalMessage))
            dlg = await s.get(Dialog, cm.dialog_id)
            assert dlg is not None and await s.get(Contact, cm.contact_id) is not None
            ev = await s.scalar(select(InboxEvent))
            assert ev.account_scope == "getvisa"            # scoped to the bot account
    _run(body)


# --- outbound + dedup + fail-safe ---------------------------------------------

def test_outbound_records_outbox_when_both_on():
    async def body(sm):
        await flags.set_flag(DOMAIN, True)
        await flags.set_flag(MSG, True)
        await messaging_shadow.mirror_outbound_message(
            phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
            body="ответ бота", idempotency_key="out-1", provider_msg_id="out-1",
            status="sent", sessionmaker=sm)
        assert await _count(sm, CanonicalMessage) == 1
        assert await _count(sm, OutboxJob) == 1
        async with sm() as s:
            job = await s.scalar(select(OutboxJob))
            assert job.account_scope == "getvisa" and job.destination_scope == CANON
    _run(body)


def test_repeat_inbound_does_not_duplicate():
    async def body(sm):
        await flags.set_flag(DOMAIN, True)
        await flags.set_flag(MSG, True)
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
        await flags.set_flag(DOMAIN, True)
        await flags.set_flag(MSG, True)

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
        for pii in (PHONE, CANON, "700123456", BODY, "db exploded"):
            assert pii not in text
    _run(body)
