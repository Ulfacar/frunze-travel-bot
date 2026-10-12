"""Owned immutable actual-date observations, without deadline or legal approval."""
from datetime import date
from sqlalchemy import select

from app.domain import entry_applications as apps, applicant_profiles as profiles, entry_issued as issued
from app.domain import entry_anchor_rules as rules
from app.domain.entry_anchor_rules import AnchorPolicy, fail
from app.domain.entry_storage import _authorize, _hash, _id, _key, _plain, EntryStorageConflict
from app.domain.models import EntryAnchorEvent, EntryAnchorPin, _now
from app.domain.service_authz import PermissionDenied
from app.knowledge.review import canonical


def pin(row):
    return dict(id=row.id, revision=row.revision, hash=row.snapshot_hash)


def _payload(row):
    keys = ('case_id', 'applicant_id', 'application_id', 'procedure', 'kind', 'anchor_key', 'revision',
            'previous_id', 'action', 'request_key', 'request_hash', 'command', 'snapshot', 'created_by')
    return {**{k: _plain(getattr(row, k)) for k in keys}, 'created_at': apps._utc(row.created_at)}


def _command(actor, case_id, applicant_id, application_id, kind, anchor_key, revision, operation):
    return dict(format=rules.FORMAT, actor=actor, case_id=case_id, applicant_id=applicant_id,
        application_id=application_id, kind=kind, anchor_key=anchor_key, expected_revision=revision, operation=operation)


def _view(row):
    return dict(id=row.id, case_id=row.case_id, applicant_id=row.applicant_id, application_id=row.application_id,
        kind=row.kind, anchor_key=row.anchor_key, revision=row.revision, snapshot_hash=row.snapshot_hash,
        created_by=row.created_by, created_at=apps._utc(row.created_at), operation=_plain(row.command)['operation'],
        snapshot=_plain(row.snapshot))


async def scope(session, case_id, applicant_id, application_id):
    case = await apps._case(session, case_id, lock=True)
    application = await apps._application(session, case_id, application_id, lock=True)
    if application.applicant_id != applicant_id: fail('actual_anchor_subject_mismatch')
    _, person = await profiles._subject(session, case_id, applicant_id, write=True)
    return case, person, application


def selected(rows, identifier, at):
    _id(identifier)
    row = next((r for r in rows if r.id == identifier), None)
    if row is None or apps._utc(row.created_at) > apps._utc(at): fail('actual_anchor_source_unavailable')
    # Retained ids establish order when two serial transactions share a clock tick.
    if any(r.revision > row.revision and apps._utc(r.created_at) < apps._utc(at) for r in rows):
        fail('actual_anchor_source_was_stale')
    return row


