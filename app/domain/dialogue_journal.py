"""Bounded immutable evidence journal. Caller owns route/capacity/case locks.

This module validates records and ordering, not current send/collection admission.
The connected composer must recheck live authority and current-stop evidence.
"""
from datetime import datetime
from sqlalchemy import select, cast, Text, func

from app.domain import entry_applications as applications, entry_interviews as interviews
from app.domain import entry_channel_policy as channels, entry_channel_stops as stops
from app.domain.dialogue_policy import DialoguePolicy
from app.domain.dialogue_session_policy import SessionPolicy, VERSION
from app.domain.current_stay_policy import CurrentStayFact
from app.domain.entry_storage import EntryStorageInvalid, _hash, _id, _key, _plain
from app.domain.models import EntryDialogueSession, EntryDialogueEvent, EntryInterview
from app.knowledge import dialogue_questions as questions, interview_catalog as catalog
from app.knowledge.review import canonical
from app.knowledge import dialogue_interrupts

MAX_SESSIONS = 128
MAX_HEADER_BYTES = 262144
MAX_EVENTS = 1024
MAX_EVENT_BYTES = 65536
MAX_JOURNAL_BYTES = 16*1048576


def fail(code='dialogue_journal_integrity_failed'):
    raise EntryStorageInvalid(code)


def exact(value, keys):
    if type(value) is not dict or set(value) != set(keys): fail()


def head(event):
    return dict(id=event.id, revision=event.revision, hash=event.snapshot_hash)


def checked_head(value):
    exact(value, ('id', 'revision', 'hash'))
    _id(value['id']); _id(value['revision']); channels.proof(value['hash'])
    return value


def header_payload(row):
    return dict(format=VERSION, transport_key=row.transport_key, case_id=row.case_id,
        applicant_id=row.applicant_id, interview_id=row.interview_id, document=_plain(row.document),
        created_at=applications._utc(row.created_at))


def event_payload(row):
    return dict(format='kg-dialogue-event/1', session_id=row.session_id, revision=row.revision,
        previous_id=row.previous_id, request_key=row.request_key, kind=row.kind,
        document=_plain(row.document), created_at=applications._utc(row.created_at))


def validate_header(row):
    doc = _plain(row.document)
    exact(doc, ('delegation', 'original_dialogue_policy', 'policy', 'channel_policy', 'channel_identity', 'fact', 'baseline', 'baseline_check'))
    exact(doc['delegation'], ('policy', 'deployed_policy_hash'))
    delegation = DialoguePolicy(doc['delegation']['policy'])
    policy = SessionPolicy(doc['policy']); fact = CurrentStayFact(doc['fact'])
    assignments = delegation.document['assignments']
    if len(assignments) != 1: fail()
    assignment = assignments[0]; route = assignment['route']; baseline = checked_head(doc['baseline'])
    original_policy = DialoguePolicy(doc['original_dialogue_policy'])
    expected_delegation = original_policy.document
    expected_delegation['assignments'] = [assignment]
    if (original_policy.digest != doc['delegation']['deployed_policy_hash'] or
            original_policy.assignment(route) != assignment or expected_delegation != delegation.document): fail()
    channel_policy = channels.policy_from_document(doc['channel_policy'])
    identity = doc['channel_identity']; exact(identity, ('id', 'contact_id', 'channel', 'bot_id', 'channel_key'))
    _id(identity['id']); _id(identity['contact_id'])
    if (identity['id'] != assignment['dialog_id'] or identity['channel'] != 'whatsapp' or
        type(identity['bot_id']) is not str or not 1 <= len(identity['bot_id']) <= 64 or
        channels.recipient(identity['channel_key']) != route['recipient'] or
        channel_policy.digest != delegation.document['channel_policy_hash'] or
        channels.route_scope(route) not in channel_policy.document()['scopes']): fail()
    proof = doc['baseline_check']
    exact(proof, ('evidence_hash', 'profile_hash', 'history_hash', 'source_hash', 'fact_hash', 'interview_head_hash', 'result'))
    for key, value in proof.items():
        if key == 'result': continue
        if value is not None: channels.proof(value)
        elif key != 'history_hash': fail()
    if (row.transport_key != _hash(route) or row.snapshot_hash != _hash(header_payload(row)) or
        len(canonical(header_payload(row)).encode()) > MAX_HEADER_BYTES or
        [row.case_id, row.applicant_id, row.interview_id] != [assignment[k] for k in ('case_id', 'applicant_id', 'interview_id')] or
        fact.document['interview'] != dict(id=row.interview_id, header_hash=assignment['header_hash'], head_hash=baseline['hash']) or
        fact.document['case_id'] != row.case_id or fact.document['applicant_id'] != row.applicant_id or
        fact.document['actor'] != assignment['actor'] or fact.digest != proof['fact_hash'] or
        fact.document['profile_hash'] != proof['profile_hash'] or baseline['hash'] != proof['interview_head_hash'] or
        (fact.document['history'] or {}).get('snapshot_hash') != proof['history_hash'] or
        policy.document['dialogue_policy_hash'] != doc['delegation']['deployed_policy_hash'] or
        fact.document['policy_hash'] != policy.document['current_stay_policy_hash']): fail()
    channels.proof(doc['delegation']['deployed_policy_hash'])
    on = applications._local_day(row.created_at).isoformat()
    for auth in (delegation.document, policy.document, fact.document, channel_policy.document()):
        if not auth['valid_from'] <= on <= auth['review_due_on']: fail()
    if fact.document['as_of'] != on: fail()
    checked_current(proof['result'], row, baseline, at=row.created_at, require_clear=False)
    if (proof['evidence_hash'] != proof['result']['evidence_hash'] or
            proof['source_hash'] != proof['result']['source']['source_hash']): fail()
    return doc, assignment


