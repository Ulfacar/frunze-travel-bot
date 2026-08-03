"""Тест-сеть подбора туров на РЕАЛЬНЫХ входах из боевых логов (31.07.2026).

Почему именно так. Прошлые баги пролезали, потому что тесты проверяли `_parse_dates` на
входах вида «05.08.2025» — ровно в том формате, в котором LLM никогда не пишет. Тут наборы
args скопированы дословно из прод-логов `agent.runner: tours tool search_tours args=...`
за 24–31.07.2026. Если тест зелёный — значит запрос, который реально шлёт бот, доезжает до
TourVisor целиком.

Сеть без сети: справочники (города вылета / страны / курорты мира) подставляются в кэш
клиента, ни одного HTTP-запроса.
"""
from __future__ import annotations

import asyncio
from datetime import date as real_date

import pytest

import app.integrations.tourvisor.client as tv
from app.integrations.tourvisor.client import TourVisorClient


class FixedDate(real_date):
    """Сегодня = 31.07.2026 (день снятия логов)."""

    @classmethod
    def today(cls):
        return cls(2026, 7, 31)


DEPARTURES = [{"id": "80", "name": "Бишкек"}, {"id": "60", "name": "Алматы"}]
COUNTRIES = [
    {"id": "1", "name": "Египет"},
    {"id": "2", "name": "Таиланд"},
    {"id": "4", "name": "Турция"},
    {"id": "9", "name": "ОАЭ"},
    {"id": "11", "name": "Кипр"},
]
# Глобальный справочник курортов — TourVisor отдаёт его одним вызовом list.php?type=region
# (676 записей на проде), каждая запись с id страны.
REGIONS = [
    {"id": "5", "name": "Хургада", "country": "1"},
    {"id": "6", "name": "Шарм-эль-Шейх", "country": "1"},
    {"id": "8", "name": "Пхукет", "country": "2"},
    {"id": "20", "name": "Анталья", "country": "4"},
    {"id": "22", "name": "Кемер", "country": "4"},
    {"id": "45", "name": "Дубай", "country": "9"},
]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(tv, "date", FixedDate)
    c = TourVisorClient()
    c._login, c._pass = "login", "pass"
    c._ref_cache["departure"] = DEPARTURES
    c._ref_cache["country"] = COUNTRIES
    c._ref_cache["region:all"] = REGIONS
    return c


def build(client, args: dict) -> dict:
    """Собрать запрос тем же путём, что и боевой код (справочники уже в кэше — сети нет)."""
    return asyncio.run(client._build_query(None, args))


# --------------------------------------------------------------------------
# D1: даты клиента доезжают до API
# --------------------------------------------------------------------------

def test_prod_case_egypt_hurghada_family(client):
    """Боевой лог 31.07 06:03 — семья Мунисы. Сейчас теряются даты и ночи."""
    q = build(client, {
        "destination": "Египет", "region": "Хургада", "dates": "10-16 августа",
        "tourists": "5", "children_ages": "6, 11, 13", "budget": "500",
        "meal": "всё включено",
    })

    assert q["country"] == "1"
    assert q["regions"] == "5"
    assert q["datefrom"] == "10.08.2026"
    assert q["dateto"] == "16.08.2026"
    # 10→16 августа это 6 ночей, а не дефолтные 7–10
    assert q["nightsfrom"] == 6
    assert q["adults"] == 2
    assert q["child"] == 3
    assert [q["childage1"], q["childage2"], q["childage3"]] == [6, 11, 13]
    assert q["meal"] == 7
    # Бюджет больше НЕ режет выдачу — он размечает её у нас (иначе «500» в EUR = пусто)
    assert "priceto" not in q


def test_prod_case_dates_september_range(client):
    """Боевой лог 31.07 07:09 — «8-10 сентября»."""
    q = build(client, {"destination": "Египет", "dates": "8-10 сентября",
                       "tourists": "4", "budget": "эконом"})

    assert q["datefrom"] == "08.09.2026"
    assert q["dateto"] == "10.09.2026"
    assert q["nightsfrom"] == 2
    assert q["adults"] == 4


def test_prod_case_month_only(client):
    """Боевой лог 31.07 07:49 — «август 2026» без чисел: окно на весь месяц."""
    q = build(client, {"destination": "Кипр", "departure_city": "Бишкек",
                       "dates": "август 2026", "tourists": "2 взрослых",
                       "budget": "3000-3500 USD", "meal": "всё включено"})

    assert q["country"] == "11"
    assert q["datefrom"] == "01.08.2026"
    assert q["dateto"] == "31.08.2026"
    assert q["adults"] == 2


def test_past_month_rolls_to_next_year(client):
    """«10 марта» при сегодня 31.07.2026 — это март 2027, а не прошедший."""
    q = build(client, {"destination": "Турция", "dates": "10-20 марта"})

    assert q["datefrom"] == "10.03.2027"
    assert q["dateto"] == "20.03.2027"