class Evidence:
    def __init__(self, session, case, person, application):
        self.session = session; self.case = case; self.person = person; self.application = application
        self.issued = {}

    async def load(self):
        self.profiles = (await profiles._history(self.session, self.case, self.person))[0]
        self.events = await apps._events(self.session, self.application)
        return self

    async def observe(self, kind, data, at, retained=None):
        profile = selected(self.profiles, data['profile_id'], at)
        event = selected(self.events, data['application_event_id'], at)
        if data['profile_hash'] != profile.snapshot_hash: fail('actual_anchor_profile_changed')
        if kind in rules.PERIODS and (event.status != 'approved' or event.source not in ('portal', 'official_document')):
            fail('actual_anchor_approval_required')
        if event.status == 'refused' or event.status == 'closed' and kind != 'permit_terminated': fail('actual_anchor_application_closed')
        if kind == 'permit_terminated' and not any(r.status == 'approved' and r.source in ('portal', 'official_document') for r in self.events if r.id <= event.id):
            fail('actual_anchor_approval_required')
        if data['on'] < event.occurred_on.isoformat() and kind in rules.PERIODS:
            fail('actual_anchor_observation_precedes_approval')
        result = dict(profile=pin(profile), application_event=pin(event), issued=None)
        if kind == 'visa_renewal_context':
            period = await self.session.get(EntryAnchorEvent, data['value']['period_anchor_id'])
            if (period is None or period.application_id != self.application.id or period.applicant_id != self.person.id or
                    period.kind != 'visa_period' or period.action != 'record' or period.snapshot_hash != data['value']['period_anchor_hash'] or
                    period.snapshot_hash != _hash(_payload(period)) or apps._utc(period.created_at) > apps._utc(at)):
                fail('actual_anchor_renewal_period_invalid')
        if kind == 'visa_period':
            if event.id not in self.issued:
                self.issued[event.id] = (await issued._history(self.session, self.application, event))[0]
            rows = self.issued[event.id]
            chosen = selected(rows, retained['issued']['id'], at) if retained else rows[-1] if rows else None
            if chosen is None or apps._utc(chosen.created_at) > apps._utc(at): fail('actual_anchor_issued_document_required')
            state = _plain(chosen.snapshot)
            from app.domain.entry_issued_rules import verified
            if (not verified(state) or state['fingerprint'] != data['value']['document_ref'] or
                    state['current_passport'] != data['value']['passport_ref']):
                fail('actual_anchor_document_mismatch')
            result['issued'] = pin(chosen)
        if kind == 'registration_period' and data['value']['tax_status'] in ('pending', 'confirmed'):
            p = _plain(profile.input_snapshot)['profile']
            if (p.get('entry_passport_country') not in rules.EAEU - {'KGZ'} or
                    len(p.get('citizenship', [])) != 1 or p['citizenship'][0] != p['entry_passport_country']):
                fail('actual_anchor_eaeu_scope_unresolved')
        if retained is not None and canonical(result) != canonical(retained): fail('actual_anchor_evidence_changed')
        return result


async def history(session, case, person, application):
    rows = list((await session.scalars(select(EntryAnchorEvent).where(EntryAnchorEvent.application_id == application.id)
        .order_by(EntryAnchorEvent.revision).limit(rules.MAX_REVISIONS + rules.MAX_ACTIVE + 1))).all())
    if len(rows) > rules.MAX_REVISIONS + rules.MAX_ACTIVE: fail('actual_anchor_history_limit')
    evidence = await Evidence(session, case, person, application).load()
    source_pins = list((await session.scalars(select(EntryAnchorPin).where(EntryAnchorPin.application_id == application.id)
        .limit(rules.MAX_REVISIONS + 1))).all())
    by_anchor = {p.anchor_id: p for p in source_pins}
    if len(by_anchor) != len(source_pins) or len(source_pins) != sum(r.action == 'record' for r in rows):
        fail('actual_anchor_source_pin_invalid')
    previous = None; size = 0; latest = {}
    for revision, row in enumerate(rows, 1):
        at = row.created_at; on = apps._local_day(at)
        if any(apps._utc(v.created_at) > apps._utc(at) for v in (case, person, application)):
            fail('actual_anchor_future_source')
        operation = rules.normalize(row.kind, _plain(row.command)['operation'], on)
        rules.text(row.anchor_key, r'[A-Z][A-Z0-9._/-]{0,63}')
        command = _command(row.created_by, case.id, person.id, application.id, row.kind, row.anchor_key, revision - 1, operation)
        if (row.case_id != case.id or row.applicant_id != person.id or row.procedure != application.procedure or
                rules.KINDS[row.kind] != application.procedure or row.action != operation['action'] or row.revision != revision or
                row.previous_id != (previous.id if previous else None) or previous and (row.id <= previous.id or apps._utc(at) < apps._utc(previous.created_at)) or
                canonical(row.command) != canonical(command) or row.request_hash != _hash(command) or row.snapshot_hash != _hash(_payload(row))):
            fail('actual_anchor_integrity_failed')
        old = latest.get(row.anchor_key)
        if old and old.kind != row.kind: fail('actual_anchor_kind_changed')
        snapshot = _plain(row.snapshot)
        rules.shape(snapshot, ('format', 'previous_hash', 'application_hash', 'applicant_hash', 'policy', 'evidence', 'operators'))
        if (snapshot['format'] != rules.FORMAT or snapshot['previous_hash'] != (previous.snapshot_hash if previous else None) or
                snapshot['application_hash'] != application.snapshot_hash or snapshot['applicant_hash'] != person.snapshot_hash):
            fail('actual_anchor_integrity_failed')
        if operation['action'] == 'record':
            policy = AnchorPolicy(snapshot['policy']); p = policy.document
            if (row.created_by not in p['operators'] or row.kind not in p['kinds'] or
                    not p['valid_from'] <= on.isoformat() <= p['review_due_on'] or snapshot['operators'] != p['operators']):
                fail('actual_anchor_authority_invalid')
            await evidence.observe(row.kind, operation['data'], at, retained=snapshot['evidence'])
            captured = snapshot['evidence']; source_pin = by_anchor.get(row.id)
            if (source_pin is None or source_pin.case_id != case.id or source_pin.applicant_id != person.id or
                    source_pin.receipt_hash != row.snapshot_hash or source_pin.profile_id != captured['profile']['id'] or
                    source_pin.application_event_id != captured['application_event']['id'] or
                    source_pin.issued_id != (captured['issued']['id'] if captured['issued'] else None)):
                fail('actual_anchor_source_pin_invalid')
            if row.kind in rules.PERIODS and any(v.anchor_key != row.anchor_key and v.kind == row.kind and v.action == 'record' for v in latest.values()):
                fail('actual_anchor_period_ambiguous')
        else:
            if (old is None or old.action != 'record' or snapshot['policy'] is not None or snapshot['evidence'] is not None or
                    snapshot['operators'] != list(old.snapshot['operators']) or row.created_by not in snapshot['operators']):
                fail('actual_anchor_withdrawal_invalid')
        row_size = len(canonical(_payload(row)).encode()); size += row_size
        if (row_size > rules.MAX_EVENT_BYTES or size > rules.MAX_BYTES or
                revision > rules.MAX_REVISIONS and (operation['action'] != 'withdraw' or row_size > rules.WITHDRAW_RESERVE)):
            fail('actual_anchor_history_limit')
        latest[row.anchor_key] = row; previous = row
        active = sum(r.action == 'record' for r in latest.values())
        if active > rules.MAX_ACTIVE: fail('actual_anchor_active_limit')
        if size + active * rules.WITHDRAW_RESERVE > rules.MAX_BYTES: fail('actual_anchor_history_limit')
    return rows, latest, size, evidence


