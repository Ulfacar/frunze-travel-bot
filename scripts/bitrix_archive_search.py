#!/usr/bin/env python3
"""Поиск старого клиента в архиве Bitrix по телефону (после отключения портала).

Читает только файлы, которые сделал `scripts/bitrix_archive_export.py`. Ничего не
пишет. Совпадение — по последним 9 цифрам номера (кыргызские номера пишут и с 996,
и с 0, и без кода), для иностранных — по полному номеру.

    python scripts/bitrix_archive_search.py --dir /root/bitrix-archive 0555 123 456
    python scripts/bitrix_archive_search.py --dir /root/bitrix-archive +77011234567 --full
    python scripts/bitrix_archive_search.py --dir /root/bitrix-archive 0555123456 --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

MIN_DIGITS = 7
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


def search(archive: Path, phone: str, *, with_comments: bool = False) -> dict:
    q = _digits(phone)
    if len(q) < MIN_DIGITS:
        raise ValueError(f"нужно не меньше {MIN_DIGITS} цифр номера")
    contacts = [c for c in _jsonl(archive / "contacts.jsonl")
                if any(phone_matches(q, d) for d in _phones(c))]
    contact_ids = {str(c.get("ID")) for c in contacts}
    leads = [x for x in _jsonl(archive / "leads.jsonl")
             if any(phone_matches(q, d) for d in _phones(x))
             or str(x.get("CONTACT_ID") or "") in contact_ids]
    lead_ids = {str(x.get("ID")) for x in leads}
    deals = [x for x in _jsonl(archive / "deals.jsonl")
             if str(x.get("CONTACT_ID") or "") in contact_ids
             or str(x.get("LEAD_ID") or "") in lead_ids]
    deal_ids = {str(x.get("ID")) for x in deals}
    timeline: dict[str, list] = {}
    for rec in _jsonl(archive / "timeline.jsonl"):
        key = f"{rec.get('entity_type')}:{rec.get('entity_id')}"
        if (rec.get("entity_type") == "lead" and str(rec.get("entity_id")) in lead_ids) or (
                rec.get("entity_type") == "deal" and str(rec.get("entity_id")) in deal_ids):
            timeline[key] = rec.get("comments") or []
    return {"query_tail": q[-TAIL:], "contacts": contacts, "leads": leads, "deals": deals,
            "timeline": timeline if with_comments else {k: len(v) for k, v in timeline.items()}}


def _name(r: dict) -> str:
    parts = [r.get("NAME"), r.get("SECOND_NAME"), r.get("LAST_NAME")]
    return " ".join(p for p in parts if p) or (r.get("TITLE") or "без имени")


def render(found: dict, *, with_comments: bool) -> str:
    lines = []
    if not (found["contacts"] or found["leads"] or found["deals"]):
        return f"Ничего не найдено по номеру …{found['query_tail']}"
    for c in found["contacts"]:
        lines.append(f"Контакт #{c.get('ID')}: {_name(c)} · создан {str(c.get('DATE_CREATE') or '')[:10]}"
                     f" · ответственный {c.get('ASSIGNED_BY_ID') or '—'}")
    for x in sorted(found["leads"], key=lambda r: str(r.get("DATE_CREATE") or "")):
        n = found["timeline"].get(f"lead:{x.get('ID')}")
        count = len(n) if isinstance(n, list) else (n or 0)
        lines.append(f"Лид #{x.get('ID')}: {x.get('TITLE') or _name(x)} · статус {x.get('STATUS_ID') or '—'}"
                     f" · {str(x.get('DATE_CREATE') or '')[:10]} · ответственный "
                     f"{x.get('ASSIGNED_BY_ID') or '—'} · комментариев {count}")
        if x.get("COMMENTS"):
            lines.append(f"    {str(x['COMMENTS'])[:300]}")
        if with_comments and isinstance(n, list):
            for cm in n:
                lines.append(f"    [{str(cm.get('CREATED') or '')[:16]}] {str(cm.get('COMMENT') or '')[:500]}")
    for d in sorted(found["deals"], key=lambda r: str(r.get("DATE_CREATE") or "")):
        n = found["timeline"].get(f"deal:{d.get('ID')}")
        count = len(n) if isinstance(n, list) else (n or 0)
        lines.append(f"Сделка #{d.get('ID')}: {d.get('TITLE') or '—'} · стадия {d.get('STAGE_ID') or '—'}"
                     f" · сумма {d.get('OPPORTUNITY') or '—'} {d.get('CURRENCY_ID') or ''}"
                     f" · {str(d.get('DATE_CREATE') or '')[:10]} · комментариев {count}")
        if with_comments and isinstance(n, list):
            for cm in n:
                lines.append(f"    [{str(cm.get('CREATED') or '')[:16]}] {str(cm.get('COMMENT') or '')[:500]}")
    return "\n".join(lines)


def main(argv: list[str] | None = None, stdout=None) -> int:
    p = argparse.ArgumentParser(description="Поиск клиента в архиве Bitrix по телефону")
    p.add_argument("--dir", required=True, help="каталог архива")
    p.add_argument("phone", nargs="+", help="номер в любом виде")
    p.add_argument("--full", action="store_true", help="показать комментарии таймлайна")
    p.add_argument("--json", action="store_true", help="вывести JSON")
    args = p.parse_args(argv)
    out = stdout or sys.stdout
    archive = Path(args.dir)
    if not (archive / "leads.jsonl").exists() and not (archive / "contacts.jsonl").exists():
        print(f"В {archive} нет архива (leads.jsonl / contacts.jsonl).", file=out)
        return 2
    try:
        found = search(archive, " ".join(args.phone), with_comments=args.full or args.json)
    except ValueError as exc:
        print(str(exc), file=out)
        return 2
    if args.json:
        json.dump(found, out, ensure_ascii=False, indent=1)
        out.write("\n")
    else:
        print(render(found, with_comments=args.full), file=out)
    return 0 if (found["contacts"] or found["leads"] or found["deals"]) else 1


if __name__ == "__main__":
    sys.exit(main())
