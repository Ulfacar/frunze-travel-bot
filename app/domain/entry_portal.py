"""Untrusted portal receipts and explicit, atomic operator confirmation.

No mailbox, outbound messages, inferred payments or automatic decisions.
"""
from copy import deepcopy
import hashlib
import re

from sqlalchemy import select

from app.domain import entry_applications as applications
from app.domain.entry_portal_parser import MAX_BYTES, parse
from app.domain.entry_portal_policy import (KINDS, SOURCES, PARSER_VERSION, authorize, day, opaque,
    policy_from_document, proof)
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _authorize, _hash, _id, _key
from app.domain.knowledge_review import _plain
from app.domain.models import EntryApplicationReference, EntryPortalReceipt, EntryPortalAction, _now
from app.domain.service_authz import PermissionDenied

MAX_ACTIONS = 64
MAX_JOURNAL_BYTES = 262144
APPLY = {'correction': 'revision_requested', 'approval': 'approved', 'refusal': 'refused'}
ISSUES = {'markup_or_quote', 'invalid_reference', 'quoted_capture', 'invalid_date', 'unknown_status',
          'reference_not_unique', 'status_not_unique', 'date_not_unique'}


def _fail(code='portal_integrity_failed'): raise EntryStorageInvalid(code)


def _exact(value, keys):
    if type(value) is not dict or value.keys() != set(keys): _fail()


def _historical_authority(policy, actor, created_at, channel=None):
    if actor not in policy.operators or not day(policy.valid_from) <= applications._local_day(created_at) <= day(policy.review_due_on): _fail()
    if channel == 'paste' and not policy.allow_paste or channel in SOURCES and channel not in policy.manual_sources: _fail()


def _stamp(row):
    return dict(request_key=row.request_key, request_hash=row.request_hash,
                created_by=row.created_by, created_at=applications._utc(row.created_at))


def _receipt_payload(row):
    return dict(case_id=row.case_id, source_namespace=row.source_namespace, channel=row.channel,
        transport_id=row.transport_id, raw_sha256=row.raw_sha256, raw_bytes=row.raw_bytes,
        command=_plain(row.command), captures=_plain(row.captures), policy=_plain(row.policy), **_stamp(row))


def _action_payload(row):
    return dict(receipt_id=row.receipt_id, case_id=row.case_id, revision=row.revision, previous_id=row.previous_id,
        action=row.action, application_id=row.application_id, applicant_id=row.applicant_id, procedure=row.procedure,
        head_id=row.head_id, cycle_id=row.cycle_id, applied_event_id=row.applied_event_id,
        applied_content_hash=row.applied_content_hash, command=_plain(row.command), snapshot=_plain(row.snapshot),
        policy=_plain(row.policy), **_stamp(row))


def _reference(value):
    if type(value) is not str or not re.fullmatch('[A-Z0-9]{8}', value): _fail('invalid_portal_reference')
    return value


def _manual(value):
    _exact(value, ('reference', 'kind', 'occurred_on'))
    _reference(value['reference'])
    if type(value['kind']) is not str or value['kind'] not in KINDS: _fail('invalid_portal_kind')
    day(value['occurred_on'])
    return value


def _captures(value, command, policy):
    _exact(value, ('parser_version', 'raw_sha256', 'raw_bytes', 'references', 'kinds', 'dates', 'issues'))
    if value['parser_version'] != PARSER_VERSION or value['raw_sha256'] != command['raw_sha256'] or value['raw_bytes'] != command['raw_bytes']: _fail()
    for key in ('references', 'kinds', 'dates', 'issues'):
        items = value[key]
        if type(items) is not list or len(items) > 128 or any(type(v) is not str for v in items) or items != sorted(set(items)): _fail()
    for ref in value['references']: _reference(ref)
    for on in value['dates']: day(on)
    if not set(value['kinds']) <= KINDS or not set(value['issues']) <= ISSUES: _fail()
    if command['channel'] == 'paste' and not set(value['kinds']) <= {k for k, _ in policy.status_labels}: _fail()
    if not value['issues'] and (len(value['references']) != 1 or len(value['kinds']) != 1 or len(value['dates']) > 1): _fail()
    if command['channel'] != 'paste':
        m = command['manual']
        if value != _manual_captures(m, command['raw_sha256'], command['raw_bytes']): _fail()


