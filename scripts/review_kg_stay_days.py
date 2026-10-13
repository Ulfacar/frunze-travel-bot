"""Read-only CALC-02 scenarios; proposed counting policy cannot approve a client answer."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge.bundle import preflight_bundle
from app.knowledge.stay_days import StayDayReview, StayReviewError
from app.knowledge.validation import InvalidDocument, load_document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True, help="Review history snapshot, no contacts or passport numbers")
    args = parser.parse_args(argv)
    report = preflight_bundle(args.directory, args.source)
    if not report.ok:
        output = report.summary()
    else:
        try:
            calculator = StayDayReview(**report.normalized_bundle, source_hash=report.normalized_bundle["meta"]["source_hash"])
            output = {"ok": True, **calculator.evaluate(load_document(args.request))}
        except (StayReviewError, InvalidDocument) as exc:
            output = {"ok": False, "code": exc.code if isinstance(exc, StayReviewError) else exc.issue.code}
    print(json.dumps(output, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
