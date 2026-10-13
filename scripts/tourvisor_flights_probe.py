"""Разведка: отдаёт ли TourVisor данные о перелётах по `tourid`.

Зачем. Гриша просит подборку в том виде, как её шлют туроператоры (образец 02.10.2026):

    ✈️ 29 окт, 06:30 - 10:00, Red Sea Airlines - 20кг
    ✈️ 4 ноя, 20:15 - 05:30 +1, Red Sea Airlines - 20кг

В поисковой выдаче (`result.php`) этого нет — разведка 11.08 перечислила все приходящие
поля, рейсов среди них не было. Зато есть `tourid`, а у шлюза есть методы актуализации
тура, которых наш клиент не зовёт ни разу. Документация `tourvisor.ru/xml/` с нашего
сервера отдаёт 403 (гео-блок), поэтому проверяем вызовом, а не чтением.

Отвечает ровно на пять вопросов:
  1. Какой метод актуализации вообще работает на нашем тарифе.
  2. Есть ли ВРЕМЯ вылета и прилёта.
  3. Есть ли НАЗВАНИЕ авиакомпании.
  4. Есть ли НОРМА БАГАЖА.
  5. Сколько метод думает — от этого зависит, можно ли звать его в живом диалоге.

Зовёт настоящие функции клиента (`_build_query`, `_call`), а не свою копию логики: копия
разошлась бы с боевым запросом на второй же правке. Учёт квоты поэтому тоже настоящий.

Только чтение: ни одной записи в БД, ни одного сообщения клиенту. Расход квоты — около
15 вызовов из 3000 в сутки. Сырые ответы кладутся в `--out` (по умолчанию /tmp), в git не
попадают. Логин и пароль не печатаются никогда.

Запуск на проде (у локальной машины доступа к шлюзу нет):
    docker cp scripts/tourvisor_flights_probe.py frunze-travel-app-1:/tmp/fprobe.py
    docker exec frunze-travel-app-1 python /tmp/fprobe.py
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, "/app")

from app.integrations.tourvisor.client import BASE_URL, TourVisorClient, _as_list  # noqa: E402

# Тот же реалистичный запрос, что у разведки 11.08, но по живому направлению из образца
# Гриши: Египет из Бишкека. Если по нему туров нет — поиск повторяется по Турции.
PROBE_PARAMS = {
    "destination": "Турция",
    "region": "Аланья",
    "dates": "20.10.2026-30.10.2026",
    "nights": "7",
    "tourists": "2 взрослых",
    "meal": "всё включено",
}

# Методы актуализации, которые встречаются в XML-шлюзе TourVisor. Какой из них доступен
# на нашем тарифе — ровно то, что выясняет этот скрипт.
METHODS = [
    ("actualize.php", {}),
    ("actualize.php", {"flights": "1"}),
    ("actdetail.php", {}),
    ("actdetail.php", {"flights": "1"}),
]

# Слова, по которым узнаём рейс в сыром ответе. Русские и английские сразу: шлюз смешивает.
NEEDLES = ("flight", "flights", "forward", "backward", "airline", "aircompany",
           "baggage", "departure", "arrival", "time", "рейс", "авиакомпан", "багаж")

_TIME = re.compile(r"\b([01]?\d|2[0-3]):[0-5]\d\b")


def _walk(node, path="") -> list[tuple[str, object]]:
    """Все листья структуры с путями: ответ актуализации вложенный, и плоский
    инвентарь полей (как в разведке 11.08) тут ничего бы не показал."""
    out: list[tuple[str, object]] = []
    if isinstance(node, dict):
        for key, value in node.items():
            out += _walk(value, f"{path}.{key}" if path else key)
    elif isinstance(node, list):
        for i, value in enumerate(node):
            out += _walk(value, f"{path}[{i}]")
    else:
        out.append((path, node))
    return out


def _verdict(raw: str, leaves: list[tuple[str, object]]) -> None:
    """Пять вопросов, ради которых всё и затевалось. Отвечаем да/нет, а не «похоже»."""
    low = raw.lower()
    times = sorted({m.group(0) for m in _TIME.finditer(raw)})
    airline_like = [(p, v) for p, v in leaves
                    if isinstance(v, str) and v.strip()
                    and re.search(r"airline|aircompany|авиакомпан|перевозчик", p, re.I)]
    baggage_like = [(p, v) for p, v in leaves
                    if str(v).strip() and re.search(r"baggage|багаж|luggage", p, re.I)]
    plus_day = [(p, v) for p, v in leaves
                if isinstance(v, str) and re.search(r"\+\s*1\b", v)]

    print("\n  ОТВЕТЫ:")
    print(f"    время (HH:MM) в ответе : {'ДА — ' + ', '.join(times[:8]) if times else 'НЕТ'}")
    print(f"    авиакомпания           : "
          f"{'ДА — ' + '; '.join(f'{p}={v}' for p, v in airline_like[:3]) if airline_like else 'НЕТ'}")
    print(f"    багаж                  : "
          f"{'ДА — ' + '; '.join(f'{p}={v}' for p, v in baggage_like[:3]) if baggage_like else 'НЕТ'}")
    print(f"    прилёт «+1 день»       : {'ДА' if plus_day else 'не найден (может не быть в этом туре)'}")
    print("    слова-маркеры          : "
          + ", ".join(f"{n}×{low.count(n)}" for n in NEEDLES if low.count(n)))


async def _find_tour_ids(tv: TourVisorClient, http: httpx.AsyncClient,
                         out: Path, params: dict) -> list[tuple[str, str]]:
    """Настоящий поиск → `tourid` первых туров вместе с именем отеля."""
    query = await tv._build_query(http, params)
    print(f"Запрос (как в бою): {json.dumps(query, ensure_ascii=False)}")
    started = await tv._call(http, "search.php", query)
    request_id = str((started.get("result") or {}).get("requestid") or started.get("requestid", ""))
    if not request_id:
        print(f"Пустой requestid, ответ: {started}")
        return []
    print(f"requestid: {request_id}")

    hotels: list[dict] = []
    for attempt in range(25):
        data = await tv._call(http, "result.php", {"requestid": request_id})
        block = data.get("data", {}) or {}
        state = (block.get("status", {}) or {}).get("state", "")
        hotels = _as_list((block.get("result", {}) or {}).get("hotel"))
        if state in ("finished", "error", "no search results"):
            print(f"  поиск: state={state}, отелей={len(hotels)}")
            break
        await asyncio.sleep(1.5)
    (out / "search-result.json").write_text(
        json.dumps(hotels[:3], ensure_ascii=False, indent=2), encoding="utf-8")

    found: list[tuple[str, str]] = []
    for hotel in hotels:
        for tour in _as_list((hotel.get("tours") or {}).get("tour")):
            tour_id = str(tour.get("tourid") or "").strip()
            if tour_id:
                found.append((tour_id, str(hotel.get("hotelname") or "")))
                break
        if len(found) >= 2:
            break
    return found


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="/tmp/tourvisor-flights")
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tv = TourVisorClient()
    if not tv.configured:
        print("НЕТ ДОСТУПОВ: TOURVISOR_LOGIN/PASS пусты — запускать нужно там, где есть prod.env")
        return 2
    print(f"Шлюз: {BASE_URL}")

    async with httpx.AsyncClient(timeout=60) as http:
        tours = await _find_tour_ids(tv, http, out, PROBE_PARAMS)
        if not tours:
            print("Туров с `tourid` не нашлось — разведку по актуализации делать не на чем.")
            return 1
        tour_id, hotel_name = tours[0]
        print(f"\nБерём тур: tourid={tour_id} ({hotel_name})")

        for path, extra in METHODS:
            name = path.replace(".php", "") + ("+flights" if extra else "")
            started_at = time.monotonic()
            try:
                data = await tv._call(http, path, {"tourid": tour_id, **extra})
            except Exception as exc:  # noqa: BLE001 — недоступность метода и есть ответ
                print(f"\n=== {name}: ОШИБКА за {time.monotonic() - started_at:.1f}с — "
                      f"{type(exc).__name__}: {exc}")
                continue
            took = time.monotonic() - started_at
            raw = json.dumps(data, ensure_ascii=False)
            (out / f"{name}.json").write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            leaves = _walk(data)
            print(f"\n=== {name}: ОТВЕТ за {took:.1f}с, {len(raw)} байт, {len(leaves)} полей")
            _verdict(raw, leaves)
            print("\n  Ответ целиком (до 2500 знаков):")
            print(json.dumps(data, ensure_ascii=False, indent=2)[:2500])

    print(f"\nСырые ответы: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