def _manual_captures(value, digest, size):
    return dict(parser_version=PARSER_VERSION, raw_sha256=digest, raw_bytes=size,
        references=[value['reference']], kinds=[value['kind']], dates=[value['occurred_on']], issues=[])


def _receipt_check(row):
    command = _plain(row.command); policy = policy_from_document(_plain(row.policy))
    _exact(command, ('action', 'case_id', 'channel', 'source_namespace', 'transport_id', 'raw_sha256', 'raw_bytes',
                     'manual', 'archive_reference', 'archive_proof', 'actor', 'policy_hash'))
    if (command['action'] != 'receive' or command['case_id'] != row.case_id or command['actor'] != row.created_by or
        command['policy_hash'] != policy.digest or command['source_namespace'] != policy.source_namespace): _fail()
    for key in ('channel', 'source_namespace', 'transport_id', 'raw_sha256', 'raw_bytes'):
        if command[key] != getattr(row, key): _fail()
    opaque(command['source_namespace']); opaque(command['archive_reference']); proof(command['archive_proof']); proof(command['raw_sha256'])
    if type(command['transport_id']) is not str or not re.fullmatch(r'[A-Za-z0-9._:@/-]{1,160}', command['transport_id']): _fail()
    if type(command['raw_bytes']) is not int or not 1 <= command['raw_bytes'] <= MAX_BYTES: _fail()
    if command['channel'] not in SOURCES | {'paste'}: _fail()
    if command['channel'] == 'paste':
        if command['manual'] is not None: _fail()
    else:
        _manual(command['manual'])
        raw = _manual_raw(command['manual'], command['channel'], command['archive_reference'], command['archive_proof'])
        if hashlib.sha256(raw).hexdigest() != row.raw_sha256 or len(raw) != row.raw_bytes: _fail()
        if day(command['manual']['occurred_on']) > applications._local_day(row.created_at): _fail()
    _historical_authority(policy, row.created_by, row.created_at, row.channel)
    _captures(_plain(row.captures), command, policy)
    _key(row.request_key)
    if row.request_hash != _hash(command) or row.snapshot_hash != _hash(_receipt_payload(row)): _fail()
    return row


def _manual_raw(value, channel, archive_reference, archive_proof):
    # Canonical structured manual observation; no free-form personal dossier.
    from app.knowledge.review import canonical
    return canonical({'observation': value, 'channel': channel, 'archive_reference': archive_reference,
                      'archive_proof': archive_proof}).encode('utf-8')


async def _receipt(session, case_id, receipt_id):
    row = await session.scalar(select(EntryPortalReceipt).where(EntryPortalReceipt.id == receipt_id, EntryPortalReceipt.case_id == case_id))
    if row is None: _fail('portal_receipt_unavailable')
    return _receipt_check(row)


def _receipt_view(row):
    return dict(id=row.id, case_id=row.case_id, channel=row.channel, source_namespace=row.source_namespace,
        transport_id=row.transport_id, raw_sha256=row.raw_sha256, raw_bytes=row.raw_bytes,
        captures=_plain(row.captures), archive_reference=row.command['archive_reference'],
        created_by=row.created_by, created_at=applications._utc(row.created_at), snapshot_hash=row.snapshot_hash)