def checked_current(value, header, observed, *, at, require_clear=True, expected_tail=None):
    """Retain and validate a bounded evidence packet, not a freestanding hash."""
    if type(value) is not dict: fail()
    copied = dict(value); fingerprint = copied.pop('evidence_hash', None)
    doc = _plain(header.document)
    try:
        checked_at = datetime.fromisoformat(value['checked_at'])
        if (fingerprint != _hash(copied) or value['scope'] != 'current_stay_stops_only' or
            applications._utc(checked_at) != applications._utc(at) or
            value['as_of'] != applications._local_day(checked_at).isoformat() or
            value['format'] not in ('kg-current-stay-checks/1', 'kg-dialogue-current-stay/1') or
            value['case_id'] != header.case_id or value['applicant_id'] != header.applicant_id or
            value['fact']['hash'] != _hash(doc['fact']) or value['profile']['snapshot_hash'] != doc['fact']['profile_hash'] or
            value['history']['snapshot_hash'] != (doc['fact']['history'] or {}).get('snapshot_hash') or
            value['authority']['hash'] != doc['fact']['policy_hash'] or
            value['interview'] != dict(id=header.interview_id,
                header_hash=doc['delegation']['policy']['assignments'][0]['header_hash'], head_hash=observed['hash']) or
            value['permission_to_remain'] is not None or value['entry_eligibility_evaluated'] is not False or
            value['may_quote'] is not False or value['delivery'] != 'not_sent'):
            fail()
        if require_clear and (value['requires_specialist'] is not False or
                value['format'] != 'kg-dialogue-current-stay/1' or
                set(value['checks']) != {'expired_stay', 'working_day_margin', 'visa_free_headroom'} or
                any(v['status'] != 'not_triggered' for v in value['checks'].values())): fail()
        if value['format'] == 'kg-dialogue-current-stay/1':
            from app.knowledge.dialogue_reconciliation import VERSION as RECONCILIATION_VERSION
            proof = dict(value['reconciliation']); evidence_hash = proof.pop('evidence_hash',None)
            expected = dict(status='verified',algorithm=RECONCILIATION_VERSION,
                map_hash=doc['policy']['reconciliation_map_hash'],authority_hash=_hash(doc['policy']),
                session_id=header.id,session_hash=header.snapshot_hash,original_fact_hash=_hash(doc['fact']),
                original_head=doc['baseline'],current_head=observed,tail=expected_tail or [],
                meaning='original_attestation_applicable_under_verified_changes_not_new_attestation')
            if proof != expected or evidence_hash != _hash(proof): fail()
    except (KeyError, TypeError, ValueError): fail()
    return value


