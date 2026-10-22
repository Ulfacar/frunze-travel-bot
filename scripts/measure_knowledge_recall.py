#!/usr/bin/env python3
"""Замер полноты поиска по базе знаний: находит ли он нужный раздел.

Зачем. Подключать поиск к клиенту, не зная его точности, нельзя: бот будет уверенно
отвечать из неверного раздела либо постоянно передавать человеку. Порог приёмки задан в
плане: **top-3 не ниже 80% на каждом языке**. Английский считается отдельно, потому что
въездную ветку обслуживают иностранцы, а токенизатор поиска знает лишь десяток алиасов
EN→RU и режет русские слова до шестибуквенной основы.

Ищем с `approved_only=False`: замер отвечает на вопрос «хорошо ли ранжирование», а не
«что уже одобрено человеком». Иначе пустой оверлей дал бы нули и скрыл бы качество.

Запуск:
    python scripts/measure_knowledge_recall.py
    python scripts/measure_knowledge_recall.py --limit 5 --verbose
"""
from __future__ import annotations

import argparse
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

QUERIES = ROOT / "scenarios" / "kg_knowledge_queries.json"
THRESHOLD = 0.80


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queries", default=str(QUERIES))
    parser.add_argument("--limit", type=int, default=3, help="сколько кусков смотреть")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    from app.knowledge import answers_index

    index = answers_index.load()
    if index is None:
        print("НЕВОЗМОЖНО: индекс базы знаний не загружается")
        return 2
    print(f"кусков в индексе: {len(index)}")

    doc = json.loads(Path(args.queries).read_text(encoding="utf-8"))
    rows = doc["queries"]
    stats: dict[str, dict[str, int]] = {}

    for row in rows:
        language = row.get("lang", "ru")
        bucket = stats.setdefault(language, {"total": 0, "top1": 0, "topn": 0})
        bucket["total"] += 1
        found = index.search(row["q"], limit=args.limit, approved_only=False)
        sections = [piece.get("section") for piece in found]
        expected = set(row["expect"])
        hit1 = bool(sections) and sections[0] in expected
        hitn = any(section in expected for section in sections)
        bucket["top1"] += int(hit1)
        bucket["topn"] += int(hitn)
        mark = "точно" if hit1 else ("в тройке" if hitn else "МИМО")
        print(f"  [{mark:9s}] {row['q'][:58]:60s} → {', '.join(s or '-' for s in sections) or 'ничего'}"
              f"   (ждали {', '.join(sorted(expected))})")
        if args.verbose and found:
            for piece in found:
                print(f"               {piece['section']:8s} {piece['title'][:50]:52s} "
                      f"{piece['kind']:10s} {len(piece['text']):4d} симв. метки {piece['labels']}")

    print()
    failed = False
    for language in sorted(stats):
        bucket = stats[language]
        top1 = bucket["top1"] / bucket["total"]
        topn = bucket["topn"] / bucket["total"]
        verdict = "порог взят" if topn >= THRESHOLD else "НИЖЕ ПОРОГА"
        print(f"{language}: вопросов {bucket['total']}, точно {top1:.0%}, "
              f"в top-{args.limit} {topn:.0%} — {verdict}")
        failed = failed or topn < THRESHOLD

    if failed:
        print(f"\nПорог {THRESHOLD:.0%} в top-{args.limit} не взят. Инструмент к клиенту "
              "подключать нельзя: сначала улучшения поиска (карта блоков в промпте, "
              "словарь EN→RU, вес заголовка), потом повторный замер.")
        return 1
    print(f"\nПорог {THRESHOLD:.0%} в top-{args.limit} взят на каждом языке.")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())