async def receive(engine, *, actor, case_id, channel, source_namespace, transport_id, archive_reference,
                  archive_proof, request_key, expected_policy_hash, policy, text=None, manual=None):
    _authorize(actor); _id(case_id); _key(request_key)
    opaque(source_namespace); opaque(archive_reference); proof(archive_proof); proof(expected_policy_hash)
    if type(transport_id) is not str or not re.fullmatch(r'[A-Za-z0-9._:@/-]{1,160}', transport_id): _fail('invalid_portal_transport')
    if channel == 'paste':
        if type(text) is not str or manual is not None: _fail('invalid_portal_input')
        try: raw = text.encode('utf-8')
        except UnicodeError: _fail('invalid_portal_input')
    elif channel in SOURCES:
        if text is not None: _fail('invalid_portal_input')
        manual = _manual(deepcopy(manual)); raw = _manual_raw(manual, channel, archive_reference, archive_proof)
    else: _fail('invalid_portal_channel')
    if not 1 <= len(raw) <= MAX_BYTES: _fail('invalid_portal_input')
    digest = hashlib.sha256(raw).hexdigest()
    command = dict(action='receive', case_id=case_id, channel=channel, source_namespace=source_namespace,
        transport_id=transport_id, archive_reference=archive_reference, archive_proof=archive_proof,
        raw_sha256=digest, raw_bytes=len(raw), manual=manual, actor=actor.manager_id, policy_hash=expected_policy_hash)
    async def write(session):
        await applications._case(session, case_id, lock=True)
        old = await session.scalar(select(EntryPortalReceipt).where(EntryPortalReceipt.case_id == case_id, EntryPortalReceipt.request_key == request_key))
        if old:
            _receipt_check(old)
            if old.request_hash != _hash(command): raise EntryStorageConflict('request_key_reused')
            return _receipt_view(old)
        same = await session.scalar(select(EntryPortalReceipt).where(EntryPortalReceipt.source_namespace == source_namespace,
            EntryPortalReceipt.channel == channel, EntryPortalReceipt.transport_id == transport_id))
        if same:
            if same.case_id != case_id: raise EntryStorageConflict('portal_transport_conflict')
            _receipt_check(same)
            if same.request_hash != _hash(command): raise EntryStorageConflict('portal_transport_conflict')
            return _receipt_view(same)
        authorize(actor, policy, on=applications._today(), channel=channel)
        if expected_policy_hash != policy.digest or source_namespace != policy.source_namespace: raise EntryStorageConflict('portal_policy_changed')
        captures = parse(text, policy) if channel == 'paste' else _manual_captures(manual, digest, len(raw))
        if manual and day(manual['occurred_on']) > applications._today(): _fail('invalid_portal_date')
        row = EntryPortalReceipt(case_id=case_id, channel=channel, source_namespace=source_namespace, transport_id=transport_id,
            raw_sha256=digest, raw_bytes=len(raw), command=command, captures=captures, policy=policy.document(),
            request_key=request_key, request_hash=_hash(command), created_by=actor.manager_id, created_at=_now())
        row.snapshot_hash = _hash(_receipt_payload(row)); session.add(row); await session.flush()
        _receipt_check(row)
        return _receipt_view(row)
    return await applications._run(engine, write)


def _binding(application, events, head=None):
    head = head or events[-1]
    cycle = next((v for v in reversed(events) if v.revision <= head.revision and v.status == 'submitted'), None)
    if cycle is None or not head.reference: _fail('portal_application_not_submitted')
    return dict(application_id=application.id, applicant_id=application.applicant_id, procedure=application.procedure,
        application_hash=application.snapshot_hash, reference=head.reference, head_id=head.id, head_hash=head.snapshot_hash,
        revision=head.revision, cycle_id=cycle.id, cycle_hash=cycle.snapshot_hash)


async def _checked_binding(session, receipt, binding):
    _exact(binding, ('application_id', 'applicant_id', 'procedure', 'application_hash', 'reference',
                     'head_id', 'head_hash', 'revision', 'cycle_id', 'cycle_hash'))
    for name in ('application_id', 'applicant_id', 'head_id', 'revision', 'cycle_id'): _id(binding[name])
    application = await applications._application(session, receipt.case_id, binding['application_id'])
    events = await applications._events(session, application)
    head = next((v for v in events if v.id == binding['head_id']), None)
    if head is None or binding != _binding(application, events, head) or receipt.captures['references'] != [binding['reference']]: _fail()
    return application, events


async def _candidate(session, receipt):
    captures = receipt.captures
    if captures['issues'] or len(captures['references']) != 1: return None
    claim = await session.scalar(select(EntryApplicationReference).where(EntryApplicationReference.reference == captures['references'][0]))
    if claim is None or claim.case_id != receipt.case_id: return None
    application = await applications._application(session, receipt.case_id, claim.application_id)
    events = await applications._events(session, application)
    return _binding(application, events)


