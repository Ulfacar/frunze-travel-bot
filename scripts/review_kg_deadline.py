"""Read-only deadline scenarios with explicitly supplied draft calendars."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge.bundle import preflight_bundle
from app.knowledge.deadlines import DeadlineError, DeadlineReview
from app.knowledge.work_calendar import CalendarError
from app.knowledge.validation import InvalidDocument, load_document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--calendars", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    report = preflight_bundle(args.directory, args.source)
    if not report.ok:
        output = report.summary()
    else:
        try:
            calculator = DeadlineReview(**report.normalized_bundle,
                source_hash=report.normalized_bundle["meta"]["source_hash"], calendars=load_document(args.calendars))
            output = {"ok": True, **calculator.evaluate(load_document(args.request))}
        except (DeadlineError, CalendarError, InvalidDocument) as exc:
            output = {"ok": False, "code": exc.issue.code if isinstance(exc, InvalidDocument) else exc.code}
    print(json.dumps(output, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
