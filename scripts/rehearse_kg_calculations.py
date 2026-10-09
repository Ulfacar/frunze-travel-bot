"""Disposable SQLite rehearsal of E5-03C using synthetic fixtures only, never a DSN."""
import argparse
import asyncio
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alembic import command
from alembic.config import Config
from sqlalchemy import event, func, select
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.entry_calculations import replay_calculation, save_calculation
from app.domain.entry_storage import import_work_calendars, save_stay_history
from app.domain.knowledge_import import create_kg_entry_set, import_bundle
from app.domain.models import Contact, ENTRY_STORAGE_MODELS
from app.domain.permissions import Actor
from app.knowledge.validation import load_document

REVISION = "e5_calculation_0015"
FIX = ROOT / "tests/fixtures/kg_entry"


def prepare_database(path):
    path = path.resolve()
    if str(path).startswith("\\\\") or path.suffix.lower() not in (".sqlite3", ".sqlite", ".db"):
        raise ValueError("explicit new local SQLite file required")
    # Never open or upgrade an existing DB, even if it happens to have this schema.
    with path.open("xb"):
        pass
    url = URL.create("sqlite", database=path.as_posix()).render_as_string(hide_password=False)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.cmd_opts = argparse.Namespace(x=[f"dburl={url}"], tag=None)
    command.upgrade(cfg, REVISION)
    return URL.create("sqlite+aiosqlite", database=path.as_posix())


async def run(url):
    engine = create_async_engine(url)
    @event.listens_for(engine.sync_engine, "connect")
    def fk(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
    actor = Actor("synthetic-rehearsal", is_full_admin=True)
    try:
        async with async_sessionmaker(engine).begin() as session:
            person = Contact()
            session.add(person)
            await session.flush()
            contact_id = person.id
        set_id = await create_kg_entry_set(engine, actor=actor)
        imported = await import_bundle(engine, actor=actor, set_id=set_id, directory=FIX / "synthetic_bundle",
                                       source=FIX / "synthetic_source.txt")
        if not imported.accepted:
            raise ValueError("synthetic import rejected")
        history = {"format": "kg-stay-history/1", "as_of": "2026-10-01", "history_complete": None,
            "intervals": [{"ref": "synthetic-trip", "entry_date": "2026-09-20", "exit_date": "2026-09-22",
                "basis": "visa_free", "passport_country": "RUS", "passport_ref": None,
                "evidence": "client_statement", "confirmed": False}]}
        stored = await save_stay_history(engine, actor=actor, contact_id=contact_id, expected_revision=0,
                                         request_key="synthetic-history", document=history)
        request = load_document(FIX / "synthetic_stay_review.json")
        request = {key: request[key] for key in ("rule_unit_id", "trip", "policy")}
        request.update(rule_unit_id="KG.VF.TEST", passport_ref=None)
        request["trip"].update(start_date="2026-10-10", end_date="2026-10-12", passport_country="RUS")
        stay = await save_calculation(engine, actor=actor, contact_id=contact_id, kind="stay",
            knowledge_version_id=imported.version_id, request_key="synthetic-stay", history_id=stored["history_id"], request=request)
        calendars = await import_work_calendars(engine, actor=actor, document=load_document(FIX / "synthetic_work_calendars.json"))
        deadline = await save_calculation(engine, actor=actor, contact_id=contact_id, kind="deadline",
            knowledge_version_id=imported.version_id, request_key="synthetic-deadline",
            calendar_ids=[r["calendar_id"] for r in calendars], request=load_document(FIX / "synthetic_deadline_review.json"))
        verified = [await replay_calculation(engine, actor=actor, contact_id=contact_id, calculation_id=r["calculation_id"])
                    for r in (stay, deadline)]
        async with async_sessionmaker(engine)() as session:
            counts = {m.__tablename__: await session.scalar(select(func.count()).select_from(m)) for m in ENTRY_STORAGE_MODELS}
        return {"ok": True, "mode": "synthetic_local_rehearsal", "revision": REVISION, "counts": counts,
                "replay_verified": all(r["replay_verified"] for r in verified),
                "stay_scenario_presence_days": stay["result"]["scenario"]["max_presence_days"],
                "deadline_scenario_due": deadline["result"]["scenario"]["due"], "may_quote": False,
                "exact_deadline": deadline["result"]["exact_deadline"], "exact_remaining_days": stay["result"]["exact_remaining_days"]}
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="New disposable local SQLite file; existing files refused")
    args = parser.parse_args()
    try:
        result = asyncio.run(run(prepare_database(args.db)))
    except Exception:
        print(json.dumps({"ok": False, "code": "synthetic_rehearsal_unavailable"}))
        return 1
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
