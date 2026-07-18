"""WP1B: shadow bridge — flag-gated, fail-safe mirror of inbound events into the
domain (Contact/Identity/Dialog only). In-memory SQLite; WP0 guard active.

Proves: flag OFF = zero writes; flag ON creates only Contact/Identity/Dialog (no
Request, no Assignment); repeat inbound = no duplicates; a shadow failure never
raises to the caller and never logs PII (phone/name/text)."""
import asyncio
import contextlib
import logging

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import flags
from app.domain import shadow_bridge
from app.domain.models import (
    Assignment, Contact, ContactIdentity, Dialog, Request,
)
from app.domain.services import ContactService, RequestService

PHONE = "0700123456"            # normalizes to 996700123456
CANON = "996700123456"


def _make_engine_sm():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    return engine


async def _prepare(engine):
    from app.domain.models import DomainBase
    async with engine.begin() as conn:
        await conn.run_sync(DomainBase.metadata.create_all)
    return async_sessionmaker(engine, expire_on_commit=False)


async def _count(sm, model) -> int:
    async with sm() as s:
        return await s.scalar(select(func.count()).select_from(model))


@contextlib.contextmanager
def capture_shadow_logs():
    """Capture 'domain.shadow' log messages via a dedicated handler — independent of
    pytest caplog / root config (other tests call logging.basicConfig, which can
    otherwise make capture order-dependent). Forces the logger enabled during capture."""
    lg = logging.getLogger("domain.shadow")
    prev = (lg.disabled, lg.level, lg.propagate)
    lg.disabled = False
    lg.setLevel(logging.WARNING)
    msgs: list[str] = []

    class _H(logging.Handler):
        def emit(self, record):
            msgs.append(record.getMessage())   # args substituted; no PII unless logged

    handler = _H()
    lg.addHandler(handler)
    try:
        yield msgs
    finally:
        lg.removeHandler(handler)
        lg.disabled, lg.level, lg.propagate = prev


def _run(coro_factory):
    async def _main():
        flags.reset()
        engine = _make_engine_sm()
        sm = await _prepare(engine)
        try:
            await coro_factory(sm)
        finally:
            flags.reset()
            await engine.dispose()
    asyncio.run(_main())


# --- flag OFF = zero domain writes --------------------------------------------

def test_flag_off_writes_nothing():
    async def body(sm):
        # Flag defaults OFF (reset). Mirror must early-return before any write.
        await shadow_bridge.mirror_inbound(
            phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
            sessionmaker=sm)
        assert await _count(sm, Contact) == 0
        assert await _count(sm, ContactIdentity) == 0
        assert await _count(sm, Dialog) == 0
    _run(body)


# --- flag ON: Contact + Identity + Dialog, NO Request, NO Assignment -----------

def test_flag_on_creates_only_contact_identity_dialog():
    async def body(sm):
        await flags.set_flag(shadow_bridge.FLAG, True)
        await shadow_bridge.mirror_inbound(
            phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
            sessionmaker=sm)
        assert await _count(sm, Contact) == 1
        assert await _count(sm, ContactIdentity) == 1
        assert await _count(sm, Dialog) == 1
        # Crucially: the bridge opens NO commercial request and assigns NO manager.
        assert await _count(sm, Request) == 0
        assert await _count(sm, Assignment) == 0
        async with sm() as s:
            ident = await s.scalar(select(ContactIdentity))
            assert ident.normalized_value == CANON and ident.provider_scope == ""
            dlg = await s.scalar(select(Dialog))
            assert dlg.channel_key == CANON and dlg.request_id is None
    _run(body)


def test_repeat_inbound_does_not_duplicate():
    async def body(sm):
        await flags.set_flag(shadow_bridge.FLAG, True)
        for _ in range(3):
            await shadow_bridge.mirror_inbound(
                phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
                sessionmaker=sm)
        assert await _count(sm, Contact) == 1
        assert await _count(sm, ContactIdentity) == 1
        assert await _count(sm, Dialog) == 1
    _run(body)


def test_links_existing_active_request_without_creating_one():
    async def body(sm):
        await flags.set_flag(shadow_bridge.FLAG, True)
        # Pre-create the same Contact (by identity) with an active visa Request.
        async with sm() as s:
            c = await ContactService.find_or_create_by_identity(s, "phone", CANON)
            active = await RequestService.open(s, c.id, "visa")
            await s.commit()
            active_id = active.id
        await shadow_bridge.mirror_inbound(
            phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
            sessionmaker=sm)
        assert await _count(sm, Contact) == 1
        assert await _count(sm, Request) == 1           # NOT increased
        async with sm() as s:
            dlg = await s.scalar(select(Dialog))
            assert dlg.request_id == active_id          # linked to the pre-existing one
    _run(body)


# --- fail-safe + PII-free logging ---------------------------------------------

def test_shadow_failure_is_swallowed_and_logs_no_pii(monkeypatch):
    async def body(sm):
        await flags.set_flag(shadow_bridge.FLAG, True)

        async def boom(*a, **k):
            raise RuntimeError("db exploded")
        monkeypatch.setattr(ContactService, "find_or_create_by_identity", boom)

        with capture_shadow_logs() as msgs:
            # Must NOT raise — the live dialog is unaffected.
            await shadow_bridge.mirror_inbound(
                phone=PHONE, channel="whatsapp", bot_id="getvisa", direction="visa",
                sessionmaker=sm)

        # Nothing persisted, error logged with class name but WITHOUT PII.
        assert await _count(sm, Contact) == 0
        text = "\n".join(msgs)
        assert "RuntimeError" in text                       # error class logged
        for pii in (PHONE, CANON, "700123456", "db exploded"):
            assert pii not in text                          # no phone / message text
    _run(body)


def test_unnormalizable_phone_skipped_no_pii():
    async def body(sm):
        await flags.set_flag(shadow_bridge.FLAG, True)
        with capture_shadow_logs() as msgs:
            await shadow_bridge.mirror_inbound(
                phone="12345", channel="whatsapp", bot_id="getvisa", direction="visa",
                sessionmaker=sm)
        assert await _count(sm, Contact) == 0
        assert "12345" not in "\n".join(msgs)               # the raw value is never logged
    _run(body)
