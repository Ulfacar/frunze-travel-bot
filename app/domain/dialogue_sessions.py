"""Local typed dialogue composer. No provider calls in retryable transactions."""
from dataclasses import asdict, dataclass
from datetime import datetime
import re
import unicodedata
from weakref import WeakKeyDictionary

from sqlalchemy import select

from app.domain import dialogue_journal as journal, entry_channel_stops as stops
from app.domain import dialogue_inbox as inbox
from app.domain import entry_channel_policy as channels, entry_interviews as interviews
from app.domain import entry_applications as applications, current_stay_stops as current
from app.domain.dialogue_authority import DialogueAuthority
from app.domain.dialogue_policy import delegated_document
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict, _hash, _plain, _transaction
from app.domain.models import EntryDialogueSession, Dialog, _now
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge import dialogue_questions as questions, dialogue_interrupts, interview_rules
from app.knowledge.review import canonical


def incoming_identity(route, provider_id, text, *, kind, voice, voice_failed, media_type, attachment_identity):
    channels.validate_route(route)
    if (type(provider_id) is not str or not 1 <= len(provider_id) <= 256 or
        any(unicodedata.category(c).startswith('C') for c in provider_id) or provider_id.strip() != provider_id or
        type(text) is not str or type(kind) is not str or not re.fullmatch('[a-z_]{1,32}', kind) or
        type(voice) is not bool or type(voice_failed) is not bool or
        media_type is not None and (type(media_type) is not str or len(media_type) > 120) or
        attachment_identity is not None and (type(attachment_identity) is not str or len(attachment_identity) > 512)):
        raise EntryStorageInvalid('invalid_dialogue_incoming_envelope')
    return (_hash(dict(route=route, provider_id=provider_id)), _hash(dict(text=text, kind=kind, voice=voice,
        voice_failed=voice_failed, media_type=media_type, attachment_identity=attachment_identity)))


async def _context(session, assignment, route, resolver, header=None):
    """Stored assignment can process operational privacy; current actor still required."""
    actor = Actor(manager_id=assignment['actor'], is_full_admin=True); channels.access(actor)
    case = await applications._case(session, assignment['case_id'], lock=True)
    person = await applications._applicant(session, case.id, assignment['applicant_id'])
    interview, pinned = await interviews._header(session, case, person, assignment['interview_id'])
    if (interview.snapshot_hash != assignment['header_hash'] or actor.manager_id not in pinned.operators or
            actor.manager_id not in interview.authority['full_admins']):
        raise PermissionDenied('dialogue_operator_or_subject_changed')
    dialog = await session.scalar(select(Dialog).where(Dialog.id == assignment['dialog_id']).with_for_update())
    if (dialog is None or dialog.contact_id != case.contact_id or dialog.channel != 'whatsapp' or
        channels.validate_route(resolver(dialog.channel, dialog.bot_id, dialog.channel_key)) != route or
        channels.recipient(dialog.channel_key) != route['recipient']):
        raise EntryStorageConflict('dialogue_transport_binding_changed')
    identity = dict(id=dialog.id, contact_id=dialog.contact_id, channel=dialog.channel, bot_id=dialog.bot_id, channel_key=dialog.channel_key)
    if header is not None and _plain(header.document['channel_identity']) != identity:
        raise EntryStorageConflict('dialogue_transport_binding_changed')
    events, state, _ = await interviews._history(session, interview, pinned)
    return actor, interview, events, state, pinned, identity


def _authorize(authority, assignment, actor, route, pinned, at):
    from app.config import settings
    if settings.panel_backend != 'postgres': raise PermissionDenied('dialogue_persistent_inbox_required')
    if not isinstance(authority, DialogueAuthority): raise PermissionDenied('dialogue_authority_required')
    authority.validate(); on = applications._local_day(at).isoformat()
    if (authority.dialogue.assignment(route) != assignment or authority.interview.digest != pinned.digest or
        any(not d['valid_from'] <= on <= d['review_due_on'] for d in (authority.policy.document, authority.dialogue.document))):
        raise PermissionDenied('dialogue_authority_changed_or_expired')
    channels.authorize(actor, authority.channel, route, on=applications._local_day(at))


async def _current(session, authority, actor, assignment, header=None):
    args = dict(actor=actor, case_id=assignment['case_id'], applicant_id=assignment['applicant_id'],
        policy=authority.current, fact=authority.fact, qualification_policy=authority.qualification,
        publication_policy=authority.publication, calendars=authority.calendars)
    if header is None: return await current.evaluate_in_session(session, **args)
    return await current.evaluate_dialogue_in_session(session, **args, dialogue_session_id=header.id,
                                                      session_policy=authority.policy)


