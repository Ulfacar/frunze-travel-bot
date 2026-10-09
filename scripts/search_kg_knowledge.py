"""Read-only review search over the pinned PDF corpus; no network/LLM/DB."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.knowledge.retrieval import RetrievalError, load_review_index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--block", type=int)
    args = parser.parse_args(argv)
    try:
        report = load_review_index().search(args.query, limit=args.limit, block=args.block)
    except RetrievalError as exc:
        print(json.dumps({"ok": False, "code": str(exc)}))
        return 1
    print(json.dumps({"ok": True, **report}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
