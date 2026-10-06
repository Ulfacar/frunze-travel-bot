"""Локальная SQLite-репетиция E5; не принимает DSN и не читает .env.

Новая БД мигрируется до e5_knowledge_0013; существующая должна быть на этой ревизии.
CLI доверяет локальному оператору, имеющему доступ к файлу, а не HTTP-параметрам.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import create_async_engine

from app.domain.knowledge_import import create_kg_entry_set, import_bundle
from app.domain.permissions import Actor

REVISION = "e5_knowledge_0013"


def prepare_database(path: Path):
    path = path.resolve()
    if str(path).startswith("\\\\") or path.suffix.lower() not in {".sqlite3", ".sqlite", ".db"}:
        raise ValueError("use an explicit local SQLite file")
    url = URL.create("sqlite", database=path.as_posix()).render_as_string(hide_password=False)
    try:
        with path.open("xb"):
            pass
    except FileExistsError:
        engine = create_engine(url)
        try:
            with engine.connect() as connection:
                if connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all() != [REVISION]:
                    raise ValueError("existing database has a different migration revision")
        finally:
            engine.dispose()
    else:
        cfg = Config(str(ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(ROOT / "alembic"))
        # -x сильнее ALEMBIC_DATABASE_URL: ambient env не может перенаправить миграцию.
        cfg.cmd_opts = argparse.Namespace(x=[f"dburl={url}"], tag=None)
        command.upgrade(cfg, REVISION)
    return URL.create("sqlite+aiosqlite", database=path.as_posix())


async def run(url, bundle, source):
    engine = create_async_engine(url)

    @event.listens_for(engine.sync_engine, "connect")
    def foreign_keys(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    actor = Actor("local-operator", is_full_admin=True)
    try:
        set_id = await create_kg_entry_set(engine, actor=actor)
        return await import_bundle(engine, actor=actor, set_id=set_id, directory=bundle, source=source)
    finally:
        await engine.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Explicit disposable local SQLite file")
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = asyncio.run(run(prepare_database(args.db), args.bundle, args.source))
    except Exception:
        # SQL exceptions include bound payloads/DSNs; diagnostics stay deliberately bounded.
        print(json.dumps({"ok": False, "code": "local_import_unavailable",
                          "message": "Check the local database revision and files; reconcile before retry."}))
        return 2
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if result.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