def checked_terminal_check(value, header, observed, at):
    """Validate a stop's scope and actual packet, allowing changed/missing facts."""
    copied = dict(value) if type(value) is dict else {}
    fingerprint = copied.pop('evidence_hash', None)
    try:
        checked_at = datetime.fromisoformat(value['checked_at'])
        if (fingerprint != _hash(copied) or value['case_id'] != header.case_id or
                value['applicant_id'] != header.applicant_id or value['scope'] != 'current_stay_stops_only' or
                value['format'] not in ('kg-current-stay-checks/1','kg-dialogue-current-stay/1') or
                applications._utc(checked_at) != applications._utc(at) or
                value['as_of'] != applications._local_day(checked_at).isoformat() or
                value['permission_to_remain'] is not None or value['may_quote'] is not False or
                value['entry_eligibility_evaluated'] is not False or value['delivery'] != 'not_sent' or
                set(value['checks']) != {'expired_stay','working_day_margin','visa_free_headroom'} or
                any(v['status'] not in ('unknown','triggered','not_triggered') for v in value['checks'].values()) or
                value['requires_specialist'] is not any(v['status'] != 'not_triggered' for v in value['checks'].values())): fail()
        if value['interview'] is not None and value['interview'] != dict(id=header.interview_id,
                header_hash=header.document['delegation']['policy']['assignments'][0]['header_hash'],
                head_hash=observed['hash']): fail()
    except (KeyError, TypeError, ValueError): fail()


def checked_triage(value, reason):
    exact(value, ('reason','families','source_rows','interpretation'))
    families = value['families']; rows = value['source_rows']
    if (value['reason'] != reason or type(families) is not list or type(rows) is not list or
            any(type(f) is not str or f not in dialogue_interrupts.FAMILIES for f in families) or
            len(families) != len(set(families)) or
            families != [f for f in dialogue_interrupts.FAMILIES if f in families] or
            rows != sorted({n for f in families for n in dialogue_interrupts.FAMILIES[f]}) or
            any(type(n) is not int for n in rows)): fail()
    if reason == 'consent_withdrawn':
        if families or value['interpretation'] not in ('possible_privacy_stop','collection_stop_request'): fail()
    else:
        if value['interpretation'] != 'review_topic_only': fail()
        if families:
            expected = ('unsafe_request' if 'unsafe_request' in families else
                'refund' if 'payment_refund' in families else
                'legal_question' if 'refusal_or_ban' in families or 'source_dispute' in families else
                'calendar_needed' if 'processing_exception' in families else 'special_process')
            if reason != expected: fail()
        elif reason not in ('manager_requested','complaint','criminal_mention','uncertain_answer'): fail()


async def registry(session):
    sizes = list((await session.execute(select(EntryDialogueSession.id,
        func.length(cast(EntryDialogueSession.document, Text))).order_by(EntryDialogueSession.id).limit(MAX_SESSIONS+1))).all())
    if len(sizes) > MAX_SESSIONS or any(n is None or n > MAX_HEADER_BYTES for _, n in sizes):
        fail('dialogue_session_capacity')
    rows = list((await session.scalars(select(EntryDialogueSession).order_by(EntryDialogueSession.id).limit(MAX_SESSIONS+1))).all())
    keys = set(); subjects = set()
    for row in rows:
        validate_header(row)
        if row.transport_key in keys or row.interview_id in subjects: fail()
        keys.add(row.transport_key); subjects.add(row.interview_id)
    return rows


def _initial(header):
    return dict(head=_plain(header.document)['baseline'], prompt=None, claimed=None, outcome=None,
                last_batch=0, stopped=False, collection_blocked=False, turns={}, reconciled_tail=[])


