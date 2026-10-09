"""Immutable per-person qualification, separate from the payer/contact interview."""
import hashlib
from pathlib import Path

from sqlalchemy import select

from app.domain import entry_applications as applications
from app.domain.entry_qualification import _evaluate_qualification, _qualification_sources
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _authorize, _document, _hash, _id, _key, _plain
from app.domain.models import EntryApplicant, EntryApplicantProfile, _now
from app.domain.qualification_storage import _runtime as qualification_runtime
from app.knowledge.qualification_schema import REQUEST_SCHEMA
from app.knowledge.review import canonical

MAX_REVISIONS = 250
MAX_BYTES = 4 * 1024 * 1024


def _runtime():
    return {**qualification_runtime(), "profile_code_hash": hashlib.sha256(
        Path(__file__).read_bytes().replace(b"\r\n", b"\n")).hexdigest()}


def _command(case_id, applicant_id, revision, version_id, request, actor):
    return dict(case_id=case_id, applicant_id=applicant_id, expected_revision=revision,
                knowledge_version_id=version_id, request=request, actor=actor)


def _payload(row):
    fields = ("case_id", "applicant_id", "revision", "previous_id", "knowledge_version_id", "request_key",
              "request_hash", "input_snapshot", "result_snapshot", "provenance", "created_by")
    return {**{k: _plain(getattr(row, k)) for k in fields}, "created_at": applications._utc(row.created_at)}


async def _subject(session, case_id, applicant_id, *, write=False):
    case = await applications._case(session, case_id)
    await session.scalar(select(EntryApplicant).where(EntryApplicant.id == applicant_id,
        EntryApplicant.case_id == case_id).with_for_update(read=not write, of=EntryApplicant))
    person = await applications._applicant(session, case_id, applicant_id)
    return case, person


async def _sources(session, case, person, version_id):
    # Contact is used only to validate the payer's case and pinned knowledge.
    # A payer's StayHistory is not evidence about this person, even for role=primary.
    review, context = await _qualification_sources(session, case.contact_id, version_id, None)
    context.pop("contact_id")
    context.update(case_id=case.id, applicant_id=person.id, payer_contact_id=case.contact_id,
                   applicant_hash=person.snapshot_hash)
    return review, context


def _evaluate(review, context, request):
    result = _evaluate_qualification(review, {**context, "contact_id": None}, request)
    result.pop("contact_id")
    result.update(case_id=context["case_id"], applicant_id=context["applicant_id"])
    return result


async def _history(session, case, person):
    rows = list((await session.scalars(select(EntryApplicantProfile).where(
        EntryApplicantProfile.applicant_id == person.id).order_by(EntryApplicantProfile.revision)
        .limit(MAX_REVISIONS + 1))).all())
    if len(rows) > MAX_REVISIONS:
        raise EntryStorageInvalid("profile_history_limit")
    previous = None
    size = 0
    sources = {}
    for revision, row in enumerate(rows, 1):
        payload = _payload(row)
        size += len(canonical(payload).encode())
        if size > MAX_BYTES:
            raise EntryStorageInvalid("profile_history_limit")
        request = _document(_plain(row.input_snapshot), REQUEST_SCHEMA)
        command = _command(case.id, person.id, revision - 1, row.knowledge_version_id, request, row.created_by)
        prior = dict(id=previous.id, snapshot_hash=previous.snapshot_hash) if previous else None
        if (row.case_id != case.id or row.revision != revision or
            row.previous_id != (previous.id if previous else None) or previous and row.id <= previous.id or
            row.request_hash != _hash(command) or row.snapshot_hash != _hash(payload) or
            row.provenance.get("previous") != prior):
            raise EntryStorageInvalid("profile_integrity_failed")
        if row.knowledge_version_id not in sources:
            sources[row.knowledge_version_id] = await _sources(session, case, person, row.knowledge_version_id)
        if sources[row.knowledge_version_id][1] != row.provenance.get("context"):
            raise EntryStorageInvalid("profile_sources_changed")
        previous = row
    return rows, size, sources


