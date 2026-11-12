#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Калибровка автозакрытия на истории. ТОЛЬКО ЧТЕНИЕ, ничего не пишет.

По правилам проекта детектор с порогом нельзя включать без калибровки на реальных
данных (`CLAUDE.md` §2.4, класс C). Автозакрытие — ровно такой детектор: порог
`auto_close_after_days` решает, через сколько дней молчания клиент считается
потерянным и получает исход «Не реализовано» с причиной «Не выходит на связь».

## Что именно меряем

Единственная ошибка, которая здесь дорого стоит, — закрыть клиента, который ещё
вернётся. Поэтому меряем долю ЛОЖНЫХ закрытий: берём каждый эпизод молчания в
истории, смотрим, закрыл бы его порог, и проверяем, написал ли клиент после этого
снова. Написал — закрытие было бы ошибкой.

## Чего эта калибровка НЕ проверяет, и почему

`select_closable` требует трёх выполненных касаний. Касания включили только
11.11.2026, поэтому в истории их нет почти ни у кого: проверять это условие на
прошлом нечем, и прогон считал бы ноль кандидатов при любом пороге — бесполезный
результат, похожий на хороший. Здесь условие касаний намеренно считается
выполненным, и меряется именно порог молчания, то есть та часть правила, у которой
есть настраиваемое число. Это ограничение, а не допущение: закрытие после трёх
касаний не может быть ЧАЩЕ, чем закрытие по одному молчанию, так что полученная доля
ложных — верхняя граница.

Эпизодом считается молчание после последнего входящего: клиент написал, потом N дней
тишины. Если после этой точки он написал снова — закрытие было бы ложным.

Запуск:
    docker cp scripts/auto_close_replay.py frunze-travel-app-1:/tmp/acr.py
    docker exec -e PYTHONPATH=/app frunze-travel-app-1 python /tmp/acr.py
    docker exec -e PYTHONPATH=/app frunze-travel-app-1 python /tmp/acr.py --funnel tours
"""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from app.admin import router as ar

# Пороги, которые имеет смысл сравнить. 7 — текущий дефолт.
THRESHOLDS = (5, 7, 10, 14, 21, 30)

QUERY = """
SELECT c.user_id, m.sender, m.created_at
FROM conversations c
JOIN messages m ON m.conversation_id = c.id
WHERE c.funnel = :funnel AND NOT c.archived
ORDER BY c.user_id, m.created_at
"""


def episodes(timeline: list[tuple[str, datetime]], threshold_days: int,
             now: datetime) -> tuple[int, int]:
    """(сколько закрыли бы, сколько из них вернулись) по одному диалогу.

    Эпизод: входящее клиента, затем `threshold_days` без входящих. Считаем только
    эпизоды, которые УСПЕЛИ дозреть (порог прошёл до «сейчас»), иначе свежие диалоги
    выглядели бы как «клиент не вернулся» просто потому, что ещё рано.
    """
    inbound = [ts for sender, ts in timeline if sender == "client"]
    if not inbound:
        return 0, 0
    closed = returned = 0
    for i, ts in enumerate(inbound):
        deadline = ts + timedelta(days=threshold_days)
        if deadline > now:
            break                      # эпизод ещё не дозрел — не считаем
        nxt = inbound[i + 1] if i + 1 < len(inbound) else None
        if nxt is not None and nxt <= deadline:
            continue                   # клиент написал раньше порога — молчания не было
        closed += 1
        if nxt is not None:
            returned += 1              # написал ПОСЛЕ того, как его бы закрыли
    return closed, returned


async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--funnel", default="visa")
    args = ap.parse_args()

    now = datetime.now(timezone.utc)
    timelines: dict[str, list[tuple[str, datetime]]] = defaultdict(list)
    async with ar._domain_sessionmaker()() as s:
        for user_id, sender, created in (await s.execute(
                text(QUERY), {"funnel": args.funnel})).all():
            ts = created.replace(tzinfo=timezone.utc) if created.tzinfo is None else created
            timelines[user_id].append((sender, ts))

    print(f"воронка: {args.funnel} | диалогов с перепиской: {len(timelines)}")
    print("\nпорог | закрыли бы | из них вернулись | доля ложных")
    print("------|------------|------------------|------------")
    for days in THRESHOLDS:
        closed = returned = 0
        for timeline in timelines.values():
            c, r = episodes(timeline, days, now)
            closed += c
            returned += r
        share = (100.0 * returned / closed) if closed else 0.0
        mark = "  ← текущий" if days == 7 else ""
        print(f"{days:5} | {closed:10} | {returned:16} | {share:9.1f}%{mark}")

    print("\nКак читать: «доля ложных» — сколько процентов закрытых клиентов потом")
    print("написали снова. Это верхняя граница: реальное правило закрывает только")
    print("после трёх касаний, то есть реже.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
