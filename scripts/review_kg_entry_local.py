"""Read-only review of an existing local SQLite knowledge DB; no .env or migrations."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.ext.asyncio import create_async_engine
from app.domain.knowledge_review import review_versions
from app.domain.permissions import Actor


async def run(path, set_id, candidate, baseline):
    import aiosqlite
    path = path.resolve()
    if not path.is_file() or str(path).startswith("\\\\"):
        raise ValueError("existing local SQLite file required")

    async def connect():
        # Driver-level read-only; opening a missing path cannot create a new DB.
        return await aiosqlite.connect(path.as_uri() + "?mode=ro", uri=True)
    engine = create_async_engine("sqlite+aiosqlite://", async_creator=connect)
    try:
        return await review_versions(engine, actor=Actor("local-operator", is_full_admin=True),
                                     set_id=set_id, candidate_id=candidate, baseline_id=baseline)
    finally:
        await engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--set-id", type=int, required=True)
    parser.add_argument("--candidate", type=int, required=True)
    parser.add_argument("--baseline", type=int, help="Default: active version; if none, compare against no baseline")
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run(args.db, args.set_id, args.candidate, args.baseline))
    except Exception:
        print(json.dumps({"ok": False, "code": "review_unavailable",
                          "message": "Check database, identifiers and snapshot integrity."}))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
