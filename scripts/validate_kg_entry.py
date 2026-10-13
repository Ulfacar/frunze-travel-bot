"""Локальная проверка E5-02A. Нет импорта настроек, БД или отправки сообщений."""
from __future__ import annotations

import argparse
from datetime import date, datetime
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.bundle import country_registry, preflight_bundle
from app.knowledge.slots import SlotContext, validate_slots
from app.knowledge.validation import InvalidDocument, load_document


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    bundle = commands.add_parser("bundle", help="Preflight only; never imports or publishes")
    bundle.add_argument("directory", type=Path)
    bundle.add_argument("--source", type=Path, required=True)
    slots = commands.add_parser("slots", help="Validate input questionnaire without persistence")
    slots.add_argument("document", type=Path)
    slots.add_argument("--countries", type=Path, required=True)
    slots.add_argument("--profile", choices=("collecting", "handoff"), default="collecting")
    slots.add_argument("--today", type=date.fromisoformat,
                       default=datetime.now(ZoneInfo("Asia/Bishkek")).date())
    args = parser.parse_args(argv)
    try:
        if args.command == "bundle":
            report = preflight_bundle(args.directory, args.source)
        else:
            _, known = country_registry(load_document(args.countries))
            report = validate_slots(load_document(args.document),
                                    context=SlotContext(known, args.today), profile=args.profile)
        result = report.summary()
    except InvalidDocument as exc:
        from dataclasses import asdict
        result = {"ok": False, "errors": [asdict(exc.issue)], "warnings": []}
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