def _collection(state, pinned, interview, at):
    on = applications._local_day(at).isoformat()
    analysis = interview_rules.analyze(state['answers'], on=on, language=state['language'],
        pre_consent=pinned.pre_consent, catalog_document=_plain(interview.catalog))
    return (state['phase'] == 'active' and not state['collection_blocked'] and analysis['consent_complete'] and
            not analysis['stops'] and analysis['questions'] == _plain(state['drafts']))


async def _enroll(session, authority, assignment, actor, interview, events, state, pinned, identity, route, registry):
    if len(registry) >= journal.MAX_SESSIONS: journal.fail('dialogue_session_capacity')
    check = await _current(session, authority, actor, assignment)
    at = datetime.fromisoformat(check['checked_at']); _authorize(authority, assignment, actor, route, pinned, at)
    if not _collection(state, pinned, interview, at): raise PermissionDenied('dialogue_consent_or_collection_required')
    if not check['source'] or not check['fact'] or check['interview'] != authority.fact.document['interview']:
        raise PermissionDenied('dialogue_baseline_unavailable')
    header = EntryDialogueSession(transport_key=_hash(route), case_id=assignment['case_id'],
        applicant_id=assignment['applicant_id'], interview_id=interview.id, created_at=at,
        document=dict(delegation=delegated_document(authority.dialogue, assignment),
            original_dialogue_policy=authority.dialogue.document, policy=authority.policy.document,
            channel_policy=authority.channel.document(), channel_identity=identity,
            fact=authority.fact.document, baseline=journal.head(events[-1]), baseline_check=dict(
                evidence_hash=check['evidence_hash'], profile_hash=check['profile']['snapshot_hash'],
                history_hash=check['history']['snapshot_hash'], source_hash=check['source']['source_hash'],
                fact_hash=authority.fact.digest, interview_head_hash=events[-1].snapshot_hash, result=check)))
    header.snapshot_hash = _hash(journal.header_payload(header)); journal.validate_header(header)
    session.add(header); await session.flush()
    return header, check, at


def _receipt(header, rows, state, *, duplicate=False):
    return dict(format='kg-dialogue-turn-receipt/1', session_id=header.id,
        revision=len(rows), head=state['head'], stopped=state['stopped'], collection_blocked=state['collection_blocked'],
        prompt_revision=state['prompt']['revision'] if state['prompt'] else None,
        delivery=state['outcome'] or ('claimed_outcome_unknown' if state['claimed'] else 'not_sent'), duplicate=duplicate)


def _original_receipt(header, rows, turn_revision):
    # Each input transaction ends with its turn and optional prompt/terminal
    # event. Later claims/outcomes/inputs never change the original receipt.
    end = turn_revision
    if len(rows) > end and rows[end].kind in ('prompt', 'stop'): end += 1
    flow = journal._initial(header)
    for row in rows[:end]: flow = journal.reduce(flow, row, header)
    return _receipt(header, rows[:end], flow, duplicate=True)


async def _stop(session, header, interview, events, state, actor, reason, key, at,
                *, check=None, triage=None, context_reason=None, old_stops=()):
    # The C terminal event is canonical. Missing/expired legacy channel authority
    # never prevents an operational consent hold. No expired old receipt is forged.
    observed = journal.head(events[-1]); effect = 'existing_handoff_retained'
    if state['phase'] in ('active', 'paused') or reason == 'consent_withdrawn' and not state['collection_blocked']:
        await interviews._record_action_in_session(session, actor=actor, case_id=header.case_id,
            applicant_id=header.applicant_id, interview_id=interview.id, expected_revision=len(events),
            request_key='session-stop-'+key[:51], operation=dict(action='interrupt', reason=reason), at=at)
        events, state, _ = await interviews._history(session, interview, interviews.policy_from_document(_plain(interview.policy)))
        effect = 'interrupt_appended'
    rows, flow, total = await journal.history(session, header, interview=interview, events=events)
    old = next((r for r in old_stops if r.transport_key == header.transport_key), None)
    if old is not None and old.interview_id != interview.id: raise EntryStorageConflict('dialogue_route_already_stopped_for_other_subject')
    trigger = rows[-1]
    if trigger.kind != 'turn' or trigger.document['payload']['message_key'] != key: journal.fail()
    await journal.append(session, header, rows, flow, total, kind='stop', request_key='stop-'+key[:59], at=at,
        payload=dict(reason=reason, head=journal.head(events[-1]), observed=observed, effect=effect,
            trigger=dict(revision=trigger.revision, hash=trigger.snapshot_hash, message_key=key),
            suppression='persistent_session_terminal', stop_id=old.id if old else None, cause_id=None,
            check_hash=_hash(check) if check else None, collection_blocked=state['collection_blocked'],
            evidence=dict(triage=triage, current_check=check, context_reason=context_reason)))
    rows, flow, _ = await journal.history(session, header, interview=interview, events=events)
    return _receipt(header, rows, flow)


