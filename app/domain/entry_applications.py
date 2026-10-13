"""Case-scoped applicant/attempt register with immutable processing facts.

Full administrator only. No messages, fees, legal eligibility, document acceptance
or changes to the commercial service-case workflow are performed here.
"""
from datetime import date, timedelta, timezone
import re

from sqlalchemy import func, select, text

from app.domain.entry_application_rules import (MAX_APPLICANTS, MAX_ATTEMPTS, MAX_EVENTS, PAGE_SIZE,
    PROCEDURES, RETRYABLE, ROLES, SOURCES, STATUSES, TRANSITIONS)
from app.domain.entry_storage import (EntryStorageConflict, EntryStorageInvalid, _authorize, _hash,
                                      _id, _key, _transaction)
from app.domain.models import (EntryApplicant, EntryApplication, EntryApplicationEvent,
                              EntryApplicationReference, Product, ServiceCase, _now)


def _utc(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()


def _local_day(value):
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone(timedelta(hours=6))).date()


def _today():
    return _local_day(_now())


async def _run(engine, operation):
    async def consistent(session):
        # sqlite3 legacy transaction mode does not BEGIN on SELECT. Start the
        # physical transaction so event rows and their unique reference claim
        # cannot come from different commits; a competing writer is retried.
        if session.bind.dialect.name == 'sqlite':
            await session.execute(text('BEGIN'))
        return await operation(session)
    return await _transaction(engine, consistent)


def _stamp(row):
    return {'request_key': row.request_key, 'request_hash': row.request_hash,
            'created_by': row.created_by, 'created_at': _utc(row.created_at)}


def _applicant_command(row):
    return {'action': 'applicant', 'case_id': row.case_id, 'role': row.role, 'actor': row.created_by}


def _applicant_payload(row):
    return {**_applicant_command(row), 'ordinal': row.ordinal, **_stamp(row)}


def _application_command(row):
    return {'action': 'application', 'case_id': row.case_id, 'applicant_id': row.applicant_id,
            'procedure': row.procedure, 'previous_id': row.previous_id, 'actor': row.created_by}


def _application_payload(row):
    return {**_application_command(row), 'attempt': row.attempt, **_stamp(row)}


def _event_command(row):
    return {'action': 'event', 'case_id': row.case_id, 'application_id': row.application_id,
            'expected_revision': row.revision - 1, 'status': row.status, 'occurred_on': row.occurred_on.isoformat(),
            'source': row.source, 'reference': row.reference, 'confirmed': True, 'actor': row.created_by}


def _event_payload(row):
    return {**_event_command(row), 'revision': row.revision, 'previous_id': row.previous_id, **_stamp(row)}


def _checked(row, command, payload):
    if row.request_hash != _hash(command(row)) or row.snapshot_hash != _hash(payload(row)):
        raise EntryStorageInvalid('application_integrity_failed')
    return row


async def _case(session, case_id, *, lock=False):
    _id(case_id)
    query = select(ServiceCase).join(Product, Product.id == ServiceCase.product_id).where(
        ServiceCase.id == case_id, Product.direction == 'visa')
    if lock:
        query = query.with_for_update(of=ServiceCase)
    row = await session.scalar(query)
    if row is None:
        raise EntryStorageInvalid('application_case_unavailable')
    return row


async def _applicant(session, case_id, applicant_id):
    _id(applicant_id)
    row = await session.scalar(select(EntryApplicant).where(EntryApplicant.id == applicant_id,
                                                           EntryApplicant.case_id == case_id))
    if row is None:
        raise EntryStorageInvalid('applicant_unavailable')
    if row.role not in ROLES or not 1 <= row.ordinal <= MAX_APPLICANTS:
        raise EntryStorageInvalid('application_integrity_failed')
    return _checked(row, _applicant_command, _applicant_payload)


async def _application(session, case_id, application_id, *, lock=False):
    _id(application_id)
    query = select(EntryApplication).where(EntryApplication.id == application_id, EntryApplication.case_id == case_id)
    # Readers also hold a shared parent lock while checking the event chain and
    # reference claim. PostgreSQL READ COMMITTED otherwise allows a torn read.
    row = await session.scalar(query.with_for_update(read=not lock, of=EntryApplication))
    if row is None:
        raise EntryStorageInvalid('application_unavailable')
    _checked(row, _application_command, _application_payload)
    if row.procedure not in PROCEDURES or not 1 <= row.attempt <= MAX_ATTEMPTS:
        raise EntryStorageInvalid('application_integrity_failed')
    await _applicant(session, case_id, row.applicant_id)
    if (row.previous_id is None) != (row.attempt == 1):
        raise EntryStorageInvalid('application_integrity_failed')
    if row.previous_id:
        previous = await session.get(EntryApplication, row.previous_id)
        if (previous is None or previous.id >= row.id or previous.case_id != case_id or
                previous.applicant_id != row.applicant_id or previous.procedure != row.procedure or
                previous.attempt + 1 != row.attempt):
            raise EntryStorageInvalid('application_integrity_failed')
        _checked(previous, _application_command, _application_payload)
        if (await _events(session, previous))[-1].status not in RETRYABLE:
            raise EntryStorageInvalid('application_integrity_failed')
    return row


