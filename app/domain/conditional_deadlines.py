"""Conditional review branch of existing deadline receipts and CRM task bindings."""
from copy import deepcopy

from sqlalchemy import select

from app.domain import entry_anchors as anchors, entry_applications as apps, entry_deadlines as legacy
from app.domain import conditional_deadline_rules as rules, conditional_deadline_sources as sources
from app.domain import conditional_deadline_evidence as evidence, conditional_deadline_policy as policies
from app.domain.entry_anchor_rules import fail, shape
from app.domain.entry_storage import _authorize, _hash, _id, _key, _plain, EntryStorageConflict
from app.domain.models import EntryDeadlineRevision, EntryConditionalEvidence, _now
from app.domain.service_authz import PermissionDenied
from app.knowledge.review import canonical

MAX_EVENT_BYTES = 256 * 1024


def is_conditional(row): return _plain(row.snapshot).get('format') == rules.FORMAT


def normalize(operation):
    shape(operation, ('action', 'confirmed', 'evidence_hash'))
    if operation['confirmed'] is not True or operation['action'] not in ('conditional_review', 'conditional_clear'): fail('conditional_deadline_operation_invalid')
    anchors.rules.text(operation['evidence_hash'], r'[a-f0-9]{64}')
    return _plain(operation)


def summary(snapshot):
    report = snapshot['report']; cleared = snapshot['cleared']
    return dict(status='cleared' if cleared else 'conditional_review_recorded', review_due_on=None if cleared else report['review_due_on'],
        operational_due_on=None, blockers=['conditional_review_cleared'] if cleared else [], manual=False,
        scope='internal_specialist_review_only', filing_allowed=False, may_quote=False)


def view(row):
    return dict(id=row.id, revision=row.revision, created_by=row.created_by, created_at=apps._utc(row.created_at),
        snapshot_hash=row.snapshot_hash, snapshot=_plain(row.snapshot), operation=_plain(row.command)['operation'], summary=summary(_plain(row.snapshot)))


async def history(session, case, application, rule, rows):
    # Profile/history writers hold the applicant lock. Acquire it before source
    # publication locks and before any task may project a conditional date.
    _, person, _ = await anchors.scope(session, case.id, application.applicant_id, application.id)
    pins = list((await session.scalars(select(EntryConditionalEvidence).where(EntryConditionalEvidence.application_id==application.id,
        EntryConditionalEvidence.rule_unit_id==rule).limit(legacy.MAX_REVISIONS+2))).all())
    if len(pins)!=len(rows): fail('conditional_deadline_independent_pin_invalid')
    cache = {'pins':{p.deadline_id:p for p in pins}}
    previous = None; size = 0; terminal = False
    for revision, row in enumerate(rows, 1):
        if not is_conditional(row): fail('conditional_deadline_mixed_track')
        operation = normalize(_plain(row.command)['operation']); snapshot = _plain(row.snapshot)
        command = legacy._command(case.id, application.id, rule, revision-1, operation, row.created_by)
        row_size = len(canonical(legacy._payload(row)).encode()); overflow = revision > legacy.MAX_REVISIONS or size+row_size > legacy.MAX_BYTES
        event_limit = MAX_EVENT_BYTES + (legacy.CLEAR_RECEIPT_ALLOWANCE if operation['action']=='conditional_clear' else 0)
        if terminal or row_size > event_limit or overflow and (operation['action'] != 'conditional_clear' or previous is None or
                row_size > len(canonical(legacy._payload(previous)).encode()) + legacy.CLEAR_RECEIPT_ALLOWANCE): fail('deadline_history_limit')
        if (row.case_id != case.id or row.revision != revision or canonical(row.command) != canonical(command) or
                row.request_hash != _hash(command) or row.snapshot_hash != _hash(legacy._payload(row)) or
                row.previous_id != (previous.id if previous else None) or previous and (row.id <= previous.id or apps._utc(row.created_at) < apps._utc(previous.created_at)) or
                snapshot['previous_hash'] != (previous.snapshot_hash if previous else None) or row.anchor_event_id is not None or row.anchor_issued_id is not None):
            fail('conditional_deadline_integrity_failed')
        if operation['action'] == 'conditional_clear':
            if previous is None or previous.snapshot['cleared'] or operation['evidence_hash'] != previous.snapshot_hash: fail('conditional_deadline_clear_invalid')
            expected = _plain(previous.snapshot) | dict(cleared=True, previous_hash=previous.snapshot_hash)
            if canonical(snapshot) != canonical(expected): fail('conditional_deadline_clear_invalid')
        elif snapshot['cleared'] or operation['evidence_hash'] != snapshot['report']['evidence_hash'] or apps._utc(row.created_at) != snapshot['report']['checked_at']:
            fail('conditional_deadline_integrity_failed')
        authority = await evidence.verify(session, case, person, application, row, cache=cache)
        if row.created_by not in authority.policy.document['operators']: fail('conditional_deadline_operator_invalid')
        previous = row; size += row_size; terminal = overflow
    return rows, size, {r.id:False for r in rows}


