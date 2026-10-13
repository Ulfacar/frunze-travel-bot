"""Review a persisted country/conditions snapshot in read-only local SQLite."""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy.ext.asyncio import create_async_engine
from app.domain.knowledge_projection import review_projection
from app.domain.permissions import Actor
from app.knowledge.validation import load_document


async def run(path, set_id, version_id, country, document_type, facts):
    import aiosqlite
    path = path.resolve()
    if not path.is_file() or str(path).startswith("\\\\"):
        raise ValueError("existing local SQLite file required")

    async def connect():
        return await aiosqlite.connect(path.as_uri() + "?mode=ro", uri=True)
    engine = create_async_engine("sqlite+aiosqlite://", async_creator=connect)
    try:
        return await review_projection(engine, actor=Actor("local-operator", is_full_admin=True),
                                       set_id=set_id, version_id=version_id, country=country,
                                       document_type=document_type, facts=facts)
    finally:
        await engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--set-id", type=int, required=True)
    parser.add_argument("--version-id", type=int, required=True)
    parser.add_argument("--country", required=True)
    parser.add_argument("--document-type", default="ordinary")
    parser.add_argument("--facts", type=Path)
    args = parser.parse_args(argv)
    try:
        facts = load_document(args.facts) if args.facts else None
        if args.facts and facts is None:
            raise ValueError("explicit facts cannot be null")
        result = asyncio.run(run(args.db, args.set_id, args.version_id, args.country, args.document_type, facts))
    except Exception:
        print(json.dumps({"ok": False, "code": "projection_review_unavailable",
                          "message": "Check local database, identifiers, inputs and snapshot integrity."}))
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
