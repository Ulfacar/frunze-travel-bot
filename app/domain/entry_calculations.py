"""Stored review calculations use DB history, pinned sources and verified replay.

No slots/history/confirmed fields from callers, no client eligibility or publication.
Read access is the same named administrator boundary as knowledge import.
"""
from __future__ import annotations

import hashlib
from importlib import metadata, resources
from pathlib import Path
import platform
import zoneinfo

from sqlalchemy import select

from app.domain.entry_storage import (EntryStorageConflict, EntryStorageInvalid, _authorize, _calendars,
    _contact, _document, _hash, _history, _id, _key, _plain, _transaction, _utc)
from app.domain.knowledge_review import _snapshot
from app.domain.models import (EntryCalculation, EntryCalculationCalendar, EntryCalculationInterval,
                               KnowledgeImport, KnowledgeSet, KnowledgeVersion, _now)
from app.knowledge.deadline_schema import DEADLINE_REQUEST
from app.knowledge.deadlines import ALGORITHM as DEADLINE_ALGORITHM, DeadlineReview
from app.knowledge.stay_days import ALGORITHM as STAY_ALGORITHM, StayDayReview
from app.knowledge.storage_schema import STORED_STAY_REQUEST


def _tz_identity():
    for base in zoneinfo.TZPATH:
        path = Path(base) / "Asia" / "Bishkek"
        if path.is_file():
            return {"source": "system", "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    try:
        raw = resources.files("tzdata.zoneinfo").joinpath("Asia", "Bishkek").read_bytes()
        return {"source": "tzdata_package", "sha256": hashlib.sha256(raw).hexdigest(),
                "package_version": metadata.version("tzdata")}
    except (ModuleNotFoundError, FileNotFoundError, metadata.PackageNotFoundError):
        return {"source": "unavailable", "sha256": None}


def _runtime(kind):
    root = Path(__file__).resolve().parents[1]
    names = ["knowledge/bundle.py", "knowledge/bundle_schema.py", "knowledge/validation.py",
             "knowledge/review.py", "knowledge/storage_schema.py", "domain/entry_calculations.py"]
    names += (["knowledge/stay_days.py", "knowledge/stay_schema.py"] if kind == "stay" else
              ["knowledge/deadlines.py", "knowledge/deadline_schema.py", "knowledge/work_calendar.py"])
    return {"algorithm": STAY_ALGORITHM if kind == "stay" else DEADLINE_ALGORITHM,
            "code_hash": _hash({n: hashlib.sha256((root / n).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                               for n in names}), "python": platform.python_version(),
            "jsonschema": metadata.version("jsonschema"), "tzdata": _tz_identity() if kind == "deadline" else None}


async def _bundle(session, version_id):
    version = await session.get(KnowledgeVersion, version_id)
    target = await session.get(KnowledgeSet, version.set_id) if version else None
    if target is None or (target.code, target.jurisdiction, target.domain) != ("kg_entry", "KG", "entry"):
        raise EntryStorageInvalid("knowledge_version_unavailable")
    accepted = await session.scalar(select(KnowledgeImport.id).where(
        KnowledgeImport.version_id == version_id, KnowledgeImport.result == "accepted").limit(1))
    if accepted is None:
        raise EntryStorageInvalid("knowledge_version_not_sealed")
    bundle, _ = await _snapshot(session, set_id=target.id, version_id=version_id)
    return bundle


def _request_hash(contact_id, kind, version_id, history_id, calendar_ids, request):
    return _hash({"contact_id": contact_id, "kind": kind, "knowledge_version_id": version_id,
                  "history_id": history_id, "calendar_ids": sorted(calendar_ids), "request": request})


def _payload(row):
    payload = {key: _plain(getattr(row, key)) for key in (
        "contact_id", "history_id", "knowledge_version_id", "kind", "request_key", "request_hash",
        "input_snapshot", "result_snapshot", "provenance", "created_by")}
    return {**payload, "created_at": _utc(row.created_at)}


async def _sources(session, contact_id, version_id, history_id, calendar_ids):
    bundle = await _bundle(session, version_id)
    rows, calendars = await _calendars(session, calendar_ids)
    history, intervals, history_info = None, [], None
    if history_id is not None:
        row, history, intervals = await _history(session, contact_id, history_id)
        history_info = {"id": row.id, "revision": row.revision, "hash": row.snapshot_hash,
                        "interval_ids": [r.id for r in intervals]}
    provenance = {"format": "kg-calculation-source/1",
        "knowledge": {"version_id": version_id, "bundle_hash": _hash(bundle), "source_hash": bundle["meta"]["source_hash"]},
        "history": history_info,
        "calendars": [{"id": r.id, "year": r.year, "version": r.version, "hash": r.content_hash} for r in rows]}
    return bundle, calendars, history, intervals, provenance


def _evaluate(kind, bundle, calendars, history, request):
    if kind == "stay":
        passport = request["passport_ref"]
        stored = [{"id": r["ref"], "entry_date": r["entry_date"], "exit_date": r["exit_date"],
            "basis": r["basis"], "passport_country": r["passport_country"], "confirmed": r["confirmed"],
            "passport_continuity": "unknown" if passport is None or r["passport_ref"] is None else
            "same" if passport == r["passport_ref"] else "changed"} for r in history["intervals"]]
        inputs = {"schema_version": "kg-stay-review-input/1", "as_of": history["as_of"],
                  "history_complete": history["history_complete"], "history": stored,
                  **{key: value for key, value in request.items() if key != "passport_ref"}}
        calc = StayDayReview(**bundle, source_hash=bundle["meta"]["source_hash"])
    else:
        inputs = _plain(request)
        calc = DeadlineReview(**bundle, source_hash=bundle["meta"]["source_hash"], calendars=calendars)
    return inputs, calc.evaluate(inputs)


async def _read(session, contact_id, calculation_id):
    row = await session.scalar(select(EntryCalculation).where(
        EntryCalculation.id == calculation_id, EntryCalculation.contact_id == contact_id))
    if row is None:
        raise EntryStorageInvalid("calculation_unavailable")
    if _hash(_payload(row)) != row.snapshot_hash:
        raise EntryStorageInvalid("calculation_integrity_failed")
    provenance = _plain(row.provenance)
    ids = [r["id"] for r in provenance["calendars"]]
    bundle, calendars, history, intervals, actual = await _sources(
        session, contact_id, row.knowledge_version_id, row.history_id, ids)
    if actual != {key: provenance[key] for key in actual}:
        raise EntryStorageInvalid("calculation_sources_changed")
    linked_calendars = (await session.scalars(select(EntryCalculationCalendar.calendar_id).where(
        EntryCalculationCalendar.calculation_id == row.id).order_by(EntryCalculationCalendar.calendar_id))).all()
    linked_intervals = (await session.scalars(select(EntryCalculationInterval.interval_id).where(
        EntryCalculationInterval.calculation_id == row.id).order_by(EntryCalculationInterval.interval_id))).all()
    if (linked_calendars != sorted(ids) or linked_intervals != sorted(r.id for r in intervals)
            or row.request_hash != _request_hash(contact_id, row.kind, row.knowledge_version_id,
                                                row.history_id, ids, provenance["request"])):
        raise EntryStorageInvalid("calculation_links_changed")
    return row, bundle, calendars, history


def _report(row, *, reused=False):
    return {"calculation_id": row.id, "contact_id": row.contact_id, "kind": row.kind,
            "snapshot_hash": row.snapshot_hash, "reused": reused, "input": _plain(row.input_snapshot),
            "result": _plain(row.result_snapshot), "provenance": _plain(row.provenance)}


async def save_calculation(engine, *, actor, contact_id, kind, knowledge_version_id, request_key,
                           request, history_id=None, calendar_ids=None):
    _authorize(actor)
    _id(contact_id)
    _id(knowledge_version_id)
    _key(request_key)
    if kind not in ("stay", "deadline"):
        raise EntryStorageInvalid("invalid_calculation_kind")
    if kind == "stay":
        _id(history_id)
    elif history_id is not None:
        raise EntryStorageInvalid("deadline_has_no_stay_history")
    calendar_ids = [] if calendar_ids is None else calendar_ids
    if type(calendar_ids) is not list or len(calendar_ids) > 10:
        raise EntryStorageInvalid("invalid_calendar_identifiers")
    for value in calendar_ids:
        _id(value)
    if len(set(calendar_ids)) != len(calendar_ids) or (kind == "stay" and calendar_ids):
        raise EntryStorageInvalid("invalid_calendar_selection")
    calendar_ids = list(calendar_ids)
    request = _document(request, STORED_STAY_REQUEST if kind == "stay" else DEADLINE_REQUEST)
    request_hash = _request_hash(contact_id, kind, knowledge_version_id, history_id, calendar_ids, request)

    async def save(session):
        await _contact(session, contact_id)
        previous = await session.scalar(select(EntryCalculation).where(
            EntryCalculation.contact_id == contact_id, EntryCalculation.request_key == request_key))
        if previous is not None:
            if previous.request_hash != request_hash:
                raise EntryStorageConflict("calculation_request_key_conflict")
            checked, *_ = await _read(session, contact_id, previous.id)
            return _report(checked, reused=True)
        bundle, calendars, history, intervals, provenance = await _sources(
            session, contact_id, knowledge_version_id, history_id, calendar_ids)
        inputs, output = _evaluate(kind, bundle, calendars, history, request)
        provenance.update(request=request, runtime=_runtime(kind))
        row = EntryCalculation(contact_id=contact_id, history_id=history_id, knowledge_version_id=knowledge_version_id,
            kind=kind, request_key=request_key, request_hash=request_hash, input_snapshot=inputs,
            result_snapshot=output, provenance=provenance, created_by=actor.manager_id, created_at=_now())
        row.snapshot_hash = _hash(_payload(row))
        session.add(row)
        await session.flush()
        session.add_all(EntryCalculationInterval(calculation_id=row.id, history_id=history_id, interval_id=r.id) for r in intervals)
        session.add_all(EntryCalculationCalendar(calculation_id=row.id, calendar_id=value) for value in calendar_ids)
        await session.flush()
        await _read(session, contact_id, row.id)
        return _report(row)
    return await _transaction(engine, save)


async def read_calculation(engine, *, actor, contact_id, calculation_id):
    _authorize(actor)
    _id(contact_id)
    _id(calculation_id)

    async def read(session):
        row, *_ = await _read(session, contact_id, calculation_id)
        return _report(row)
    return await _transaction(engine, read)


async def replay_calculation(engine, *, actor, contact_id, calculation_id):
    _authorize(actor)
    _id(contact_id)
    _id(calculation_id)

    async def replay(session):
        row, bundle, calendars, history = await _read(session, contact_id, calculation_id)
        if _runtime(row.kind) != row.provenance["runtime"]:
            raise EntryStorageInvalid("replay_runtime_changed")
        inputs, result = _evaluate(row.kind, bundle, calendars, history, _plain(row.provenance["request"]))
        if _hash(inputs) != _hash(row.input_snapshot) or _hash(result) != _hash(row.result_snapshot):
            raise EntryStorageInvalid("replay_result_changed")
        return {**_report(row), "replay_verified": True}
    return await _transaction(engine, replay)
