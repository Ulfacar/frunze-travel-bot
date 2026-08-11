"""ГЕЙТ: сколько ночей просил клиент, столько и ищем.

Найдено разведкой 11.08: на параметрах `nights="7"` и датах 17–25.08 в TourVisor ушло
`nightsfrom/nightsto = 8`. Причина — `_explicit_nights` ищет число ТОЛЬКО рядом со словом
«ноч», а модель кладёт в поле `nights` голое число («7»), как и описано в схеме инструмента.
Число молча терялось, и длительность бралась из диапазона дат.

Цена ошибки та же, из-за которой поле вообще появилось: в августовский пик разница между 7 и
8 ночами — десятки евро на человека, и клиент видит не ту цену, которую называл менеджеру.
"""
from __future__ import annotations

import asyncio

from app.integrations.tourvisor.client import TourVisorClient


class _FakeHttp:
    """Справочники подменяем, сети в тестах нет."""


def _query(**params) -> dict:
    tv = TourVisorClient()

    async def _fake_departure(client, text):
        return "80"

    async def _fake_destination(client, destination, region_text=""):
        return "4", "19"

    tv.resolve_departure = _fake_departure
    tv.resolve_destination = _fake_destination
    return asyncio.run(tv._build_query(_FakeHttp(), params))


def test_plain_number_of_nights_is_respected():
    """Главный кейс: модель прислала «7», даты — диапазон на 8 ночей. Побеждают ночи."""
    q = _query(destination="Турция", dates="17.08.2026-25.08.2026", nights="7")
    assert (q["nightsfrom"], q["nightsto"]) == (7, 7)


def test_worded_nights_still_work():
    q = _query(destination="Турция", dates="17.08.2026-25.08.2026", nights="7 ночей")
    assert (q["nightsfrom"], q["nightsto"]) == (7, 7)


def test_range_of_nights_survives():
    q = _query(destination="Турция", nights="7-10")
    assert (q["nightsfrom"], q["nightsto"]) == (7, 10)


def test_dates_still_define_nights_when_not_asked():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: ночи не названы — по-прежнему считаем их из дат."""
    q = _query(destination="Турция", dates="17.08.2026-25.08.2026")
    assert (q["nightsfrom"], q["nightsto"]) == (8, 8)


def test_default_when_nothing_known():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: без дат и ночей остаётся прежний дефолт."""
    q = _query(destination="Турция")
    assert (q["nightsfrom"], q["nightsto"]) == (7, 10)


def test_garbage_nights_do_not_break_search():
    q = _query(destination="Турция", dates="17.08.2026-25.08.2026", nights="сколько-нибудь")
    assert (q["nightsfrom"], q["nightsto"]) == (8, 8)


def test_absurd_number_is_ignored():
    """«2 взрослых» в поле ночей не должно превратиться в двухночный тур... но и 400 ночей
    искать незачем: за границами здравого смысла берём то, что дают даты."""
    q = _query(destination="Турция", dates="17.08.2026-25.08.2026", nights="400")
    assert (q["nightsfrom"], q["nightsto"]) == (8, 8)
