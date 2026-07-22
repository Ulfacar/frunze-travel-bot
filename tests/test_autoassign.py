"""Sprint 2: авто-назначение визовых лидов по round-robin (флаг visa_autoassign_enabled)."""
import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

import app.config
from app.domain import autoassign
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

PHONE_1 = "996700111222"
PHONE_2 = "996700333444"
UID_1 = f"getvisa:{PHONE_1}"


def _clear():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()


def _sm(tmp_path):
    url = f"sqlite+aiosqlite:///{(tmp_path / 'domain.db').as_posix()}"

    async def _init():
        eng = create_async_engine(url)
        async with eng.begin() as conn:
            from app.domain.models import DomainBase
            await conn.run_sync(DomainBase.metadata.create_all)
        await eng.dispose()
    asyncio.run(_init())
    eng = create_async_engine(url, poolclass=NullPool)
    return async_sessionmaker(eng, expire_on_commit=False)


def _on():
    from app.core import flags
    asyncio.run(flags.set_flag("visa_autoassign_enabled", True))


def _run(sm, *, phone=PHONE_1, direction="visa", user_id=UID_1):
    return asyncio.run(autoassign.maybe_autoassign(
        phone=phone, direction=direction, user_id=user_id, sessionmaker=sm))


def _assignments(sm):
    async def _q():
        from app.domain.models import Assignment
        async with sm() as s:
            return (await s.scalars(select(Assignment).order_by(Assignment.id))).all()
    return asyncio.run(_q())


def test_flag_off_is_noop(tmp_path):
    _clear()
    sm = _sm(tmp_path)
    assert _run(sm) is None
    assert _assignments(sm) == []


def test_non_visa_direction_is_noop(tmp_path):
    _clear()
    _on()
    sm = _sm(tmp_path)
    assert _run(sm, direction="tours") is None
    assert _assignments(sm) == []


def test_first_lead_goes_to_first_roster_manager(tmp_path):
    _clear()
    _on()
    sm = _sm(tmp_path)
    assert _run(sm) == "medina"                    # roster: medina, eliza
    rows = _assignments(sm)
    assert len(rows) == 1 and rows[0].manager_id == "medina"
    assert rows[0].assigned_by == "system" and rows[0].reason == "round_robin"


def test_idempotent_per_contact(tmp_path):
    """Второе входящее того же клиента ничего не переназначает."""
    _clear()
    _on()
    sm = _sm(tmp_path)
    assert _run(sm) == "medina"
    assert _run(sm) is None
    assert len(_assignments(sm)) == 1


def test_round_robin_second_lead_goes_to_next_manager(tmp_path):
    _clear()
    _on()
    sm = _sm(tmp_path)
    assert _run(sm) == "medina"
    assert _run(sm, phone=PHONE_2, user_id=f"getvisa:{PHONE_2}") == "eliza"


def test_manager_off_flag_skips_manager(tmp_path):
    _clear()
    _on()
    from app.core import flags
    asyncio.run(flags.set_flag("manager_off:medina", True))
    sm = _sm(tmp_path)
    assert _run(sm) == "eliza"


def test_all_managers_off_returns_none(tmp_path):
    _clear()
    _on()
    from app.core import flags
    asyncio.run(flags.set_flag("manager_off:medina", True))
    asyncio.run(flags.set_flag("manager_off:eliza", True))
    sm = _sm(tmp_path)
    assert _run(sm) is None
    assert _assignments(sm) == []


def test_panel_mirror_sets_owner_only_if_empty(tmp_path):
    _clear()
    _on()
    sm = _sm(tmp_path)
    store = get_conversation_store()

    async def _seed():
        await store.add_message(UID_1, "client", "виза в США", channel="whatsapp",
                                bot_id="getvisa", phone=PHONE_1)
    asyncio.run(_seed())
    assert _run(sm) == "medina"
    conv = asyncio.run(store.get(UID_1))
    assert conv.assigned_to == "medina"            # зеркало в панель
    # Клиент с уже закреплённым менеджером не перезатирается.
    asyncio.run(store.update_meta(UID_1, assigned_to="eliza"))

    async def _wipe_domain():
        from app.domain.models import Assignment
        async with sm() as s:
            for a in (await s.scalars(select(Assignment))).all():
                await s.delete(a)
            await s.commit()
    asyncio.run(_wipe_domain())
    assert _run(sm) == "medina"                    # домен снова назначил
    assert asyncio.run(store.get(UID_1)).assigned_to == "eliza"   # панель не тронута


def test_autoassign_does_not_intercept_bot(tmp_path):
    _clear()
    _on()
    sm = _sm(tmp_path)
    store = get_conversation_store()

    async def _seed():
        await store.add_message(UID_1, "client", "нужна виза", channel="whatsapp",
                                bot_id="getvisa", phone=PHONE_1)
    asyncio.run(_seed())
    _run(sm)
    conv = asyncio.run(store.get(UID_1))
    assert not conv.intercepted                    # бот продолжает вести диалог


def test_notify_manager_pushes_to_personal_chat(monkeypatch):
    sent = []

    async def _fake_push(token, chat_id, text):
        sent.append((token, chat_id, text))
        return True

    import app.core.calendar_brief as cb
    monkeypatch.setattr(cb, "_push_telegram", _fake_push)
    monkeypatch.setattr(app.config.settings, "telegram_bot_token", "t0k")
    from app.config import ManagerConfig
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="medina", name="Медина", password="x",
                      telegram_chat_id="42"),
        ManagerConfig(login="eliza", name="Элиза", password="x"),
    ])
    asyncio.run(autoassign._notify_manager("medina", UID_1))
    assert len(sent) == 1 and sent[0][1] == "42" and "назначен новый лид" in sent[0][2]
    sent.clear()
    asyncio.run(autoassign._notify_manager("eliza", UID_1))   # без chat_id → не шлём
    assert sent == []


def test_telegram_lead_uses_telegram_identity(tmp_path):
    """TG-лид: from.id не превращается в выдуманный телефон 996XXXXXXXXX."""
    _clear()
    _on()
    sm = _sm(tmp_path)
    assert asyncio.run(autoassign.maybe_autoassign(
        phone="123456789", direction="visa", user_id="getvisa_tg:123456789",
        channel="telegram", sessionmaker=sm)) == "medina"

    async def _identities():
        from app.domain.models import ContactIdentity
        async with sm() as s:
            return (await s.scalars(select(ContactIdentity))).all()
    idents = asyncio.run(_identities())
    assert len(idents) == 1 and idents[0].identity_type == "telegram"
    assert idents[0].normalized_value == "123456789"


def test_fail_safe_never_raises(tmp_path):
    _clear()
    _on()

    class _BrokenSM:
        def __call__(self):
            raise RuntimeError("db down")

    assert asyncio.run(autoassign.maybe_autoassign(
        phone=PHONE_1, direction="visa", user_id=UID_1, sessionmaker=_BrokenSM())) is None
