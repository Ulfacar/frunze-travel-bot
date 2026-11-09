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
# Куски, подпись с которых СНЯТА решением владельца. Правило отбора машинное и о
# таких решениях знать не может: без этого списка повторный запуск скрипта молча
# вернул бы снятые подписи, и бот снова начал бы произносить снятое. Поэтому список
# живёт здесь, рядом с правилом, и каждая строка несёт причину и дату.
UNSIGNED: dict[str, str] = {
    # Истёкший срок: льготная сетка швейной отрасли действовала до 01.11.2026.
    # Встреча с владельцем 30.10.2026: «снимаем этот вопрос, передаём менеджеру».
    "KG.KB.12.3#011": "льгота ТПП истекла 01.11.2026 (решение владельца 30.10)",
    # Ответ владельца 5.5 от 05.11.2026 «снимаем»: формулировки для сотрудника, а не
    # ответ клиенту. Коды статусов в таблице блока 17 этим списком НЕ закрываются —
    # там вырезан служебный столбец (`answerable.without_service_columns`), и 41
    # подпись осталась в силе.
    "KG.KB.1.1#003": "«сопровождаем, только менеджер (не бот)» (ответ 5.5)",
    "KG.KB.6.2#003": "«данные копируются из CRM на портал» (ответ 5.5)",
    "KG.KB.6.3#014": "«чей e-mail указывать» — в ТЗ стоит [РЕШЕНИЕ] (ответ 5.5)",
    "KG.KB.6.3#016": "внутренняя оргструктура: ответственный, дублёр (ответ 5.5)",
    "KG.KB.7.0#019": "«кто отвечает» — внутренняя роль (ответ 5.5)",
    "KG.KB.7.0#024": "«копия — в CRM» (ответ 5.5)",
    "KG.KB.16.3#001": "«копия — в CRM» (ответ 5.5)",
    "KG.KB.16.5#001": "контрольный календарь менеджера: «→ статус V24» (ответ 5.5)",
    "KG.KB.16.5#004": "контрольный календарь менеджера: «флаг X11» (ответ 5.5)",
    "KG.KB.17.0#022": "код статуса «V18:» внутри ответа (ответ 5.5)",
}

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
    # Текущий оверлей читаем ДО перезаписи — только ради следа вывода. Ключ включает
    # хеш: если текст с тех пор менялся снова, старый след к нему не относится.
    carried: dict[tuple[str, str], dict[str, str]] = {}
    if OVERLAY.exists():
        try:
            for row in json.loads(OVERLAY.read_text(encoding="utf-8")).get("approved") or ():
                trail = {k: row[k] for k in ("derived_from_sha256", "derivation") if row.get(k)}
                if trail:
                    carried[(str(row.get("piece_id")), str(row.get("text_sha256")))] = trail
        except (OSError, ValueError) as exc:
            print(f"ВНИМАНИЕ: текущий оверлей не прочитан ({type(exc).__name__}) — "
                  "след вывода подписей будет потерян")
    for piece in pieces:
        if piece["piece_id"] in UNSIGNED:
            skipped["снято решением владельца"] += 1
            continue
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
        # След вывода (`derived_from_sha256`, `derivation`) переносим из текущего
        # оверлея, если хеш не изменился: иначе перегенерация стёрла бы запись о том,
        # что подпись человека стоит под ДОРЕЗАННЫМ текстом, и строка снова выглядела
        # бы прочитанной глазами. Ревью 09.11.2026.
        trail = carried.get((piece["piece_id"], piece["text_sha256"]), {})
        rows.append({
            "piece_id": piece["piece_id"],
            "text_sha256": piece["text_sha256"],
            **trail,
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