def _operation(value):
    if type(value) is not dict or type(value.get('action')) is not str: _fail('invalid_portal_operation')
    action = value['action']
    fields = {'correlate': ('binding',), 'confirm': ('on', 'source', 'verification_reference', 'verification_proof', 'cycle_verified'), 'dismiss': ('reason',)}
    if action not in fields or value.keys() != {'action', 'confirmed', *fields[action]}: _fail('invalid_portal_operation')
    if value['confirmed'] is not True: _fail('operator_confirmation_required')
    if action == 'correlate':
        if type(value['binding']) is not dict: _fail('invalid_portal_operation')
    elif action == 'dismiss':
        if type(value['reason']) is not str or value['reason'] not in ('duplicate', 'unrelated', 'unclear', 'superseded'): _fail('invalid_portal_operation')
    else:
        day(value['on']); opaque(value['verification_reference']); proof(value['verification_proof'])
        if type(value['source']) is not str or value['source'] not in SOURCES or value['cycle_verified'] is not True: _fail('portal_independent_verification_required')
    return value


def _confirmation(receipt, state, operation, events, cutoff):
    if state['disposition'] != 'correlated' or not state['binding'] or receipt.captures['issues']: _fail('portal_correlation_required')
    binding = state['binding']
    head = next(v for v in events if v.id == binding['head_id'])
    cycle = next(v for v in events if v.id == binding['cycle_id'])
    actual = day(operation['on'])
    if not cycle.occurred_on <= actual <= cutoff or actual < head.occurred_on: _fail('invalid_portal_date')
    if receipt.captures['dates'] and receipt.captures['dates'] != [operation['on']]: _fail('portal_observed_date_conflict')
    if operation['verification_proof'] == receipt.raw_sha256: _fail('portal_independent_verification_required')
    kind = receipt.captures['kinds'][0]
    if kind in APPLY and head.status != 'submitted': _fail('portal_application_not_submitted')
    return kind


def _content_hash(receipt):
    if receipt.channel == 'paste':
        return _hash({'namespace': receipt.source_namespace, 'raw_sha256': receipt.raw_sha256})
    # Renaming an archive location or manual transport ID cannot create fresh
    # source evidence. A distinct verified capture needs a different proof.
    return _hash({'namespace': receipt.source_namespace, 'manual': _plain(receipt.command['manual']),
                  'archive_proof': receipt.command['archive_proof']})


def _event_key(receipt, request_key): return _hash({'portal_receipt_id': receipt.id, 'portal_action_key': request_key})


async def _history(session, receipt):
    rows = (await session.scalars(select(EntryPortalAction).where(EntryPortalAction.receipt_id == receipt.id)
                                  .order_by(EntryPortalAction.revision).limit(MAX_ACTIONS + 1))).all()
    if len(rows) > MAX_ACTIONS: _fail()
    state = dict(disposition='pending', binding=None, applied_event=None)
    previous = None; size = 0
    for i, row in enumerate(rows, 1):
        command = _plain(row.command); operation = _operation(command.get('operation'))
        _exact(command, ('receipt_id', 'case_id', 'expected_revision', 'actor', 'policy_hash', 'operation'))
        if (row.case_id != receipt.case_id or row.revision != i or row.previous_id != (previous.id if previous else None) or
            row.action != operation['action'] or command['receipt_id'] != receipt.id or command['case_id'] != receipt.case_id or
            type(command['expected_revision']) is not int or command['expected_revision'] != i - 1 or command['actor'] != row.created_by or
            row.request_hash != _hash(command) or row.snapshot_hash != _hash(_action_payload(row)) or
            previous and row.id <= previous.id or applications._utc(row.created_at) < applications._utc(receipt.created_at)): _fail()
        _key(row.request_key)
        if state['disposition'] in ('applied', 'checked', 'dismissed'): _fail()
        if operation['action'] == 'dismiss' and row.policy is None:
            if command['policy_hash'] is not None or row.created_by not in policy_from_document(_plain(receipt.policy)).operators: _fail()
        else:
            policy = policy_from_document(_plain(row.policy))
            _historical_authority(policy, row.created_by, row.created_at)
            if policy.source_namespace != receipt.source_namespace or command['policy_hash'] != policy.digest: _fail()
            if operation['action'] == 'confirm' and operation['source'] not in policy.verification_sources: _fail()
        expected = deepcopy(state)
        if operation['action'] == 'correlate':
            if receipt.captures['issues'] or i == MAX_ACTIONS: _fail()
            await _checked_binding(session, receipt, operation['binding'])
            expected = dict(disposition='correlated', binding=operation['binding'], applied_event=None)
        elif operation['action'] == 'dismiss': expected['disposition'] = 'dismissed'
        else:
            if state['binding'] is None: _fail()
            application, events = await _checked_binding(session, receipt, state['binding'])
            kind = _confirmation(receipt, state, operation, events, applications._local_day(row.created_at))
            if kind in APPLY:
                applied = next((v for v in events if v.id == row.applied_event_id), None)
                if (applied is None or applied.previous_id != state['binding']['head_id'] or applied.status != APPLY[kind] or
                    applied.occurred_on.isoformat() != operation['on'] or applied.source != operation['source'] or
                    applied.created_by != row.created_by or applied.request_key != _event_key(receipt, row.request_key) or
                    row.applied_content_hash != _content_hash(receipt)): _fail()
                expected['applied_event'] = {'id': applied.id, 'hash': applied.snapshot_hash}
                expected['disposition'] = 'applied'
            else: expected['disposition'] = 'checked'
        if expected != _plain(row.snapshot): _fail()
        binding = expected['binding'] or {}
        for name in ('application_id', 'applicant_id', 'procedure', 'head_id', 'cycle_id'):
            if getattr(row, name) != binding.get(name): _fail()
        if expected['disposition'] != 'applied' and (row.applied_event_id is not None or row.applied_content_hash is not None): _fail()
        state = expected; previous = row
        size += len(str(_action_payload(row)).encode('utf-8'))
    if size > MAX_JOURNAL_BYTES: _fail()
    return rows, state, size