def _event_facts(*, status, occurred_on, source, reference, previous, cutoff):
    if status not in TRANSITIONS.get(previous.status, ()):
        raise EntryStorageInvalid('invalid_application_transition')
    if type(occurred_on) is not date or occurred_on > cutoff:
        raise EntryStorageInvalid('invalid_application_date')
    if previous.revision > 1 and occurred_on < previous.occurred_on:
        raise EntryStorageInvalid('invalid_application_date')
    if source not in SOURCES or status != 'closed' and source not in ('portal', 'official_document'):
        raise EntryStorageInvalid('invalid_application_source')
    if reference is not None and (not isinstance(reference, str) or not re.fullmatch('[A-Z0-9]{8}', reference)):
        raise EntryStorageInvalid('invalid_portal_reference')
    if previous.reference and reference != previous.reference:
        raise EntryStorageInvalid('portal_reference_is_immutable')
    if source == 'portal' and not reference:
        raise EntryStorageInvalid('portal_reference_required')
    if not previous.reference and reference and (status != 'submitted' or source != 'portal'):
        raise EntryStorageInvalid('portal_reference_requires_submission')


async def _events(session, application):
    rows = (await session.scalars(select(EntryApplicationEvent).where(
        EntryApplicationEvent.application_id == application.id).order_by(EntryApplicationEvent.revision).limit(MAX_EVENTS + 1))).all()
    reference = await session.get(EntryApplicationReference, application.id)
    return _validate_events(application, rows, reference)


def _validate_events(application, rows, reference):
    """Same integrity rules for one journal and a coherent batched group read."""
    if not rows or len(rows) > MAX_EVENTS:
        raise EntryStorageInvalid('application_integrity_failed')
    previous = None
    for i, row in enumerate(rows, 1):
        if (row.application_id != application.id or row.case_id != application.case_id or row.revision != i or
                row.previous_id != (previous.id if previous else None) or row.snapshot_hash != _hash(_event_payload(row))):
            raise EntryStorageInvalid('application_integrity_failed')
        if previous is None:
            if (row.status != 'draft' or row.source != 'crm' or row.reference is not None or
                    row.created_by != application.created_by or _utc(row.created_at) != _utc(application.created_at) or
                    row.occurred_on != _local_day(row.created_at) or row.request_key != application.request_key or
                    row.request_hash != application.request_hash):
                raise EntryStorageInvalid('application_integrity_failed')
        else:
            if row.id <= previous.id or row.request_hash != _hash(_event_command(row)):
                raise EntryStorageInvalid('application_integrity_failed')
            _event_facts(status=row.status, occurred_on=row.occurred_on, source=row.source, reference=row.reference,
                         previous=previous, cutoff=_local_day(row.created_at))
        previous = row
    if (rows[-1].reference is None) != (reference is None) or reference and (
            reference.application_id != application.id or reference.case_id != application.case_id or reference.reference != rows[-1].reference):
        raise EntryStorageInvalid('application_integrity_failed')
    return rows


def _applicant_view(row):
    return {'id': row.id, 'ordinal': row.ordinal, 'role': row.role, 'created_by': row.created_by,
            'created_at': _utc(row.created_at)}


def _application_view(row):
    return {'id': row.id, 'case_id': row.case_id, 'applicant_id': row.applicant_id, 'procedure': row.procedure,
            'process': PROCEDURES[row.procedure][0], 'attempt': row.attempt, 'previous_id': row.previous_id,
            'created_by': row.created_by, 'created_at': _utc(row.created_at)}


def _event_view(row):
    return {'id': row.id, 'application_id': row.application_id, 'revision': row.revision, 'status': row.status,
            'occurred_on': row.occurred_on.isoformat(), 'source': row.source, 'reference': row.reference,
            'created_by': row.created_by, 'created_at': _utc(row.created_at)}


