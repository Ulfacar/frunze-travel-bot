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


# ==================== Пилот: single-manager tours assignment ====================

TOURS_PHONE = "996700555666"
TOURS_UID = "frunze_tours:996700555666"


def _tours_on():
    from app.core import flags
    asyncio.run(flags.set_flag("tours_pilot_assign_enabled", True))


def _run_tours(sm, *, phone=TOURS_PHONE, bot_id="frunze_tours", direction="tours",
               user_id=TOURS_UID):
    return asyncio.run(autoassign.maybe_assign_tours_pilot(
        phone=phone, direction=direction, bot_id=bot_id, user_id=user_id,
        channel="whatsapp", sessionmaker=sm))


def _tours_assignments(sm):
    async def _q():
        from app.domain.models import Assignment
        async with sm() as s:
            return (await s.scalars(
                select(Assignment).where(Assignment.direction == "tours")
                .order_by(Assignment.id))).all()
    return asyncio.run(_q())


def test_tours_pilot_flag_off_no_assignment(tmp_path):
    """1. flag OFF → assignment отсутствует."""
    _clear()
    sm = _sm(tmp_path)
    assert _run_tours(sm) is None
    assert _tours_assignments(sm) == []


def test_tours_pilot_assigns_ademi_when_no_owner(tmp_path):
    """2. flag ON + frunze_tours + no owner → owner Адеми (ademi)."""
    _clear()
    _tours_on()
    sm = _sm(tmp_path)
    assert _run_tours(sm) == "ademi"
    rows = _tours_assignments(sm)
    assert len(rows) == 1
    assert rows[0].manager_id == "ademi" and rows[0].active
    assert rows[0].assigned_by == "system" and rows[0].reason == "tours_pilot"


def test_tours_pilot_idempotent(tmp_path):
    """3. повторное событие → дубля нет."""
    _clear()
    _tours_on()
    sm = _sm(tmp_path)
    assert _run_tours(sm) == "ademi"
    assert _run_tours(sm) is None
    assert len(_tours_assignments(sm)) == 1


def test_tours_pilot_never_overwrites_existing_owner(tmp_path):
    """4. существующий owner → не меняется."""
    _clear()
    _tours_on()
    sm = _sm(tmp_path)
    # Предзакрепляем контакт за другим менеджером напрямую в домене.
    from app.domain import live_assign

    async def _preassign():
        async with sm() as s:
            contact = await live_assign.contact_for_channel(
                s, channel="whatsapp", raw=TOURS_PHONE)
            await live_assign.assign_locked(
                s, contact.id, "tours", "sezim",
                assigned_by="manual", reason="test")
            await s.commit()
    asyncio.run(_preassign())
    assert _run_tours(sm) is None
    rows = _tours_assignments(sm)
    assert len(rows) == 1 and rows[0].manager_id == "sezim"   # Адеми не перезаписала


def test_tours_pilot_other_bot_id_not_assigned(tmp_path):
    """5. другой bot_id → не назначается (напр. Сезим-бот frunze_tours_sezim)."""
    _clear()
    _tours_on()
    sm = _sm(tmp_path)
    assert _run_tours(sm, bot_id="frunze_tours_sezim",
                      user_id="frunze_tours_sezim:996700555666") is None
    assert _tours_assignments(sm) == []


def test_tours_pilot_non_tours_direction_noop(tmp_path):
    """Визовое направление через туровый хук не назначается (кросс-скоуп-защита)."""
    _clear()
    _tours_on()
    sm = _sm(tmp_path)
    assert _run_tours(sm, direction="visa") is None
    assert _tours_assignments(sm) == []


def test_tours_pilot_configurable_manager(tmp_path):
    """pilot_manager берётся из настроек, не хардкодится."""
    _clear()
    _tours_on()
    import app.config
    from unittest.mock import patch
    sm = _sm(tmp_path)
    with patch.object(app.config.settings, "tours_pilot_manager", "ademi_alt"):
        assert _run_tours(sm) == "ademi_alt"


def test_tours_pilot_flag_off_after_on_stops_new(tmp_path):
    """После выключения флага новые лиды больше не назначаются."""
    _clear()
    _tours_on()
    sm = _sm(tmp_path)
    assert _run_tours(sm) == "ademi"                    # первый — назначен
    from app.core import flags
    asyncio.run(flags.set_flag("tours_pilot_assign_enabled", False))
    assert _run_tours(sm, phone="996700777888",
                      user_id="frunze_tours:996700777888") is None   # новый — нет
    assert len(_tours_assignments(sm)) == 1


def test_tours_pilot_fail_safe_never_raises(tmp_path):
    _clear()
    _tours_on()

    class _BrokenSM:
        def __call__(self):
            raise RuntimeError("db down")

    assert asyncio.run(autoassign.maybe_assign_tours_pilot(
        phone=TOURS_PHONE, direction="tours", bot_id="frunze_tours",
        user_id=TOURS_UID, sessionmaker=_BrokenSM())) is None
