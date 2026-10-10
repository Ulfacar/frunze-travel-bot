"""Immutable procedural journal; recording a stage performs no external action."""
from copy import deepcopy
import re

from sqlalchemy import select

from app.domain import entry_applications as applications
from app.domain.entry_package_policy import policy_from_document as package_policy_from_document
from app.domain.entry_process_evidence import Evidence, Sources, SOURCE_COLUMNS
from app.domain.entry_process_policy import ProcessPolicy, ROLES, authorize, edge_id, policy_from_document
from app.domain.entry_process_rules import (MAX_BYTES, MAX_EVENTS, MAX_PINS, apply, catalog, edge_for,
    focus, invalid, normalize, CORRECTIVE_TARGETS)
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _authorize, _hash, _id, _key
from app.domain.knowledge_review import _plain
from app.domain.models import EntryApplication, EntryProcessEvent, EntryProcessPin, _now
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge.process_preview import CATALOG_SHA256
from app.knowledge.review import canonical


def _command(case_id, application_id, revision, operation, actor, expected_policy_hash=None):
    return dict(case_id=case_id, application_id=application_id, expected_revision=revision,
        operation=operation, actor=actor, expected_policy_hash=expected_policy_hash)


def _payload(row):
    fields = ('application_id', 'case_id', 'applicant_id', 'root_procedure', 'active_application_id',
        'active_procedure', 'revision', 'action', 'previous_id', 'request_key', 'request_hash',
        'command', 'snapshot', 'policy', 'evidence', 'created_by')
    return {**{k:_plain(getattr(row, k)) for k in fields}, 'created_at':applications._utc(row.created_at)}


def _pins(evidence):
    result = []
    for fact, packet in sorted(evidence['facts'].items()):
        for source in packet['pins']:
            result.append(dict(fact=fact, **source))
    if len(result) > MAX_PINS: invalid('process_evidence_limit')
    return result


def _pin_values(row):
    fields = ('fact', 'kind', 'source_hash', 'application_id', 'procedure', *SOURCE_COLUMNS.values())
    return {key:getattr(row, key) for key in fields if getattr(row, key) is not None}


def _policy(row, cache=None):
    if row.policy is None: return None
    document = _plain(row.policy)
    digest = _hash(document)
    if cache is not None and digest in cache: return cache[digest]
    parsed = policy_from_document(document)
    if cache is not None: cache[digest] = parsed
    return parsed


def _authorize_operation(actor, policy, operation, state, rows, day):
    if operation['action'] in ('initialize', 'link', 'transition') and operation['data']['on'] != day.isoformat():
        invalid('process_recording_date_required')
    if operation['action'] in ('stop', 'withdraw'):
        previous = next((_policy(r) for r in reversed(rows) if r.policy is not None), None)
        _authorize(actor)
        if previous is None or actor.manager_id not in previous.operators:
            raise PermissionDenied('process operator is not authorized by policy')
        return None
    authorize(actor, policy, day=day)
    action, data = operation['action'], operation['data']
    if action == 'initialize':
        if data['catalog_digest'] != CATALOG_SHA256: invalid('process_catalog_changed')
    elif action == 'transition':
        if data['edge_id'] not in policy.allowed_edges: invalid('process_edge_not_authorized')
    elif action == 'attest':
        if data['source'] not in dict(policy.manual_sources).get(data['fact'], ()):
            invalid('process_attestation_not_authorized')
    return policy


async def _evidence(sources, state, rows, operation, policy, package_policy, at, *, historical=False, observed=None):
    action, data = operation['action'], operation['data']
    if action in ('stop', 'withdraw'): package_policy = None
    context = Evidence(sources, state, rows, policy, package_policy, at=at, historical=historical, observed=observed)
    facts = {}
    if action == 'transition':
        edge = edge_for(state, data['edge_id'])
        role, _ = focus(state, edge)
        app = await context.app(role)
        if edge['to'] not in CORRECTIVE_TARGETS and not await context.usable(app):
            invalid('process_application_terminal')
        facts = await context.transition(edge)
        facts[role + '.identity'] = await context.resolve(role, 'identity')
    elif action in ('initialize', 'link'):
        role = state['active_role'] if action == 'initialize' else data['role']
        # The new link is part of this event, so validate it in a temporary scope.
        if action == 'link':
            context.state = deepcopy(state)
            context.state['links'][role] = data['application_id']
        app = await context.app(role)
        if not await context.usable(app): invalid('process_application_terminal')
        facts[role + '.identity'] = await context.resolve(role, 'identity')
    elif action == 'attest':
        role = data['role']; app = await context.app(role)
        if app is None: invalid('process_dependency_missing')
        if not await context.usable(app): invalid('process_application_terminal')
        facts[role + '.identity'] = await context.resolve(role, 'identity')
        if data['profile_id'] is not None:
            from app.domain.entry_process_evidence import pin, packet
            profiles = context.prefix(await sources.profile_history(), 'profiles')
            if not profiles or profiles[-1].id != data['profile_id']: invalid('process_profile_changed')
            if data['on'] < applications._local_day(profiles[-1].created_at).isoformat():
                invalid('process_profile_review_predates_version')
            facts[role + '.profile_review_source'] = packet(True, 'current_individual_profile', [pin('profile', profiles[-1], app)])
    return dict(facts=facts, package_policy=package_policy.document() if package_policy else None, observed=context.observed)


