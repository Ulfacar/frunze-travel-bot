import asyncio
from datetime import date as real_date
from unittest.mock import AsyncMock

import pytest

import app.integrations.tourvisor.client as tv
from app.integrations.tourvisor.client import (
    TourVisorClient,
    _format_hotels,
    _hotel_link,
    _hotel_price,
    _min_price_label,
    _parse_budget,
    _parse_dates,
)


class FixedDate(real_date):
    @classmethod
    def today(cls):
        return cls(2026, 6, 30)


def _hotel(name: str, price: str, currency: str = "USD") -> dict:
    return {
        "hotelname": name,
        "hotelstars": "5",
        "regionname": "Хургада",
        "tours": {
            "tour": {
                "nights": "7",
                "mealrussian": "AI",
                "price": price,
                "currency": currency,
                "operatorname": "Operator",
            }
        },
    }


def test_parse_dates_moves_past_range_to_nearest_future_year(monkeypatch):
    monkeypatch.setattr(tv, "date", FixedDate)

    assert _parse_dates("05.08.2025-12.08.2025") == ("05.08.2026", "12.08.2026")


def test_parse_dates_single_past_date_keeps_14_day_window_in_future(monkeypatch):
    monkeypatch.setattr(tv, "date", FixedDate)

    assert _parse_dates("05.08.2025") == ("05.08.2026", "19.08.2026")


def test_parse_dates_future_date_is_not_changed(monkeypatch):
    monkeypatch.setattr(tv, "date", FixedDate)

    assert _parse_dates("05.08.2026-12.08.2026") == ("05.08.2026", "12.08.2026")


def test_hotel_price_reads_best_tour_price():
    assert _hotel_price(_hotel("A", "3 153")) == 3153
    assert _hotel_price(_hotel("B", "мусор")) == 10**9


def test_min_price_label_reads_cheapest_hotel():
    label = _min_price_label(
        [_hotel("Expensive", "3485"), _hotel("Cheap", "3 153"), _hotel("Middle", "3300")]
    )

    assert label == "3 153 USD"


def test_format_hotels_gives_facts_and_no_link():
    """Ссылку на отель бот не даёт: поиск Google уводил оплаченного рекламой клиента к
    конкурентам и Booking. Клиент должен получить факты словами, а карточку — от менеджера."""
    lines = _format_hotels([_hotel("Palmora Lara", "2612")])

    assert "http" not in lines[0] and "ссылка" not in lines[0]
    # Всё, по чему клиент принимает решение, остаётся на месте.
    assert "Palmora Lara" in lines[0] and "Хургада" in lines[0]
    assert "2612" in lines[0]


@pytest.mark.parametrize(("text", "tourists", "expected"), [
    ("2500 долларов", 2, (2500, "USD")),
    ("2500$", 2, (2500, "USD")),
    ("250 тыс сом", 2, (250000, "KGS")),
    ("2000-2500", 2, (2500, "USD")),
    ("800 на человека", 4, (3200, "USD")),
    ("эконом", 2, (None, None)),
])
def test_parse_budget_amount_currency_and_person_basis(text, tourists, expected):
    assert _parse_budget(text, tourists) == expected


def test_format_hotels_marks_each_budget_band():
    lines = _format_hotels(
        [_hotel("Fit", "2500"), _hotel("Near", "2700"), _hotel("High", "3000")],
        budget=(2500, "USD"),
    )
    assert "в бюджет" in lines[0]
    assert "чуть выше бюджета" in lines[1]
    assert "выше бюджета на 20%" in lines[2]


def test_format_hotels_without_budget_has_no_budget_marks():
    assert "бюджет" not in _format_hotels([_hotel("A", "2500")])[0]


def test_budget_comparison_converts_eur_to_usd():
    line = _format_hotels([_hotel("A", "2400", "EUR")], budget=(2500, "USD"))[0]
    assert "чуть выше бюджета" in line
    assert "в бюджет" not in line
    assert "http" not in line


def test_hotel_link_is_disabled_everywhere():
    assert _hotel_link("Palmora Lara", "Анталья") == ""
    assert _hotel_link("Отель", "Анталья") == ""


