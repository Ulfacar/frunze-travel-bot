# -*- coding: utf-8 -*-
"""Бюджет из разговора — отдельный тумблер, отдельно от остальных полей.

После полного прогона по 10 000 боевых сообщений шесть полей (направление, курорт,
даты, состав, возрасты детей, город вылета) читаются чисто. Бюджет — нет: в нём
остаются семантические ошибки, которые регуляркой не берутся («До этого вы писали цену
420 $» — это НАША цена, процитированная обратно; «500$ за номер» — цена за комнату;
«Мы за 1800$ брали на ноябрь» — прошлая покупка).

Это разные по цене ошибки. Неверное направление менеджер увидит и поправит, неверный
бюджет раньше уезжал в сумму сделки. Поэтому поля включаются порознь: карточка
заполняется уже сегодня, а бюджет ждёт, пока его доведут.

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
import asyncio

import pytest

from app.agent import facts
from app.core import flags


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    flags.reset()
    yield
    flags.reset()


TEXT = "бюджет 3000 долларов, хотим в Турцию на двоих"


def test_extract_itself_is_unchanged():
    """Сам разбор тумблера не знает — он чистая функция, её поведение не трогаем."""
    got = facts.extract(TEXT)
    assert got.get("budget") == "3000 USD"
    assert got.get("destination") == "Турция"


def test_budget_is_dropped_when_the_toggle_is_off():
    got = run(facts.allowed(facts.extract(TEXT), bot_id="frunze_tours"))
    assert "budget" not in got
    assert got.get("destination") == "Турция"
    assert str(got.get("tourists")) == "2"


def test_budget_passes_when_the_toggle_is_on():
    run(flags.set_flag("tour_facts_budget_enabled", True))
    got = run(facts.allowed(facts.extract(TEXT), bot_id="frunze_tours"))
    assert got.get("budget") == "3000 USD"


def test_per_bot_toggle_wins():
    run(flags.set_flag("tour_facts_budget_enabled", False))
    run(flags.set_flag("tour_facts_budget_enabled:frunze_tours", True))
    got = run(facts.allowed(facts.extract(TEXT), bot_id="frunze_tours"))
    assert got.get("budget") == "3000 USD"
    other = run(facts.allowed(facts.extract(TEXT), bot_id="frunze_tours_sezim"))
    assert "budget" not in other


def test_nothing_else_is_filtered():
    """Ложное срабатывание дороже: остальные шесть полей проходят всегда."""
    got = run(facts.allowed(facts.extract(
        "Нячанг 20.10 до 10.11, вылет из Бишкека, 2 взрослых с ребенком 5 лет"),
        bot_id="frunze_tours"))
    for field in ("destination", "region", "dates", "tourists", "departure_city"):
        assert got.get(field), f"поле {field} не должно фильтроваться"
