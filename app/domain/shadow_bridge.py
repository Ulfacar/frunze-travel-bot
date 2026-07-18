"""WP1B shadow bridge: mirror a live inbound Conversation event into the new
domain entities, behind a default-OFF feature flag, as a best-effort, fail-safe
side effect.

Guarantees:

* Does NOTHING when ``domain_shadow_enabled`` is off (early return).
* Creates ONLY Contact → ContactIdentity → Dialog. It may LINK a Dialog to an
  already-active Request of the same contact+direction, but NEVER opens a new
  Request and NEVER creates an Assignment.
* Uses its OWN session/transaction, isolated from the live dialog.
* Catches ALL of its own errors — a shadow failure never propagates to the caller
  (the live dialog is unaffected).
* Logs failures WITHOUT PII: no phone number, name, or message text — only the
  operation, direction, and the exception class name.
* No backfill; does not read the domain back into the runtime; does not switch the
  source of truth.
"""
from __future__ import annotations

import logging

from app.config import settings
from app.core.flags import get_flag
from app.domain.models import DomainError
from app.domain.phones import normalize_phone
from app.domain.services import ContactService, DialogService

log = logging.getLogger("domain.shadow")

FLAG = "domain_shadow_enabled"


async def mirror_inbound(*, phone: str, channel: str, bot_id: str, direction: str,
                         sessionmaker=None) -> None:
    """Mirror one inbound touch into Contact/Identity/Dialog. Never raises."""
    if not await get_flag(FLAG, settings.domain_shadow_enabled):
        return

    # Normalize up front so an unusable identity is skipped cleanly (no PII logged).
    try:
        normalized = normalize_phone(phone)
    except DomainError:
        log.warning("shadow inbound skipped: unnormalizable identity "
                    "(op=normalize direction=%s)", direction or "")
        return

    try:
        sm = sessionmaker
        if sm is None:
            from app.integrations.crm.db import get_sessionmaker
            sm = get_sessionmaker()
        async with sm() as session:
            contact = await ContactService.find_or_create_by_identity(
                session, "phone", normalized)
            await DialogService.get_or_create(
                session, contact.id, channel=channel, bot_id=bot_id,
                channel_key=normalized,
                link_active_request_direction=direction or "")
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — fail-safe; never break the live dialog
        # PII-free: log only the operation, direction and error class (no phone/text).
        log.warning("shadow inbound mirror failed "
                    "(op=mirror_inbound direction=%s err=%s)",
                    direction or "", type(exc).__name__)
