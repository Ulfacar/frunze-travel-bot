"""WP1A domain foundation — target entities defined ALONGSIDE the current
Conversation/DialogState/Deal, NOT wired into the runtime yet.

Design source: docs/architecture/TARGET_DESIGN_PHASE2.md (architecturally approved)
and docs/architecture/IMPLEMENTATION_READINESS_PHASE3A.md.

These models live on their own metadata (``DomainBase``) and are intentionally
NOT registered with the runtime schema init (`app.integrations.crm.db.init_models`),
so importing/deploying this package changes NO production table. The repository has
no Alembic/migration framework wired (schema today is `create_all` + `_ensure_columns`),
so actually creating these tables in a real database is deferred to a separate
migration-tooling decision (see WP1A report). Tests build the schema in an in-memory
SQLite database.

Nothing here changes message handling, Bitrix sync, follow-up, attribution, STT,
the fact-safety gate, or the current bot runtime. No existing table/field is renamed
or removed. There is no production backfill.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (Boolean, DateTime, ForeignKey, Index, Integer, String,
                        Text, UniqueConstraint, func, select, text)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class DomainBase(DeclarativeBase):
    """Separate metadata so WP1A tables never touch the runtime crm.db schema."""


class DomainError(ValueError):
    """Raised when a WP1A domain invariant would be violated (app-level guard)."""


DIRECTIONS: tuple[str, ...] = ("tours", "visa", "tickets")


def _uuid() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- entities ------------------------------------------------------------------

class Contact(DomainBase):
    """Internal identity anchor for a person. Independent of bot_id; holds NO bot
    mode, funnel stage, or assignment (those live in Dialog / Request / Assignment)."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    identities: Mapped[list["ContactIdentity"]] = relationship(
        back_populates="contact", cascade="all, delete-orphan")


