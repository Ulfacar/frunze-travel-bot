"""Atomic projection into the existing CRM inbox; no mirror or assignment.

Caller owns the route and case locks and has checked current collection consent.
Privacy requests retain only an operational cause, never their raw body here.
"""
from sqlalchemy import select

from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _hash
from app.domain.entry_channel_policy import recipient
from app.integrations.crm.db import Conversation, ConvMessage


def omitted(reason):
    return dict(status='not_retained', reason=reason, message_id=None, body_hash=None)


def _identity(header):
    identity = header.document['channel_identity']
    return identity, identity['bot_id']+':'+recipient(identity['channel_key'])


def _check_conversation(conv, identity, key):
    try:
        valid = (conv is not None and conv.user_id == key and conv.channel == identity['channel'] and
            conv.bot_id == identity['bot_id'] and recipient(conv.chat_id) == recipient(identity['channel_key']) and
            (not conv.phone or recipient(conv.phone) == recipient(identity['channel_key'])))
    except EntryStorageInvalid:
        valid = False
    if not valid:
        raise EntryStorageConflict('dialogue_inbox_identity_changed')


async def save(session, header, *, message_key, text, provider_id, at):
    identity, key = _identity(header)
    conv = await session.scalar(select(Conversation).where(Conversation.user_id == key).with_for_update())
    if conv is None:
        conv = Conversation(user_id=key, channel=identity['channel'], bot_id=identity['bot_id'],
            chat_id=identity['channel_key'], phone=recipient(identity['channel_key']))
        session.add(conv)
        await session.flush()
    _check_conversation(conv, identity, key)
    idem = 'kg-dialogue-in-'+message_key
    existing = list((await session.scalars(select(ConvMessage).where(ConvMessage.idempotency_key == idem).limit(2))).all())
    # No late backfill or adoption of an orphan/foreign projection.
    if existing:
        raise EntryStorageConflict('dialogue_inbox_receipt_conflict')
    msg = ConvMessage(conversation_id=conv.id, sender='client', text=text, status='',
        # Exact full provider ID is already bound into message_key. The legacy
        # display column is narrower; leave it empty instead of truncating it.
        provider_msg_id=provider_id if len(provider_id) <= 128 else '',
        idempotency_key=idem, created_at=at)
    session.add(msg)
    conv.archived = False
    conv.last_text = text
    conv.last_sender = 'client'
    conv.last_message_at = at
    await session.flush()
    return dict(status='recorded', reason=None, message_id=msg.id, body_hash=_hash(text))


async def availability(session, header, turns):
    """Mutable display availability, never a condition for operational privacy.

The immutable receipt proves what was written at the time. Later inbox removal
or editing does not rewrite that receipt or impose a new raw retention policy.
"""
    selected = [r for r in turns if r.document['payload']['inbox']['status'] == 'recorded']
    if not selected:
        return dict(recorded=0, available=0, unavailable=0)
    identity, key = _identity(header)
    conv = await session.scalar(select(Conversation).where(Conversation.user_id == key))
    try: _check_conversation(conv, identity, key)
    except EntryStorageConflict:
        return dict(recorded=len(selected), available=0, unavailable=len(selected))
    ids = [r.document['payload']['inbox']['message_id'] for r in selected]
    messages = {m.id:m for m in (await session.scalars(select(ConvMessage).where(ConvMessage.id.in_(ids)))).all()}
    available = 0
    for row in selected:
        doc = row.document['payload']; receipt = doc['inbox']; msg = messages.get(receipt['message_id'])
        if (msg is not None and msg.conversation_id == conv.id and msg.sender == 'client' and
                msg.idempotency_key == 'kg-dialogue-in-'+doc['message_key'] and _hash(msg.text) == receipt['body_hash']):
            available += 1
    return dict(recorded=len(selected), available=available, unavailable=len(selected)-available)
