"""ГЕЙТ: пустая выдача — повод ослабить условия, а не отказать клиенту.

Написан ДО правки.

## Замер, из которого выросла задача (прод 11.09.2026)

Живой диалог владельца проекта. Клиент сказал «в Турцию, вылет с Алматы желательно» и
«неделю». Бот честно поискал ровно по этим словам, ничего не нашёл на 2 октября и
ответил «туров нет». Клиент сам открыл TourVisor и нашёл тур:

    Бишкек → Анталья, 7 октября, 5 ночей, чартер, 181 856 сом

То есть тур был. Не совпали два условия, и оба бот получил от самого клиента:
вылет (он искал Алматы, чартер летит из Бишкека) и длительность (неделя против 5 ночей).

Проверено запросами к боевому TourVisor: меняешь ТОЛЬКО ночи с 7 на 5 — выдача другая;
меняешь только город вылета — тоже.

Требование владельца 11.09: «не нужно отпугивать клиента, если не нашло — другие тоже
поискать».

## Правило

Пустой результат — не ответ клиенту, а повод попробовать ещё, по убыванию вероятности:

1. как просил клиент;
2. другой город вылета — В ОБЕ стороны (была только Бишкек → Алматы);
3. без жёсткой длительности;
4. без конкретного курорта, по стране целиком.

Что именно ослабили — возвращаем наверх, чтобы бот сказал это клиенту честно, а не выдал
чужие условия за его собственные.
"""
from __future__ import annotations

import pytest

from app.integrations.tourvisor.client import ALMATY_ID, BISHKEK_ID, TourVisorClient


class FakeSearch:
    """Подменяет один проход поиска: отвечает отелями только на «правильный» запрос."""

    def __init__(self, accept):
        self.accept = accept
        self.tried: list[dict] = []

    async def __call__(self, client, query):
        self.tried.append(dict(query))
        return [{"hotelname": "TEST HOTEL", "price": "1000"}] if self.accept(query) else []


def _client(monkeypatch, accept):
    c = TourVisorClient()
    # Без доступов клиент уходит в демо-режим и до поиска не доходит вовсе — тогда тест
    # проверял бы заглушку, а не лестницу ослаблений.
    monkeypatch.setattr(type(c), "configured", property(lambda self: True))
    fake = FakeSearch(accept)
    monkeypatch.setattr(c, "_search_once", fake)

    async def ref(*a, **kw):
        return [{"id": BISHKEK_ID, "name": "Бишкек"}, {"id": ALMATY_ID, "name": "Алматы"}]

    async def dep(_client, text):
        return ALMATY_ID if "алмат" in (text or "").lower() else BISHKEK_ID

    async def dest(_client, destination, region):
        return "4", "20"          # Турция, Анталья — справочники в тестах не дёргаем

    monkeypatch.setattr(c, "_ref", ref)
    monkeypatch.setattr(c, "resolve_departure", dep)
    monkeypatch.setattr(c, "resolve_destination", dest)
    return c, fake


BASE = {"destination": "Турция, Анталья", "dates": "2 октября", "nights": "7",
        "tourists": "2 взрослых", "departure_city": "Алматы"}


@pytest.mark.asyncio
async def test_other_departure_city_is_tried_both_ways(monkeypatch):
    """Клиент назвал Алматы, а чартер летит из Бишкека — обязаны проверить Бишкек."""
    c, fake = _client(monkeypatch, lambda q: str(q.get("departure")) == BISHKEK_ID)
    r = await c.search_detailed(BASE)
    assert r.found > 0, "не нашли то, что есть из другого города"
    assert r.fallback_departure is True
    assert any(str(q.get("departure")) == BISHKEK_ID for q in fake.tried)


@pytest.mark.asyncio
async def test_nights_are_relaxed(monkeypatch):
    """«Неделю» не должно отсекать пятидневный чартер."""
    c, fake = _client(monkeypatch, lambda q: "nightsfrom" not in q)
    r = await c.search_detailed(BASE)
    assert r.found > 0
    assert "длительн" in (r.relaxed or "").lower(), r.relaxed


@pytest.mark.asyncio
async def test_resort_is_relaxed(monkeypatch):
    """Нет в Анталье — посмотреть по стране целиком, а не отказывать."""
    c, fake = _client(monkeypatch, lambda q: "regions" not in q)
    r = await c.search_detailed(BASE)
    assert r.found > 0
    assert "курорт" in (r.relaxed or "").lower(), r.relaxed


@pytest.mark.asyncio
async def test_exact_request_wins_and_nothing_is_relaxed(monkeypatch):
    """Ложноположительный: нашлось сразу — ослаблять нечего и лишних заходов нет."""
    c, fake = _client(monkeypatch, lambda q: True)
    r = await c.search_detailed(BASE)
    assert r.found > 0
    assert not r.relaxed
    assert len(fake.tried) == 1, f"лишние запросы в портал: {len(fake.tried)}"


@pytest.mark.asyncio
async def test_truly_empty_is_still_honest(monkeypatch):
    """Ложноположительный: если нет вообще ничего — говорим «нет», а не выдумываем."""
    c, fake = _client(monkeypatch, lambda q: False)
    r = await c.search_detailed(BASE)
    assert r.reason == "nothing_found"
    assert r.found == 0
    assert len(fake.tried) <= 4, f"слишком много заходов в портал: {len(fake.tried)}"