def configured(rule):
    from app.config import settings
    return policies.configured(settings, rule)


async def current(session, case, application, row, *, authority=None):
    at = _now()
    latest = await session.scalar(select(EntryDeadlineRevision).where(EntryDeadlineRevision.application_id==application.id,
        EntryDeadlineRevision.rule_unit_id==row.rule_unit_id).order_by(EntryDeadlineRevision.revision.desc()).limit(1))
    if latest is None or latest.id != row.id:
        return dict(status='superseded', reason='conditional_deadline_revision_superseded', review_due_on=None)
    if apps._utc(row.created_at) > apps._utc(at):
        return dict(status='unknown', reason='conditional_deadline_receipt_from_future', review_due_on=None)
    if row.snapshot['cleared']: return dict(status='cleared', reason='conditional_review_cleared', review_due_on=None)
    authority = configured(row.rule_unit_id) if authority is None else authority
    if authority is None or canonical(authority.document) != canonical(_plain(row.snapshot)['authority']):
        return dict(status='unknown', reason='conditional_deadline_authority_changed', review_due_on=None)
    person = await apps._applicant(session, case.id, application.applicant_id)
    fresh = await sources.evaluate(session, actor=row.created_by, case=case, person=person, application=application,
        rule_id=row.rule_unit_id, authority=authority, at=at)
    retained = _plain(row.snapshot)['report']
    keys = ('source','profile','application_event','interview','interruptions','anchors','stay_history','renewal_context','calculations','trigger','status')
    if fresh['review_due_on'] is None or any(canonical(fresh[k]) != canonical(retained[k]) for k in keys):
        return dict(status='unknown', reason=fresh['reason'] if fresh['review_due_on'] is None else 'conditional_deadline_evidence_changed', review_due_on=None)
    return dict(status='current_conditional_review', reason=fresh['reason'], review_due_on=retained['review_due_on'],
        within_review_date=fresh['on'] <= retained['review_due_on'] if authority.policy.document['boundary_inclusive'] else fresh['on'] < retained['review_due_on'])


async def task_authorize(session, case, application, rule, actor):
    rows, _, _ = await legacy._history(session, case, application, rule)
    if rows and is_conditional(rows[-1]):
        authority = configured(rule)
        if authority is None or actor not in authority.policy.document['operators']: raise PermissionDenied('conditional review task authority required')


async def preview(engine, *, actor, case_id, applicant_id, application_id, rule_unit_id, authority=None):
    _authorize(actor)
    for v in (case_id, applicant_id, application_id): _id(v)
    rules.definition(rule_unit_id)
    async def run(session):
        case, person, application = await anchors.scope(session, case_id, applicant_id, application_id)
        rows, _, _ = await legacy._history(session, case, application, rule_unit_id)
        if rows and not is_conditional(rows[-1]): fail('conditional_deadline_legacy_track_preserved')
        report = await sources.evaluate(session, actor=actor.manager_id, case=case, person=person, application=application,
            rule_id=rule_unit_id, authority=authority)
        return dict(report=report, revision=len(rows), selected=view(rows[-1]) if rows else None)
    return await apps._run(engine, run)