async def add_applicant(engine, *, actor, case_id, role, request_key):
    _authorize(actor); _id(case_id); _key(request_key)
    if not isinstance(role, str) or role not in ROLES:
        raise EntryStorageInvalid('invalid_applicant_role')
    command = {'action': 'applicant', 'case_id': case_id, 'role': role, 'actor': actor.manager_id}
    async def write(session):
        await _case(session, case_id, lock=True)
        old = await session.scalar(select(EntryApplicant).where(EntryApplicant.case_id == case_id,
                                                               EntryApplicant.request_key == request_key))
        if old:
            await _applicant(session, case_id, old.id)
            if old.request_hash != _hash(command):
                raise EntryStorageConflict('request_key_reused')
            return _applicant_view(old)
        ordinal = (await session.scalar(select(func.max(EntryApplicant.ordinal)).where(EntryApplicant.case_id == case_id)) or 0) + 1
        if ordinal > MAX_APPLICANTS:
            raise EntryStorageInvalid('applicant_limit_reached')
        row = EntryApplicant(case_id=case_id, ordinal=ordinal, role=role, request_key=request_key,
                             request_hash=_hash(command), created_by=actor.manager_id, created_at=_now())
        row.snapshot_hash = _hash(_applicant_payload(row))
        session.add(row); await session.flush()
        return _applicant_view(row)
    return await _run(engine, write)


async def open_application(engine, *, actor, case_id, applicant_id, procedure, previous_id=None, request_key):
    _authorize(actor); _id(case_id); _id(applicant_id); _key(request_key)
    if previous_id is not None: _id(previous_id)
    if not isinstance(procedure, str) or procedure not in PROCEDURES:
        raise EntryStorageInvalid('invalid_application_procedure')
    command = {'action': 'application', 'case_id': case_id, 'applicant_id': applicant_id,
               'procedure': procedure, 'previous_id': previous_id, 'actor': actor.manager_id}
    async def write(session):
        await _case(session, case_id, lock=True)
        await _applicant(session, case_id, applicant_id)
        old = await session.scalar(select(EntryApplication).where(EntryApplication.case_id == case_id,
                                                                 EntryApplication.request_key == request_key))
        if old:
            await _application(session, case_id, old.id); await _events(session, old)
            if old.request_hash != _hash(command): raise EntryStorageConflict('request_key_reused')
            return _application_view(old)
        attempt = 1
        if previous_id:
            previous = await _application(session, case_id, previous_id, lock=True)
            if previous.applicant_id != applicant_id or previous.procedure != procedure:
                raise EntryStorageInvalid('application_subject_mismatch')
            if (await _events(session, previous))[-1].status not in RETRYABLE:
                raise EntryStorageInvalid('previous_application_not_retryable')
            if await session.scalar(select(EntryApplication.id).where(EntryApplication.previous_id == previous_id)):
                raise EntryStorageConflict('application_successor_exists')
            attempt = previous.attempt + 1
            if attempt > MAX_ATTEMPTS: raise EntryStorageInvalid('application_attempt_limit')
        row = EntryApplication(case_id=case_id, applicant_id=applicant_id, procedure=procedure, attempt=attempt,
            previous_id=previous_id, request_key=request_key, request_hash=_hash(command),
            created_by=actor.manager_id, created_at=_now())
        row.snapshot_hash = _hash(_application_payload(row))
        session.add(row); await session.flush()
        first = EntryApplicationEvent(case_id=case_id, application_id=row.id, revision=1, previous_id=None,
            status='draft', occurred_on=_local_day(row.created_at), source='crm', reference=None,
            request_key=request_key, request_hash=row.request_hash, created_by=actor.manager_id, created_at=row.created_at)
        first.snapshot_hash = _hash(_event_payload(first))
        session.add(first); await session.flush()
        return _application_view(row)
    return await _run(engine, write)


async def record_application_event(engine, *, actor, case_id, application_id, expected_revision, request_key,
                                   status, occurred_on, source, reference=None, confirmed=False):
    # Preserve the public preflight contract before any engine/session access.
    _validated_event_input(actor=actor, case_id=case_id, application_id=application_id,
        expected_revision=expected_revision, request_key=request_key, status=status,
        occurred_on=occurred_on, source=source, reference=reference, confirmed=confirmed)
    async def write(session):
        return await _record_application_event_in_session(session, actor=actor, case_id=case_id,
            application_id=application_id, expected_revision=expected_revision, request_key=request_key,
            status=status, occurred_on=occurred_on, source=source, reference=reference, confirmed=confirmed)
    return await _run(engine, write)


