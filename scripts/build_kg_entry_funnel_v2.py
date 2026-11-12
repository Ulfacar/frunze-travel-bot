#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Собрать РАБОЧУЮ версию въездной воронки по устным правкам Гриши от 05.11.2026.

Зачем отдельная версия, а не правка черновика. `processes_v1_1/visa-funnel-draft.json`
— это добросовестный перенос воронки из PDF «Визы в Кыргызстан» v1.1, и он должен
таким остаться: по нему сверяют, не потеряли ли мы что-то из документа. Устные правки
владельца — это следующая версия, а не исправление документа. Поэтому исходник не
трогаем, а собираем из него новый файл.

Источник правок: запись разговора 05.11.2026
(`Screen Recording 20261105 143527 WhatsApp.txt`). Три этапа Гриша убрал прямо в
разговоре, его словами:

  V08 «Счёт выставлен»             → «Без счёта, просто оплачено сделать»
  V11 «Ждём приглашающую сторону»  → «приглашающую сторону можно убрать»
  V15 «Черновик на портале»        → «Без черновик на портале»

## Почему коды НЕ перенумеровываются

`V08`, `V11` и `V15` упоминаются в 13–20 файлах каждый: каталог процессов, архив
исходного текста, единицы знаний, документация. Сдвиг нумерации (V09 → V08 и дальше)
молча перенаправил бы все эти ссылки на ДРУГОЙ этап — ошибку такого рода не видно ни
в одном тесте. Поэтому убранные коды остаются выведенными из обращения и больше
никогда не используются; остальные сохраняют свои номера.

Два режима движения — тоже из этой записи: «она будет сама двигать, либо
автоматически», «может быть сразу одобрено, значит перепрыгнет несколько». Записано в
`movement` как требование к публикации, чтобы при переносе в CRM это не потерялось.

Запуск:  python scripts/build_kg_entry_funnel_v2.py
Результат: knowledge/kg_entry/visa-funnel-work-v2.json (ничего не публикует)
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "knowledge" / "kg_entry" / "processes_v1_1" / "visa-funnel-draft.json"
OUT = ROOT / "knowledge" / "kg_entry" / "visa-funnel-work-v2.json"

# Код → дословная фраза Гриши, по которой этап убран. Фраза важнее кода: по ней
# правку можно перепроверить в записи, не веря этому файлу на слово.
REMOVED = {
    "V08": "Без счёта, просто оплачено сделать",
    "V11": "приглашающую сторону можно убрать",
    "V15": "Без черновик на портале",
}

MOVEMENT = {
    "manual": "Менеджер двигает карточку сам",
    "auto": "Часть переходов ставит система",
    "skip_allowed": True,
    "quote": "Там будет возможность перепрыгнуть же несколько воронок… "
             "Ну, она будет сама двигать, либо автоматически",
}


def build() -> dict:
    src = json.loads(SRC.read_text(encoding="utf-8"))
    stages = src["stages"]

    missing = sorted(set(REMOVED) - {s["code"] for s in stages})
    if missing:
        raise SystemExit(f"в черновике нет этапов {missing} — правка уже применена "
                         "или черновик изменился; проверьте руками")

    kept = [s for s in stages if s["code"] not in REMOVED]
    dropped = [s for s in stages if s["code"] in REMOVED]

    return {
        "format": src.get("format"),
        "status": "work_draft_unpublished",
        "based_on": str(SRC.relative_to(ROOT)).replace("\\", "/"),
        "source": "Устные правки Гриши 05.11.2026 поверх PDF v1.1",
        "source_record": "Screen Recording 20261105 143527 WhatsApp.txt",
        "product": src.get("product"),
        "mechanism_note": src.get("mechanism_note"),
        "flags_note": src.get("flags_note"),
        "movement": MOVEMENT,
        "retired_codes": [
            {"code": s["code"], "name": s["name"], "quote": REMOVED[s["code"]]}
            for s in dropped
        ],
        "numbering_note": ("Коды НЕ перенумерованы: V08/V11/V15 упоминаются в 13–20 "
                           "файлах каждый, и сдвиг нумерации молча перенаправил бы "
                           "ссылки на другой этап. Убранные коды выведены из обращения."),
        "stages": kept,
        "transitions": src.get("transitions"),
        "transition_basis": src.get("transition_basis"),
    }


def main() -> int:
    data = build()
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    work = [s for s in data["stages"] if s["code"].startswith("V")]
    exc = [s for s in data["stages"] if s["code"].startswith("X")]
    print(f"записано: {OUT.relative_to(ROOT)}")
    print(f"  рабочих этапов: {len(work)} (было {len(work) + len(REMOVED)})")
    print(f"  исключений:     {len(exc)}")
    print("  убрано по его словам:")
    for item in data["retired_codes"]:
        print(f"    {item['code']} «{item['name']}» — «{item['quote']}»")
    return 0


if __name__ == "__main__":
    sys.exit(main())