def reduce(state, row, header):
    """Validate durable ordering; link ordinary turns to the actually accepted batch."""
    state = _plain(state); outer = _plain(row.document); exact(outer, ('previous_hash', 'payload'))
    doc = outer['payload']; kind = row.kind
    if kind == 'prompt':
        exact(doc, ('prompt', 'head', 'check_hash', 'check'))
        prompt = questions.validate_prompt(doc['prompt'], catalog_document=catalog.by_digest(questions.CATALOG_HASH))
        channels.proof(doc['check_hash']); checked_head(doc['head'])
        checked_current(doc['check'], header, doc['head'], at=row.created_at, expected_tail=state['reconciled_tail'])
        if doc['check_hash'] != _hash(doc['check']): fail()
        if state['stopped'] or state['prompt'] is not None or doc['head'] != state['head'] or prompt['batch'] != state['last_batch']+1: fail()
        state.update(prompt=dict(revision=row.revision, hash=row.snapshot_hash, **doc),
                     claimed=None, outcome=None, last_batch=prompt['batch'])
    elif kind == 'claim':
        exact(doc, ('prompt_revision', 'prompt_hash', 'body_hash', 'head_hash', 'check_hash', 'check'))
        p = state['prompt']; channels.proof(doc['check_hash'])
        checked_current(doc['check'], header, state['head'], at=row.created_at, expected_tail=state['reconciled_tail'])
        if doc['check_hash'] != _hash(doc['check']): fail()
        if (state['stopped'] or p is None or state['claimed'] is not None or
            type(doc['prompt_revision']) is not int or doc['prompt_revision'] != p['revision'] or
            doc['prompt_hash'] != p['hash'] or doc['body_hash'] != p['prompt']['body_hash'] or
            doc['head_hash'] != state['head']['hash']): fail()
        state['claimed'] = dict(revision=row.revision, hash=row.snapshot_hash)
    elif kind == 'outcome':
        exact(doc, ('claim_revision', 'claim_hash', 'outcome'))
        c = state['claimed']
        if (c is None or type(doc['claim_revision']) is not int or doc['claim_revision'] != c['revision'] or
            doc['claim_hash'] != c['hash'] or state['outcome'] is not None or
            doc['outcome'] not in ('provider_accepted', 'unknown', 'denied')): fail()
        state['outcome'] = doc['outcome']
    elif kind == 'turn':
        exact(doc, ('message_key', 'input_hash', 'parsed', 'before', 'after', 'inbox'))
        receipt = doc['inbox']; exact(receipt, ('status', 'reason', 'message_id', 'body_hash'))
        if receipt['status'] == 'recorded':
            _id(receipt['message_id']); channels.proof(receipt['body_hash'])
            if receipt['reason'] is not None: fail()
        elif receipt['status'] == 'not_retained':
            if (receipt['reason'] not in ('privacy_stop', 'collection_unavailable', 'non_text_input', 'unsupported_text') or
                    receipt['message_id'] is not None or receipt['body_hash'] is not None): fail()
        else: fail()
        for key in ('message_key', 'input_hash'): channels.proof(doc[key])
        checked_head(doc['before']); checked_head(doc['after'])
        parsed = doc['parsed']; action = parsed.get('action') if type(parsed) is dict else None
        if doc['message_key'] in state['turns'] or doc['before'] != state['head']: fail()
        if action == 'answer':
            exact(parsed, ('action', 'changes', 'displayed', 'batch', 'prompt_hash'))
            p = state['prompt']; changes = parsed['changes']
            if (state['stopped'] or state['outcome'] != 'provider_accepted' or p is None or
                parsed['prompt_hash'] != _hash(p['prompt']) or parsed['batch'] != p['prompt']['batch'] or
                type(parsed['batch']) is not int or parsed['displayed'] != [f['path'] for f in p['prompt']['displayed']] or
                type(changes) is not dict or len(changes) != 1 or not set(changes) <= set(parsed['displayed']) or
                doc['after']['revision'] != doc['before']['revision']+1 or doc['after']['id'] <= doc['before']['id'] or
                doc['after']['hash'] == doc['before']['hash']): fail()
            # The actual retained interview event is cross-checked in history().
            state['reconciled_tail'].append(dict(event=doc['after'],turn_hash=row.snapshot_hash))
            state.update(head=doc['after'], prompt=None, claimed=None, outcome=None)
        elif action == 'acknowledgement':
            exact(parsed, ('action',))
            if state['stopped'] or doc['before'] != doc['after']: fail()
        elif action == 'interrupt':
            exact(parsed, ('action', 'reason'))
            if parsed['reason'] not in interviews.rules.INTERRUPTS or doc['before'] != doc['after']: fail()
            if state['stopped'] and (parsed['reason'] != 'consent_withdrawn' or state['collection_blocked']): fail()
            if parsed['reason'] == 'consent_withdrawn' and receipt != dict(
                    status='not_retained',reason='privacy_stop',message_id=None,body_hash=None): fail()
        else: fail()
        state['turns'][doc['message_key']] = dict(revision=row.revision, input_hash=doc['input_hash'])
    elif kind == 'stop':
        exact(doc, ('reason', 'head', 'observed', 'effect', 'trigger', 'suppression', 'stop_id', 'cause_id', 'check_hash', 'collection_blocked', 'evidence'))
        exact(doc['trigger'], ('revision','hash','message_key'))
        _id(doc['trigger']['revision']); channels.proof(doc['trigger']['hash']); channels.proof(doc['trigger']['message_key'])
        checked_head(doc['head'])
        checked_head(doc['observed'])
        if doc['suppression'] != 'persistent_session_terminal' or doc['effect'] not in ('interrupt_appended', 'existing_handoff_retained'): fail()
        if doc['stop_id'] is not None: _id(doc['stop_id'])
        if doc['cause_id'] is not None: _id(doc['cause_id'])
        if doc['check_hash'] is not None: channels.proof(doc['check_hash'])
        if (doc['reason'] not in interviews.rules.INTERRUPTS or type(doc['collection_blocked']) is not bool or
            state['stopped'] and (doc['reason'] != 'consent_withdrawn' or state['collection_blocked'] or not doc['collection_blocked']) or
            doc['head']['revision'] < state['head']['revision']): fail()
        exact(doc['evidence'], ('triage', 'current_check', 'context_reason'))
        if (doc['evidence']['current_check'] is None) != (doc['check_hash'] is None): fail()
        if doc['check_hash'] is not None and _hash(doc['evidence']['current_check']) != doc['check_hash']: fail()
        if doc['check_hash'] is not None:
            checked_terminal_check(doc['evidence']['current_check'],header,doc['observed'],row.created_at)
        if doc['evidence']['triage'] is not None: checked_triage(doc['evidence']['triage'],doc['reason'])
        if doc['evidence']['context_reason'] not in (None, 'native_interview_changed',
                'current_checks_or_collection_require_review', 'typed_or_current_stop',
                'client_prompt_needs_operator_setup', 'inbox_identity_or_receipt_conflict', 'existing_channel_stop'): fail()
        if all(v is None for v in doc['evidence'].values()): fail()
        state.update(stopped=True, collection_blocked=doc['collection_blocked'], head=doc['head'])
    else: fail()
    return state


