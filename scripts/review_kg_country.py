"""Read-only country lookup in a local draft bundle. No DB, config, network or publication."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.knowledge.bundle import preflight_bundle
from app.knowledge.country_index import CountryIndexError, CountryRuleIndex, DOCUMENT_TYPES


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--source", type=Path, required=True)
    query = parser.add_mutually_exclusive_group(required=True)
    query.add_argument("--country", help="ISO3 or explicit alias in this bundle")
    query.add_argument("--summary", action="store_true")
    parser.add_argument("--document-type", choices=sorted(DOCUMENT_TYPES), default="ordinary")
    args = parser.parse_args(argv)
    report = preflight_bundle(args.directory, args.source)
    if not report.ok:
        result = report.summary()
    else:
        try:
            index = CountryRuleIndex(**report.normalized_bundle, source_hash=report.normalized_bundle["meta"]["source_hash"])
            result = {"ok": True, **(index.summary() if args.summary else
                                     index.lookup(args.country, document_type=args.document_type))}
        except CountryIndexError as exc:
            result = {"ok": False, "code": exc.code}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