async def _terminal_input(session, header, interview, events, state, actor, key, body_hash, at,
                          *, reason='uncertain_answer', **evidence):
    rows, flow, total = await journal.history(session, header, interview=interview, events=events)
    await journal.append(session, header, rows, flow, total, kind='turn', request_key='input-'+key[:58], at=at,
        payload=dict(message_key=key, input_hash=body_hash, parsed=dict(action='interrupt', reason=reason),
                     before=flow['head'], after=flow['head'], inbox=inbox.omitted('collection_unavailable')))
    return await _stop(session, header, interview, events, state, actor, reason, key, at, **evidence)


async def receive(engine, *, route, provider_id, text, resolver, authority=None,
                  kind='text', voice=False, voice_failed=False, media_type=None, attachment_identity=None):
    key, body_hash = incoming_identity(route, provider_id, text, kind=kind, voice=voice,
        voice_failed=voice_failed, media_type=media_type, attachment_identity=attachment_identity)
    triage = dialogue_interrupts.triage(text, kind=kind, voice=voice or voice_failed)
    # Privacy is an operational hold, including when the ordinary input limit
    # is exceeded. Hash the exact input; never persist its oversized raw body.
    if len(text) > 65536 and triage.reason != 'consent_withdrawn':
        raise EntryStorageInvalid('dialogue_input_too_large')
    async def write(session):
        await stops._lock(session, route, writer=True)
        old_stops, _ = await stops._registry(session)
        registry = await journal.registry(session)
        header = next((r for r in registry if r.transport_key == _hash(route)), None)
        assignment = journal.validate_header(header)[1] if header else (
            authority.dialogue.assignment(route) if isinstance(authority, DialogueAuthority) else None)
        if assignment is None: raise PermissionDenied('dialogue_assignment_required')
        actor, interview, events, state, pinned, identity = await _context(session, assignment, route, resolver, header)
        at = _now(); check = None
        if header is None:
            _authorize(authority, assignment, actor, route, pinned, at)
            header, check, at = await _enroll(session, authority, assignment, actor, interview, events, state, pinned, identity, route, registry)
        rows, flow, total = await journal.history(session, header, interview=interview, events=events)
        prior = flow['turns'].get(key)
        if prior:
            if prior['input_hash'] != body_hash: raise EntryStorageConflict('dialogue_message_changed')
            # No send/append on retry, including after later policy/head changes.
            return _original_receipt(header, rows, prior['revision'])
        privacy = triage.reason == 'consent_withdrawn'
        if flow['stopped'] and (not privacy or flow['collection_blocked']):
            return _receipt(header, rows, flow)
        stop_context = None
        if privacy:
            parsed = dict(action='interrupt', reason='consent_withdrawn')
        else:
            _authorize(authority, assignment, actor, route, pinned, at)
            if any(r.transport_key == header.transport_key for r in old_stops):
                parsed = dict(action='interrupt', reason=triage.reason or 'uncertain_answer')
                stop_context = 'existing_channel_stop'
            elif flow['head'] != journal.head(events[-1]):
                # Do not reinterpret a new native head as this session's prompt.
                return await _terminal_input(session, header, interview, events, state, actor, key, body_hash, at,
                    context_reason='native_interview_changed', old_stops=old_stops)
            else:
                check = await _current(session, authority, actor, assignment, header)
                at = datetime.fromisoformat(check['checked_at']); _authorize(authority, assignment, actor, route, pinned, at)
                if check['requires_specialist'] or not _collection(state, pinned, interview, at):
                    return await _terminal_input(session, header, interview, events, state, actor, key, body_hash, at,
                        check=check, context_reason='current_checks_or_collection_require_review', old_stops=old_stops)
                if triage.reason not in (None, 'uncertain_answer'):
                    parsed = dict(action='interrupt', reason=triage.reason)
                elif flow['prompt'] is None:
                    parsed = dict(action='acknowledgement') if triage.reason is None else dict(action='interrupt', reason='uncertain_answer')
                elif flow['outcome'] != 'provider_accepted':
                    parsed = dict(action='interrupt', reason='uncertain_answer')
                else:
                    parsed = questions.parse(flow['prompt']['prompt'], text, catalog_document=_plain(interview.catalog),
                        kind=kind, voice=voice or voice_failed)
                    if parsed['action'] == 'interrupt': parsed = dict(action='interrupt', reason=parsed['triage']['reason'])
        before = flow['head'] if parsed['action'] == 'interrupt' else journal.head(events[-1])
        incoming = inbox.omitted('privacy_stop' if privacy else 'collection_unavailable')
        if not privacy and (kind != 'text' or voice or voice_failed):
            incoming = inbox.omitted('non_text_input')
        elif not privacy and (len(text) > 2048 or any(unicodedata.category(c).startswith('C')
                and c not in '\r\n\t' for c in text)):
            incoming = inbox.omitted('unsupported_text')
        elif not privacy and _collection(state, pinned, interview, at):
            try:
                incoming = await inbox.save(session, header, message_key=key, text=text, provider_id=provider_id, at=at)
            except EntryStorageConflict:
                return await _terminal_input(session, header, interview, events, state, actor, key, body_hash, at,
                    context_reason='inbox_identity_or_receipt_conflict', old_stops=old_stops)
        if parsed['action'] == 'answer':
            await interviews._record_action_in_session(session, actor=actor, case_id=header.case_id,
                applicant_id=header.applicant_id, interview_id=interview.id, expected_revision=len(events),
                request_key='client-'+key[:57], expected_policy_hash=pinned.digest, policy=pinned,
                operation=dict(action='answer', changes=parsed['changes'], displayed=parsed['displayed']), at=at)
            events, state, _ = await interviews._history(session, interview, pinned)
        await journal.append(session, header, rows, flow, total, kind='turn', request_key='input-'+key[:58], at=at,
            payload=dict(message_key=key, input_hash=body_hash, parsed=parsed, before=before,
                         after=before if parsed['action'] == 'interrupt' else journal.head(events[-1]), inbox=incoming))
        rows, flow, total = await journal.history(session, header, interview=interview, events=events)
        if parsed['action'] == 'interrupt':
            return await _stop(session, header, interview, events, state, actor, parsed['reason'], key, at,
                check=check, triage=asdict(triage) if triage.reason == parsed['reason'] else None,
                context_reason=stop_context, old_stops=old_stops)
        check = await _current(session, authority, actor, assignment, header)
        at = datetime.fromisoformat(check['checked_at']); _authorize(authority, assignment, actor, route, pinned, at)
        if check['requires_specialist'] or not _collection(state, pinned, interview, at):
            return await _stop(session, header, interview, events, state, actor, 'special_process', key, at,
                check=check, context_reason='typed_or_current_stop', old_stops=old_stops)
        if flow['prompt'] is None:
            try:
                prompt = questions.render(batch=flow['last_batch']+1, paths=[q['path'] for q in state['drafts']],
                    language=state['language'], catalog_document=_plain(interview.catalog))
            except questions.QuestionInvalid:
                return await _stop(session, header, interview, events, state, actor, 'uncertain_answer', key, at,
                    context_reason='client_prompt_needs_operator_setup', old_stops=old_stops)
            await journal.append(session, header, rows, flow, total, kind='prompt',
                request_key='prompt-'+str(flow['last_batch']+1), at=at,
                payload=dict(prompt=prompt, head=journal.head(events[-1]), check_hash=_hash(check), check=check))
        rows, flow, _ = await journal.history(session, header, interview=interview, events=events)
        return _receipt(header, rows, flow)
    return await _transaction(engine, write)


