# -*- coding: utf-8 -*-
"""«Новый лид» → «В работе» — правка Медины 12.11.2026.

Её слова: «когда менеджер начинает общение с клиентом, система может автоматически
переводить его из „Новый лид“ во „В работе“. А остальные стадии менеджер уже будет
менять самостоятельно».

Поэтому главное, что здесь проверяется, — не сам перевод, а его ГРАНИЦЫ: автоматика
одна и только одна. Карточка, которую менеджер уже подвинул дальше, не должна
откатываться назад ни при каком новом сообщении, иначе система будет отбирать у него
его же работу — ровно то, от чего он просил уйти.
"""
import asyncio

import pytest

from app.core.lead_stage import (STAGE_IN_WORK, STAGE_NEW_LEAD,
                                 stage_after_manager_message)

VISA = ["visa"]


# --- чистое правило ---------------------------------------------------------

def test_a_manager_message_moves_a_new_lead_into_work():
    assert stage_after_manager_message("visa", STAGE_NEW_LEAD, VISA) == STAGE_IN_WORK


@pytest.mark.parametrize("stage", ["qualification", "progress", "silent",
                                   "follow_up", "office", "manager"])
def test_a_lead_further_along_is_never_moved_back(stage):
    """Её условие: остальные стадии двигает менеджер.

    Если бы автоматика срабатывала на любой стадии, карточка из «Записан в офис»
    откатывалась бы во «В работе» на каждом новом сообщении менеджера.
    """
    assert stage_after_manager_message("visa", stage, VISA) is None


def test_tours_are_not_touched():
    """Правка про визы: у туров свой набор колонок и своя логика."""
    assert stage_after_manager_message("tours", STAGE_NEW_LEAD, VISA) is None


def test_an_unknown_or_empty_funnel_is_left_alone():
    for funnel in ("", None, "tickets"):
        assert stage_after_manager_message(funnel, STAGE_NEW_LEAD, VISA) is None


def test_an_empty_stage_is_not_treated_as_a_new_lead():
    """Пустая стадия — это «не знаем», а не «новый лид»: трогать её нельзя."""
    for stage in ("", None):
        assert stage_after_manager_message("visa", stage, VISA) is None


# --- через хранилище --------------------------------------------------------

def _store_with(monkeypatch, *, flag_on: bool):
    from app.config import settings
    from app.core import flags
    from app.integrations.panel import store as st

    flags.reset()
    monkeypatch.setattr(settings, "auto_stage_funnels", ["visa"])
    if flag_on:
        asyncio.run(flags.set_flag("auto_stage_on_manager_reply_enabled", True))
    st._memory_store._conv.clear()
    return st._memory_store


def _seed(store, user_id="getvisa:996700999001", funnel="visa", stage=STAGE_NEW_LEAD):
    asyncio.run(store.add_message(user_id, "client", "нужна виза", channel="whatsapp"))
    asyncio.run(store.update_meta(user_id, funnel=funnel, stage=stage))
    return user_id


def test_the_manager_message_advances_the_card(monkeypatch):
    store = _store_with(monkeypatch, flag_on=True)
    user_id = _seed(store)

    asyncio.run(store.add_message(user_id, "manager", "Здравствуйте! Сейчас уточню."))

    assert asyncio.run(store.get(user_id)).stage == STAGE_IN_WORK


def test_the_bot_message_does_not_advance_the_card(monkeypatch):
    """Бот отвечает ночью сам — это не «менеджер начал общение»."""
    store = _store_with(monkeypatch, flag_on=True)
    user_id = _seed(store)

    asyncio.run(store.add_message(user_id, "bot", "Здравствуйте! Уточню детали."))

    assert asyncio.run(store.get(user_id)).stage == STAGE_NEW_LEAD


def test_the_client_message_does_not_advance_the_card(monkeypatch):
    store = _store_with(monkeypatch, flag_on=True)
    user_id = _seed(store)

    asyncio.run(store.add_message(user_id, "client", "а сколько стоит?"))

    assert asyncio.run(store.get(user_id)).stage == STAGE_NEW_LEAD


def test_with_the_flag_off_nothing_moves(monkeypatch):
    """Дефолт OFF: выкат кода ничего не двигает, включение — отдельное решение."""
    store = _store_with(monkeypatch, flag_on=False)
    user_id = _seed(store)

    asyncio.run(store.add_message(user_id, "manager", "Здравствуйте!"))

    assert asyncio.run(store.get(user_id)).stage == STAGE_NEW_LEAD


def test_a_card_in_office_stays_in_office(monkeypatch):
    """Через хранилище, не только через чистое правило: откат назад недопустим."""
    store = _store_with(monkeypatch, flag_on=True)
    user_id = _seed(store, stage="office")

    asyncio.run(store.add_message(user_id, "manager", "Ждём вас завтра в офисе."))

    assert asyncio.run(store.get(user_id)).stage == "office"


def test_a_tours_card_stays_put(monkeypatch):
    store = _store_with(monkeypatch, flag_on=True)
    user_id = _seed(store, user_id="frunze_tours:996700999002", funnel="tours")

    asyncio.run(store.add_message(user_id, "manager", "Добрый день!"))

    assert asyncio.run(store.get(user_id)).stage == STAGE_NEW_LEAD


def test_the_message_is_saved_even_if_the_flag_read_fails(monkeypatch):
    """Сбой чтения флага не должен терять сообщение клиенту.

    Стадия — удобство, сообщение — работа. Если база флагов недоступна, карточка
    остаётся где была, но реплика записывается.
    """
    store = _store_with(monkeypatch, flag_on=True)
    user_id = _seed(store)

    from app.core import flags

    async def boom(*a, **k):
        raise RuntimeError("флаги недоступны")

    monkeypatch.setattr(flags, "get_flag", boom)
    asyncio.run(store.add_message(user_id, "manager", "Здравствуйте!"))

    conv = asyncio.run(store.get(user_id))
    assert conv.stage == STAGE_NEW_LEAD
    assert conv.messages[-1].text == "Здравствуйте!"


def test_the_backfill_script_uses_the_same_stage_keys():
    """Скрипт переноса дублирует две константы, чтобы показ работал до выката.

    Дубликат допустим, расхождение — нет: если ключи стадий разойдутся, скрипт
    молча двинет карточки не туда.
    """
    import pathlib
    import re

    src = (pathlib.Path(__file__).resolve().parents[1]
           / "scripts" / "backfill_lead_stage.py").read_text(encoding="utf-8")
    m = re.search(r'STAGE_NEW_LEAD, STAGE_IN_WORK = "([a-z_]+)", "([a-z_]+)"', src)
    assert m, "в скрипте нет запасных значений — проверьте, не переписан ли импорт"
    assert m.group(1) == STAGE_NEW_LEAD
    assert m.group(2) == STAGE_IN_WORK