async def current(session, case, person, application, *, policy=None, at=None):
    rows, latest, size, evidence = await history(session, case, person, application)
    at = _now() if at is None else at; on = apps._local_day(at).isoformat(); observations = []
    if policy is not None and not isinstance(policy, AnchorPolicy): fail('invalid_actual_anchor_policy')
    replacements, active_changes = await passport_observations(session, case, person, application, rows, latest)
    for row in latest.values():
        reasons = []; snapshot = _plain(row.snapshot); data = _plain(row.command)['operation']['data']
        if row.action == 'withdraw': reasons.append('actual_anchor_withdrawn')
        else:
            if policy is None or policy.digest != _hash(snapshot['policy']): reasons.append('actual_anchor_authority_changed')
            elif not policy.document['valid_from'] <= on <= policy.document['review_due_on']: reasons.append('actual_anchor_authority_expired')
            if not evidence.profiles or pin(evidence.profiles[-1]) != snapshot['evidence']['profile']: reasons.append('actual_anchor_profile_changed')
            if pin(evidence.events[-1]) != snapshot['evidence']['application_event']: reasons.append('actual_anchor_application_changed')
            if any(apps._utc(r.created_at) > apps._utc(at) for r in (case, person, application, row, evidence.events[-1], *evidence.profiles[-1:])):
                reasons.append('actual_anchor_future_source')
            if row.kind == 'visa_period':
                issued_rows = evidence.issued[data['application_event_id']]
                if not issued_rows or pin(issued_rows[-1]) != snapshot['evidence']['issued']: reasons.append('actual_anchor_document_changed')
            if row.kind in rules.PERIODS:
                if row.kind == 'permit_period' and any(r.kind == 'permit_terminated' and r.action == 'record' for r in latest.values()):
                    reasons.append('actual_anchor_permit_terminated')
                # A later observed replacement invalidates an old period even if
                # that replacement is subsequently withdrawn. A fresh explicit
                # period confirmation is needed to settle the document identity.
                newest = max(active_changes, key=lambda r: (r.command['operation']['data']['on'], r.id)) if active_changes else None
                if (any(r.id > row.id for r in replacements) or newest and
                        newest.command['operation']['data']['value']['after_ref'] != data['value']['passport_ref']):
                    reasons.append('actual_anchor_passport_changed')
                if any(apps._utc(r.created_at) > apps._utc(at) for r in replacements): reasons.append('actual_anchor_future_source')
                from app.domain.entry_document_packages import quarantined_fingerprints
                if await quarantined_fingerprints(session, {data['value']['document_ref'], data['value']['passport_ref']}):
                    reasons.append('actual_anchor_document_quarantined')
        observations.append(dict(receipt=_view(row), usable=not reasons, reasons=reasons))
    return dict(revision=len(rows), head=rows[-1].snapshot_hash if rows else None,
        observations=observations, checked_at=apps._utc(at), terminal=len(rows)>rules.MAX_REVISIONS)


