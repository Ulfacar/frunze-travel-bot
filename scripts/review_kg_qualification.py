"""Read-only unified review of a partial profile; no DB, environment or network."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.knowledge.bundle import preflight_bundle
from app.knowledge.qualification import QualificationReview
from app.knowledge.validation import InvalidDocument, load_document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--catalog", type=Path)
    args = parser.parse_args(argv)
    try:
        checked = preflight_bundle(args.directory, args.source)
        if not checked.ok:
            result = checked.summary()
        else:
            catalog = load_document(args.catalog) if args.catalog else None
            result = {"ok": True, **QualificationReview(**checked.normalized_bundle,
                source_hash=checked.normalized_bundle["meta"]["source_hash"], catalog=catalog).evaluate(load_document(args.request))}
    except (InvalidDocument, ValueError, TypeError, KeyError, OSError):
        result = {"ok": False, "code": "qualification_input_invalid"}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