async def history(session, header, *, interview=None, events=None, through_revision=None, legacy_subject=None):
    validate_header(header)
    scope=[EntryDialogueEvent.session_id == header.id]
    if through_revision is not None:
        if type(through_revision) is not int or not 0<=through_revision<=MAX_EVENTS:fail()
        scope.append(EntryDialogueEvent.revision<=through_revision)
    if legacy_subject is not None and legacy_subject!=(header.case_id,header.applicant_id):fail()
    sizes = list((await session.execute(select(EntryDialogueEvent.id,
        func.length(cast(EntryDialogueEvent.document, Text))).where(*scope)
        .order_by(EntryDialogueEvent.revision).limit(MAX_EVENTS+1))).all())
    if (len(sizes) > MAX_EVENTS or any(n is None or n > MAX_EVENT_BYTES for _, n in sizes) or
            sum(n for _, n in sizes) > MAX_JOURNAL_BYTES): fail('dialogue_event_capacity')
    rows = list((await session.scalars(select(EntryDialogueEvent).where(*scope)
        .order_by(EntryDialogueEvent.revision).limit(MAX_EVENTS+1))).all())
    if through_revision is not None and len(rows)!=through_revision:fail()
    if interview is None:
        interview = await session.get(EntryInterview, header.interview_id)
    if interview is None or interview.snapshot_hash != _hash(interviews._header_payload(interview)): fail()
    pinned = interviews.policy_from_document(_plain(interview.policy))
    if events is None: events, _, _ = await interviews._history(session, interview, pinned)
    by_head = {e.snapshot_hash: e for e in events}; by_id = {e.id: e for e in events}
    original = by_head.get(header.document['baseline']['hash'])
    if (original is None or head(original) != _plain(header.document['baseline']) or
        original.interview_id != header.interview_id or
        applications._utc(original.created_at) > applications._utc(header.created_at) or
        interview.snapshot_hash != header.document['delegation']['policy']['assignments'][0]['header_hash']): fail()
    state = _initial(header); previous = None; total = 0; keys = set()
    for n, row in enumerate(rows, 1):
        payload = event_payload(row); amount = len(canonical(payload).encode()); total += amount
        _key(row.request_key)
        if (row.revision != n or row.request_key in keys or row.snapshot_hash != _hash(payload) or
            row.previous_id != (previous.id if previous else None) or
            row.document.get('previous_hash') != (previous.snapshot_hash if previous else None) or
            previous and row.id <= previous.id or amount > MAX_EVENT_BYTES or total > MAX_JOURNAL_BYTES or
            applications._utc(row.created_at) < applications._utc(previous.created_at if previous else header.created_at)): fail()
        state = reduce(state, row, header); doc = _plain(row.document)['payload']
        if row.kind == 'prompt':
            target = by_id.get(doc['head']['id'])
            if (target is None or head(target) != doc['head'] or target.snapshot['phase'] != 'active' or
                target.snapshot['collection_blocked'] or target.snapshot['language'] != doc['prompt']['language'] or
                [q['path'] for q in target.snapshot['drafts']] != [q['path'] for q in doc['prompt']['displayed']]): fail()
        if row.kind == 'turn':
            before = by_id.get(doc['before']['id']); after = by_id.get(doc['after']['id'])
            if before is None or after is None or head(before) != doc['before'] or head(after) != doc['after']: fail()
            if doc['parsed']['action'] == 'answer':
                operation = dict(action='answer', changes=doc['parsed']['changes'], displayed=doc['parsed']['displayed'])
                if (after.previous_id != before.id or after.command['operation'] != operation or
                    after.created_by != header.document['delegation']['policy']['assignments'][0]['actor'] or
                    applications._utc(after.created_at) != applications._utc(row.created_at)): fail()
        if row.kind == 'stop':
            if (previous is None or previous.kind != 'turn' or doc['trigger'] != dict(
                    revision=previous.revision,hash=previous.snapshot_hash,
                    message_key=previous.document['payload']['message_key'])): fail()
            parsed = previous.document['payload']['parsed']
            if parsed['action'] == 'interrupt' and parsed['reason'] != doc['reason']: fail()
            if parsed['action'] != 'interrupt' and doc['evidence']['context_reason'] not in (
                    'typed_or_current_stop','client_prompt_needs_operator_setup'): fail()
            if parsed['action'] != 'interrupt' and doc['evidence']['triage'] is not None: fail()
            observed = by_id.get(doc['observed']['id']); target = by_id.get(doc['head']['id'])
            if (observed is None or target is None or head(observed) != doc['observed'] or head(target) != doc['head'] or
                target.snapshot['phase'] not in ('pending', 'acked') or not target.snapshot['handoff'] or
                target.snapshot['collection_blocked'] is not doc['collection_blocked']): fail()
            if doc['effect'] == 'interrupt_appended':
                if (target.previous_id != observed.id or target.action != 'interrupt' or
                    target.command['operation'] != dict(action='interrupt', reason=doc['reason']) or
                    target.created_by != header.document['delegation']['policy']['assignments'][0]['actor'] or
                    applications._utc(target.created_at) != applications._utc(row.created_at)): fail()
            elif target.id != observed.id: fail()
            if doc['reason'] == 'consent_withdrawn' and not doc['collection_blocked']: fail()
            if doc['stop_id'] is not None or doc['cause_id'] is not None:
                old_stops, _ = await stops._registry(session,subject=legacy_subject)
                old = next((s for s in old_stops if s.id == doc['stop_id']), None)
                if old is None or old.transport_key != header.transport_key or old.interview_id != header.interview_id: fail()
                if doc['cause_id'] is not None:
                    from app.domain import dialogue_stops
                    causes, _ = await dialogue_stops._registry(session, old_stops,subject=legacy_subject)
                    cause = next((c for c in causes if c.id == doc['cause_id']), None)
                    if cause is None or cause.stop_id != old.id or cause.interview_id != header.interview_id: fail()
        observed = by_head.get(state['head']['hash'])
        if observed is None or head(observed) != state['head'] or applications._utc(observed.created_at) > applications._utc(row.created_at): fail()
        keys.add(row.request_key); previous = row
    return rows, state, total