async def _history(sources):
    root = sources.root
    rows = list((await sources.session.scalars(select(EntryProcessEvent).where(
        EntryProcessEvent.application_id == root.id).order_by(EntryProcessEvent.revision).limit(MAX_EVENTS+1))).all())
    if len(rows) > MAX_EVENTS: invalid('process_history_limit')
    state = None; previous = None; size = 0; policies = {}
    stored_pins = list((await sources.session.scalars(select(EntryProcessPin).where(
        EntryProcessPin.root_id == root.id).order_by(EntryProcessPin.event_id, EntryProcessPin.ordinal)
        .limit(MAX_EVENTS*MAX_PINS+1))).all())
    if len(stored_pins) > MAX_EVENTS*MAX_PINS: invalid('process_evidence_limit')
    by_event = {}
    for p in stored_pins: by_event.setdefault(p.event_id, []).append(p)
    if set(by_event) - {r.id for r in rows}: invalid('process_integrity_failed')
    for revision, row in enumerate(rows, 1):
        operation = normalize(_plain(row.command).get('operation'), cutoff=applications._local_day(row.created_at))
        expected_policy_hash = row.command.get('expected_policy_hash')
        request = _command(root.case_id, root.id, revision-1, operation, row.created_by, expected_policy_hash)
        _key(row.request_key)
        if (row.case_id != root.case_id or row.applicant_id != root.applicant_id or row.root_procedure != root.procedure or
            row.revision != revision or row.action != operation['action'] or row.command != request or
            row.request_hash != _hash(request) or row.snapshot_hash != _hash(_payload(row)) or
            row.previous_id != (previous.id if previous else None) or
            previous and (row.id <= previous.id or applications._utc(row.created_at) < applications._utc(previous.created_at))):
            invalid('process_integrity_failed')
        policy = _policy(row, policies)
        if expected_policy_hash is not None and (policy is None or expected_policy_hash != policy.digest):
            invalid('process_policy_changed')
        _authorize_operation(Actor(row.created_by, True), policy, operation, state, rows[:revision-1], applications._local_day(row.created_at))
        if operation['action'] in ('stop', 'withdraw') and policy is not None: invalid('process_integrity_failed')
        if operation['action'] == 'initialize':
            if root.procedure not in policy.initial_procedures: invalid('process_root_not_authorized')
            initial = apply(None, operation, root=root, revision=revision)
        else: initial = state
        stored_evidence = _plain(row.evidence)
        if type(stored_evidence) is not dict or stored_evidence.keys() != {'facts', 'package_policy', 'observed'}:
            invalid('process_integrity_failed')
        package_policy = package_policy_from_document(stored_evidence['package_policy']) if stored_evidence['package_policy'] is not None else None
        evidence = await _evidence(sources, initial, rows[:revision-1], operation, policy, package_policy, row.created_at,
            historical=True, observed=stored_evidence['observed'])
        if evidence != stored_evidence: invalid('process_evidence_changed')
        if operation['action'] == 'transition' and operation['data']['evidence_digest'] != _hash(evidence):
            invalid('process_evidence_changed')
        state = apply(state, operation, root=root, revision=revision, resolved=evidence['facts'])
        if (state != _plain(row.snapshot) or row.active_application_id != state['active_application_id'] or
            row.active_procedure != ROLES[state['active_role']]): invalid('process_integrity_failed')
        expected_pins = _pins(evidence); actual_pins = by_event.get(row.id, [])
        if len(expected_pins) != len(actual_pins): invalid('process_pin_integrity_failed')
        for ordinal, (expected, actual) in enumerate(zip(expected_pins, actual_pins), 1):
            if (actual.ordinal != ordinal or actual.case_id != root.case_id or actual.applicant_id != root.applicant_id or
                _pin_values(actual) != expected): invalid('process_pin_integrity_failed')
        size += len(canonical(_payload(row)).encode())
        if size > MAX_BYTES: invalid('process_history_limit')
        previous = row
    return rows, state, size