@dataclass(frozen=True, eq=False)
class TypedSend:
    """A durable attempt reference, never sufficient by itself for admission."""
    session_id: int
    claim_revision: int
    claim_hash: str
    body: str
    route_hash: str


_issued = WeakKeyDictionary()


def consume_capability(capability):
    """One process-local use of an object issued only after a new claim commit.

    A restarted process cannot reissue the durable claim. Reconstructed objects,
    copied row IDs and a second call with the same object do not grant admission.
    Consumption precedes awaits; a failed admission also never retries this send.
    """
    if not isinstance(capability, TypedSend) or _issued.get(capability) is not False: return False
    _issued[capability] = True
    return True


async def claim(engine, *, route, session_id, prompt_revision, authority, resolver):
    """Only a newly committed claim yields a capability; an old claim never does."""
    channels.validate_route(route)
    journal._id(session_id); journal._id(prompt_revision)
    async def write(session):
        await stops._lock(session, route, writer=True)
        old_stops, _ = await stops._registry(session)
        rows = await journal.registry(session)
        header = next((r for r in rows if r.id == session_id and r.transport_key == _hash(route)), None)
        if header is None: raise PermissionDenied('dialogue_session_required')
        if any(r.transport_key == header.transport_key for r in old_stops): return None
        _, assignment = journal.validate_header(header)
        actor, interview, events, state, pinned, _ = await _context(session, assignment, route, resolver, header)
        rows, flow, total = await journal.history(session, header, interview=interview, events=events)
        if flow['stopped'] or flow['claimed'] is not None or flow['prompt'] is None: return None
        if flow['prompt']['revision'] != prompt_revision or flow['head'] != journal.head(events[-1]): return None
        _authorize(authority, assignment, actor, route, pinned, _now())
        check = await _current(session, authority, actor, assignment, header)
        at = datetime.fromisoformat(check['checked_at']); _authorize(authority, assignment, actor, route, pinned, at)
        if check['requires_specialist'] or not _collection(state, pinned, interview, at): return None
        p = flow['prompt']
        row = await journal.append(session, header, rows, flow, total, kind='claim', request_key='claim-'+str(prompt_revision), at=at,
            payload=dict(prompt_revision=p['revision'], prompt_hash=p['hash'], body_hash=p['prompt']['body_hash'],
                head_hash=flow['head']['hash'], check_hash=_hash(check), check=check))
        return TypedSend(header.id, row.revision, row.snapshot_hash, p['prompt']['body'], header.transport_key)
    capability = await _transaction(engine, write)
    if capability is not None: _issued[capability] = False
    return capability


