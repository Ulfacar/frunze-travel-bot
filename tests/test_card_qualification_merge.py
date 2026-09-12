# -*- coding: utf-8 -*-
"""Собранная анкета не должна пропадать, когда состояние диалога истекло.

`_sync_card` пишет в карточку `state.qualification` целиком, а `update_meta` заменяет
поле, а не сливает (`store.py:212` и `:453`). Состояние живёт в Redis 7 дней
(`config.py:227`), и `RedisStateStore.load` при истёкшем ключе возвращает ПУСТОЙ
`DialogState` — из карточки ничего не восстанавливается.

Значит клиент, вернувшийся через восемь дней, первым же ходом бота стирает всё, что о
нём собрали. Замер 13.09: 87 туровых диалогов с паузой больше недели, у 80 анкета пуста,
и в 14 клиент называл направление прямым текстом.

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
from __future__ import annotations

import asyncio

import pytest

from app.integrations.panel import store as ps

BOT = "frunze_tours"
KEY = f"{BOT}:996700777888"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    ps._memory_store._conv.clear()
    yield


def _card(**qualification):
    store = ps.get_conversation_store()
    run(store.ensure(KEY, bot_id=BOT))
    run(store.update_meta(KEY, funnel="tours", qualification=dict(qualification)))
    return store


def _merge(store, state_qualification: dict):
    """То, что делает `_sync_card`: кладёт в карточку анкету из состояния."""
    from app.core.orchestrator import merge_qualification
    known = run(store.get(KEY)).qualification or {}
    return merge_qualification(known, state_qualification)


def test_expired_state_does_not_wipe_the_card():
    """Главный случай: состояние пустое, карточка заполнена — данные обязаны выжить."""
    store = _card(destination="Турция", dates="12-19 октября", tourists="2")
    merged = _merge(store, {})
    assert merged.get("destination") == "Турция"
    assert merged.get("dates") == "12-19 октября"
    assert merged.get("tourists") == "2"


def test_fresh_facts_win_over_the_card():
    """Клиент передумал — новое значение главнее старого, иначе карточка соврёт."""
    store = _card(destination="Турция", region="Анталья")
    merged = _merge(store, {"destination": "ОАЭ", "region": "Дубай"})
    assert merged.get("destination") == "ОАЭ"
    assert merged.get("region") == "Дубай"


def test_card_keeps_fields_the_state_does_not_know():
    store = _card(destination="Турция", budget="1500 USD")
    merged = _merge(store, {"destination": "Турция", "tourists": "3"})
    assert merged.get("budget") == "1500 USD"
    assert merged.get("tourists") == "3"


def test_empty_value_from_state_does_not_erase():
    """Пустая строка — это «не знаю», а не «сотри»."""
    store = _card(destination="Турция")
    merged = _merge(store, {"destination": ""})
    assert merged.get("destination") == "Турция"


def test_both_empty_is_empty():
    store = _card()
    assert _merge(store, {}) == {}