async def _readiness(sources, state, rows, actor, policy, package_policy, at):
    result = dict(ready=False, reason='process_not_initialized', retained={}, transitions=[])
    if state is None: return result
    if state['stopped']: return {**result, 'reason':'process_stopped'}
    context = Evidence(sources, state, rows, policy, package_policy, at=at)
    try:
        authorize(actor, policy, day=applications._local_day(at))
    except (PermissionDenied, EntryStorageInvalid) as exc:
        return {**result, 'reason':str(exc)}
    for key, expected in state['retained'].items():
        role, fact = key.split('.', 1)
        value = await context.resolve(role, fact)
        result['retained'][key] = {**value, 'expected':expected,
            'satisfied':type(value['value']) is type(expected) and value['value'] == expected}
    changed = any(not p['satisfied'] for p in result['retained'].values())
    last_policy = next((_policy(r) for r in reversed(rows) if r.policy is not None), None)
    policy_changed = last_policy is None or last_policy.digest != policy.digest
    active = await context.app(state['active_role'])
    usable = active is not None and await context.usable(active)
    result.update(ready=not changed and not policy_changed and usable,
        reason='process_application_terminal' if not usable else 'process_policy_changed' if policy_changed else
            'process_prerequisites_changed' if changed else 'current_evidence')
    for edge in catalog()['edges']:
        if edge['from'] != state['stage']: continue
        digest = edge_id(edge)
        item = dict(edge=deepcopy(edge), edge_id=digest, ready=False, reason='process_edge_not_authorized', evidence_digest=None, facts={})
        if digest in policy.allowed_edges:
            operation = dict(action='transition', confirmed=True,
                data=dict(edge_id=digest, on=applications._local_day(at).isoformat(), evidence_digest='0'*64))
            try:
                evidence = await _evidence(sources, state, rows, operation, policy, package_policy, at)
                _pins(evidence)
                item.update(facts=evidence['facts'], evidence_digest=_hash(evidence))
                apply(state, operation, root=sources.root, revision=len(rows)+1, resolved=evidence['facts'])
                item.update(ready=True, reason='current_evidence')
            except EntryStorageInvalid as exc: item['reason'] = str(exc)
        result['transitions'].append(item)
    return result


def _view(row):
    return dict(id=row.id, revision=row.revision, snapshot_hash=row.snapshot_hash, snapshot=_plain(row.snapshot),
        operation=_plain(row.command)['operation'], evidence=_plain(row.evidence),
        created_by=row.created_by, created_at=applications._utc(row.created_at))


