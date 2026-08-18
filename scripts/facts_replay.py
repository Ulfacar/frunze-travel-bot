#!/usr/bin/env python3
"""Замер разбора фактов по РЕАЛЬНОЙ переписке, а не по придуманным фразам.

Закон 5 (`docs/venom-v2.md`): тесты проверяют логику («извлечёт ли бюджет из фразы»),
а не калибровку («как часто ошибётся на нашем трафике»). Это разные вопросы, и второй
тестом на поведение не закрывается — сторож каналов мы так уже выкатывали трижды.

Скрипт гоняет `app.agent.facts.extract` по последним клиентским сообщениям туровых
каналов и печатает, что именно он из них достал. Смотреть глазами: ошибка здесь —
это чужой бюджет в карточке менеджера.

Порог приёмки из ТЗ: на сотне размеченных сообщений не больше 2 неверных извлечений
и НИ ОДНОГО неверного бюджета — бюджет уезжает в сумму сделки.

Запуск внутри контейнера прода:
    docker exec -w /app frunze-travel-app-1 python facts_replay.py --limit 500
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.agent import facts  # noqa: E402


async def _messages(limit: int, bot_prefix: str) -> list[str]:
    from sqlalchemy import select
    from app.integrations.crm.db import ConvMessage, Conversation, get_sessionmaker

    sm = get_sessionmaker()
    async with sm() as session:
        rows = await session.execute(
            select(ConvMessage.text)
            .join(Conversation, Conversation.id == ConvMessage.conversation_id)
            .where(ConvMessage.sender == "client")
            .where(Conversation.bot_id.like(f"{bot_prefix}%"))
            # Синтетические диалоги симулятора (`sim_tour_card.py`) в замер не берём:
            # они написаны мной и мерили бы мой же разбор об мои же фразы.
            .where(~Conversation.user_id.like("%99670000%"))
            .order_by(ConvMessage.id.desc())
            .limit(limit)
        )
        return [r[0] for r in rows if (r[0] or "").strip()]


async def main(limit: int, bot_prefix: str, show: int) -> int:
    texts = await _messages(limit, bot_prefix)
    print(f"=== разобрано сообщений: {len(texts)}")

    hits: Counter = Counter()
    examples: dict[str, list[tuple[str, str]]] = {}
    silent = 0
    for text in texts:
        found = facts.extract(text)
        if not found:
            silent += 1
            continue
        for field, value in found.items():
            hits[field] += 1
            examples.setdefault(field, []).append((str(value), text.replace("\n", " ")[:70]))

    touched = len(texts) - silent
    share = (touched / len(texts) * 100) if texts else 0
    print(f"    ничего не нашли: {silent} ({100 - share:.0f}%)")
    print(f"    хоть что-то нашли: {touched} ({share:.0f}%)\n")

    for field, count in hits.most_common():
        print(f"--- {field}: {count}")
        for value, text in examples[field][:show]:
            print(f"      {value:<22} ← {text}")
        print()
    print("Смотреть глазами: каждая строка «значение ← реплика» должна быть правдой.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--bot", default="frunze_tours")
    ap.add_argument("--show", type=int, default=12, help="примеров на поле")
    args = ap.parse_args()
    raise SystemExit(asyncio.run(main(args.limit, args.bot, args.show)))
