#!/usr/bin/env python
"""Прогон сторожа СБОЕВ по реальной истории — до выкатки, а не после.

Зачем. 17-22.09.2026 OpenRouter отдавал `402`, бот шесть дней отвечал клиентам отпиской
«Секундочку, уточню детали и вернусь к вам», и сторож сбоев не сказал НИ СЛОВА. Разбор
показал две причины, и порог — только вторая:

    1. `watchdog.run` выходил первой строкой: `ALERT_WHATSAPP_TO`/`ALERT_BOT_ID` пусты,
       а тумблер `watchdog_telegram_enabled` не включён. Адресата нет — сторожа нет.
    2. Порог `alert_fail_threshold = 5` сравнивался с приростом ЗА ТИК (300 секунд).
       Авария шла ровным потоком ~1.7 сбоя за тик и под такой порог не попадала.

Здесь проверяется второе. Первое порогами не лечится.

Почему нельзя было взять порог из рассуждения: ровно на этом обожглись трижды в августе
со сторожем тишины — там пороги трижды брали «по смыслу», и трижды прод оказывался
человеком, которому это приходило. Вся преамбула `scripts/alert_replay.py` про это.

Скрипт зовёт НАСТОЯЩУЮ `watchdog.decide()`, а не копию логики: копия разошлась бы с кодом
на второй правке и снова врала бы.

Откуда берётся история. Счётчики сбоев живут в памяти процесса (`observ._COUNTERS`), и
переживших аварию логов уже нет — контейнер пересоздан. Зато каждый сбой оставил след
у клиента: аварийная отписка записана в `messages`. Её и берём за ряд событий:

    ssh root@62.171.185.155 "docker exec frunze-travel-db-1 psql -U postgres -d frunze \
      -t -A -c \\"select extract(epoch from created_at)::bigint from messages
        where sender='bot' and text like '%Секундочку%'
          and created_at > now() - interval '30 days' order by 1\\"" > failures.csv

    python scripts/watchdog_replay.py failures.csv
    python scripts/watchdog_replay.py failures.csv --window 60 --window-threshold 6
"""
from __future__ import annotations

import argparse
import collections
import datetime
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.core import watchdog  # noqa: E402

TICK = 300.0


class Cfg:
    """Только то, что читает `decide`. Ночь не трогаем: сбои будят и ночью."""

    alert_silence_minutes = 30
    alert_fail_threshold = 5
    alert_cooldown_minutes = 60
    alert_fail_window_minutes = 60
    alert_fail_window_threshold = 6


def load(path: pathlib.Path) -> list[int]:
    out = []
    for chunk in path.read_text(encoding="utf-8").split():
        chunk = chunk.strip().strip(",")
        if chunk.isdigit():
            out.append(int(chunk))
    return sorted(out)


def replay(events: list[int], cfg) -> list[float]:
    """Тик за тиком, как это делает планировщик. Возвращает моменты тревог.

    `last_inbound_ago=None` — тишину вебхуков здесь не меряем, иначе она примешала бы
    к счёту свои тревоги и ответ был бы не про сбои.
    """
    if not events:
        return []
    state = {"alert_silence_ts": 0.0, "alert_fail_ts": 0.0, "fail_baseline": 0.0,
             "fail_window": []}
    fired: list[float] = []
    total = 0
    idx = 0
    now = float(events[0])
    end = float(events[-1]) + TICK
    while now <= end:
        while idx < len(events) and events[idx] <= now:
            total += 1
            idx += 1
        alerts = watchdog.decide(now, None, {"llm_failures": total, "send_failures": 0},
                                 state, cfg, night=False)
        if alerts:
            fired.append(now)
        now += TICK
    return fired


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=pathlib.Path)
    ap.add_argument("--threshold", type=int, help="порог всплеска за тик")
    ap.add_argument("--window", type=int, help="окно, минут")
    ap.add_argument("--window-threshold", type=int, help="порог за окно")
    args = ap.parse_args()

    cfg = Cfg()
    if args.threshold is not None:
        cfg.alert_fail_threshold = args.threshold
    if args.window is not None:
        cfg.alert_fail_window_minutes = args.window
    if args.window_threshold is not None:
        cfg.alert_fail_window_threshold = args.window_threshold

    events = load(args.path)
    if not events:
        print("в файле нет событий")
        return

    day = lambda ts: datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%d.%m")
    by_day_events = collections.Counter(day(t) for t in events)
    fired = replay(events, cfg)
    by_day_alerts = collections.Counter(day(t) for t in fired)

    span_days = max(1.0, (events[-1] - events[0]) / 86400)
    print(f"событий: {len(events)} за {span_days:.1f} дн.")
    print(f"настройки: всплеск >={cfg.alert_fail_threshold}/тик, "
          f"окно {cfg.alert_fail_window_minutes} мин >={cfg.alert_fail_window_threshold}, "
          f"cooldown {cfg.alert_cooldown_minutes} мин")
    print(f"тревог всего: {len(fired)}  ({len(fired)/span_days:.2f} в сутки)")
    print()
    print("день   сбоев  тревог")
    for d in sorted(set(by_day_events) | set(by_day_alerts),
                    key=lambda x: (x[3:], x[:2])):
        print(f"{d}  {by_day_events.get(d, 0):5}  {by_day_alerts.get(d, 0):5}")


if __name__ == "__main__":
    main()