async def passport_observations(session, case, person, application, rows, latest):
    """Case lock serializes own-person writers across distinct document attempts."""
    ids = list((await session.scalars(select(EntryAnchorEvent.application_id).where(
        EntryAnchorEvent.case_id == case.id, EntryAnchorEvent.applicant_id == person.id,
        EntryAnchorEvent.kind == 'passport_change').distinct().limit(33))).all())
    if len(ids) > 32: fail('actual_anchor_passport_scope_limit')
    replacements = [r for r in rows if r.kind == 'passport_change' and r.action == 'record']
    active = [r for r in latest.values() if r.kind == 'passport_change' and r.action == 'record']
    for identifier in ids:
        if identifier == application.id: continue
        other = await apps._application(session, case.id, identifier)
        if other.applicant_id != person.id: fail('actual_anchor_subject_mismatch')
        other_rows, other_latest, _, _ = await history(session, case, person, other)
        replacements.extend(r for r in other_rows if r.kind == 'passport_change' and r.action == 'record')
        active.extend(r for r in other_latest.values() if r.kind == 'passport_change' and r.action == 'record')
    return replacements, active


async def read(engine, *, actor, case_id, applicant_id, application_id, policy=None):
    _authorize(actor)
    for value in (case_id, applicant_id, application_id): _id(value)
    async def run(session):
        case, person, application = await scope(session, case_id, applicant_id, application_id)
        return await current(session, case, person, application, policy=policy)
    return await apps._run(engine, run)