async def record_process_operation(engine, *, actor, case_id, application_id, expected_revision, request_key,
                                   operation, policy=None, package_policy=None, expected_policy_hash=None):
    _authorize(actor); _id(case_id); _id(application_id); _key(request_key)
    if type(expected_revision) is not int or not 0 <= expected_revision < MAX_EVENTS: invalid('invalid_process_revision')
    operation = normalize(operation, cutoff=applications._today())
    if expected_policy_hash is not None and (type(expected_policy_hash) is not str or not re.fullmatch('[a-f0-9]{64}', expected_policy_hash)):
        invalid('invalid_process_policy')
    request = _command(case_id, application_id, expected_revision, operation, actor.manager_id, expected_policy_hash)
    async def write(session):
        from app.domain.entry_quarantine import lock_process_observation
        await lock_process_observation(session)
        case = await applications._case(session, case_id, lock=True)
        root = await applications._application(session, case_id, application_id, lock=True)
        sources = Sources(session, case, root)
        # The case lock serializes all procedure/package/issued writers. Discover
        # previous links before locking their applications in deterministic order.
        last = await session.scalar(select(EntryProcessEvent).where(EntryProcessEvent.application_id == root.id)
            .order_by(EntryProcessEvent.revision.desc()).limit(1))
        ids = [root.id]
        if last: ids.extend(_plain(last.snapshot).get('links', {}).values())
        if operation['action'] == 'link': ids.append(operation['data']['application_id'])
        await sources.lock_apps(ids)
        rows, state, size = await _history(sources)
        old = next((r for r in rows if r.request_key == request_key), None)
        at = _now(); day = applications._local_day(at)
        if old:
            if old.request_hash != _hash(request): raise EntryStorageConflict('request_key_reused')
            return {**_view(old), 'current_revision':len(rows),
                'readiness':await _readiness(sources, state, rows, actor, policy, package_policy, at)}
        if len(rows) != expected_revision: raise EntryStorageConflict('process_revision_changed')
        if rows and applications._utc(at) < applications._utc(rows[-1].created_at): invalid('process_clock_reversed')
        normalize(operation, cutoff=day)
        used_policy = _authorize_operation(actor, policy, operation, state, rows, day)
        if expected_policy_hash is not None and (used_policy is None or expected_policy_hash != used_policy.digest):
            raise EntryStorageConflict('process_policy_changed')
        if operation['action'] == 'initialize':
            if root.procedure not in policy.initial_procedures: invalid('process_root_not_authorized')
            initial = apply(None, operation, root=root, revision=1)
        else: initial = state
        if initial is None: invalid('process_not_initialized')
        # Stop remains available at the final reserved slot and after expiry.
        stop = operation['action'] == 'stop'
        if len(rows) >= MAX_EVENTS - (0 if stop else 1): invalid('process_history_limit')
        evidence = await _evidence(sources, initial, rows, operation, used_policy, package_policy, at)
        if operation['action'] == 'transition' and operation['data']['evidence_digest'] != _hash(evidence):
            raise EntryStorageConflict('process_evidence_changed')
        next_state = apply(state, operation, root=root, revision=len(rows)+1, resolved=evidence['facts'])
        row = EntryProcessEvent(application_id=root.id, case_id=case_id, applicant_id=root.applicant_id,
            root_procedure=root.procedure, active_application_id=next_state['active_application_id'],
            active_procedure=ROLES[next_state['active_role']], revision=len(rows)+1, action=operation['action'],
            previous_id=rows[-1].id if rows else None, request_key=request_key, request_hash=_hash(request),
            command=request, snapshot=next_state, policy=used_policy.document() if used_policy else None,
            evidence=evidence, created_by=actor.manager_id, created_at=at)
        row.snapshot_hash = _hash(_payload(row))
        reserve = 0 if stop else 2*len(canonical(next_state).encode()) + 8192
        if size + len(canonical(_payload(row)).encode()) > MAX_BYTES - reserve: invalid('process_history_limit')
        pins = _pins(evidence)
        session.add(row); await session.flush()
        for ordinal, data in enumerate(pins, 1):
            session.add(EntryProcessPin(event_id=row.id, ordinal=ordinal, root_id=root.id,
                case_id=case_id, applicant_id=root.applicant_id, **data))
        await session.flush()
        rows.append(row)
        return {**_view(row), 'current_revision':len(rows),
            'readiness':await _readiness(sources, next_state, rows, actor, policy, package_policy, at)}
    return await applications._run(engine, write)


async def read_process_history(engine, *, actor, case_id, application_id, revision=None, policy=None, package_policy=None):
    _authorize(actor); _id(case_id); _id(application_id)
    if revision is not None and (type(revision) is not int or not 1 <= revision <= MAX_EVENTS): invalid('invalid_process_revision')
    async def read(session):
        case = await applications._case(session, case_id, lock=True)
        root = await applications._application(session, case_id, application_id)
        sources = Sources(session, case, root)
        rows, state, _ = await _history(sources)
        selected = next((r for r in rows if r.revision == revision), None) if revision else rows[-1] if rows else None
        if revision and selected is None: invalid('process_revision_unavailable')
        candidates = list((await session.scalars(select(EntryApplication).where(
            EntryApplication.case_id == case_id, EntryApplication.applicant_id == root.applicant_id)
            .order_by(EntryApplication.id).limit(101))).all())
        profile_rows = await sources.profile_history()
        return dict(application=applications._application_view(root), current_revision=len(rows),
            profile_id=profile_rows[-1].id if profile_rows else None,
            link_candidates=[applications._application_view(r) for r in candidates[:100]],
            link_candidates_truncated=len(candidates) > 100,
            selected=_view(selected) if selected else None,
            readiness=await _readiness(sources, state, rows, actor, policy, package_policy, _now()),
            history=[dict(revision=r.revision, action=r.action, stage=r.snapshot['stage'],
                active_application_id=r.active_application_id, created_by=r.created_by,
                created_at=applications._utc(r.created_at)) for r in reversed(rows)])
    return await applications._run(engine, read)