def _stub_search(client, poll_results: list[list[dict]]) -> list[tuple[str, dict]]:
    """Подменить сеть: вернуть журнал вызовов, скормив _poll заготовленные выдачи."""
    calls: list[tuple[str, dict]] = []

    async def call(_http_client, path, params):
        calls.append((path, dict(params)))
        return {"result": {"requestid": f"request-{len(calls)}"}}

    client._call = AsyncMock(side_effect=call)
    client._poll = AsyncMock(side_effect=poll_results)
    client._ref_cache["departure"] = [
        {"id": "80", "name": "Бишкек"}, {"id": "60", "name": "Алматы"},
    ]
    return calls


def test_empty_from_bishkek_falls_back_to_almaty():
    """Из Бишкека TourVisor не продаёт Египет/Таиланд/Кипр — правило менеджеров велит
    смотреть из Алматы. Раньше этого не делал никто и заявка уходила в пустоту."""
    client = TourVisorClient()
    client._login, client._pass = "login", "pass"

    async def build_query(_http_client, _params):
        return {"departure": "80", "country": "1"}

    client._build_query = build_query
    calls = _stub_search(client, [[], [_hotel("Cheap", "3153")]])

    result = asyncio.run(client.search_detailed({"destination": "Египет"}))

    search_calls = [p for path, p in calls if path == "search.php"]
    assert [p["departure"] for p in search_calls] == ["80", "60"]
    assert result.reason == "ok"
    assert result.fallback_departure is True
    assert result.departure == "Алматы"
    assert "Cheap" in result.lines[0]


def test_no_fallback_when_bishkek_already_has_tours():
    client = TourVisorClient()
    client._login, client._pass = "login", "pass"

    async def build_query(_http_client, _params):
        return {"departure": "80", "country": "4"}

    client._build_query = build_query
    calls = _stub_search(client, [[_hotel("Ares", "1096")]])

    result = asyncio.run(client.search_detailed({"destination": "Турция"}))

    assert len([p for path, p in calls if path == "search.php"]) == 1
    assert result.fallback_departure is False
    assert result.departure == "Бишкек"


def test_unresolved_destination_never_searches_worldwide():
    """Без страны TourVisor ищет по всему миру — так на «Пхукет» прилетал Шарм-эль-Шейх."""
    client = TourVisorClient()
    client._login, client._pass = "login", "pass"

    async def build_query(_http_client, _params):
        return {"departure": "80"}          # страна не распозналась

    client._build_query = build_query
    calls = _stub_search(client, [])

    result = asyncio.run(client.search_detailed({"destination": "Тмутаракань"}))

    assert result.reason == "no_destination"
    assert result.lines == []
    assert [path for path, _ in calls if path == "search.php"] == []


def test_nothing_found_reports_reason_instead_of_silence():
    client = TourVisorClient()
    client._login, client._pass = "login", "pass"

    async def build_query(_http_client, _params):
        return {"departure": "80", "country": "1"}

    client._build_query = build_query
    _stub_search(client, [[], []])

    result = asyncio.run(client.search_detailed({"destination": "Египет"}))

    assert result.reason == "nothing_found"
    assert result.found == 0


def test_transport_error_is_retried_not_fatal(monkeypatch):
    """Обрыв связи с tourvisor.ru — регулярный (3 раза за сеанс 31.07). Без ретрая одна
    осечка роняла весь подбор, и клиент слышал «поиск временно недоступен»."""
    import httpx

    import app.integrations.tourvisor.client as tvc

    client = TourVisorClient()
    client._login, client._pass = "login", "pass"
    monkeypatch.setattr(tvc.asyncio, "sleep", AsyncMock())

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"lists": {}}

    attempts = {"n": 0}

    async def get(_url, params=None):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise httpx.ReadError("boom")
        return Resp()

    http = type("C", (), {"get": staticmethod(get)})()

    assert asyncio.run(client._call(http, "list.php", {})) == {"lists": {}}
    assert attempts["n"] == 2


def test_transport_error_gives_up_after_retries(monkeypatch):
    import httpx

    import app.integrations.tourvisor.client as tvc

    client = TourVisorClient()
    client._login, client._pass = "login", "pass"
    monkeypatch.setattr(tvc.asyncio, "sleep", AsyncMock())
    attempts = {"n": 0}

    async def get(_url, params=None):
        attempts["n"] += 1
        raise httpx.ReadError("boom")

    http = type("C", (), {"get": staticmethod(get)})()

    with pytest.raises(httpx.ReadError):
        asyncio.run(client._call(http, "list.php", {}))
    assert attempts["n"] == tvc.NETWORK_RETRIES + 1