def _view(row):
    return dict(qualification_id=row.id, case_id=row.case_id, applicant_id=row.applicant_id,
        revision=row.revision, previous_id=row.previous_id, snapshot_hash=row.snapshot_hash,
        created_by=row.created_by, created_at=applications._utc(row.created_at), input=_plain(row.input_snapshot),
        result=_plain(row.result_snapshot), provenance=_plain(row.provenance))


async def save_applicant_profile(engine, *, actor, case_id, applicant_id, expected_revision,
                                 request_key, knowledge_version_id, request):
    _authorize(actor)
    for value in (case_id, applicant_id, knowledge_version_id):
        _id(value)
    _key(request_key)
    if type(expected_revision) is not int or not 0 <= expected_revision < MAX_REVISIONS:
        raise EntryStorageInvalid("invalid_profile_revision")
    request = _document(request, REQUEST_SCHEMA)
    command = _command(case_id, applicant_id, expected_revision, knowledge_version_id, request, actor.manager_id)

    async def save(session):
        case, person = await _subject(session, case_id, applicant_id, write=True)
        rows, size, _ = await _history(session, case, person)
        old = next((r for r in rows if r.request_key == request_key), None)
        if old:
            if old.request_hash != _hash(command):
                raise EntryStorageConflict("profile_request_key_reused")
            return _view(old)
        if len(rows) != expected_revision:
            raise EntryStorageConflict("profile_revision_changed")
        review, context = await _sources(session, case, person, knowledge_version_id)
        previous = rows[-1] if rows else None
        row = EntryApplicantProfile(case_id=case_id, applicant_id=applicant_id, revision=len(rows) + 1,
            previous_id=previous.id if previous else None, knowledge_version_id=knowledge_version_id,
            request_key=request_key, request_hash=_hash(command), input_snapshot=request,
            result_snapshot=_evaluate(review, context, request), created_by=actor.manager_id, created_at=_now(),
            provenance=dict(format="kg-applicant-profile/1", context=context, runtime=_runtime(),
                previous=dict(id=previous.id, snapshot_hash=previous.snapshot_hash) if previous else None))
        if size + len(canonical(_payload(row)).encode()) > MAX_BYTES:
            raise EntryStorageInvalid("profile_history_limit")
        row.snapshot_hash = _hash(_payload(row))
        session.add(row)
        await session.flush()
        return _view(row)
    return await applications._run(engine, save)


async def read_applicant_profile(engine, *, actor, case_id, applicant_id, qualification_id=None, replay=False):
    _authorize(actor)
    _id(case_id)
    _id(applicant_id)
    if qualification_id is not None:
        _id(qualification_id)
    if type(replay) is not bool:
        raise EntryStorageInvalid("invalid_profile_replay")

    async def read(session):
        case, person = await _subject(session, case_id, applicant_id)
        rows, _, sources = await _history(session, case, person)
        row = next((r for r in rows if r.id == qualification_id), None) if qualification_id else rows[-1] if rows else None
        if qualification_id and row is None:
            raise EntryStorageInvalid("profile_unavailable")
        if replay and row:
            review, context = sources[row.knowledge_version_id]
            if row.provenance["runtime"] != _runtime():
                raise EntryStorageInvalid("profile_replay_runtime_changed")
            if _evaluate(review, context, _plain(row.input_snapshot)) != row.result_snapshot:
                raise EntryStorageInvalid("profile_replay_result_changed")
        return dict(applicant=applications._applicant_view(person), payer_contact_id=case.contact_id,
            current_revision=len(rows), saved=_view(row) if row else None,
            history=[dict(qualification_id=r.id, revision=r.revision, created_by=r.created_by,
                          created_at=applications._utc(r.created_at)) for r in reversed(rows)])
    return await applications._run(engine, read)