async def append(session, header, rows, state, total, *, kind, request_key, payload, at):
    """Reserve six records for an outcome, first stop and later privacy recovery."""
    _key(request_key)
    reserve = (0 if kind in ('stop', 'outcome') else
        1 if kind == 'turn' and payload.get('parsed') == dict(action='interrupt', reason='consent_withdrawn') else
        4 if kind == 'turn' and payload.get('parsed', {}).get('action') == 'interrupt' else 6)
    if len(rows)+1 > MAX_EVENTS-reserve: fail('dialogue_event_capacity')
    row = EntryDialogueEvent(session_id=header.id, revision=len(rows)+1,
        previous_id=rows[-1].id if rows else None, request_key=request_key, kind=kind, created_at=at,
        document=dict(previous_hash=rows[-1].snapshot_hash if rows else None, payload=payload))
    row.snapshot_hash = _hash(event_payload(row)); amount = len(canonical(event_payload(row)).encode())
    if amount > MAX_EVENT_BYTES or total+amount > MAX_JOURNAL_BYTES-reserve*MAX_EVENT_BYTES: fail('dialogue_event_capacity')
    if applications._utc(at) < applications._utc(rows[-1].created_at if rows else header.created_at): fail('dialogue_clock_reversed')
    reduce(state, row, header)
    session.add(row); await session.flush()
    return row
