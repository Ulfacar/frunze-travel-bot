#!/usr/bin/env python3
"""Собрать оверлей одобрения кусков базы знаний.

Одобрение разрешает боту произносить норму из базы клиенту, поэтому оверлей не
правится руками: он собирается этим скриптом по явному правилу отбора, а результат
проверяется гейтами `tests/test_answers_index.py` и прогоном историй.

Правило отбора — ровно и только это:

  * кусок подлежит одобрению (`approvable`): не несёт метку `[РЕШЕНИЕ]`, которую ТЗ
    запрещает озвучивать клиенту безусловно, и не содержит сумм — решение владельца
    21.10, бот цен не называет вообще;
  * блок входит в область поиска, предписанную ТЗ (стр. 2): 1-2, 5-13, 15-17;
  * текст непустой.

`--labels none` (по умолчанию) подписывает только куски БЕЗ метки. Это строже самого
ТЗ, где `[ПРОВЕРИТЬ]` разрешено произносить мягко, а `[ПРАКТИКА]` — не выдавая за
закон. Так сделано нарочно: правильная формулировка метки не проверяется машинно, и
допуск помеченных кусков требует отдельного решения владельца.

Запуск:
    python scripts/build_answers_approval.py --dry-run
    python scripts/build_answers_approval.py --approved-by "..." [--labels soft]
"""
from __future__ import annotations

import argparse
import collections
from datetime import date
import io
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OVERLAY = ROOT / "knowledge" / "kg_entry" / "answers-approved-v1.1.yaml"
BASIS = ("отбор по правилу scripts/build_answers_approval.py: кусок подлежит одобрению "
         "(нет метки РЕШЕНИЕ, нет сумм), блок в области поиска ТЗ, текст непустой")
CHECKED_BY = "tests/test_answers_index.py + scripts/run_entry_stories.py"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved-by", default="",
                        help="кто разрешил и как это получено — в каждую строку")
    parser.add_argument("--labels", choices=("none", "soft"), default="none",
                        help="none — только куски без метки; soft — плюс ПРОВЕРИТЬ и ПРАКТИКА")
    parser.add_argument("--approved-at", default=date.today().isoformat())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.dry_run and not args.approved_by.strip():
        print("НЕВОЗМОЖНО: без --approved-by оверлей не подписан человеком")
        return 2

    from app.knowledge import answers_approval, answers_index

    index = answers_index.load()
    if index is None:
        print("НЕВОЗМОЖНО: индекс базы знаний не загружается")
        return 2

    pieces = list(index._pieces.values())              # noqa: SLF001
    rows = []
    skipped: collections.Counter[str] = collections.Counter()
    for piece in pieces:
        if not piece.get("approvable"):
            skipped["метка РЕШЕНИЕ" if "РЕШЕНИЕ" in piece["labels"] else "сумма"] += 1
            continue
        marks = list(piece["labels"]) + [
            kind for kind in piece["inherited_labels"] if kind not in piece["labels"]]
        if args.labels == "none" and marks:
            # Унаследованная метка считается так же, как своя: раздел 5.5
            # «Внутренний стандарт качества файлов [ПРАКТИКА]» помечен в ЗАГОЛОВКЕ, и
            # его куски без собственной метки проскакивали фильтр. Найдено ревью 22.10.
            skipped[f"метка {', '.join(marks)}"] += 1
            continue
        if not str(piece.get("text") or "").strip():
            skipped["пустой текст"] += 1
            continue
        rows.append({
            "piece_id": piece["piece_id"],
            "text_sha256": piece["text_sha256"],
            "block": piece["block"],
            "section": piece["section"],
            "pdf_pages": piece["pdf_pages"],
            "basis": BASIS,
            "approved_by": args.approved_by or "(не подписано — dry-run)",
            "checked_by": CHECKED_BY,
            "approved_at": args.approved_at,
        })

    rows.sort(key=lambda row: row["piece_id"])
    print(f"кусков в индексе: {len(pieces)}")
    print(f"будет одобрено:   {len(rows)}")
    print("по блокам ТЗ:")
    by_block = collections.Counter(row["block"] for row in rows)
    for block, count in sorted(by_block.items()):
        print(f"   блок {block:2d}: {count:4d}")
    print("пропущено:")
    for reason, count in skipped.most_common():
        print(f"   {reason}: {count}")

    if args.dry_run:
        print("\n--dry-run: файл не записан")
        return 0

    doc = {
        "schema_version": answers_approval.SCHEMA_VERSION,
        "corpus_hash": index.corpus_hash,
        "source_hash": index.source_hash,
        "approved": rows,
    }
    OVERLAY.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n",
                       encoding="utf-8")
    print(f"\nзаписан {OVERLAY.relative_to(ROOT)}")
    print("НЕ ЗАБЫТЬ: добавить COPY этого файла в Dockerfile — иначе на проде "
          "одобрено ничего при зелёном /health (тест это проверяет)")
    return 0


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    raise SystemExit(main())