class ContactIdentity(DomainBase):
    """A phone or other channel identity belonging to a Contact. Obvious duplicates
    of a normalized identity (same type + normalized value + provider scope) are
    rejected both by a unique constraint and by app-level validation."""

    __tablename__ = "contact_identities"
    __table_args__ = (
        UniqueConstraint("identity_type", "normalized_value", "provider_scope",
                         name="uq_contact_identity_normalized"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    identity_type: Mapped[str] = mapped_column(String(32))            # phone | telegram | whatsapp | …
    normalized_value: Mapped[str] = mapped_column(String(190), index=True)
    display_value: Mapped[str] = mapped_column(String(190), default="")
    provider_scope: Mapped[str] = mapped_column(String(64), default="")  # only where a channel/profile scope matters
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    source: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    contact: Mapped[Contact] = relationship(back_populates="identities")


class Request(DomainBase):
    """A commercial request in one direction. Business ``status`` is a SEPARATE axis
    from bot/dialog mode. Invariant: at most one active (``closed_at`` IS NULL)
    Request per (contact, direction); a repeat purchase opens a NEW Request rather
    than overwriting the old one, which stays in history."""

    __tablename__ = "requests"
    __table_args__ = (
        Index("uq_active_request_per_contact_direction", "contact_id", "direction",
              unique=True,
              sqlite_where=text("closed_at IS NULL"),
              postgresql_where=text("closed_at IS NULL")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(32), unique=True, default=_uuid)  # immutable external-facing id
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    direction: Mapped[str] = mapped_column(String(16))               # tours | visa | tickets
    status: Mapped[str] = mapped_column(String(32), default="new")   # business status (not bot mode)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Dialog(DomainBase):
    """A concrete communication-channel thread for a Contact. Holds channel/bot
    identifiers separately from Contact. It is NOT a lead/deal/request and carries
    NO business status. A Contact may have several Dialogs across channels."""

    __tablename__ = "dialogs"
    __table_args__ = (
        # DB-level idempotency for the shadow bridge: at most one Dialog per
        # (channel, bot_id, channel_key). Added in migration wp1b_dialog_uidx_0002.
        Index("uq_dialog_channel_bot_key", "channel", "bot_id", "channel_key",
              unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(32))                 # whatsapp | telegram | bitrix_openlines
    bot_id: Mapped[str] = mapped_column(String(64), default="")
    channel_key: Mapped[str] = mapped_column(String(128), default="")  # chat id / profile-scoped key
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Assignment(DomainBase):
    """Pins a manager to a Contact+direction with a revision and full history.
    Invariant: at most one active Assignment per (contact, direction). History rows
    are never deleted or overwritten. Peer takeover is forbidden at the (future)
    service layer; only an emergency (full-admin) reassignment may replace a
    different active owner."""

    __tablename__ = "assignments"
    __table_args__ = (
        Index("uq_active_assignment_per_contact_direction", "contact_id", "direction",
              unique=True,
              sqlite_where=text("active = 1"),
              postgresql_where=text("active")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    manager_id: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer, default=1)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_by: Mapped[str] = mapped_column(String(64), default="")
    reason: Mapped[str] = mapped_column(String(255), default="")


class ExternalReference(DomainBase):
    """Stable mapping from a Request to an external Bitrix Lead/Deal WITHOUT making
    Bitrix the owner of the Contact. Invariant: one external Deal maps to at most one
    Request (unique active mapping). Replaced references are kept as history."""

    __tablename__ = "external_references"
    __table_args__ = (
        Index("uq_active_external_reference", "provider", "external_type", "external_id",
              unique=True,
              sqlite_where=text("active = 1"),
              postgresql_where=text("active")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))               # bitrix
    external_type: Mapped[str] = mapped_column(String(32))          # lead | deal
    external_id: Mapped[str] = mapped_column(String(64))
    request_ref: Mapped[int] = mapped_column(ForeignKey("requests.id"), index=True)
    direction: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# --- WP2 messaging foundation (unified history + inbox/outbox ledgers) ---------
# All three live on DomainBase and are NOT wired into live delivery. They are
# mirrored, under the `messaging_shadow_enabled` flag (default OFF), from the
# existing runtime; they do NOT replace ConvMessage / own_outbound and do NOT
# touch the Bitrix mirror. Dedup is enforced at the DB level (partial unique).

class CanonicalMessage(DomainBase):
    """One channel-agnostic entry in a Dialog's unified message history. Deduplicated
    per (dialog, direction, dedup_key) so a replayed webhook / resent job does not
    create a second timeline row."""

    __tablename__ = "canonical_messages"
    __table_args__ = (
        Index("uq_canonical_message_dedup", "dialog_id", "direction", "dedup_key",
              unique=True,
              sqlite_where=text("dedup_key <> ''"),
              postgresql_where=text("dedup_key <> ''")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id"), index=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    direction: Mapped[str] = mapped_column(String(16))               # inbound | outbound
    sender_role: Mapped[str] = mapped_column(String(16))             # client | bot | manager
    channel: Mapped[str] = mapped_column(String(32), default="")
    body: Mapped[str] = mapped_column(Text, default="")             # content (never logged)
    provider_msg_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    dedup_key: Mapped[str] = mapped_column(String(190), default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class InboxEvent(DomainBase):
    """Ledger of INCOMING provider events. DB-level dedup is scoped to
    (provider, account_scope, external_event_id) so the SAME external id under two
    different bot/provider accounts does NOT collide (e.g. Telegram message ids
    repeat across bots). NOT yet in the live path."""

    __tablename__ = "inbox_events"
    __table_args__ = (
        Index("uq_inbox_event_dedup", "provider", "account_scope", "external_event_id",
              unique=True,
              sqlite_where=text("external_event_id <> ''"),
              postgresql_where=text("external_event_id <> ''")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(32))                # wappi | telegram | bitrix | …
    # account_scope pins the receiving bot/provider account (bot_id), so ids are
    # unique only WITHIN one account, never across accounts.
    account_scope: Mapped[str] = mapped_column(String(190), default="")
    external_event_id: Mapped[str] = mapped_column(String(190), default="")
    channel: Mapped[str] = mapped_column(String(32), default="")
    dialog_id: Mapped[int | None] = mapped_column(ForeignKey("dialogs.id"), nullable=True, index=True)
    canonical_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_messages.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="received")  # received|processed|skipped
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OutboxJob(DomainBase):
    """Ledger of OUTGOING send intents. DB-level dedup is scoped to
    (provider, account_scope, destination_scope, idempotency_key) so the same
    idempotency/action key never collides across providers, sending accounts or
    recipients. NOT wired into live delivery — the runtime still sends via the
    existing channel/own_outbound path; this only records a shadow copy."""

    __tablename__ = "outbox_jobs"
    __table_args__ = (
        Index("uq_outbox_job_idem", "provider", "account_scope", "destination_scope",
              "idempotency_key",
              unique=True,
              sqlite_where=text("idempotency_key <> ''"),
              postgresql_where=text("idempotency_key <> ''")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dialog_id: Mapped[int] = mapped_column(ForeignKey("dialogs.id"), index=True)
    canonical_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("canonical_messages.id"), nullable=True)
    channel: Mapped[str] = mapped_column(String(32), default="")
    # Scope of the idempotency key: provider (wappi/telegram/…), sending account
    # (bot_id) and destination (recipient). Keys are unique only within this scope.
    provider: Mapped[str] = mapped_column(String(32), default="")
    account_scope: Mapped[str] = mapped_column(String(190), default="")
    destination_scope: Mapped[str] = mapped_column(String(190), default="")
    idempotency_key: Mapped[str] = mapped_column(String(190), default="")
    provider_msg_id: Mapped[str] = mapped_column(String(128), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")   # pending|sent|delivered|failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# --- application-level invariants (foundation helpers, not a service/API) -------
# These encode the invariants with clear errors, in addition to the DB constraints.
# They are NOT wired into the runtime; the future WP1B service layer will build on
# them. No UI/API for assignment is provided here.

async def add_identity(session: AsyncSession, contact_id: int, identity_type: str,
                       normalized_value: str, *, display_value: str = "",
                       provider_scope: str = "", verified: bool = False,
                       source: str = "") -> ContactIdentity:
    existing = await session.scalar(select(ContactIdentity).where(
        ContactIdentity.identity_type == identity_type,
        ContactIdentity.normalized_value == normalized_value,
        ContactIdentity.provider_scope == provider_scope,
    ))
    if existing is not None:
        raise DomainError(
            f"duplicate identity {identity_type}:{normalized_value} (scope={provider_scope!r})")
    identity = ContactIdentity(
        contact_id=contact_id, identity_type=identity_type,
        normalized_value=normalized_value, display_value=display_value,
        provider_scope=provider_scope, verified=verified, source=source)
    session.add(identity)
    await session.flush()
    return identity


async def open_request(session: AsyncSession, contact_id: int, direction: str) -> Request:
    if direction not in DIRECTIONS:
        raise DomainError(f"unknown direction {direction!r}")
    active = await session.scalar(select(Request).where(
        Request.contact_id == contact_id, Request.direction == direction,
        Request.closed_at.is_(None)))
    if active is not None:
        raise DomainError(
            f"an active {direction} request already exists for contact {contact_id}")
    request = Request(contact_id=contact_id, direction=direction)
    session.add(request)
    await session.flush()
    return request


async def close_request(session: AsyncSession, request: Request, *, status: str = "closed") -> Request:
    request.status = status
    request.closed_at = _now()
    await session.flush()
    return request


async def reassign_manager(session: AsyncSession, contact_id: int, direction: str,
                           manager_id: str, *, assigned_by: str, reason: str = "",
                           allow_emergency: bool = False) -> Assignment:
    """Deactivate the current active assignment (if any), bump revision, create a new
    active one. Replacing a DIFFERENT active owner requires ``allow_emergency`` (the
    future service grants it only to a full-admin). A first assignment or re-affirming
    the same manager needs no emergency flag."""
    current = await session.scalar(select(Assignment).where(
        Assignment.contact_id == contact_id, Assignment.direction == direction,
        Assignment.active.is_(True)))
    if current is not None and current.manager_id != manager_id and not allow_emergency:
        raise DomainError(
            "cannot take over an owned contact without emergency (full-admin) authorization")
    next_revision = 1
    if current is not None:
        current.active = False
        current.ended_at = _now()
        next_revision = current.revision + 1
        # Flush the deactivation UPDATE BEFORE inserting the new active row, so the
        # partial unique index (one active assignment per contact+direction) never
        # sees two active rows within a single flush. Without this explicit flush the
        # ordering relies on SQLAlchemy's unit-of-work heuristic (which currently
        # emits UPDATE before INSERT) — an implementation detail we must not depend on
        # across backends/versions, especially under immediate constraint checking.
        await session.flush()
    assignment = Assignment(
        contact_id=contact_id, direction=direction, manager_id=manager_id,
        revision=next_revision, active=True, assigned_by=assigned_by, reason=reason)
    session.add(assignment)
    await session.flush()
    return assignment


async def link_external(session: AsyncSession, provider: str, external_type: str,
                        external_id: str, request: Request, direction: str) -> ExternalReference:
    existing = await session.scalar(select(ExternalReference).where(
        ExternalReference.provider == provider,
        ExternalReference.external_type == external_type,
        ExternalReference.external_id == external_id,
        ExternalReference.active.is_(True)))
    if existing is not None and existing.request_ref != request.id:
        raise DomainError(
            f"external {provider}:{external_type}:{external_id} is already linked to another request")
    if existing is not None:
        return existing
    reference = ExternalReference(
        provider=provider, external_type=external_type, external_id=external_id,
        request_ref=request.id, direction=direction, active=True)
    session.add(reference)
    await session.flush()
    return reference
