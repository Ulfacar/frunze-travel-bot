"""WP1B domain service layer.

Transactional, invariant-preserving wrappers around ``app.domain.models``. These
services own find-or-create semantics, phone normalization and race handling; the
underlying model helpers already encode the business invariants (one active
Request / Assignment per contact+direction, assignment history, external-ref
uniqueness) and their explicit flushes.

The services take an ``AsyncSession`` from the caller, so several operations can
share one unit of work / transaction. They are NOT wired into the live runtime
except through the flag-gated, fail-safe shadow bridge (``shadow_bridge.py``).

Race handling: creates run inside a SAVEPOINT (``session.begin_nested()``). If a
concurrent transaction inserts the same unique row first, the IntegrityError rolls
the SAVEPOINT back (leaving the outer session usable) and we re-read the winner.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    Assignment, Contact, ContactIdentity, Dialog, DomainError, ExternalReference,
    Request,
)
from app.domain.models import (
    close_request as _close_request,
    link_external as _link_external,
    open_request as _open_request,
    reassign_manager as _reassign_manager,
)
from app.domain.phones import normalize_phone


class ContactService:
    """Contact + ContactIdentity find-or-create with normalization and race safety."""

    @staticmethod
    async def _find(session: AsyncSession, identity_type: str, normalized: str,
                    provider_scope: str) -> Contact | None:
        ident = await session.scalar(select(ContactIdentity).where(
            ContactIdentity.identity_type == identity_type,
            ContactIdentity.normalized_value == normalized,
            ContactIdentity.provider_scope == provider_scope))
        if ident is None:
            return None
        return await session.get(Contact, ident.contact_id)

    @staticmethod
    async def find_or_create_by_identity(session: AsyncSession, identity_type: str,
                                         raw_value: str, *,
                                         provider_scope: str = "") -> Contact:
        """Return the Contact owning this identity, creating Contact+Identity if new.

        Phone identities are normalized and always use ``provider_scope=""`` so one
        person is a single Contact across every bot/profile.
        """
        normalized = (normalize_phone(raw_value) if identity_type == "phone"
                      else (raw_value or "").strip())
        if not normalized:
            raise DomainError("empty identity value")

        found = await ContactService._find(session, identity_type, normalized, provider_scope)
        if found is not None:
            return found
        try:
            async with session.begin_nested():          # SAVEPOINT
                contact = Contact()
                session.add(contact)
                await session.flush()
                session.add(ContactIdentity(
                    contact_id=contact.id, identity_type=identity_type,
                    normalized_value=normalized, provider_scope=provider_scope))
                await session.flush()
            return contact
        except IntegrityError:
            # Lost the race: SAVEPOINT rolled back (no orphan Contact), session still
            # usable. Re-read the row the concurrent writer created.
            found = await ContactService._find(session, identity_type, normalized, provider_scope)
            if found is not None:
                return found
            raise


class RequestService:
    """Commercial Request lifecycle (open/close) — one active per contact+direction."""

    @staticmethod
    async def active_for(session: AsyncSession, contact_id: int,
                         direction: str) -> Request | None:
        return await session.scalar(select(Request).where(
            Request.contact_id == contact_id, Request.direction == direction,
            Request.closed_at.is_(None)))

    @staticmethod
    async def open(session: AsyncSession, contact_id: int, direction: str) -> Request:
        return await _open_request(session, contact_id, direction)

    @staticmethod
    async def close(session: AsyncSession, request: Request, *,
                    status: str = "closed") -> Request:
        return await _close_request(session, request, status=status)


class DialogService:
    """Channel-thread Dialog get-or-create, idempotent on (channel, bot_id, channel_key).

    May LINK a Dialog to an already-active Request of the same contact+direction, but
    NEVER opens a new Request (that is a commercial action, out of the bridge's scope).
    """

    @staticmethod
    async def _find(session: AsyncSession, channel: str, bot_id: str,
                    channel_key: str) -> Dialog | None:
        return await session.scalar(select(Dialog).where(
            Dialog.channel == channel, Dialog.bot_id == bot_id,
            Dialog.channel_key == channel_key))

    @staticmethod
    async def get_or_create(session: AsyncSession, contact_id: int, *, channel: str,
                            bot_id: str, channel_key: str,
                            link_active_request_direction: str = "") -> Dialog:
        dialog = await DialogService._find(session, channel, bot_id, channel_key)
        if dialog is None:
            try:
                async with session.begin_nested():      # SAVEPOINT
                    dialog = Dialog(contact_id=contact_id, channel=channel,
                                    bot_id=bot_id, channel_key=channel_key)
                    session.add(dialog)
                    await session.flush()
            except IntegrityError:
                dialog = await DialogService._find(session, channel, bot_id, channel_key)
                if dialog is None:
                    raise

        # Optionally attach to an EXISTING active Request; never create one.
        if link_active_request_direction and dialog.request_id is None:
            active = await RequestService.active_for(
                session, dialog.contact_id, link_active_request_direction)
            if active is not None:
                dialog.request_id = active.id
                await session.flush()
        return dialog


class AssignmentService:
    """Manager assignment with peer-takeover protection and full history.

    Delegates to the model helper (revision bump, history, explicit flush ordering).
    NOTE: this only performs a requested assignment; automatic round-robin routing
    and concurrency-safe (PostgreSQL-lock) assignment are WP3, not WP1B.
    """

    @staticmethod
    async def active_for(session: AsyncSession, contact_id: int,
                         direction: str) -> Assignment | None:
        return await session.scalar(select(Assignment).where(
            Assignment.contact_id == contact_id, Assignment.direction == direction,
            Assignment.active.is_(True)))

    @staticmethod
    async def assign(session: AsyncSession, contact_id: int, direction: str,
                     manager_id: str, *, assigned_by: str, reason: str = "",
                     allow_emergency: bool = False) -> Assignment:
        return await _reassign_manager(
            session, contact_id, direction, manager_id,
            assigned_by=assigned_by, reason=reason, allow_emergency=allow_emergency)


class ExternalRefService:
    """Stable Request → external Bitrix Lead/Deal mapping (unique active mapping)."""

    @staticmethod
    async def link(session: AsyncSession, provider: str, external_type: str,
                   external_id: str, request: Request, direction: str) -> ExternalReference:
        return await _link_external(session, provider, external_type, external_id,
                                    request, direction)