async def admit_in_session(session, *, route, capability, authority, resolver):
    """Existing final guard owns route lock; retain all evidence locks through callback."""
    if not isinstance(capability, TypedSend) or capability.route_hash != _hash(route): return False
    headers = await journal.registry(session)
    header = next((r for r in headers if r.id == capability.session_id and r.transport_key == capability.route_hash), None)
    if header is None: return False
    _, assignment = journal.validate_header(header)
    actor, interview, events, state, pinned, _ = await _context(session, assignment, route, resolver, header)
    _, flow, _ = await journal.history(session, header, interview=interview, events=events)
    if (flow['stopped'] or flow['outcome'] is not None or flow['claimed'] !=
        dict(revision=capability.claim_revision, hash=capability.claim_hash) or flow['prompt'] is None or
        flow['prompt']['prompt']['body'] != capability.body or flow['head'] != journal.head(events[-1])): return False
    _authorize(authority, assignment, actor, route, pinned, _now())
    check = await _current(session, authority, actor, assignment, header)
    at = datetime.fromisoformat(check['checked_at']); _authorize(authority, assignment, actor, route, pinned, at)
    return not check['requires_specialist'] and _collection(state, pinned, interview, at)


async def record_outcome(engine, *, route, capability, outcome):
    """Append evidence only. No automatic provider retry, including on DB uncertainty."""
    if not isinstance(capability, TypedSend) or outcome not in ('provider_accepted', 'unknown', 'denied'):
        raise EntryStorageInvalid('invalid_dialogue_send_outcome')
    issued = _issued.get(capability)
    if issued is None or outcome == 'provider_accepted' and issued is not True:
        raise EntryStorageInvalid('unissued_or_unconsumed_dialogue_send_outcome')
    channels.validate_route(route)
    async def write(session):
        await stops._lock(session, route, writer=True)
        headers = await journal.registry(session)
        header = next((r for r in headers if r.id == capability.session_id and r.transport_key == _hash(route)), None)
        if header is None or capability.route_hash != header.transport_key: journal.fail()
        rows, flow, total = await journal.history(session, header)
        if flow['claimed'] != dict(revision=capability.claim_revision, hash=capability.claim_hash):
            # A later accepted answer can consume the prompt; find the original
            # immutable outcome rather than attributing this result to a new batch.
            previous = next((r for r in rows if r.kind == 'outcome' and
                r.document['payload']['claim_hash'] == capability.claim_hash), None)
            if previous and previous.document['payload']['outcome'] == outcome: return previous.snapshot_hash
            raise EntryStorageConflict('dialogue_attempt_changed')
        previous = next((r for r in rows if r.kind == 'outcome' and
            r.document['payload']['claim_hash'] == capability.claim_hash), None)
        if previous:
            if previous.document['payload']['outcome'] != outcome: raise EntryStorageConflict('dialogue_outcome_changed')
            return previous.snapshot_hash
        row = await journal.append(session, header, rows, flow, total, kind='outcome',
            request_key='outcome-'+str(capability.claim_revision), at=_now(),
            payload=dict(claim_revision=capability.claim_revision, claim_hash=capability.claim_hash, outcome=outcome))
        return row.snapshot_hash
    return await _transaction(engine, write)