def _view(receipt, rows, state):
    return {'receipt': _receipt_view(receipt), 'revision': len(rows), 'state': deepcopy(state),
        'history': [dict(id=r.id, revision=r.revision, action=r.action, created_by=r.created_by,
                        created_at=applications._utc(r.created_at), snapshot_hash=r.snapshot_hash,
                        operation=_plain(r.command)['operation'], snapshot=_plain(r.snapshot)) for r in rows]}


async def read_receipt(engine, *, actor, case_id, receipt_id, policy=None):
    _authorize(actor); _id(case_id); _id(receipt_id)
    async def read(session):
        await applications._case(session, case_id)
        receipt = await _receipt(session, case_id, receipt_id)
        rows, state, _ = await _history(session, receipt)
        value = _view(receipt, rows, state)
        candidate = await _candidate(session, receipt)
        enabled = False
        try:
            authorize(actor, policy, on=applications._today())
            enabled = policy.source_namespace == receipt.source_namespace
        except (EntryStorageInvalid, PermissionDenied): pass
        confirmable = enabled and state['disposition'] == 'correlated' and state['binding'] == candidate and len(rows) < MAX_ACTIONS - 1
        if confirmable and receipt.captures['kinds'][0] in APPLY:
            _, current_events = await _checked_binding(session, receipt, candidate)
            confirmable = current_events[-1].status == 'submitted'
        value.update(candidate=candidate, policy_enabled=enabled, policy_hash=policy.digest if enabled else None,
            can_dismiss=state['disposition'] in ('pending', 'correlated') and (enabled or actor.manager_id in policy_from_document(_plain(receipt.policy)).operators),
            can_confirm=confirmable,
            can_correlate=enabled and candidate is not None and state['disposition'] in ('pending', 'correlated') and len(rows) < MAX_ACTIONS - 1)
        return value
    return await applications._run(engine, read)


async def list_receipts(engine, *, actor, case_id, before=None):
    _authorize(actor); _id(case_id)
    if before is not None: _id(before)
    async def read(session):
        await applications._case(session, case_id)
        query = select(EntryPortalReceipt).where(EntryPortalReceipt.case_id == case_id)
        if before is not None: query = query.where(EntryPortalReceipt.id < before)
        rows = (await session.scalars(query.order_by(EntryPortalReceipt.id.desc()).limit(21))).all()
        return dict(receipts=[_receipt_view(_receipt_check(v)) for v in rows[:20]], next_before=rows[19].id if len(rows) > 20 else None)
    return await applications._run(engine, read)


