"""Поиск по архиву Bitrix24 (JSONL, `scripts/bitrix_archive_export.py`) — только чтение.

Общий код для командной строки (`scripts/bitrix_archive_search.py`) и страницы панели
«Архив Битрикса» (`app/admin/bitrix_archive.py`). Файлы читаются построчно: в памяти
только совпавшие записи, поэтому архив любого размера не грузится целиком.
Совпадение — по последним 9 цифрам номера (кыргызские номера пишут и с 996, и с 0, и
без кода), для иностранных — по полному номеру.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

LIMIT = 100
# Сравнение идёт по последним TAIL цифрам: 7–8 цифр раньше принимались и молча ничего
# не находили (ревью ux 30.10, A3). Меньше TAIL — просим номер целиком.
MIN_DIGITS = 9
TAIL = 9


def _digits(value) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _phones(record: dict) -> list[str]:
    out = []
    for item in record.get("PHONE") or []:
        value = item.get("VALUE") if isinstance(item, dict) else item
        d = _digits(value)
        if d:
            out.append(d)
    return out


def phone_matches(query: str, candidate: str) -> bool:
    if len(query) >= 11 and len(candidate) >= 11 and not (
            query.startswith("996") or candidate.startswith("996")):
        return query == candidate                      # иностранный номер — целиком
    return candidate[-TAIL:] == query[-TAIL:]


def _jsonl(path: Path):
    if not path.exists():
        return
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue                            # оборванная строка при выгрузке


def search(archive: Path, phone: str, *, with_comments: bool = False,
           limit: int = LIMIT) -> dict:
    """Четыре потоковых прохода по файлам: в памяти только совпавшее, не весь архив.

    `limit` — не больше стольких записей каждого типа (общая карточка Открытой линии
    или мусорный номер вроде 000000000 не должны вывалить в ответ тысячи строк)."""
    q = _digits(phone)
    if len(q) < MIN_DIGITS:
        raise ValueError(f"нужно не меньше {MIN_DIGITS} цифр номера")
    truncated = False

    def take(rows):
        nonlocal truncated
        out = []
        for row in rows:
            if len(out) >= limit:
                truncated = True
                break
            out.append(row)
        return out
    contacts = take(c for c in _jsonl(archive / "contacts.jsonl")
                    if any(phone_matches(q, d) for d in _phones(c)))
    contact_ids = {str(c.get("ID")) for c in contacts}
    leads = take(x for x in _jsonl(archive / "leads.jsonl")
                 if any(phone_matches(q, d) for d in _phones(x))
                 or str(x.get("CONTACT_ID") or "") in contact_ids)
    lead_ids = {str(x.get("ID")) for x in leads}
    deals = take(x for x in _jsonl(archive / "deals.jsonl")
                 if str(x.get("CONTACT_ID") or "") in contact_ids
                 or str(x.get("LEAD_ID") or "") in lead_ids)
    deal_ids = {str(x.get("ID")) for x in deals}
    timeline: dict[str, list] = {}
    for rec in _jsonl(archive / "timeline.jsonl"):
        key = f"{rec.get('entity_type')}:{rec.get('entity_id')}"
        if (rec.get("entity_type") == "lead" and str(rec.get("entity_id")) in lead_ids) or (
                rec.get("entity_type") == "deal" and str(rec.get("entity_id")) in deal_ids):
            timeline[key] = rec.get("comments") or []
    return {"query_tail": q[-TAIL:], "contacts": contacts, "leads": leads, "deals": deals,
            "truncated": truncated,
            "timeline": timeline if with_comments else {k: len(v) for k, v in timeline.items()}}
