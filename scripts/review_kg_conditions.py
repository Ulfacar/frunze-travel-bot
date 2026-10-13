"""Read-only profile check against unapproved conditions; never decides permission to enter."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge.bundle import preflight_bundle
from app.knowledge.conditions import ConditionError, ConditionReview
from app.knowledge.validation import InvalidDocument, load_document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=ROOT / "knowledge/kg_entry/conditions_v1_1/catalog.json")
    parser.add_argument("--facts", type=Path, required=True, help="No names, passport numbers or contacts")
    args = parser.parse_args(argv)
    report = preflight_bundle(args.directory, args.source)
    if not report.ok:
        result = report.summary()
    else:
        try:
            review = ConditionReview(load_document(args.catalog), **report.normalized_bundle,
                                     source_hash=report.normalized_bundle["meta"]["source_hash"])
            result = {"ok": True, **review.evaluate(load_document(args.facts))}
        except (ConditionError, InvalidDocument) as exc:
            result = {"ok": False, "code": exc.code if isinstance(exc, ConditionError) else exc.issue.code}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
