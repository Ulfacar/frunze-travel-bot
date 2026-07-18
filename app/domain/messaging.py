"""WP2 messaging service: record inbound/outbound into the unified history
(CanonicalMessage) and the inbox/outbox ledgers (InboxEvent / OutboxJob).

Deduplication is enforced at the DB level (partial unique indexes) and handled
here with the same SAVEPOINT + IntegrityError-retry pattern as WP1B: a replayed
webhook or resent job returns the existing row instead of creating a duplicate.

These services take an ``AsyncSession`` from the caller. They are NOT wired into
live delivery; the runtime still sends/receives via the existing channel path.
No Bitrix call is made here.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import CanonicalMessage, InboxEvent, OutboxJob


async def _get_or_insert_canonical(session: AsyncSession, *, dialog_id: int,
                                   contact_id: int, direction: str, sender_role: str,
                                   channel: str, body: str, provider_msg_id: str,
                                   dedup_key: str) -> CanonicalMessage:
    async def _find():
        return await session.scalar(select(CanonicalMessage).where(
            CanonicalMessage.dialog_id == dialog_id,
            CanonicalMessage.direction == direction,
            CanonicalMessage.dedup_key == dedup_key))

    if dedup_key:
        found = await _find()
        if found is not None:
            return found
    row = CanonicalMessage(
        dialog_id=dialog_id, contact_id=contact_id, direction=direction,
        sender_role=sender_role, channel=channel, body=body,
        provider_msg_id=provider_msg_id, dedup_key=dedup_key)
    if not dedup_key:
        session.add(row)
        await session.flush()
        return row
    try:
        async with session.begin_nested():          # SAVEPOINT
            session.add(row)
            await session.flush()
        return row
    except IntegrityError:
        found = await _find()
        if found is not None:
            return found
        raise


class MessageService:
    """Unified history + inbox/outbox recording (idempotent, DB-level dedup)."""

    @staticmethod
    async def record_inbound(session: AsyncSession, *, dialog_id: int, contact_id: int,
                             channel: str, body: str, provider: str = "",
                             provider_msg_id: str = "", external_event_id: str = "",
                             sender_role: str = "client") -> CanonicalMessage:
        dedup_key = external_event_id or provider_msg_id
        canonical = await _get_or_insert_canonical(
            session, dialog_id=dialog_id, contact_id=contact_id, direction="inbound",
            sender_role=sender_role, channel=channel, body=body,
            provider_msg_id=provider_msg_id, dedup_key=dedup_key)
        if external_event_id:
            await MessageService._get_or_insert_inbox(
                session, provider=provider or channel, external_event_id=external_event_id,
                channel=channel, dialog_id=dialog_id, canonical_message_id=canonical.id)
        return canonical

    @staticmethod
    async def record_outbound(session: AsyncSession, *, dialog_id: int, contact_id: int,
                              channel: str, body: str, idempotency_key: str = "",
                              provider_msg_id: str = "", sender_role: str = "bot",
                              status: str = "pending") -> CanonicalMessage:
        dedup_key = idempotency_key or provider_msg_id
        canonical = await _get_or_insert_canonical(
            session, dialog_id=dialog_id, contact_id=contact_id, direction="outbound",
            sender_role=sender_role, channel=channel, body=body,
            provider_msg_id=provider_msg_id, dedup_key=dedup_key)
        if idempotency_key:
            await MessageService._get_or_insert_outbox(
                session, dialog_id=dialog_id, canonical_message_id=canonical.id,
                channel=channel, idempotency_key=idempotency_key,
                provider_msg_id=provider_msg_id, status=status)
        return canonical

    @staticmethod
    async def history(session: AsyncSession, dialog_id: int) -> list[CanonicalMessage]:
        return list((await session.scalars(select(CanonicalMessage)
            .where(CanonicalMessage.dialog_id == dialog_id)
            .order_by(CanonicalMessage.occurred_at, CanonicalMessage.id))).all())

    # --- ledger upserts --------------------------------------------------------

    @staticmethod
    async def _get_or_insert_inbox(session: AsyncSession, *, provider: str,
                                   external_event_id: str, channel: str,
                                   dialog_id: int | None,
                                   canonical_message_id: int | None) -> InboxEvent:
        async def _find():
            return await session.scalar(select(InboxEvent).where(
                InboxEvent.provider == provider,
                InboxEvent.external_event_id == external_event_id))
        found = await _find()
        if found is not None:
            return found
        row = InboxEvent(provider=provider, external_event_id=external_event_id,
                         channel=channel, dialog_id=dialog_id,
                         canonical_message_id=canonical_message_id, status="processed")
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
            return row
        except IntegrityError:
            found = await _find()
            if found is not None:
                return found
            raise

    @staticmethod
    async def _get_or_insert_outbox(session: AsyncSession, *, dialog_id: int,
                                    canonical_message_id: int | None, channel: str,
                                    idempotency_key: str, provider_msg_id: str,
                                    status: str) -> OutboxJob:
        async def _find():
            return await session.scalar(select(OutboxJob).where(
                OutboxJob.idempotency_key == idempotency_key))
        found = await _find()
        if found is not None:
            return found
        row = OutboxJob(dialog_id=dialog_id, canonical_message_id=canonical_message_id,
                        channel=channel, idempotency_key=idempotency_key,
                        provider_msg_id=provider_msg_id, status=status)
        try:
            async with session.begin_nested():
                session.add(row)
                await session.flush()
            return row
        except IntegrityError:
            found = await _find()
            if found is not None:
                return found
            raise