async def _record_application_event_in_session(session, *, actor, case_id, application_id, expected_revision,
        request_key, status, occurred_on, source, reference=None, confirmed=False):
    """Caller owns the transaction; keep case→application locks and task sync.

    Used by explicit portal-observation confirmation to commit the application
    fact and its receipt action together. No commit/session/exception swallowing.
    """
    command, actual_date = _validated_event_input(actor=actor, case_id=case_id, application_id=application_id,
        expected_revision=expected_revision, request_key=request_key, status=status,
        occurred_on=occurred_on, source=source, reference=reference, confirmed=confirmed)
    case = await _case(session, case_id, lock=True)
    application = await _application(session, case_id, application_id, lock=True)
    rows = await _events(session, application)
    old = next((row for row in rows if row.request_key == request_key), None)
    if old:
        if old.request_hash != _hash(command): raise EntryStorageConflict('request_key_reused')
        return _event_view(old)
    previous = rows[-1]
    if previous.revision != expected_revision: raise EntryStorageConflict('application_revision_changed')
    _event_facts(status=status, occurred_on=actual_date, source=source, reference=reference, previous=previous, cutoff=_today())
    if reference and not previous.reference:
        if await session.scalar(select(EntryApplicationReference.application_id).where(EntryApplicationReference.reference == reference)):
            raise EntryStorageConflict('portal_reference_already_recorded')
        session.add(EntryApplicationReference(application_id=application_id, case_id=case_id, reference=reference))
    row = EntryApplicationEvent(case_id=case_id, application_id=application_id, revision=previous.revision + 1,
        previous_id=previous.id, status=status, occurred_on=actual_date, source=source, reference=reference,
        request_key=request_key, request_hash=_hash(command), created_by=actor.manager_id, created_at=_now())
    row.snapshot_hash = _hash(_event_payload(row))
    session.add(row); await session.flush()
    from app.domain.entry_deadline_tasks import sync_enabled
    await sync_enabled(session, case, application, actor.manager_id)
    return _event_view(row)


def _validated_event_input(*, actor, case_id, application_id, expected_revision, request_key,
        status, occurred_on, source, reference, confirmed):
    _authorize(actor); _id(case_id); _id(application_id); _key(request_key)
    if type(expected_revision) is not int or not 1 <= expected_revision < MAX_EVENTS:
        raise EntryStorageInvalid('invalid_application_revision')
    if confirmed is not True:
        raise EntryStorageInvalid('operator_confirmation_required')
    try:
        actual_date = date.fromisoformat(occurred_on)
        if actual_date.isoformat() != occurred_on: raise ValueError
    except (TypeError, ValueError):
        raise EntryStorageInvalid('invalid_application_date') from None
    command = {'action': 'event', 'case_id': case_id, 'application_id': application_id,
               'expected_revision': expected_revision, 'status': status, 'occurred_on': occurred_on,
               'source': source, 'reference': reference, 'confirmed': True, 'actor': actor.manager_id}
    return command, actual_date


async def read_application(engine, *, actor, case_id, application_id):
    _authorize(actor); _id(case_id); _id(application_id)
    async def read(session):
        await _case(session, case_id)
        row = await _application(session, case_id, application_id)
        events = await _events(session, row)
        child = await session.scalar(select(EntryApplication.id).where(EntryApplication.previous_id == row.id))
        return {**_application_view(row), 'events': [_event_view(event) for event in events],
                'current': _event_view(events[-1]), 'successor_id': child}
    return await _run(engine, read)


async def read_application_register(engine, *, actor, case_id, page=1):
    _authorize(actor); _id(case_id)
    if type(page) is not int or not 1 <= page <= 100000:
        raise EntryStorageInvalid('invalid_register_page')
    async def read(session):
        await _case(session, case_id)
        people = (await session.scalars(select(EntryApplicant).where(EntryApplicant.case_id == case_id)
                                       .order_by(EntryApplicant.ordinal).limit(MAX_APPLICANTS + 1))).all()
        if len(people) > MAX_APPLICANTS: raise EntryStorageInvalid('application_integrity_failed')
        for person in people:
            _checked(person, _applicant_command, _applicant_payload)
            if person.role not in ROLES: raise EntryStorageInvalid('application_integrity_failed')
        total = await session.scalar(select(func.count()).select_from(EntryApplication).where(EntryApplication.case_id == case_id))
        ids = (await session.scalars(select(EntryApplication.id).where(EntryApplication.case_id == case_id)
                                    .order_by(EntryApplication.id.desc()).offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE))).all()
        applications = []
        for application_id in ids:
            row = await _application(session, case_id, application_id)
            current = (await _events(session, row))[-1]
            applications.append({**_application_view(row), 'current': _event_view(current)})
        return {'applicants': [_applicant_view(row) for row in people], 'applications': applications,
                'total': total, 'page': page, 'has_next': total > page * PAGE_SIZE}
    return await _run(engine, read)
