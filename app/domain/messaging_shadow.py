"""WP2 messaging shadow bridge: mirror live inbound/outbound touches into the
CanonicalMessage / InboxEvent / OutboxJob ledgers.

Gated by BOTH flags (M6): it runs only when
``domain_shadow_enabled AND messaging_shadow_enabled`` are both on. This keeps the
contact/dialog shadow (WP1B) as the prerequisite layer, so a message row is never
written without its Contact/Dialog.

Same guarantees as WP1B: records ONLY into the domain ledgers (no send/receive, no
source-of-truth switch, no Bitrix); own session/transaction; awaited but
self-contained (swallows its own errors); logs WITHOUT PII (op + error class only).

Scoping (M1/M2): ``account_scope`` = the bot/provider account (``bot_id``),
``provider`` = the channel, ``destination_scope`` = the recipient identity.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.core.flags import get_flag
from app.domain.messaging import MessageService
from app.domain.models import DomainError
from app.domain.phones import normalize_phone
from app.domain.services import ContactService, DialogService

log = logging.getLogger("domain.messaging_shadow")

FLAG = "messaging_shadow_enabled"
DOMAIN_FLAG = "domain_shadow_enabled"


async def _both_flags_on() -> bool:
    """Messaging shadow requires BOTH the contact/dialog shadow AND the messaging
    shadow flags — so a CanonicalMessage is never written without its Contact/Dialog."""
    if not await get_flag(DOMAIN_FLAG, settings.domain_shadow_enabled):
        return False
    return await get_flag(FLAG, settings.messaging_shadow_enabled)


async def _resolve_dialog(session, *, normalized: str, channel: str, bot_id: str,
                          direction: str):
    contact = await ContactService.find_or_create_by_identity(session, "phone", normalized)
    dialog = await DialogService.get_or_create(
        session, contact.id, channel=channel, bot_id=bot_id, channel_key=normalized,
        link_active_request_direction=direction or "")
    return contact, dialog


async def mirror_inbound_message(*, phone: str, channel: str, bot_id: str, direction: str,
                                 body: str, provider_msg_id: str = "",
                                 external_event_id: str = "", sessionmaker=None) -> None:
    """Record one inbound message into the domain ledgers. Never raises."""
    if not await _both_flags_on():
        return
    try:
        normalized = normalize_phone(phone)
    except DomainError:
        log.warning("messaging shadow inbound skipped: unnormalizable identity "
                    "(op=normalize direction=%s)", direction or "")
        return
    try:
        sm = sessionmaker
        if sm is None:
            from app.integrations.crm.db import get_sessionmaker
            sm = get_sessionmaker()
        async with sm() as session:
            contact, dialog = await _resolve_dialog(
                session, normalized=normalized, channel=channel, bot_id=bot_id,
                direction=direction)
            await MessageService.record_inbound(
                session, dialog_id=dialog.id, contact_id=contact.id, channel=channel,
                body=body, provider=channel, account_scope=bot_id,
                provider_msg_id=provider_msg_id, external_event_id=external_event_id,
                sender_role="client")
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — fail-safe; never break the live dialog
        log.warning("messaging shadow inbound failed "
                    "(op=mirror_inbound direction=%s err=%s)",
                    direction or "", type(exc).__name__)


async def mirror_outbound_message(*, phone: str, channel: str, bot_id: str, direction: str,
                                  body: str, idempotency_key: str = "",
                                  provider_msg_id: str = "", sender_role: str = "bot",
                                  status: str = "sent", sessionmaker=None) -> None:
    """Record one outbound message into the domain ledgers. Never raises."""
    if not await _both_flags_on():
        return
    try:
        normalized = normalize_phone(phone)
    except DomainError:
        log.warning("messaging shadow outbound skipped: unnormalizable identity "
                    "(op=normalize direction=%s)", direction or "")
        return
    try:
        sm = sessionmaker
        if sm is None:
            from app.integrations.crm.db import get_sessionmaker
            sm = get_sessionmaker()
        async with sm() as session:
            contact, dialog = await _resolve_dialog(
                session, normalized=normalized, channel=channel, bot_id=bot_id,
                direction=direction)
            await MessageService.record_outbound(
                session, dialog_id=dialog.id, contact_id=contact.id, channel=channel,
                body=body, provider=channel, account_scope=bot_id,
                destination_scope=normalized, idempotency_key=idempotency_key,
                provider_msg_id=provider_msg_id, sender_role=sender_role, status=status)
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — fail-safe; never break the live dialog
        log.warning("messaging shadow outbound failed "
                    "(op=mirror_outbound direction=%s err=%s)",
                    direction or "", type(exc).__name__)
