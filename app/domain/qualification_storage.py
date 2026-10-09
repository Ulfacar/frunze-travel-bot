"""Admin-only immutable qualification revisions, resumable without client publication."""
import hashlib
from importlib import metadata
from pathlib import Path
import platform

from sqlalchemy import select

from app.domain.entry_qualification import _evaluate_qualification, _qualification_sources
from app.domain.entry_storage import (EntryStorageConflict, EntryStorageInvalid, _authorize, _contact,
    _document, _hash, _id, _key, _plain, _transaction, _utc)
from app.domain.models import EntryQualification, _now
from app.knowledge.qualification import ALGORITHM
from app.knowledge.qualification_schema import REQUEST_SCHEMA


def _runtime():
    root = Path(__file__).resolve().parents[1]
    names = ("domain/qualification_storage.py", "domain/entry_qualification.py", "domain/entry_storage.py",
             "domain/entry_calculations.py", "domain/knowledge_review.py", "domain/knowledge_projection.py",
             "knowledge/qualification.py", "knowledge/qualification_schema.py", "knowledge/intake.py", "knowledge/country_index.py",
             "knowledge/conditions.py", "knowledge/condition_schema.py", "knowledge/projection.py",
             "knowledge/bundle.py", "knowledge/bundle_schema.py", "knowledge/slots.py",
             "knowledge/schemas/kg-entry-slots-v1.json", "knowledge/review.py", "knowledge/validation.py")
    return {"algorithm": ALGORITHM, "python": platform.python_version(), "jsonschema": metadata.version("jsonschema"),
            "code_hash": _hash({name: hashlib.sha256((root/name).read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                                for name in names})}


def _request_hash(contact_id, revision, version_id, history_id, request):
    return _hash({"contact_id": contact_id, "expected_revision": revision,
                  "knowledge_version_id": version_id, "history_id": history_id, "request": request})


def _payload(row):
    fields = ("contact_id", "revision", "previous_id", "history_id", "knowledge_version_id", "request_key",
              "request_hash", "input_snapshot", "result_snapshot", "provenance", "created_by")
    return {**{key: _plain(getattr(row, key)) for key in fields}, "created_at": _utc(row.created_at)}


async def _latest(session, contact_id):
    return await session.scalar(select(EntryQualification).where(EntryQualification.contact_id == contact_id)
                                .order_by(EntryQualification.revision.desc()).limit(1))


async def _read(session, contact_id, qualification_id):
    row = await session.scalar(select(EntryQualification).where(
        EntryQualification.id == qualification_id, EntryQualification.contact_id == contact_id))
    if row is None:
        raise EntryStorageInvalid("qualification_unavailable")
    if _hash(_payload(row)) != row.snapshot_hash:
        raise EntryStorageInvalid("qualification_integrity_failed")
    request = _document(_plain(row.input_snapshot), REQUEST_SCHEMA)
    if row.request_hash != _request_hash(contact_id, row.revision - 1, row.knowledge_version_id, row.history_id, request):
        raise EntryStorageInvalid("qualification_request_changed")
    previous = None
    if row.previous_id is not None:
        old = await session.scalar(select(EntryQualification).where(
            EntryQualification.id == row.previous_id, EntryQualification.contact_id == contact_id))
        if old is None or old.revision != row.revision - 1 or _hash(_payload(old)) != old.snapshot_hash:
            raise EntryStorageInvalid("qualification_previous_changed")
        previous = {"id": old.id, "revision": old.revision, "snapshot_hash": old.snapshot_hash}
    if (row.revision == 1) != (previous is None) or previous != row.provenance["previous"]:
        raise EntryStorageInvalid("qualification_previous_changed")
    review, context = await _qualification_sources(session, contact_id, row.knowledge_version_id, row.history_id)
    if context != row.provenance["context"]:
        raise EntryStorageInvalid("qualification_sources_changed")
    # The old result is intentionally not recomputed here: reads survive code upgrades.
    return row, review, context


def _report(row, *, reused=False):
    return {"qualification_id": row.id, "contact_id": row.contact_id, "revision": row.revision,
            "previous_id": row.previous_id, "snapshot_hash": row.snapshot_hash, "reused": reused,
            "created_by": row.created_by, "created_at": _utc(row.created_at),
            "input": _plain(row.input_snapshot), "result": _plain(row.result_snapshot),
            "provenance": _plain(row.provenance)}


async def save_qualification(engine, *, actor, contact_id, expected_revision, request_key,
                             knowledge_version_id, request, history_id=None):
    """Full replacement only; missing fields remove old answers, never merge stale decisions."""
    _authorize(actor)
    _id(contact_id)
    _id(knowledge_version_id)
    _key(request_key)
    if history_id is not None:
        _id(history_id)
    if type(expected_revision) is not int or not 0 <= expected_revision < 2147483647:
        raise EntryStorageInvalid("invalid_qualification_revision")
    request = _document(request, REQUEST_SCHEMA)
    digest = _request_hash(contact_id, expected_revision, knowledge_version_id, history_id, request)

    async def save(session):
        await _contact(session, contact_id)
        old = await session.scalar(select(EntryQualification).where(
            EntryQualification.contact_id == contact_id, EntryQualification.request_key == request_key))
        if old is not None:
            if old.request_hash != digest:
                raise EntryStorageConflict("qualification_request_key_conflict")
            checked, *_ = await _read(session, contact_id, old.id)
            return _report(checked, reused=True)
        previous = await _latest(session, contact_id)
        if (previous.revision if previous else 0) != expected_revision:
            raise EntryStorageConflict("stale_qualification_revision")
        previous_info = None
        if previous is not None:
            await _read(session, contact_id, previous.id)
            previous_info = {"id": previous.id, "revision": previous.revision, "snapshot_hash": previous.snapshot_hash}
        review, context = await _qualification_sources(session, contact_id, knowledge_version_id, history_id)
        result = _evaluate_qualification(review, context, request)
        row = EntryQualification(contact_id=contact_id, revision=expected_revision + 1,
            previous_id=previous.id if previous else None, history_id=history_id, knowledge_version_id=knowledge_version_id,
            request_key=request_key, request_hash=digest, input_snapshot=request, result_snapshot=result,
            provenance={"format": "kg-qualification-snapshot/1", "context": context,
                        "previous": previous_info, "runtime": _runtime()}, created_by=actor.manager_id, created_at=_now())
        row.snapshot_hash = _hash(_payload(row))
        session.add(row)
        await session.flush()
        await _read(session, contact_id, row.id)
        return _report(row)
    return await _transaction(engine, save)


async def read_qualification(engine, *, actor, contact_id, qualification_id=None):
    """Omitting the id resumes the latest revision for this contact; no row means None."""
    _authorize(actor)
    _id(contact_id)
    if qualification_id is not None:
        _id(qualification_id)

    async def read(session):
        selected_id = qualification_id
        if selected_id is None:
            await _contact(session, contact_id)
            latest = await _latest(session, contact_id)
            if latest is None:
                return None
            selected_id = latest.id
        row, *_ = await _read(session, contact_id, selected_id)
        return _report(row)
    return await _transaction(engine, read)


async def replay_qualification(engine, *, actor, contact_id, qualification_id):
    _authorize(actor)
    _id(contact_id)
    _id(qualification_id)

    async def replay(session):
        row, review, context = await _read(session, contact_id, qualification_id)
        if _runtime() != row.provenance["runtime"]:
            raise EntryStorageInvalid("qualification_replay_runtime_changed")
        result = _evaluate_qualification(review, context, _plain(row.input_snapshot))
        if _hash(result) != _hash(row.result_snapshot):
            raise EntryStorageInvalid("qualification_replay_result_changed")
        return {**_report(row), "replay_verified": True}
    return await _transaction(engine, replay)
