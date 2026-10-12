"""Explicit managed Wappi intake before STT/legacy automation; defaults empty."""
from copy import deepcopy
import logging

from app.channels.base import Message
from app.domain import entry_channel_policy as channels, dialogue_sessions as sessions
from app.domain.dialogue_session_policy import managed_routes, SessionPolicy
from app.domain.dialogue_authority import DialogueAuthority
from app.domain.dialogue_policy import DialoguePolicy
from app.domain.current_stay_policy import CurrentStayPolicy, CurrentStayFact
from app.domain.entry_interview_policy import policy_from_document as interview_policy
from app.domain.qualification_policy import QualificationPolicy
from app.domain.knowledge_publication_rules import configured_policy
from app.domain.entry_storage import _hash, EntryStorageUnavailable
from app.knowledge.work_calendar import WorkCalendars
from app.knowledge.review import canonical
from app.knowledge.dialogue_interrupts import triage

log = logging.getLogger(__name__)


def declared(adapter, chat_id):
    if getattr(adapter, 'channel', None) != 'whatsapp': return False
    from app.config import settings
    from app.core.kg_channel_guard import descriptor
    try:
        routes = managed_routes(settings.kg_dialogue_managed_routes)
        if not routes: return False
        return _hash(descriptor(adapter, chat_id)) in routes
    except Exception:
        # Invalid deployment declaration/identity is never interpreted as empty.
        return True


def normalize(adapter, raw):
    """Managed messages retain raw text/metadata without media capture or STT."""
    from app.core.kg_channel_guard import capture_adapter
    from app.channels.wappi import _TEXT_TYPE
    chat = raw.get('chatId') or raw.get('from') or ''
    if not declared(adapter, chat): return None
    captured = capture_adapter(adapter)
    kind = 'text' if raw.get('type') == _TEXT_TYPE else 'non_text'
    body = raw.get('body')
    try: user = channels.recipient(raw.get('from') or chat)
    except Exception: user = ''
    msg = Message(channel='whatsapp', user_id=user, chat_id=chat,
        text=body if type(body) is str else '', kind=kind, raw=deepcopy(raw),
        voice=str(raw.get('type') or '').lower() in ('ptt', 'audio', 'voice'),
        media_type='' if kind == 'text' else str(raw.get('type') or 'unknown'))
    # Captured server adapter is not populated from an event-supplied account.
    msg._kg_adapter = captured
    return msg


def authority_for(route):
    from app.config import settings
    if _hash(route) not in managed_routes(settings.kg_dialogue_managed_routes): return None
    values = deepcopy(settings.kg_typed_dialogue_authority)
    if values == {}: return None
    if (type(values) is not dict or set(values) != {'policy', 'dialogue_policy', 'current_stay_policy', 'facts', 'calendars'} or
        len(canonical(values).encode()) > 1048576 or type(values['facts']) is not list or not 1 <= len(values['facts']) <= 128):
        channels.fail('invalid_typed_dialogue_authority')
    dp = DialoguePolicy(values['dialogue_policy']); assignment = dp.assignment(route)
    if assignment is None: return None
    facts = [CurrentStayFact(v) for v in values['facts']]
    keys = [(v.document['case_id'], v.document['applicant_id']) for v in facts]
    if len(keys) != len(set(keys)): channels.fail('conflicting_dialogue_facts')
    target = (assignment['case_id'], assignment['applicant_id'])
    if target not in keys: channels.fail('dialogue_fact_required')
    return DialogueAuthority(SessionPolicy(values['policy']), dp,
        channels.policy_from_document(deepcopy(settings.kg_channel_stop_policy)),
        interview_policy(deepcopy(settings.kg_interview_policy)), CurrentStayPolicy(values['current_stay_policy']),
        facts[keys.index(target)], QualificationPolicy(deepcopy(settings.kg_qualification_policy)),
        configured_policy(settings), WorkCalendars(values['calendars']))


async def output_enabled(orchestrator, msg):
    from app.core.state import get_state_store
    if not await orchestrator._bots_on(): return False
    state = await get_state_store().load(orchestrator._key(msg))
    return not state.intercepted


async def consume(orchestrator, msg):
    from app.channels.wappi import is_incoming_user_message
    from app.core import kg_channel_guard as guard
    adapter = getattr(msg, '_kg_adapter', None) or guard.capture_adapter(orchestrator.channel)
    if not declared(adapter, msg.chat_id): return False
    try:
        # Direct/alternate entrypoints receive the same echo/group/status gate.
        if msg.channel != 'whatsapp' or not is_incoming_user_message(msg.raw): return True
        route = guard.descriptor(adapter, msg.chat_id)
        if (channels.recipient(msg.user_id) != route['recipient'] or
            msg.raw.get('from') and channels.recipient(msg.raw['from']) != route['recipient'] or
            msg.raw.get('profile_id') and msg.raw['profile_id'] != adapter._profile_id):
            channels.fail('dialogue_incoming_identity_conflict')
        if (len(canonical(msg.raw).encode()) > 131072 and
                triage(msg.text, kind=msg.kind, voice=msg.voice or msg.voice_failed).reason != 'consent_withdrawn'):
            channels.fail('dialogue_packet_too_large')
        try: authority = authority_for(route)
        except Exception:
            # Stored operational privacy remains processable if current
            # collection configuration is removed/malformed; it grants no send.
            authority = None
        result = await sessions.receive(guard._engine(), route=route,
            provider_id=msg.raw.get('id') or msg.raw.get('message_id') or msg.raw.get('msg_id'), text=msg.text,
            kind=msg.kind, voice=msg.voice, voice_failed=msg.voice_failed, media_type=msg.media_type,
            attachment_identity=_hash(msg.raw), resolver=guard.resolve_dialog, authority=authority)
        if result['duplicate'] or result['stopped'] or result['prompt_revision'] is None or not await output_enabled(orchestrator, msg):
            return True
        capability = await sessions.claim(guard._engine(), route=route, session_id=result['session_id'],
            prompt_revision=result['prompt_revision'], authority=authority_for(route), resolver=guard.resolve_dialog)
        if capability is None: return True
        outcome = 'unknown'
        async def callback():
            if not await output_enabled(orchestrator, msg): return None
            provider_id = await adapter.send(msg.chat_id, capability.body, require_acceptance_id=True)
            # Wappi dry-run/no-token and missing acceptance identity are not delivery evidence.
            return provider_id if type(provider_id) is str and provider_id else None
        try:
            sent = await guard.send(adapter, msg.chat_id, callback, typed_capability=capability,
                dialogue_authority=authority_for(route))
            outcome = 'provider_accepted' if sent.invoked and sent.value else 'denied' if not sent.invoked else 'unknown'
        finally:
            await sessions.record_outcome(guard._engine(), route=route, capability=capability, outcome=outcome)
    except EntryStorageUnavailable:
        # The provider must not receive a successful intake ACK when the input
        # or an operational privacy hold could not be committed. A repeated
        # batch uses the same durable identities; no provider callback is retried.
        from fastapi import HTTPException
        raise HTTPException(status_code=503, detail='managed_dialogue_storage_unavailable') from None
    except Exception as exc:
        # Consume errors without legacy fallback, personal data or success claims.
        log.warning('managed dialogue unavailable or delivery unknown: %s', type(exc).__name__)
    return True
