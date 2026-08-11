"""Разведка: что НА САМОМ ДЕЛЕ отдаёт TourVisor в ответе result.php.

Зачем. Полгода в коде живёт утверждение «XML TourVisor не отдаёт ни URL карточки, ни
идентификаторов отеля» (`client.py:_hotel_link`) — и оно не подтверждено ничем: в
репозитории нет ни одного сохранённого сырого ответа. Мы читаем 11 полей и молча
выбрасываем всё остальное. Этот скрипт закрывает вопрос фактами.

Отвечает ровно на три вопроса:
  1. Есть ли в ответе тип номера (`room`/`placement`) — от этого зависит строка 🛌 карточки.
  2. Есть ли идентификаторы (`tourid`, `hotelcode`, `hotelid`) и любые URL — то есть можно ли
     собрать ссылку на карточку тура программно.
  3. Меняется ли состав полей от флагов, которые мы никогда не передавали
     (`hotelsmall`, `showtours`, `onpage`, `type`).

Зовёт НАСТОЯЩИЕ функции клиента (`_build_query`, `_call`), а не свою копию логики: копия
разошлась бы с боевым запросом на второй же правке (закон Венома).

Только чтение: ни одной записи в БД, ни одного сообщения клиенту. Расход квоты — около
30 вызовов из 3000 в сутки. Сырые ответы кладутся в `--out` (по умолчанию /tmp), в git не
попадают. Логин и пароль не печатаются никогда.

Запуск на проде:
    docker cp scripts/tourvisor_probe.py frunze-travel-app-1:/tmp/probe.py
    docker exec frunze-travel-app-1 python /tmp/probe.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections import Counter
from pathlib import Path

import httpx

sys.path.insert(0, "/app")

from app.integrations.tourvisor.client import BASE_URL, TourVisorClient, _as_list  # noqa: E402

# Реалистичный запрос: ровно то, что спрашивают живые клиенты (разбор диалогов 03-11.08).
PROBE_PARAMS = {
    "destination": "Турция",
    "region": "Аланья",
    "dates": "17.08.2026-25.08.2026",
    "nights": "7",
    "tourists": "2 взрослых",
    "children_ages": "7, 12",
    "meal": "всё включено",
    "hotel_stars": "5",
}

# Флаги старого XML-шлюза, которые наш `_build_query` не передаёт НИКОГДА. Разные наборы
# полей у разных флагов — единственный способ узнать, что шлюз умеет отдавать сверх дефолта.
VARIANTS = [
    ("base", {}),
    ("hotelsmall", {"hotelsmall": "1"}),
    ("showtours", {"showtours": "1"}),
    ("onpage25", {"onpage": "25"}),
    ("type_result", {"type": "result"}),
    ("type_hotel", {"type": "hotel"}),
]

# Что ищем в сыром тексте ответа: из этого собиралась бы ссылка на карточку.
NEEDLES = ("tvcard", "tourcart", "http://", "https://", "tourid", "hotelcode", "hotelid",
           "picturelink", "fulldesclink", "room", "placement")


def _inventory(hotels: list[dict]) -> tuple[Counter, Counter, int]:
    """Какие поля реально приходят и у скольких записей они непустые."""
    hotel_fields: Counter = Counter()
    tour_fields: Counter = Counter()
    tours_seen = 0
    for hotel in hotels:
        for key, value in hotel.items():
            if key == "tours":
                continue
            if value not in (None, "", [], {}):
                hotel_fields[key] += 1
        for tour in _as_list((hotel.get("tours") or {}).get("tour")):
            tours_seen += 1
            for key, value in tour.items():
                if value not in (None, "", [], {}):
                    tour_fields[key] += 1
    return hotel_fields, tour_fields, tours_seen


def _report(title: str, fields: Counter, total: int) -> None:
    print(f"\n  {title} (всего записей: {total})")
    if not total:
        print("    — пусто")
        return
    for key, count in sorted(fields.items(), key=lambda kv: (-kv[1], kv[0])):
        print(f"    {key:<22} {count:>4}/{total}  ({100 * count // total}%)")


def _needles(raw: str) -> None:
    print("\n  Поиск по сырому тексту:")
    for needle in NEEDLES:
        hits = raw.lower().count(needle.lower())
        mark = "✓" if hits else "·"
        print(f"    {mark} {needle:<14} {hits}")
    urls = sorted(set(re.findall(r"https?://[^\s\"'<>]+", raw)))[:10]
    if urls:
        print("    URL в ответе:")
        for url in urls:
            print(f"      {url}")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/tourvisor-probe")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tv = TourVisorClient()
    if not tv.configured:
        print("НЕТ ДОСТУПОВ: TOURVISOR_LOGIN/PASS пусты — запускать нужно там, где есть prod.env")
        return 2

    async with httpx.AsyncClient(timeout=40) as http:
        query = await tv._build_query(http, PROBE_PARAMS)
        print(f"Запрос (как в бою): {json.dumps(query, ensure_ascii=False)}")
        print(f"Шлюз: {BASE_URL}")

        started = await tv._call(http, "search.php", query)
        request_id = str((started.get("result") or {}).get("requestid")
                         or started.get("requestid", ""))
        if not request_id:
            print(f"Пустой requestid, ответ: {started}")
            return 1
        print(f"requestid: {request_id}")

        # Ждём завершения поиска — разведке спешить некуда, в отличие от живого диалога.
        hotels: list[dict] = []
        for attempt in range(25):
            data = await tv._call(http, "result.php", {"requestid": request_id})
            block = data.get("data", {}) or {}
            state = (block.get("status", {}) or {}).get("state", "")
            hotels = _as_list((block.get("result", {}) or {}).get("hotel"))
            (out / f"result-{attempt:02d}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            if attempt == 0 or state == "finished":
                print(f"  проба {attempt}: state={state} отелей={len(hotels)} "
                      f"status={json.dumps(block.get('status', {}), ensure_ascii=False)}")
            if state in ("finished", "error", "no search results"):
                break
            await asyncio.sleep(1.5)

        print(f"\n=== ДЕФОЛТНЫЙ ОТВЕТ: {len(hotels)} отелей ===")
        hotel_fields, tour_fields, tours_seen = _inventory(hotels)
        _report("Поля отеля", hotel_fields, len(hotels))
        _report("Поля тура", tour_fields, tours_seen)
        if hotels:
            print("\n  Первый отель целиком:")
            print(json.dumps(hotels[0], ensure_ascii=False, indent=2)[:2000])

        # Варианты флагов — по ТОМУ ЖЕ requestid, новый поиск не запускаем (экономим квоту).
        for name, extra in VARIANTS:
            try:
                data = await tv._call(http, "result.php", {"requestid": request_id, **extra})
            except Exception as exc:  # noqa: BLE001 — вариант может быть не поддержан, это факт
                print(f"\n=== ВАРИАНТ {name}: ошибка {type(exc).__name__}: {exc}")
                continue
            raw = json.dumps(data, ensure_ascii=False)
            (out / f"variant-{name}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            variant_hotels = _as_list(
                ((data.get("data", {}) or {}).get("result", {}) or {}).get("hotel"))
            h_fields, t_fields, t_seen = _inventory(variant_hotels)
            new_h = set(h_fields) - set(hotel_fields)
            new_t = set(t_fields) - set(tour_fields)
            print(f"\n=== ВАРИАНТ {name}: отелей={len(variant_hotels)} "
                  f"новых полей отеля={sorted(new_h) or '—'} новых полей тура={sorted(new_t) or '—'}")
            if name == "base":
                _needles(raw)

    print(f"\nСырые ответы: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