async def record_action(engine, *, actor, case_id, receipt_id, expected_revision, request_key,
                        operation, policy=None, expected_policy_hash=None):
    _authorize(actor); _id(case_id); _id(receipt_id); _key(request_key)
    if type(expected_revision) is not int or not 0 <= expected_revision < MAX_ACTIONS: _fail('invalid_portal_revision')
    operation = _operation(deepcopy(operation))
    if expected_policy_hash is not None: proof(expected_policy_hash)
    command = dict(receipt_id=receipt_id, case_id=case_id, expected_revision=expected_revision,
        actor=actor.manager_id, policy_hash=expected_policy_hash, operation=operation)
    async def write(session):
        await applications._case(session, case_id, lock=True)
        receipt = await _receipt(session, case_id, receipt_id)
        rows, state, size = await _history(session, receipt)
        old = next((v for v in rows if v.request_key == request_key), None)
        if old:
            if old.request_hash != _hash(command): raise EntryStorageConflict('request_key_reused')
            return dict(id=old.id, revision=old.revision, snapshot_hash=old.snapshot_hash, state=_plain(old.snapshot))
        if expected_revision != len(rows): raise EntryStorageConflict('portal_revision_changed')
        if state['disposition'] not in ('pending', 'correlated'): _fail('portal_receipt_finished')
        action = operation['action']
        saved_policy = None
        if action == 'dismiss' and expected_policy_hash is None:
            if actor.manager_id not in policy_from_document(_plain(receipt.policy)).operators: raise PermissionDenied('portal disposition operator unavailable')
        else:
            authorize(actor, policy, on=applications._today())
            if policy.digest != expected_policy_hash or policy.source_namespace != receipt.source_namespace: raise EntryStorageConflict('portal_policy_changed')
            saved_policy = policy.document()
            if action == 'confirm' and operation['source'] not in policy.verification_sources: raise PermissionDenied('portal verification source unavailable')
        if action != 'dismiss' and len(rows) >= MAX_ACTIONS - 1: _fail('portal_action_limit')
        target = deepcopy(state); applied_event_id = None; applied_content_hash = None
        if action == 'correlate':
            candidate = await _candidate(session, receipt)
            if candidate is None or operation['binding'] != candidate: raise EntryStorageConflict('portal_correlation_changed')
            target = dict(disposition='correlated', binding=candidate, applied_event=None)
        elif action == 'dismiss': target['disposition'] = 'dismissed'
        else:
            if state['binding'] is None: _fail('portal_correlation_required')
            application = await applications._application(session, case_id, state['binding']['application_id'], lock=True)
            events = await applications._events(session, application)
            if state['binding'] != _binding(application, events): raise EntryStorageConflict('portal_application_changed')
            kind = _confirmation(receipt, state, operation, events, applications._today())
            if kind in APPLY:
                applied_content_hash = _content_hash(receipt)
                if await session.scalar(select(EntryPortalAction.id).where(EntryPortalAction.applied_content_hash == applied_content_hash)):
                    raise EntryStorageConflict('portal_content_already_applied')
                event = await applications._record_application_event_in_session(session, actor=actor, case_id=case_id,
                    application_id=application.id, expected_revision=events[-1].revision,
                    request_key=_event_key(receipt, request_key), status=APPLY[kind],
                    occurred_on=operation['on'], source=operation['source'], reference=events[-1].reference, confirmed=True)
                applied = (await applications._events(session, application))[-1]
                if event['id'] != applied.id: _fail()
                applied_event_id = applied.id
                target.update(disposition='applied', applied_event={'id': applied.id, 'hash': applied.snapshot_hash})
            else: target['disposition'] = 'checked'
        binding = target['binding'] or {}
        row = EntryPortalAction(receipt_id=receipt.id, case_id=case_id, revision=len(rows) + 1,
            previous_id=rows[-1].id if rows else None, action=action, **{k: binding.get(k) for k in ('application_id', 'applicant_id', 'procedure', 'head_id', 'cycle_id')},
            applied_event_id=applied_event_id, applied_content_hash=applied_content_hash,
            request_key=request_key, request_hash=_hash(command), command=command, snapshot=target,
            policy=saved_policy, created_by=actor.manager_id, created_at=_now())
        row.snapshot_hash = _hash(_action_payload(row))
        # Reserve enough bytes for a final disposition; reject before any commit.
        if size + len(str(_action_payload(row)).encode('utf-8')) > MAX_JOURNAL_BYTES - (8192 if action != 'dismiss' else 0): _fail('portal_action_limit')
        session.add(row); await session.flush()
        await _history(session, receipt)
        return dict(id=row.id, revision=row.revision, snapshot_hash=row.snapshot_hash, state=target)
    return await applications._run(engine, write)
