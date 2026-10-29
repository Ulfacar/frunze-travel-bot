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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.integrations.crm.bitrix_archive import (  # noqa: E402
    MIN_DIGITS, TAIL, _digits, _jsonl, _phones, phone_matches, search)

__all__ = ["MIN_DIGITS", "TAIL", "_digits", "_jsonl", "_phones", "phone_matches", "search"]


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