def test_explicit_numeric_dates_still_work(client):
    """Старый формат dd.mm.yyyy не сломан."""
    q = build(client, {"destination": "Турция", "dates": "10.08.2026-16.08.2026"})

    assert (q["datefrom"], q["dateto"]) == ("10.08.2026", "16.08.2026")


def test_nights_stated_explicitly_win_over_date_span(client):
    """Явные «7 ночей» важнее вычисленных из диапазона."""
    q = build(client, {"destination": "Турция", "dates": "10-25 августа",
                       "nights": "7 ночей"})

    assert q["nightsfrom"] == 7
    assert q["nightsto"] == 7


# --------------------------------------------------------------------------
# D2: курорт резолвится в страну
# --------------------------------------------------------------------------

def test_prod_case_phuket_resolves_country(client):
    """Боевой лог 31.07 06:27 — «Пхукет». Сейчас страна не резолвится и запрос уходит
    БЕЗ country: TourVisor ищет по всему миру и выдаёт Шарм-эль-Шейх."""
    q = build(client, {"destination": "Пхукет", "dates": "10-16 августа",
                       "tourists": "2", "departure_city": "Бишкек", "budget": "1500"})

    assert q["country"] == "2"      # Таиланд
    assert q["regions"] == "8"      # Пхукет
    assert q["departure"] == "80"


def test_prod_case_phuket_from_almaty(client):
    """Тот же лог 19 секундами позже — клиент согласился на вылет из Алматы."""
    q = build(client, {"destination": "Пхукет", "departure_city": "Алматы",
                       "dates": "10-16 августа", "tourists": "2"})

    assert q["departure"] == "60"
    assert q["country"] == "2"


@pytest.mark.parametrize("text, country, region", [
    ("Хургада", "1", "5"),
    ("Шарм-эль-Шейх", "1", "6"),
    ("Дубай", "9", "45"),
    ("Анталья", "4", "20"),
])
def test_resort_names_resolve_without_country(client, text, country, region):
    """Клиент называет курорт, а не страну — это норма, а не исключение."""
    q = build(client, {"destination": text})

    assert (q["country"], q["regions"]) == (country, region)


def test_country_plus_resort_in_one_string(client):
    q = build(client, {"destination": "Турция, Кемер"})

    assert q["country"] == "4"
    assert q["regions"] == "22"


def test_unknown_destination_yields_no_country(client):
    """Нераспознанное направление НЕ должно превращаться в поиск по всему миру."""
    q = build(client, {"destination": "Тмутаракань"})

    assert "country" not in q


# --------------------------------------------------------------------------
# D7: звёзды доезжают до API
# --------------------------------------------------------------------------

def test_stars_reach_the_query(client):
    q = build(client, {"destination": "Турция", "hotel_stars": "5"})

    assert q["stars"] == 5


def test_changing_country_forgets_the_old_resort():
    """Клиент передумал «Турция, Белек» → «Египет». Модель прислала только страну, и раньше
    в запрос уходил Белек внутри Египта — гарантированно пустая выдача с честным
    «ничего не нашлось». Курорт живёт внутри страны и смену страны переживать не должен."""
    import asyncio

    from app.agent.runner import _tours_exec_tool
    from app.core.state import DialogState

    captured = {}

    class _TV:
        async def search_detailed(self, params):
            captured.update(params)
            raise RuntimeError("дальше не идём — нужен только запрос")

    class _CRM:
        async def create_lead(self, *a, **kw):
            return "deal-1"

    import app.agent.runner as runner
    tv_backup = runner._tourvisor
    runner._tourvisor = _TV()
    try:
        state = DialogState(user_id="u")
        state.qualification.update({"destination": "Турция", "region": "Белек",
                                    "dates": "10-17 августа", "budget": "2500 долларов"})
        try:
            asyncio.run(_tours_exec_tool("search_tours", {"destination": "Египет"}, state, _CRM()))
        except RuntimeError:
            pass
    finally:
        runner._tourvisor = tv_backup

    assert captured.get("destination") == "Египет"
    assert "region" not in captured                    # старый курорт не поехал в другую страну
    assert captured.get("budget") == "2500 долларов"   # остальное досье пережило смену
    assert captured.get("dates") == "10-17 августа"


def test_same_country_keeps_the_resort():
    """Уточнение внутри той же страны курорт не теряет."""
    import asyncio

    from app.agent.runner import _tours_exec_tool
    from app.core.state import DialogState

    captured = {}

    class _TV:
        async def search_detailed(self, params):
            captured.update(params)
            raise RuntimeError("stop")

    class _CRM:
        async def create_lead(self, *a, **kw):
            return "deal-1"

    import app.agent.runner as runner
    tv_backup = runner._tourvisor
    runner._tourvisor = _TV()
    try:
        state = DialogState(user_id="u")
        state.qualification.update({"destination": "Турция", "region": "Белек", "nights": "7"})
        try:
            asyncio.run(_tours_exec_tool("search_tours", {"destination": "Турция"}, state, _CRM()))
        except RuntimeError:
            pass
    finally:
        runner._tourvisor = tv_backup

    assert captured.get("region") == "Белек"