async def record(engine, *, actor, case_id, applicant_id, application_id, rule_unit_id, expected_revision,
                 request_key, operation, authority=None):
    _authorize(actor)
    for v in (case_id, applicant_id, application_id): _id(v)
    _key(request_key); rules.definition(rule_unit_id); operation = normalize(operation)
    if type(expected_revision) is not int or not 0 <= expected_revision <= legacy.MAX_REVISIONS: fail('invalid_deadline_revision')
    command = legacy._command(case_id, application_id, rule_unit_id, expected_revision, operation, actor.manager_id)
    async def run(session):
        case, person, application = await anchors.scope(session, case_id, applicant_id, application_id)
        rows, size, _ = await legacy._history(session, case, application, rule_unit_id)
        if rows and not is_conditional(rows[-1]): fail('conditional_deadline_legacy_track_preserved')
        old = next((r for r in rows if r.request_key == request_key), None)
        if old:
            if old.request_hash != _hash(command): raise EntryStorageConflict('deadline_request_key_reused')
            return view(old)
        if len(rows) != expected_revision: raise EntryStorageConflict('deadline_revision_changed')
        previous = rows[-1] if rows else None
        if operation['action'] == 'conditional_review':
            # The first receipt has no history verifier to acquire this lock.
            # Capture the admission day only after a concurrent publisher finishes.
            await sources.publication._runtime_context(session)
        at = _now()
        if previous and apps._utc(at) < apps._utc(previous.created_at): fail('conditional_deadline_clock_moved_back')
        if len(rows) > legacy.MAX_REVISIONS or size > legacy.MAX_BYTES: fail('deadline_history_limit')
        if not previous:
            tracks = list((await session.scalars(select(EntryDeadlineRevision.rule_unit_id).where(EntryDeadlineRevision.application_id==application.id).distinct().limit(legacy.MAX_TRACKS))).all())
            if len(tracks) >= legacy.MAX_TRACKS: fail('deadline_track_limit')
        if operation['action'] == 'conditional_clear':
            if previous is None or previous.snapshot['cleared']: fail('conditional_deadline_clear_unavailable')
            if operation['evidence_hash'] != previous.snapshot_hash: raise EntryStorageConflict('conditional_deadline_evidence_changed')
            snapshot = _plain(previous.snapshot) | dict(cleared=True, previous_hash=previous.snapshot_hash)
            operators = snapshot['authority']['policy']['operators']
        else:
            if not isinstance(authority, policies.ConditionalAuthority): raise PermissionDenied('conditional review authority required')
            report = await sources.evaluate(session, actor=actor.manager_id, case=case, person=person, application=application,
                rule_id=rule_unit_id, authority=authority, at=at)
            if report['review_due_on'] is None: fail(report['reason'])
            # The preview pins source inputs, not a fleeting wall-clock timestamp.
            if operation['evidence_hash'] != report['evidence_hash']: raise EntryStorageConflict('conditional_deadline_preview_changed')
            snapshot = dict(format=rules.FORMAT, authority=authority.document, report=report, cleared=False,
                previous_hash=previous.snapshot_hash if previous else None)
            operators = authority.policy.document['operators']
        if actor.manager_id not in operators: raise PermissionDenied('conditional review operator is not authorized')
        report = snapshot['report']
        row = EntryDeadlineRevision(case_id=case.id, application_id=application.id, rule_unit_id=rule_unit_id,
            knowledge_version_id=report['source']['version_id'], anchor_event_id=None, anchor_issued_id=None,
            revision=len(rows)+1, previous_id=previous.id if previous else None, request_key=request_key,
            request_hash=_hash(command), command=command, snapshot=snapshot, created_by=actor.manager_id, created_at=at)
        amount = len(canonical(legacy._payload(row)).encode())
        event_limit = MAX_EVENT_BYTES + (legacy.CLEAR_RECEIPT_ALLOWANCE if operation['action']=='conditional_clear' else 0)
        if amount > event_limit or (len(rows)+1 > legacy.MAX_REVISIONS or size+amount > legacy.MAX_BYTES) and (
                operation['action'] != 'conditional_clear' or previous is None or amount > len(canonical(legacy._payload(previous)).encode())+legacy.CLEAR_RECEIPT_ALLOWANCE): fail('deadline_history_limit')
        row.snapshot_hash = _hash(legacy._payload(row)); session.add(row); await session.flush()
        arows, _, _, _ = await anchors.history(session, case, person, application)
        count = report['anchors']['revision']
        session.add(EntryConditionalEvidence(deadline_id=row.id, case_id=case.id, application_id=application.id,
            rule_unit_id=rule_unit_id, applicant_id=person.id, profile_id=report['profile']['id'],
            application_event_id=report['application_event']['id'], anchor_id=arows[count-1].id if count else None,
            history_id=report['stay_history']['id'] if report['stay_history'] else None, receipt_hash=row.snapshot_hash))
        await session.flush()
        from app.domain.entry_deadline_tasks import sync_enabled
        await sync_enabled(session, case, application, actor.manager_id)
        return view(row)
    return await apps._run(engine, run)
