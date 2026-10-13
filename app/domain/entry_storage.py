"""E5-03C admin-only immutable history/calendar storage, with owned transactions.

Actor must come from trusted server auth. No HTTP/LLM/config/runtime integration.
Only synthetic/local rehearsal is approved until retention and release gates close.
"""
from __future__ import annotations

import asyncio
from datetime import date, timezone
import hashlib
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError

from app.domain.knowledge_import import _authorize, _sessions
from app.domain.knowledge_review import _plain
from app.domain.models import (Contact, DomainError, StayHistory, StayInterval, WorkCalendar, WorkCalendarDay, _now)
from app.knowledge.review import canonical
from app.knowledge.storage_schema import HISTORY
from app.knowledge.validation import InvalidDocument, check_tree, schema_errors
from app.knowledge.work_calendar import WorkCalendars


class EntryStorageInvalid(DomainError):
    pass


class EntryStorageConflict(DomainError):
    pass


class EntryStorageUnavailable(DomainError):
    pass


def _hash(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def _id(value):
    if type(value) is not int or not 1 <= value <= 2147483647:
        raise EntryStorageInvalid("invalid_identifier")


def _key(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", value):
        raise EntryStorageInvalid("invalid_request_key")


def _document(value, schema):
    try:
        check_tree(value)
        if schema_errors(value, schema):
            raise EntryStorageInvalid("invalid_document")
        return _plain(value)
    except (InvalidDocument, TypeError, ValueError):
        raise EntryStorageInvalid("invalid_document") from None


def _normalize_history(document):
    doc = _document(document, HISTORY)
    try:
        cutoff = date.fromisoformat(doc["as_of"])
        refs, opened = set(), []
        for row in doc["intervals"]:
            start = date.fromisoformat(row["entry_date"])
            end = date.fromisoformat(row["exit_date"]) if row["exit_date"] else None
            if row["ref"] in refs or start > cutoff or (end is not None and not start <= end <= cutoff):
                raise ValueError
            if row["confirmed"] and row["evidence"] == "client_statement":
                raise ValueError
            refs.add(row["ref"])
            if end is None:
                opened.append(start)
        if len(opened) > 1 or (opened and any(r["exit_date"] and date.fromisoformat(r["exit_date"]) > opened[0]
                                            for r in doc["intervals"])):
            raise ValueError
    except ValueError:
        raise EntryStorageInvalid("invalid_history") from None
    doc["intervals"].sort(key=lambda r: r["ref"])
    return doc


async def _transaction(engine, operation):
    """No caller session/connection; each retry starts a clean transaction."""
    sessions = _sessions(engine)
    for attempt in range(3):
        committing = False
        try:
            # Keep session cleanup outside transaction.__aexit__: even a lost
            # commit acknowledgement must return its connection to the pool.
            async with sessions() as session:
                async with session.begin():
                    result = await operation(session)
                    await session.flush()
                    committing = True
            return result
        except DomainError:
            raise
        except (IntegrityError, OperationalError):
            if committing:
                raise EntryStorageUnavailable("commit_outcome_unknown_retry_same_request") from None
            if attempt < 2:
                await asyncio.sleep(0.03 * (attempt + 1))
                continue
            raise EntryStorageConflict("concurrent_or_constraint_conflict") from None
        except (TypeError, ValueError, KeyError, AttributeError):
            if not committing:
                raise EntryStorageInvalid("stored_data_invalid") from None
            raise EntryStorageUnavailable("commit_outcome_unknown_retry_same_request") from None
        except Exception:
            raise EntryStorageUnavailable("commit_outcome_unknown_retry_same_request" if committing else
                                          "entry_storage_unavailable") from None


async def _contact(session, contact_id):
    _id(contact_id)
    if await session.scalar(select(Contact.id).where(Contact.id == contact_id).with_for_update()) is None:
        raise EntryStorageInvalid("contact_unavailable")


def _history_payload(row):
    return {"contact_id": row.contact_id, "revision": row.revision, "previous_id": row.previous_id,
            "as_of": row.as_of.isoformat(), "history_complete": row.history_complete,
            "request_key": row.request_key, "request_hash": row.request_hash,
            "created_by": row.created_by, "created_at": _utc(row.created_at), "snapshot": _plain(row.snapshot)}


def _utc(stamp):
    # SQLite drops the offset. All timestamps this service writes are UTC.
    return stamp.replace(tzinfo=timezone.utc).isoformat() if stamp.tzinfo is None else stamp.astimezone(timezone.utc).isoformat()


async def _history(session, contact_id, history_id):
    row = await session.scalar(select(StayHistory).where(StayHistory.id == history_id, StayHistory.contact_id == contact_id))
    if row is None:
        raise EntryStorageInvalid("history_unavailable")
    doc = _normalize_history(_plain(row.snapshot))
    expected = {"contact_id": contact_id, "expected_revision": row.revision - 1, "document": doc}
    if (_hash(_history_payload(row)) != row.snapshot_hash or row.request_hash != _hash(expected)
            or doc["as_of"] != row.as_of.isoformat() or doc["history_complete"] is not row.history_complete):
        raise EntryStorageInvalid("history_integrity_failed")
    intervals = (await session.scalars(select(StayInterval).where(
        StayInterval.history_id == history_id).order_by(StayInterval.ref).limit(1001))).all()
    if len(intervals) != len(doc["intervals"]):
        raise EntryStorageInvalid("history_integrity_failed")
    for item, expected in zip(intervals, doc["intervals"]):
        actual = {key: getattr(item, key) for key in expected}
        for key in ("entry_date", "exit_date"):
            actual[key] = actual[key].isoformat() if actual[key] else None
        if (actual != expected or item.contact_id != contact_id or
                item.confirmed_by != (row.created_by if item.confirmed else None) or
                (item.confirmed_at is None) != (not item.confirmed) or
                (item.confirmed and _utc(item.confirmed_at) != _utc(row.created_at))):
            raise EntryStorageInvalid("history_integrity_failed")
    return row, doc, intervals


async def save_stay_history(engine, *, actor, contact_id, expected_revision, request_key, document):
    _authorize(actor)
    _id(contact_id)
    _key(request_key)
    if type(expected_revision) is not int or not 0 <= expected_revision < 2147483647:
        raise EntryStorageInvalid("invalid_history_revision")
    doc = _normalize_history(document)
    request_hash = _hash({"contact_id": contact_id, "expected_revision": expected_revision, "document": doc})

    async def save(session):
        await _contact(session, contact_id)
        old = await session.scalar(select(StayHistory).where(
            StayHistory.contact_id == contact_id, StayHistory.request_key == request_key))
        if old is not None:
            if old.request_hash != request_hash:
                raise EntryStorageConflict("history_request_key_conflict")
            await _history(session, contact_id, old.id)
            return {"history_id": old.id, "revision": old.revision, "snapshot_hash": old.snapshot_hash, "reused": True}
        previous = await session.scalar(select(StayHistory).where(StayHistory.contact_id == contact_id)
                                        .order_by(StayHistory.revision.desc()).limit(1))
        if (previous.revision if previous else 0) != expected_revision:
            raise EntryStorageConflict("stale_history_revision")
        if previous is not None:
            await _history(session, contact_id, previous.id)
        row = StayHistory(contact_id=contact_id, revision=expected_revision + 1, previous_id=previous.id if previous else None,
            as_of=date.fromisoformat(doc["as_of"]), history_complete=doc["history_complete"], request_key=request_key,
            request_hash=request_hash, snapshot=doc, created_by=actor.manager_id, created_at=_now())
        row.snapshot_hash = _hash(_history_payload(row))
        session.add(row)
        await session.flush()
        stamp = row.created_at
        for record in doc["intervals"]:
            fields = dict(record)
            fields["entry_date"] = date.fromisoformat(fields["entry_date"])
            fields["exit_date"] = date.fromisoformat(fields["exit_date"]) if fields["exit_date"] else None
            session.add(StayInterval(history_id=row.id, contact_id=contact_id, **fields,
                confirmed_by=actor.manager_id if record["confirmed"] else None, confirmed_at=stamp if record["confirmed"] else None))
        await session.flush()
        await _history(session, contact_id, row.id)
        return {"history_id": row.id, "revision": row.revision, "snapshot_hash": row.snapshot_hash, "reused": False}
    return await _transaction(engine, save)


async def read_stay_history(engine, *, actor, contact_id, history_id):
    _authorize(actor)
    _id(contact_id)
    _id(history_id)

    async def read(session):
        row, doc, intervals = await _history(session, contact_id, history_id)
        return {"history_id": row.id, "contact_id": contact_id, "revision": row.revision,
                "snapshot_hash": row.snapshot_hash, "document": doc, "interval_ids": [r.id for r in intervals]}
    return await _transaction(engine, read)


async def _calendar(session, calendar_id):
    row = await session.get(WorkCalendar, calendar_id)
    if row is None:
        raise EntryStorageInvalid("calendar_unavailable")
    doc = _plain(row.document)
    book = WorkCalendars({"format": "kg-work-calendars/1", "calendars": [doc]})
    info = book.describe()[0]
    if (row.content_hash != info["hash"] or (row.year, row.version, row.status, row.jurisdiction) !=
            (doc["year"], doc["version"], doc["status"], doc["jurisdiction"])):
        raise EntryStorageInvalid("calendar_integrity_failed")
    days = (await session.scalars(select(WorkCalendarDay).where(
        WorkCalendarDay.calendar_id == row.id).order_by(WorkCalendarDay.day).limit(367))).all()
    actual = [{"date": d.day.isoformat(), "is_working": d.is_working, "kind": d.kind,
               "title": d.title, "source_ref": d.source_ref} for d in days]
    if actual != book.export()["calendars"][0]["days"]:
        raise EntryStorageInvalid("calendar_integrity_failed")
    return row, book.export()["calendars"][0]


async def _calendars(session, ids):
    if type(ids) is not list or len(ids) > 10:
        raise EntryStorageInvalid("invalid_calendar_identifiers")
    for value in ids:
        _id(value)
    if len(set(ids)) != len(ids):
        raise EntryStorageInvalid("duplicate_calendar_identifier")
    rows, docs = [], []
    for value in sorted(ids):
        row, doc = await _calendar(session, value)
        rows.append(row)
        docs.append(doc)
    book = WorkCalendars({"format": "kg-work-calendars/1", "calendars": docs})
    return rows, book.export()


async def import_work_calendars(engine, *, actor, document):
    _authorize(actor)
    book = WorkCalendars(document)
    docs, infos = book.export()["calendars"], book.describe()

    async def save(session):
        result = []
        for doc, info in zip(docs, infos):
            row = await session.scalar(select(WorkCalendar).where(
                WorkCalendar.jurisdiction == "KG", WorkCalendar.year == doc["year"], WorkCalendar.version == doc["version"]))
            reused = row is not None
            if reused:
                await _calendar(session, row.id)
                if row.content_hash != info["hash"]:
                    raise EntryStorageConflict("calendar_version_conflict")
            else:
                row = WorkCalendar(jurisdiction="KG", year=doc["year"], version=doc["version"], status="draft",
                                   content_hash=info["hash"], document=doc, created_by=actor.manager_id)
                session.add(row)
                await session.flush()
                session.add_all(WorkCalendarDay(calendar_id=row.id, day=date.fromisoformat(d["date"]),
                    **{k: v for k, v in d.items() if k != "date"}) for d in doc["days"])
                await session.flush()
                await _calendar(session, row.id)
            result.append({"calendar_id": row.id, "year": row.year, "version": row.version,
                           "content_hash": row.content_hash, "reused": reused})
        return result
    return await _transaction(engine, save)


async def read_work_calendars(engine, *, actor, calendar_ids):
    _authorize(actor)

    async def read(session):
        _, document = await _calendars(session, calendar_ids)
        return document
    return await _transaction(engine, read)
