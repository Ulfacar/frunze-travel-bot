"""Калибровка подборки на РЕАЛЬНЫХ запросах прода — до выкатки, как требует закон 5 Венома.

Сторож каналов выкатывался трижды за сутки, и трижды пороги брались из рассуждения, а не из
замера; проверкой каждый раз работал владелец, которому это падало в Telegram. Здесь тот же
риск: тесты доказывают, что форматтер делает то, что описано, но не отвечают на вопрос «как
это выглядит на нашем трафике».

Запросы берутся дословно из прод-логов (`agent.runner: tours tool search_tours args=...`) —
это то, что модель реально передавала в поиск за последнюю неделю.

Скрипт зовёт НАСТОЯЩИЕ `search_detailed` и `render_block`: копия логики разошлась бы с боем.
Только чтение, ничего никому не отправляет. Расход квоты — по одному поиску на запрос.
"""
from __future__ import annotations

import asyncio
import statistics
import sys

sys.path.insert(0, "/app")

from app.integrations.tourvisor.cards import render_block, render_cards  # noqa: E402
from app.integrations.tourvisor.client import TourVisorClient  # noqa: E402

# Дословно из прод-логов за 7 дней (`sort -u`, взяты разные направления и составы).
REAL_QUERIES = [
    {"destination": "Турция", "dates": "10-17 августа", "tourists": "3",
     "children_ages": "18, 12", "meal": "всё включено", "departure_city": "Бишкек"},
    {"destination": "ОАЭ", "region": "Дубай", "dates": "25-31 августа",
     "tourists": "2 взрослых", "children_ages": "6, 3", "meal": "всё включено",
     "departure_city": "Бишкек"},
    {"destination": "Египет", "region": "Шарм-эль-Шейх", "dates": "28 декабря",
     "nights": "7", "tourists": "2 взрослых, 1 ребёнок", "children_ages": "1",
     "meal": "всё включено", "departure_city": "Бишкек"},
    {"destination": "Вьетнам", "region": "Нячанг", "dates": "24 августа", "nights": "7-8",
     "tourists": "2 взрослых", "meal": "всё включено", "departure_city": "Алматы"},
    {"destination": "Мальдивы", "departure_city": "Алматы", "dates": "декабрь 2026",
     "nights": "14", "tourists": "4", "children_ages": "2.5, 0.75",
     "budget": "3000-4000 USD"},
    {"destination": "Стамбул", "dates": "15 октября", "nights": "7-8", "tourists": "2-3",
     "departure_city": "Бишкек"},
    {"destination": "Египет", "dates": "3 декабря", "tourists": "7", "hotel_stars": "5",
     "meal": "всё включено", "region": "Шарм-эль-Шейх"},
    {"destination": "Вьетнам", "region": "Дананг", "dates": "2-15 сентября",
     "departure_city": "Алматы", "tourists": "3 взрослых"},
    {"destination": "Вьетнам", "tourists": "4", "dates": "февраль 2027",
     "departure_city": "Бишкек", "meal": "полный пансион"},
    {"destination": "Турция", "region": "Аланья", "dates": "17-25 августа", "nights": "7",
     "tourists": "2 взрослых", "children_ages": "7, 12", "meal": "всё включено",
     "hotel_stars": "5", "departure_city": "Бишкек"},
]


async def main() -> int:
    tv = TourVisorClient()
    if not tv.configured:
        print("нет доступов TourVisor — запускать там, где есть prod.env")
        return 2

    lengths: list[int] = []
    counts: list[int] = []
    no_room = total_cards = 0
    almaty = empty = 0

    for i, params in enumerate(REAL_QUERIES, 1):
        try:
            found = await tv.search_detailed(params)
        except Exception as exc:  # noqa: BLE001 — калибровка не должна падать на одном запросе
            print(f"\n[{i}] {params.get('destination')}: ОШИБКА {type(exc).__name__}: {exc}")
            continue
        cards = render_cards(found.hotels, departure=found.departure)
        block = render_block(cards, offer_url="https://frunzetravel.kg/t/xxxxxxxxxx")
        print(f"\n{'=' * 72}\n[{i}] {params}\n"
              f"реакция: reason={found.reason} отелей={found.found} "
              f"вылет={found.departure or '—'}"
              f"{' (ПОДМЕНА НА АЛМАТЫ)' if found.fallback_departure else ''}\n{'-' * 72}")
        print(block or "(карточек нет)")
        if found.fallback_departure:
            almaty += 1
        if not cards:
            empty += 1
            continue
        lengths.append(len(block))
        counts.append(len(cards))
        total_cards += len(cards)
        no_room += sum(1 for c in cards if "🛌" not in c or c.count("🛌") == 0)

    print(f"\n{'=' * 72}\nЗАМЕР ПО {len(REAL_QUERIES)} ЖИВЫМ ЗАПРОСАМ")
    if lengths:
        print(f"  длина сообщения: медиана {int(statistics.median(lengths))}, "
              f"максимум {max(lengths)} знаков")
        print(f"  карточек в сообщении: медиана {int(statistics.median(counts))}, "
              f"минимум {min(counts)}")
        print(f"  карточек без типа номера: {no_room} из {total_cards}")
    print(f"  запросов без единой карточки: {empty}")
    print(f"  выдача подменена на Алматы: {almaty}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