async def record(engine, *, actor, case_id, applicant_id, application_id, kind, anchor_key,
                 expected_revision, request_key, operation, policy=None):
    _authorize(actor)
    for value in (case_id, applicant_id, application_id): _id(value)
    _key(request_key); rules.text(anchor_key, r'[A-Z][A-Z0-9._/-]{0,63}')
    if type(expected_revision) is not int or not 0 <= expected_revision < rules.MAX_REVISIONS + rules.MAX_ACTIVE: fail('invalid_actual_anchor_revision')
    operation = rules.normalize(kind, operation, date.max)
    command = _command(actor.manager_id, case_id, applicant_id, application_id, kind, anchor_key, expected_revision, operation)
    async def run(session):
        case, person, application = await scope(session, case_id, applicant_id, application_id)
        if application.procedure != rules.KINDS[kind]: fail('actual_anchor_procedure_mismatch')
        rows, latest, size, evidence = await history(session, case, person, application)
        old_request = await session.scalar(select(EntryAnchorEvent).where(EntryAnchorEvent.case_id == case_id, EntryAnchorEvent.request_key == request_key))
        if old_request:
            if old_request.application_id != application_id or old_request.request_hash != _hash(command): raise EntryStorageConflict('actual_anchor_request_reused')
            return _view(old_request)
        if len(rows) != expected_revision: raise EntryStorageConflict('actual_anchor_revision_changed')
        at = _now(); on = apps._local_day(at).isoformat(); old = latest.get(anchor_key); action = operation['action']
        rules.normalize(kind, operation, apps._local_day(at))
        if any(apps._utc(v.created_at) > apps._utc(at) for v in (case, person, application)):
            fail('actual_anchor_future_source')
        if len(rows) >= rules.MAX_REVISIONS + rules.MAX_ACTIVE or len(rows) >= rules.MAX_REVISIONS and action != 'withdraw': fail('actual_anchor_history_limit')
        if old and old.kind != kind: fail('actual_anchor_kind_changed')
        captured = None; document = None
        if action == 'record':
            if not isinstance(policy, AnchorPolicy): raise PermissionDenied('actual anchor authority required')
            document = policy.document; operators = document['operators']
            if actor.manager_id not in operators or kind not in document['kinds'] or not document['valid_from'] <= on <= document['review_due_on']:
                raise PermissionDenied('actual anchor operator is not authorized')
            if kind in rules.PERIODS and any(r.anchor_key != anchor_key and r.kind == kind and r.action == 'record' for r in latest.values()):
                fail('actual_anchor_period_ambiguous')
            data = operation['data']
            if not evidence.profiles or data['profile_id'] != evidence.profiles[-1].id or data['application_event_id'] != evidence.events[-1].id:
                raise EntryStorageConflict('actual_anchor_sources_changed')
            captured = await evidence.observe(kind, data, at)
            replacements, active_changes = await passport_observations(session, case, person, application, rows, latest)
            if kind == 'passport_change':
                scopes = list((await session.scalars(select(EntryAnchorEvent.application_id).where(
                    EntryAnchorEvent.case_id==case.id,EntryAnchorEvent.applicant_id==person.id,
                    EntryAnchorEvent.kind=='passport_change').distinct().limit(33))).all())
                if application.id not in scopes and len(scopes)>=32: fail('actual_anchor_passport_scope_limit')
            if any(apps._utc(r.created_at) > apps._utc(at) for r in replacements): fail('actual_anchor_future_source')
            newest = max(active_changes, key=lambda r: (r.command['operation']['data']['on'], r.id)) if active_changes else None
            if kind in rules.PERIODS and newest and newest.command['operation']['data']['value']['after_ref'] != data['value']['passport_ref']:
                fail('actual_anchor_passport_changed')
        else:
            if old is None or old.action != 'record': fail('actual_anchor_withdrawal_unavailable')
            operators = list(old.snapshot['operators'])
            if actor.manager_id not in operators: raise PermissionDenied('actual anchor operator is not authorized')
        previous = rows[-1] if rows else None
        if previous and apps._utc(at) < apps._utc(previous.created_at): fail('actual_anchor_clock_moved_back')
        snapshot = dict(format=rules.FORMAT, previous_hash=previous.snapshot_hash if previous else None,
            application_hash=application.snapshot_hash, applicant_hash=person.snapshot_hash,
            policy=document, evidence=captured, operators=operators)
        row = EntryAnchorEvent(case_id=case_id, applicant_id=applicant_id, application_id=application_id,
            procedure=application.procedure, kind=kind, anchor_key=anchor_key, revision=len(rows)+1,
            previous_id=previous.id if previous else None, action=action, request_key=request_key,
            request_hash=_hash(command), command=command, snapshot=snapshot, created_by=actor.manager_id, created_at=at)
        row_size = len(canonical(_payload(row)).encode())
        active = sum(r.action == 'record' for k, r in latest.items() if k != anchor_key) + int(action == 'record')
        if active > rules.MAX_ACTIVE: fail('actual_anchor_active_limit')
        if row_size > rules.MAX_EVENT_BYTES or size + row_size > rules.MAX_BYTES - active * rules.WITHDRAW_RESERVE or action == 'withdraw' and row_size > rules.WITHDRAW_RESERVE:
            fail('actual_anchor_history_limit')
        row.snapshot_hash = _hash(_payload(row)); session.add(row); await session.flush()
        if captured is not None:
            session.add(EntryAnchorPin(anchor_id=row.id, case_id=case_id, applicant_id=applicant_id, application_id=application_id,
                profile_id=captured['profile']['id'], application_event_id=captured['application_event']['id'],
                issued_id=captured['issued']['id'] if captured['issued'] else None, receipt_hash=row.snapshot_hash))
            await session.flush()
        return _view(row)
    return await apps._run(engine, run)
