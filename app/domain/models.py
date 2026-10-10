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
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, ForeignKey,
                        ForeignKeyConstraint, Index, Integer, String, Text,
                        Numeric, LargeBinary, UniqueConstraint, event, func, inspect, select, text, true,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship, validates
from sqlalchemy.types import TypeDecorator


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


# --- Sprint 1: calendar tasks (manager calendar + client-card tasks) ----------
# Manager-owned tasks (calls/meetings/office visits) linked to a domain Contact and
# optionally a Request/Assignment. Ownership is per manager_id (login). Times use the
# repo's Bishkek convention (UTC+6): scheduled_date is the Bishkek day; scheduled_at
# is an exact UTC instant, NULL = "без точного времени". Only ai_summary may be
# AI-written; client/date/time/owner come solely from the DB.

# Виды задач. `checkin`, `departure`, `review_request` и `complaint` заводят
# операции по билетам и турам (E2-01, E2-02): без них задача попадала в
# календарь без подписи, сырым кодом, и менеджер не понимал, что это.
TASK_KINDS: tuple[str, ...] = ("call", "meeting", "office_visit", "followup",
                              "checkin", "departure", "review_request",
                              "complaint", "other")
TASK_STATUSES: tuple[str, ...] = ("planned", "rescheduled", "completed", "cancelled")
ACTIVE_TASK_STATUSES: tuple[str, ...] = ("planned", "rescheduled")
TASK_PRIORITIES: tuple[str, ...] = ("low", "normal", "high")


class CalendarTask(DomainBase):
    """One manager task tied to a Contact (+ optional Request/Assignment)."""

    __tablename__ = "calendar_tasks"
    __table_args__ = (
        Index("ix_calendar_tasks_manager_date", "manager_id", "scheduled_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"), index=True)
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), nullable=True)
    assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("assignments.id"), nullable=True)   # populated once WP3 is wired
    manager_id: Mapped[str] = mapped_column(String(64), index=True)   # owner login (lowercased)
    direction: Mapped[str] = mapped_column(String(16))               # visa | tours | tickets
    user_id: Mapped[str] = mapped_column(String(160), default="", index=True)  # live bot_id:phone
    kind: Mapped[str] = mapped_column(String(24))                    # call | meeting | office_visit | …
    priority: Mapped[str] = mapped_column(String(8), default="normal")
    status: Mapped[str] = mapped_column(String(16), default="planned")
    comment: Mapped[str] = mapped_column(Text, default="")
    ai_summary: Mapped[str] = mapped_column(Text, default="")        # ONLY AI-writable field
    scheduled_date: Mapped[date] = mapped_column(Date)               # Bishkek calendar day
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)                     # exact instant; NULL = no time
    created_by: Mapped[str] = mapped_column(String(64), default="")
    # Услуга и сегмент, к которым относится задача. Без них нельзя пересчитать
    # напоминание при переносе рейса: непонятно, какую именно задачу отменять
    # (AC-08). Это же закрывает долг E1-03 — раньше связь шла только через контакт.
    service_case_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_cases.id"), nullable=True, index=True)
    ticket_segment_id: Mapped[int | None] = mapped_column(
        ForeignKey("ticket_segments.id"), nullable=True, index=True)
    # Захват задачи в обработку (E2-04, AC-28). Исполнитель помечает, что взял
    # задачу; если процесс упал между захватом и результатом, незавершённый захват
    # ВИДЕН — и перед повтором его сверяют, а не отправляют слепо второй раз.
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    claimed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class CalendarTaskEvent(DomainBase):
    """Authoritative history of a task's lifecycle actions (audit trail)."""

    __tablename__ = "calendar_task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("calendar_tasks.id"), index=True)
    event: Mapped[str] = mapped_column(String(24))   # created|rescheduled|completed|cancelled|reassigned
    actor: Mapped[str] = mapped_column(String(64), default="")
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    from_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    to_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


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


class _ServiceJSONList(list):
    # Вложенное изменение JSON иначе проходит мимо ORM и защиты опубликованной версии.
    def _immutable(self, *args, **kwargs):
        raise DomainError("service JSON is immutable; replace the draft value instead")

    __setitem__ = __delitem__ = __iadd__ = __imul__ = _immutable
    append = extend = insert = pop = remove = clear = reverse = sort = _immutable


class _ServiceJSONDict(dict):
    def _immutable(self, *args, **kwargs):
        raise DomainError("service JSON is immutable; replace the draft value instead")

    __setitem__ = __delitem__ = __ior__ = _immutable
    clear = pop = popitem = setdefault = update = _immutable


class _ServiceJSON(TypeDecorator):
    """Копия без изменяемых вложенных ссылок защищает также JSON после загрузки из БД."""

    impl = JSON
    cache_ok = True

    @classmethod
    def freeze(cls, value):
        if isinstance(value, dict):
            return _ServiceJSONDict({key: cls.freeze(item) for key, item in value.items()})
        if isinstance(value, list):
            return _ServiceJSONList(cls.freeze(item) for item in value)
        return value

    def process_result_value(self, value, dialect):
        return self.freeze(value)


class KnowledgeSet(DomainBase):
    """E5: набор правил; импорт никогда не меняет active_version_id."""

    __tablename__ = "knowledge_sets"
    __table_args__ = (
        ForeignKeyConstraint(["active_version_id", "id"],
                             ["knowledge_versions.id", "knowledge_versions.set_id"],
                             name="fk_knowledge_active_version"),
        CheckConstraint("review_period_days IS NULL OR review_period_days > 0",
                        name="ck_knowledge_review_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    jurisdiction: Mapped[str] = mapped_column(String(2))
    domain: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(Text)
    # DEC-07 не решён: неизвестный срок нельзя подменить предложенными 30 днями.
    review_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class KnowledgeVersion(DomainBase):
    __tablename__ = "knowledge_versions"
    __table_args__ = (
        UniqueConstraint("set_id", "version", name="uq_knowledge_version_number"),
        UniqueConstraint("set_id", "bundle_hash", name="uq_knowledge_version_bundle"),
        UniqueConstraint("id", "set_id", name="uq_knowledge_version_set"),
        CheckConstraint("version >= 1", name="ck_knowledge_version_positive"),
        CheckConstraint("status IN ('draft','review','approved','active','retired','rejected')",
                        name="ck_knowledge_version_status"),
        CheckConstraint("length(source_hash) = 64 AND length(bundle_hash) = 64",
                        name="ck_knowledge_version_hashes"),
        Index("uq_knowledge_active", "set_id", unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Встречный FK, как WorkflowVersion.product_id: ORM проверяет существование набора.
    set_id: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="draft")
    source_document: Mapped[str] = mapped_column(Text)
    source_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 исходного PDF
    bundle_hash: Mapped[str] = mapped_column(String(64))  # SHA-256 normalized bundle
    source_prepared_by: Mapped[str] = mapped_column(Text)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Полный мета-контракт и алиасы нужны для воспроизводимости хеша; это не права стран.
    bundle_meta: Mapped[dict] = mapped_column(_ServiceJSON)
    country_aliases: Mapped[dict] = mapped_column(_ServiceJSON)
    import_report: Mapped[dict] = mapped_column(_ServiceJSON)

    @validates("bundle_meta", "country_aliases", "import_report")
    def _freeze_json(self, key, value):
        return _ServiceJSON.freeze(value)


class KnowledgeUnit(DomainBase):
    __tablename__ = "knowledge_units"
    __table_args__ = (
        UniqueConstraint("version_id", "unit_id", name="uq_knowledge_unit"),
        CheckConstraint("kind IN ('visa_free_regime','registration_exemption','registration_default',"
                        "'registration_term','special_regime','visa_required_regime','rule_param',"
                        "'deadline','processing_time','tariff','template','escalation_trigger')",
                        name="ck_knowledge_unit_kind"),
        CheckConstraint("label IN ('none','verify','practice','decision')", name="ck_knowledge_unit_label"),
        CheckConstraint("confirmation_status IN ('confirmed','needs_verification','blocked','decision_pending')",
                        name="ck_knowledge_unit_confirmation"),
        CheckConstraint("confirmation_status NOT IN ('blocked','decision_pending') OR "
                        "(value IS NULL AND blocked_value IS NOT NULL)", name="ck_knowledge_unit_pending"),
        CheckConstraint("confirmation_status != 'blocked' OR conflict_ref IS NOT NULL",
                        name="ck_knowledge_unit_conflict"),
        CheckConstraint("effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
                        name="ck_knowledge_unit_dates"),
        CheckConstraint("(verified_at IS NULL AND verified_by IS NULL) OR "
                        "(verified_at IS NOT NULL AND verified_by IS NOT NULL)", name="ck_knowledge_unit_verifier"),
        CheckConstraint("value_schema_version = 1", name="ck_knowledge_unit_schema"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_versions.id"))
    unit_id: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    section: Mapped[str] = mapped_column(Text)
    page: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(Text)
    source_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    label: Mapped[str] = mapped_column(String(16))
    confirmation_status: Mapped[str] = mapped_column(String(32))
    # none_as_null обязателен: JSON null не удовлетворяет SQL CHECK value IS NULL.
    value: Mapped[dict | None] = mapped_column(_ServiceJSON(none_as_null=True), nullable=True)
    value_schema_version: Mapped[int] = mapped_column(Integer)
    blocked_value: Mapped[dict | None] = mapped_column(_ServiceJSON(none_as_null=True), nullable=True)
    conflict_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verified_by: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    # Исходная оболочка сохраняет отсутствие необязательных полей vs явный null.
    source_record: Mapped[dict] = mapped_column(_ServiceJSON)

    @validates("value", "blocked_value", "source_record")
    def _freeze_json(self, key, value):
        return _ServiceJSON.freeze(value)


class KnowledgeImport(DomainBase):
    __tablename__ = "knowledge_imports"
    __table_args__ = (
        ForeignKeyConstraint(["version_id", "set_id"],
                             ["knowledge_versions.id", "knowledge_versions.set_id"],
                             name="fk_knowledge_import_version"),
        CheckConstraint("(result = 'accepted' AND version_id IS NOT NULL AND error_stage IS NULL) OR "
                        "(result = 'rejected' AND version_id IS NULL AND error_stage IS NOT NULL)",
                        name="ck_knowledge_import_result"),
        CheckConstraint("error_stage IS NULL OR error_stage IN ('syntax','schema','semantic','db')",
                        name="ck_knowledge_import_stage"),
        CheckConstraint("finished_at >= started_at", name="ck_knowledge_import_dates"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("knowledge_sets.id"))
    bundle_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    filename: Mapped[str] = mapped_column(Text)
    started_by: Mapped[str] = mapped_column(String(64))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    result: Mapped[str] = mapped_column(String(16))
    version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_stage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    error_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    report: Mapped[dict] = mapped_column(_ServiceJSON)

    @validates("report")
    def _freeze_json(self, key, value):
        return _ServiceJSON.freeze(value)


class KnowledgeProjection(DomainBase):
    """Sealed review materialization; no customer facts or eligibility decisions."""

    __tablename__ = "knowledge_projections"
    __table_args__ = (
        CheckConstraint("format_version = 1", name="ck_knowledge_projection_format"),
        CheckConstraint("length(projection_hash) = 64 AND (catalog_hash IS NULL OR length(catalog_hash) = 64)",
                        name="ck_knowledge_projection_hash"),
        CheckConstraint("(catalog_hash IS NULL AND condition_catalog IS NULL) OR "
                        "(catalog_hash IS NOT NULL AND condition_catalog IS NOT NULL)",
                        name="ck_knowledge_projection_catalog"),
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_versions.id"), primary_key=True)
    format_version: Mapped[int] = mapped_column(Integer)
    projection_hash: Mapped[str] = mapped_column(String(64))
    catalog_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    country_summary: Mapped[dict] = mapped_column(_ServiceJSON)
    condition_catalog: Mapped[dict | None] = mapped_column(_ServiceJSON(none_as_null=True), nullable=True)

    @validates("country_summary", "condition_catalog")
    def _freeze_json(self, key, value):
        return _ServiceJSON.freeze(value)


class KnowledgeCountryLink(DomainBase):
    __tablename__ = "knowledge_country_links"
    __table_args__ = (
        ForeignKeyConstraint(["version_id", "unit_id"], ["knowledge_units.version_id", "knowledge_units.unit_id"],
                             name="fk_knowledge_country_unit"),
        CheckConstraint("length(country_iso3) = 3", name="ck_knowledge_country_iso3"),
        CheckConstraint("association IN ('value_country','unit_id_country','evidence_country','explicit_not_in_list')",
                        name="ck_knowledge_country_association"),
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_projections.version_id"), primary_key=True)
    country_iso3: Mapped[str] = mapped_column(String(3), primary_key=True)
    unit_id: Mapped[str] = mapped_column(Text, primary_key=True)
    association: Mapped[str] = mapped_column(String(32))


class KnowledgeConditionLink(DomainBase):
    __tablename__ = "knowledge_condition_links"
    __table_args__ = (
        ForeignKeyConstraint(["version_id", "unit_id"], ["knowledge_units.version_id", "knowledge_units.unit_id"],
                             name="fk_knowledge_condition_unit"),
    )
    version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_projections.version_id"), primary_key=True)
    unit_id: Mapped[str] = mapped_column(Text, primary_key=True)


def _knowledge_immutable(mapper, connection, target):
    raise DomainError("knowledge snapshots and import journal are immutable; import a new bundle")


for _knowledge_cls in (KnowledgeVersion, KnowledgeUnit, KnowledgeImport,
                       KnowledgeProjection, KnowledgeCountryLink, KnowledgeConditionLink):
    event.listen(_knowledge_cls, "before_update", _knowledge_immutable)
    event.listen(_knowledge_cls, "before_delete", _knowledge_immutable)
event.listen(KnowledgeSet, "before_delete", _knowledge_immutable)
event.listen(KnowledgeSet, "before_update", _knowledge_immutable)


@event.listens_for(KnowledgeVersion, "before_insert")
def _knowledge_version_insert(mapper, connection, target):
    if target.status not in (None, "draft"):
        raise DomainError("only draft import is implemented")
    if connection.scalar(select(KnowledgeSet.id).where(KnowledgeSet.id == target.set_id)) is None:
        raise DomainError("unknown knowledge set")


@event.listens_for(KnowledgeUnit, "before_insert")
@event.listens_for(KnowledgeProjection, "before_insert")
@event.listens_for(KnowledgeCountryLink, "before_insert")
@event.listens_for(KnowledgeConditionLink, "before_insert")
def _knowledge_unit_insert(mapper, connection, target):
    status = connection.scalar(select(KnowledgeVersion.status).where(KnowledgeVersion.id == target.version_id))
    if status != "draft":
        raise DomainError("units may only be inserted into a draft")
    sealed = connection.scalar(select(KnowledgeImport.id).where(
        KnowledgeImport.version_id == target.version_id, KnowledgeImport.result == "accepted").limit(1))
    if sealed is not None:
        raise DomainError("an imported snapshot is sealed; import a new bundle")


class Product(DomainBase):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("direction IN (" + ", ".join(repr(d) for d in DIRECTIONS) + ")",
                        name="ck_products_direction"),
        ForeignKeyConstraint(
            ["current_version_id", "id"], ["workflow_versions.id", "workflow_versions.product_id"],
            name="fk_products_current_version"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    direction: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    current_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    @validates("code", "direction")
    def _stable_identity(self, key, value):
        if inspect(self).has_identity and value != getattr(self, key):
            raise DomainError("product code and direction are immutable")
        if key == "direction" and value not in DIRECTIONS:
            raise DomainError(f"unknown direction {value!r}")
        return value

    @classmethod
    def __declare_last__(cls):
        def reject_delete(mapper, connection, target):
            raise DomainError("archive the product instead of deleting it")

        event.listen(cls, "before_delete", reject_delete)


class WorkflowVersion(DomainBase):
    __tablename__ = "workflow_versions"
    __table_args__ = (
        UniqueConstraint("product_id", "version", name="uq_workflow_product_version"),
        # Составные FK не позволяют назначить продукту или услуге процесс другого продукта.
        UniqueConstraint("id", "product_id", name="uq_workflow_id_product"),
        CheckConstraint("version >= 1", name="ck_workflow_version_positive"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    # Физического FK на products здесь намеренно нет: products уже ссылается на
    # версию через current_version_id, и встречный FK заставил бы создавать таблицы
    # с ALTER, чего эта ревизия избегает. Цена: сырой INSERT мимо ORM может завести
    # версию с несуществующим product_id — целостность держит хук before_insert.
    # Связь проверяется ниже при записи, удаление продукта запрещено доменным слоем.
    product_id: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    stages: Mapped[list[dict]] = mapped_column(_ServiceJSON)
    transitions: Mapped[dict[str, list[str]]] = mapped_column(_ServiceJSON)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("id", "product_id", "version", "stages", "transitions",
               "published_at", "published_by", "created_at")
    def _immutable_after_publication(self, key, value):
        if self.__dict__.get("published_at") is not None:
            raise DomainError("published workflow version is immutable")
        return _ServiceJSON.freeze(value) if key in ("stages", "transitions") else value

    @classmethod
    def __declare_last__(cls):
        def validate_product(mapper, connection, target):
            if connection.scalar(select(Product.id).where(Product.id == target.product_id)) is None:
                raise DomainError(f"unknown product {target.product_id}")

        def protect_published(mapper, connection, target):
            # Читаем сохранённый признак, чтобы expire/merge не обходили неизменяемость.
            published = connection.scalar(select(cls.published_at).where(
                cls.id == inspect(target).identity[0]))
            if published is not None:
                raise DomainError("published workflow version is immutable")

        event.listen(cls, "before_insert", validate_product)
        event.listen(cls, "before_update", protect_published)
        event.listen(cls, "before_update", validate_product)
        event.listen(cls, "before_delete", protect_published)


class ServiceCase(DomainBase):
    __tablename__ = "service_cases"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workflow_version_id", "product_id"],
            ["workflow_versions.id", "workflow_versions.product_id"],
            name="fk_service_cases_workflow_product"),
        CheckConstraint("revision >= 1", name="ck_service_case_revision_positive"),
        # AC-01: повтор запроса с тем же ключом не заводит вторую услугу. Уникальность
        # держит БД: две параллельные отправки формы прошли бы проверку «а нет ли уже»
        # обе — между SELECT и INSERT успевает вклиниться вторая транзакция.
        # Частичный индекс: ключ не обязателен, а NULL в уникальном индексе PostgreSQL
        # не конфликтует сам с собой, но в SQLite ведёт себя иначе — отсюда WHERE.
        Index("uq_service_case_idempotency", "idempotency_key", unique=True,
              sqlite_where=text("idempotency_key IS NOT NULL"),
              postgresql_where=text("idempotency_key IS NOT NULL")),
        CheckConstraint(
            "(agreed_amount IS NULL) OR (currency IS NOT NULL AND length(trim(currency)) = 3)",
            name="ck_service_case_amount_needs_currency"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    request_id: Mapped[int | None] = mapped_column(ForeignKey("requests.id"), nullable=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    workflow_version_id: Mapped[int] = mapped_column(Integer)
    owner_login: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str] = mapped_column(String(64))
    outcome: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # --- E1-03: договор. Техприложение ТЗ разрешает держать его полями услуги, пока
    # не понадобится несколько договоров на одну услугу. Отдельная таблица без такой
    # потребности — лишняя связь, которую потом тащить в каждый запрос.
    contract_reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # Отправленный договор НЕ равен подписанному (FLOW-02): пока сотрудник не
    # подтвердил подпись, здесь пусто, и продажа не считается состоявшейся.
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    signed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Сумма договора. Decimal, не float: на деньгах разница в копейку превращается
    # в расхождение отчётов. Операции с платежами — отдельная задача E2-03, здесь
    # только согласованная цена из договора.
    agreed_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    # «Сумма уточняется» — законное состояние по FLOW-02, но с причиной: неизвестная
    # сумма не равна нулю и не должна молча превращаться в него в отчётах.
    amount_unknown_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Ключ операции для AC-01: повтор запроса с тем же ключом обязан вернуть ту же
    # услугу, а не завести вторую. Уникальность держит БД, а не проверка в коде:
    # две параллельные отправки формы проверку бы прошли обе.
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    waiting_party: Mapped[str | None] = mapped_column(String(64), nullable=True)
    waiting_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    # Проверка ревизии входит в сам UPDATE, поэтому два менеджера не затрут друг друга.
    __mapper_args__ = {"version_id_col": revision}

    @validates("contact_id", "product_id", "workflow_version_id", "revision")
    def _fixed_process(self, key, value):
        if inspect(self).has_identity and value != getattr(self, key):
            raise DomainError(f"service case {key} cannot be reassigned")
        return value

    @validates("agreed_amount", "currency")
    def _contract_money_only_via_operation(self, key, value):
        """Цену договора меняет только операция, с правом, причиной и событием.

        Аудит нашёл главную дыру денежного модуля: журнал платежей закрыт от
        правок, а сама сумма договора менялась из любой сессии бесследно — и это
        ретроактивно переписывало все остатки. Отчёт за прошлый месяц, пересчитанный
        сегодня, показывал бы другие числа, и сверить его было бы нечем.
        """
        if inspect(self).has_identity and value != getattr(self, key):
            if not getattr(self, "_money_correction_in_progress", False):
                raise DomainError(
                    "contract amount and currency change only via correct_contract_amount")
        return value

    @validates("stage")
    def _stage_only_via_operation(self, key, value):
        """Этап меняет только `service_cases.advance`, и только с событием.

        Аудит показал: прямое `case.stage = "TOUR-05"` проходило мимо проверки
        допустимости перехода и обязательных фактов. Ревизия при этом росла, а
        события не возникало — и восстановить прежний этап из истории было
        нельзя, то есть такая запись неотличима от правильной. Закрыто тем же
        приёмом, что и владелец: операция снимает защиту на один вызов.
        """
        if inspect(self).has_identity and value != getattr(self, key):
            if not getattr(self, "_advance_in_progress", False):
                raise DomainError("service case stage changes only via advance")
        return value

    @validates("owner_login")
    def _owner_only_via_operation(self, key, value):
        """Владельца меняет только `service_cases.reassign_case`, и только с событием.

        Аудит нашёл тупик: прямое присваивание `case.owner_login = "..."` двигало
        ревизию, но не оставляло следа в истории — то есть услуга меняла хозяина
        бесследно, вопреки обещанию в докстрингах. Теперь поле закрыто, а операция
        снимает защиту явно и на один вызов.
        """
        if inspect(self).has_identity and value != getattr(self, key):
            if not getattr(self, "_reassign_in_progress", False):
                raise DomainError("service case owner changes only via reassign_case")
        return value

    @classmethod
    def __declare_last__(cls):
        def validate_stage(mapper, connection, target):
            workflow = connection.execute(select(
                WorkflowVersion.product_id, WorkflowVersion.stages,
                WorkflowVersion.published_at,
            ).where(WorkflowVersion.id == target.workflow_version_id)).first()
            if (workflow is None or workflow.product_id != target.product_id
                    or workflow.published_at is None):
                raise DomainError("service case requires a published workflow of its product")
            if target.stage not in {stage["code"] for stage in workflow.stages}:
                raise DomainError(f"unknown stage {target.stage!r}")

        event.listen(cls, "before_insert", validate_stage)
        event.listen(cls, "before_update", validate_stage)


class BookingAttempt(DomainBase):
    """Попытка забронировать тур у оператора: заявка, подтверждение или отказ.

    Зачем отдельная сущность, а не поля в услуге: оператор отказывает регулярно —
    нет мест, цена изменилась, отель снят с продажи. Клиент выбирает альтернативу,
    и это НОВАЯ попытка со своей ценой, своим отелем и своими датами. Прежняя
    попытка обязана сохраниться: без неё нельзя ответить, что именно просили
    сначала и почему не вышло (AC-03).

    Отказ оператора НЕ закрывает услугу и не трогает деньги. Клиент уже внёс
    предоплату, она относится к договору, а не к конкретной брони: деньги живут
    отдельными событиями в журнале (E2-03).

    Цена попытки — не цена договора. Договор меняется отдельной операцией с
    причиной (`correct_contract_amount`), и видно, какая попытка стала основанием.
    """

    __tablename__ = "booking_attempts"
    __table_args__ = (
        # Номер попытки уникален внутри услуги: «вторая попытка» одна.
        UniqueConstraint("case_id", "attempt", name="uq_booking_attempt_number"),
        CheckConstraint("attempt >= 1", name="ck_booking_attempt_number"),
        CheckConstraint("check_out > check_in", name="ck_booking_attempt_dates"),
        CheckConstraint("price IS NULL OR price > 0", name="ck_booking_attempt_price"),
        CheckConstraint("(price IS NULL) = (currency IS NULL)",
                        name="ck_booking_attempt_price_currency"),
        CheckConstraint(
            "status IN ('requested', 'confirmed', 'declined', 'cancelled')",
            name="ck_booking_attempt_status"),
        # Подтверждённая бронь обязана иметь номер и дату подтверждения: это тот
        # самый «обязательный факт» перехода из FLOW-03.
        CheckConstraint(
            "status <> 'confirmed'"
            " OR (reference IS NOT NULL AND confirmed_at IS NOT NULL)",
            name="ck_booking_attempt_confirmed_facts"),
        CheckConstraint(
            "status <> 'declined' OR decline_reason IS NOT NULL",
            name="ck_booking_attempt_decline_reason"),
        CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id",
                        name="ck_booking_attempt_no_self_supersede"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("service_cases.id"), index=True)
    attempt: Mapped[int] = mapped_column(Integer)
    operator: Mapped[str] = mapped_column(String(128))
    country: Mapped[str] = mapped_column(String(64))
    hotel: Mapped[str] = mapped_column(String(255))
    check_in: Mapped[date] = mapped_column(Date)
    check_out: Mapped[date] = mapped_column(Date)
    tourists: Mapped[int] = mapped_column(Integer, default=1)
    # Цена ЭТОЙ попытки, а не договора. У альтернативы она своя.
    price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="requested")
    reference: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Попытка, которую эта заменила после отказа. Прежняя остаётся в истории.
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("booking_attempts.id"), nullable=True)
    requested_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                 server_default=func.now())

    @validates("case_id", "attempt", "supersedes_id")
    def _identity_is_fixed(self, key, value):
        if inspect(self).has_identity and value != getattr(self, key):
            raise DomainError(f"booking attempt {key} cannot be reassigned")
        return value


class TicketSegment(DomainBase):
    """Один полётный сегмент билета: откуда, куда, когда и в какой зоне.

    Зачем отдельная сущность, а не поля в услуге: билет со стыковкой — это два
    и больше перелётов, у каждого своё время, свой аэропорт и своя часовая зона.
    Задачи («напомнить о регистрации», «подтвердить вылет») относятся к КОНКРЕТНОМУ
    сегменту, иначе напоминание придёт не к тому рейсу (AC-09).

    Время хранится в UTC, а зона — рядом, строкой IANA (`Asia/Bishkek`). Без зоны
    нельзя показать клиенту местное время вылета, а показывать UTC бессмысленно:
    человек смотрит на табло в аэропорту, а не на UTC.

    `checkin_opens_hours_before` — окно регистрации ИМЕННО этой авиакомпании.
    NULL означает «не знаем», и тогда задача на регистрацию не ставится вовсе.
    Это требование ТЗ: универсального предположения о 24 часах быть не должно —
    у разных перевозчиков окно от 23 до 72 часов, и выдуманный срок хуже
    отсутствующего, потому что клиент на него полагается.

    Перенос рейса не правит сегмент, а создаёт новый со ссылкой `supersedes_id`:
    прежнее расписание остаётся в истории, иначе нельзя ответить на вопрос
    «а когда рейс был изначально» (AC-08).
    """

    __tablename__ = "ticket_segments"
    __table_args__ = (
        # Уникальна позиция только среди ДЕЙСТВУЮЩИХ сегментов. Полная уникальность
        # по (case, position, superseded) ломала второй перенос того же рейса:
        # заменённый сегмент занимал ключ навсегда, а авиакомпании двигают рейс
        # по нескольку раз. Частичный индекс работает и на SQLite, и на PostgreSQL.
        # Позиция уникальна среди ДЕЙСТВУЮЩИХ сегментов: заменённые и отменённые
        # её не занимают. Иначе после отмены рейса нельзя поставить на его место
        # новый — а именно это и делают, когда перевозчик снял рейс.
        Index("uq_ticket_segment_active_position", "case_id", "position", unique=True,
              sqlite_where=text("superseded = 0 AND status <> 'cancelled'"),
              postgresql_where=text("superseded = false AND status <> 'cancelled'")),
        CheckConstraint("position >= 1", name="ck_ticket_segment_position"),
        CheckConstraint("arrival_at > departure_at", name="ck_ticket_segment_order"),
        CheckConstraint(
            "checkin_opens_hours_before IS NULL"
            " OR (checkin_opens_hours_before > 0 AND checkin_opens_hours_before <= 336)",
            name="ck_ticket_segment_checkin_window"),
        CheckConstraint("status IN ('planned', 'confirmed', 'cancelled')",
                        name="ck_ticket_segment_status"),
        CheckConstraint("supersedes_id IS NULL OR supersedes_id <> id",
                        name="ck_ticket_segment_no_self_supersede"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("service_cases.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)          # 1, 2, 3 — порядок в билете
    carrier: Mapped[str] = mapped_column(String(64))
    flight_number: Mapped[str] = mapped_column(String(16))
    departure_airport: Mapped[str] = mapped_column(String(8))
    arrival_airport: Mapped[str] = mapped_column(String(8))
    departure_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    arrival_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    departure_tz: Mapped[str] = mapped_column(String(64))   # IANA, напр. Asia/Bishkek
    arrival_tz: Mapped[str] = mapped_column(String(64))
    # Окно регистрации этого перевозчика в часах. NULL = не знаем, задачу не ставим.
    checkin_opens_hours_before: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="planned")
    # Сегмент, который этот заменил при переносе. Прежний остаётся в истории.
    supersedes_id: Mapped[int | None] = mapped_column(
        ForeignKey("ticket_segments.id"), nullable=True)
    # Заменён другим сегментом. В уникальности участвует, чтобы позиция была
    # свободна для нового сегмента, а старый никуда не исчезал.
    superseded: Mapped[bool] = mapped_column(Boolean, default=False)
    booking_reference: Mapped[str | None] = mapped_column(String(64), nullable=True)
    passenger_name: Mapped[str | None] = mapped_column(String(160), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                 server_default=func.now())

    @validates("case_id", "position", "supersedes_id")
    def _identity_is_fixed(self, key, value):
        if inspect(self).has_identity and value != getattr(self, key):
            raise DomainError(f"ticket segment {key} cannot be reassigned")
        return value


class ServicePayment(DomainBase):
    """Денежное движение по услуге: оплата, обязательство возврата или факт возврата.

    Это **журнал фактов**, а не счёт. Строки не меняются и не удаляются: исправление
    добавляет новую строку с типом `correction` и ссылкой на исправляемую. Остаток
    всегда считается заново по журналу — хранимого «итого» нет, чтобы не было двух
    источников правды, которые разойдутся.

    Почему обязательство возврата и факт возврата — разные типы (AC-04): клиент
    решил вернуть деньги, а перевод ещё не сделан. Если пометить это как возврат,
    отчёт покажет деньги вернувшимися, хотя они у компании. Обязательство видно
    отдельно и не трогает «возвращено».

    Валюта платежа может отличаться от валюты договора. Тогда без курса зачесть
    платёж в остаток нельзя (AC-06): сумма висит в своей валюте и не создаёт
    ложного остатка. Зачёт нигде не хранится — он считается при расчёте остатка,
    иначе платёж, внесённый до появления суммы в договоре, выпадал бы навсегда.

    Защита уровня ORM: построчные и массовые UPDATE/DELETE запрещены. Core-соединение
    и сырой SQL её обходят — это принятый предел, настоящая защита потребовала бы
    триггера или REVOKE на стороne PostgreSQL (решение не принято).
    """

    __tablename__ = "service_payments"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_service_payment_idempotency"),
        # Одну строку исправляет РОВНО одна: иначе два менеджера (или двойной клик
        # с разными ключами) исправляют одно и то же, и обе поправки суммируются.
        Index("uq_service_payment_corrects", "corrects_id", unique=True,
              sqlite_where=text("corrects_id IS NOT NULL"),
              postgresql_where=text("corrects_id IS NOT NULL")),
        CheckConstraint("amount > 0", name="ck_service_payment_amount_positive"),
        CheckConstraint("length(trim(currency)) = 3", name="ck_service_payment_currency"),
        CheckConstraint("fx_rate IS NULL OR fx_rate > 0",
                        name="ck_service_payment_rate_positive"),
        # Курс и валюта, к которой он дан, существуют только вместе.
        CheckConstraint("(fx_rate IS NULL) = (fx_to IS NULL)",
                        name="ck_service_payment_rate_needs_target"),
        # Строка не исправляет сама себя: иначе она исключает себя из расчёта и
        # деньги исчезают из остатка молча.
        CheckConstraint("corrects_id IS NULL OR corrects_id <> id",
                        name="ck_service_payment_no_self_correction"),
        CheckConstraint(
            "kind IN ('payment', 'refund_due', 'refund_paid', 'correction', 'void')",
            name="ck_service_payment_kind"),
        CheckConstraint("settles_id IS NULL OR settles_id <> id",
                        name="ck_service_payment_no_self_settlement"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("service_cases.id"), index=True)
    # payment | refund_due | refund_paid | correction
    kind: Mapped[str] = mapped_column(String(16))
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))
    # Курс к валюте договора на момент записи. Зачтённая сумма НЕ хранится: она
    # вычисляется при расчёте остатка. Хранимый зачёт был ошибкой — он фиксировался
    # в момент платежа, и предоплата, внесённая до появления суммы в договоре,
    # навсегда выпадала из остатка.
    fx_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 6), nullable=True)
    # Валюта, К КОТОРОЙ дан курс. Без неё курс бессмысленен: он задавался к валюте
    # договора на момент записи, а если валюта договора потом сменится, тот же курс
    # применился бы к другой валюте и дал ложный зачёт.
    fx_to: Mapped[str | None] = mapped_column(String(3), nullable=True)
    idempotency_key: Mapped[str] = mapped_column(String(128))
    corrects_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_payments.id"), nullable=True)
    # Обязательство, которое закрывает этот фактический возврат. Без ссылки
    # обязательство жило в отчёте вечно: услуга показывала и «вернули», и
    # «обязаны вернуть», а сигнал «нужен человек» становился шумом.
    settles_id: Mapped[int | None] = mapped_column(
        ForeignKey("service_payments.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    recorded_by: Mapped[str] = mapped_column(String(64))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now,
                                                  server_default=func.now())

    @classmethod
    def __declare_last__(cls):
        def reject_write(mapper, connection, target):
            # Строка журнала не меняется и не удаляется: исправление — новая строка.
            # Валидатор полей ловит только присваивание через ORM, а этот хук
            # закрывает и удаление объекта целиком.
            raise DomainError("service payments are append-only")

        event.listen(cls, "before_update", reject_write)
        event.listen(cls, "before_delete", reject_write)

    @validates("kind", "amount", "currency", "fx_rate", "fx_to", "case_id",
               "idempotency_key", "corrects_id", "settles_id", "reason",
               "recorded_by", "recorded_at")
    def _append_only(self, key, value):
        """Журнал денег не правится на месте: исправление — отдельная строка.

        Иначе сумма могла измениться бесследно, и сверить отчёт с историей было бы
        нечем. Ровно та же причина, по которой закрыты `stage` и `owner_login`
        у услуги.
        """
        if inspect(self).has_identity and value != getattr(self, key):
            raise DomainError(f"service payment {key} is append-only; record a correction")
        return value


class ServiceEvent(DomainBase):
    __tablename__ = "service_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("service_cases.id"))
    event_type: Mapped[str] = mapped_column(String(64))
    actor: Mapped[str] = mapped_column(String(64))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    from_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    to_stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict] = mapped_column(_ServiceJSON, default=lambda: _ServiceJSON.freeze({}))

    @validates("id", "case_id", "event_type", "actor", "occurred_at", "recorded_at",
               "from_stage", "to_stage", "reason", "payload")
    def _append_only(self, key, value):
        if inspect(self).has_identity:
            raise DomainError("service events are append-only")
        return _ServiceJSON.freeze(value) if key == "payload" else value

    @classmethod
    def __declare_last__(cls):
        def reject_write(mapper, connection, target):
            raise DomainError("service events are append-only")

        def reject_bulk_write(state):
            # Массовый DML обходит mapper-события, историю и проверку revision.
            if state.is_update or state.is_delete:
                table = getattr(state.statement, "table", None)
                if table is not None and table.name in {
                    "products", "workflow_versions", "service_cases", "service_events",
                    # Журнал денег тоже: массовый UPDATE стирал суммы бесследно, а
                    # DELETE удалял оплаты целиком — валидатор поля этого не ловит,
                    # потому что bulk-DML обходит mapper-события.
                    "service_payments",
                }:
                    raise DomainError("bulk writes bypass service invariants; use domain operations")

        event.listen(cls, "before_update", reject_write)
        event.listen(cls, "before_delete", reject_write)
        event.listen(Session, "do_orm_execute", reject_bulk_write)


# E5-03C: immutable review storage. No live runtime wiring or publication.
class StayHistory(DomainBase):
    __tablename__ = "stay_histories"
    __table_args__ = (
        UniqueConstraint("id", "contact_id", name="uq_stay_history_contact"),
        UniqueConstraint("contact_id", "revision", name="uq_stay_history_revision"),
        UniqueConstraint("contact_id", "request_key", name="uq_stay_history_request"),
        ForeignKeyConstraint(["previous_id", "contact_id"], ["stay_histories.id", "stay_histories.contact_id"],
                             name="fk_stay_history_previous"),
        CheckConstraint("revision >= 1", name="ck_stay_history_revision"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL)",
                        name="ck_stay_history_previous"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_stay_history_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    as_of: Mapped[date] = mapped_column(Date)
    history_complete: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("snapshot")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class StayInterval(DomainBase):
    __tablename__ = "stay_intervals"
    __table_args__ = (
        ForeignKeyConstraint(["history_id", "contact_id"], ["stay_histories.id", "stay_histories.contact_id"],
                             name="fk_stay_interval_history"),
        UniqueConstraint("history_id", "ref", name="uq_stay_interval_ref"),
        UniqueConstraint("id", "history_id", name="uq_stay_interval_history"),
        CheckConstraint("exit_date IS NULL OR exit_date >= entry_date", name="ck_stay_interval_dates"),
        CheckConstraint("basis IN ('visa_free','visa','ep','resident_card','residence_permit','registration_contract','unknown')",
                        name="ck_stay_interval_basis"),
        CheckConstraint("evidence IN ('esuvm','passport_stamp','boarding_pass','visa_document','client_statement','crm_record')",
                        name="ck_stay_interval_evidence"),
        CheckConstraint("(confirmed AND confirmed_by IS NOT NULL AND confirmed_at IS NOT NULL) OR "
                        "(NOT confirmed AND confirmed_by IS NULL AND confirmed_at IS NULL)", name="ck_stay_interval_confirmation"),
        CheckConstraint("evidence <> 'client_statement' OR NOT confirmed", name="ck_stay_interval_statement"),
        CheckConstraint("passport_ref IS NULL OR length(passport_ref) = 32", name="ck_stay_interval_passport"),
        Index("uq_stay_history_open", "history_id", unique=True,
              sqlite_where=text("exit_date IS NULL"), postgresql_where=text("exit_date IS NULL")),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    history_id: Mapped[int] = mapped_column(Integer)
    contact_id: Mapped[int] = mapped_column(Integer)
    ref: Mapped[str] = mapped_column(String(64))
    entry_date: Mapped[date] = mapped_column(Date)
    exit_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    basis: Mapped[str] = mapped_column(String(32))
    passport_country: Mapped[str | None] = mapped_column(String(3), nullable=True)
    passport_ref: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence: Mapped[str] = mapped_column(String(32))
    confirmed: Mapped[bool] = mapped_column(Boolean)
    confirmed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkCalendar(DomainBase):
    __tablename__ = "work_calendars"
    __table_args__ = (
        UniqueConstraint("jurisdiction", "year", "version", name="uq_work_calendar_version"),
        CheckConstraint("jurisdiction = 'KG' AND status = 'draft'", name="ck_work_calendar_scope"),
        CheckConstraint("year BETWEEN 1 AND 9999 AND version BETWEEN 1 AND 1000000", name="ck_work_calendar_version"),
        CheckConstraint("length(content_hash) = 64", name="ck_work_calendar_hash"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    jurisdiction: Mapped[str] = mapped_column(String(2))
    year: Mapped[int] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    content_hash: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("document")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class WorkCalendarDay(DomainBase):
    __tablename__ = "work_calendar_days"
    __table_args__ = (
        CheckConstraint("kind IN ('public_holiday','floating_holiday','transfer_rest','transfer_working','weekend_override')",
                        name="ck_work_calendar_day_kind"),
        CheckConstraint("(kind = 'weekend_override') OR (kind = 'transfer_working' AND is_working) OR "
                        "(kind IN ('public_holiday','floating_holiday','transfer_rest') AND NOT is_working)",
                        name="ck_work_calendar_day_working"),
    )
    calendar_id: Mapped[int] = mapped_column(ForeignKey("work_calendars.id"), primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    is_working: Mapped[bool] = mapped_column(Boolean)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    source_ref: Mapped[str] = mapped_column(Text)


class EntryCalculation(DomainBase):
    __tablename__ = "entry_calculations"
    __table_args__ = (
        ForeignKeyConstraint(["history_id", "contact_id"], ["stay_histories.id", "stay_histories.contact_id"],
                             name="fk_entry_calculation_history"),
        UniqueConstraint("contact_id", "request_key", name="uq_entry_calculation_request"),
        UniqueConstraint("id", "history_id", name="uq_entry_calculation_history"),
        CheckConstraint("(kind = 'stay' AND history_id IS NOT NULL) OR (kind = 'deadline' AND history_id IS NULL)",
                        name="ck_entry_calculation_kind"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_calculation_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    history_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_versions.id"))
    kind: Mapped[str] = mapped_column(String(16))
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    result_snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    provenance: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("input_snapshot", "result_snapshot", "provenance")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class EntryCalculationInterval(DomainBase):
    __tablename__ = "entry_calculation_intervals"
    __table_args__ = (
        ForeignKeyConstraint(["calculation_id", "history_id"], ["entry_calculations.id", "entry_calculations.history_id"],
                             name="fk_calculation_interval_calculation"),
        ForeignKeyConstraint(["interval_id", "history_id"], ["stay_intervals.id", "stay_intervals.history_id"],
                             name="fk_calculation_interval_history"),
    )
    calculation_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    interval_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    history_id: Mapped[int] = mapped_column(Integer)


class EntryCalculationCalendar(DomainBase):
    __tablename__ = "entry_calculation_calendars"
    calculation_id: Mapped[int] = mapped_column(ForeignKey("entry_calculations.id"), primary_key=True)
    calendar_id: Mapped[int] = mapped_column(ForeignKey("work_calendars.id"), primary_key=True)


class EntryQualification(DomainBase):
    """E5-03E full replacement snapshots of the partial review interview."""
    __tablename__ = "entry_qualifications"
    __table_args__ = (
        UniqueConstraint("id", "contact_id", name="uq_entry_qualification_contact"),
        UniqueConstraint("contact_id", "revision", name="uq_entry_qualification_revision"),
        UniqueConstraint("contact_id", "request_key", name="uq_entry_qualification_request"),
        ForeignKeyConstraint(["previous_id", "contact_id"], ["entry_qualifications.id", "entry_qualifications.contact_id"],
                             name="fk_entry_qualification_previous"),
        ForeignKeyConstraint(["history_id", "contact_id"], ["stay_histories.id", "stay_histories.contact_id"],
                             name="fk_entry_qualification_history"),
        CheckConstraint("revision >= 1", name="ck_entry_qualification_revision"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL)",
                        name="ck_entry_qualification_previous"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_qualification_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("contacts.id"))
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    history_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_versions.id"))
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    result_snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    provenance: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("input_snapshot", "result_snapshot", "provenance")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class EntryApplicant(DomainBase):
    """Numbered, case-scoped person placeholder; never inferred from the payer."""
    __tablename__ = "entry_applicants"
    __table_args__ = (
        UniqueConstraint("id", "case_id", name="uq_entry_applicant_case"),
        UniqueConstraint("case_id", "ordinal", name="uq_entry_applicant_ordinal"),
        UniqueConstraint("case_id", "request_key", name="uq_entry_applicant_request"),
        CheckConstraint("ordinal BETWEEN 1 AND 1000", name="ck_entry_applicant_ordinal"),
        CheckConstraint("role IN ('unknown','primary','spouse','child','parent','employee','other')", name="ck_entry_applicant_role"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_applicant_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("service_cases.id"))
    ordinal: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(String(16))
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EntryApplication(DomainBase):
    """One procedure/document attempt; identity is immutable, facts are revisions."""
    __tablename__ = "entry_applications"
    __table_args__ = (
        UniqueConstraint("id", "case_id", name="uq_entry_application_case"),
        UniqueConstraint("id", "case_id", "applicant_id", "procedure", name="uq_entry_application_subject"),
        UniqueConstraint("case_id", "request_key", name="uq_entry_application_request"),
        UniqueConstraint("previous_id", name="uq_entry_application_successor"),
        ForeignKeyConstraint(["applicant_id", "case_id"], ["entry_applicants.id", "entry_applicants.case_id"], name="fk_entry_application_applicant"),
        ForeignKeyConstraint(["previous_id", "case_id", "applicant_id", "procedure"],
                             ["entry_applications.id", "entry_applications.case_id", "entry_applications.applicant_id", "entry_applications.procedure"], name="fk_entry_application_previous"),
        CheckConstraint("procedure IN ('visa','unified_permit','resident_card','registration','violation_protocol','exit_visa')", name="ck_entry_application_procedure"),
        CheckConstraint("attempt BETWEEN 1 AND 100", name="ck_entry_application_attempt"),
        CheckConstraint("(attempt = 1 AND previous_id IS NULL) OR (attempt > 1 AND previous_id IS NOT NULL AND previous_id < id)", name="ck_entry_application_previous"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_application_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("service_cases.id"))
    applicant_id: Mapped[int] = mapped_column(Integer)
    procedure: Mapped[str] = mapped_column(String(32))
    attempt: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EntryApplicationEvent(DomainBase):
    __tablename__ = "entry_application_events"
    __table_args__ = (
        UniqueConstraint("id", "application_id", name="uq_entry_application_event_parent"),
        UniqueConstraint("application_id", "revision", name="uq_entry_application_event_revision"),
        UniqueConstraint("application_id", "request_key", name="uq_entry_application_event_request"),
        ForeignKeyConstraint(["application_id", "case_id"], ["entry_applications.id", "entry_applications.case_id"], name="fk_entry_application_event_case"),
        ForeignKeyConstraint(["previous_id", "application_id"], ["entry_application_events.id", "entry_application_events.application_id"], name="fk_entry_application_event_previous"),
        CheckConstraint("revision BETWEEN 1 AND 500", name="ck_entry_application_event_revision"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL AND status = 'draft') OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id AND status <> 'draft')", name="ck_entry_application_event_previous"),
        CheckConstraint("status IN ('draft','submitted','revision_requested','approved','refused','closed')", name="ck_entry_application_event_status"),
        CheckConstraint("source IN ('crm','portal','official_document','client_request')", name="ck_entry_application_event_source"),
        CheckConstraint("reference IS NULL OR length(reference) = 8", name="ck_entry_application_event_reference"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_application_event_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer)
    application_id: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(24))
    occurred_on: Mapped[date] = mapped_column(Date)
    source: Mapped[str] = mapped_column(String(24))
    reference: Mapped[str | None] = mapped_column(String(8), nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class EntryApplicationReference(DomainBase):
    """A portal identifier belongs to exactly one attempt, including across cases."""
    __tablename__ = "entry_application_references"
    __table_args__ = (
        ForeignKeyConstraint(["application_id", "case_id"], ["entry_applications.id", "entry_applications.case_id"], name="fk_entry_application_reference_case"),
        CheckConstraint("length(reference) = 8", name="ck_entry_application_reference_length"),
    )
    application_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str] = mapped_column(String(8), unique=True)


class EntryDocumentRevision(DomainBase):
    """Immutable per-application inventory commands and resulting metadata snapshots."""
    __tablename__ = "entry_document_revisions"
    __table_args__ = (
        UniqueConstraint("id", "application_id", "case_id", name="uq_entry_document_parent"),
        UniqueConstraint("application_id", "revision", name="uq_entry_document_revision"),
        UniqueConstraint("application_id", "request_key", name="uq_entry_document_request"),
        ForeignKeyConstraint(["application_id", "case_id"], ["entry_applications.id", "entry_applications.case_id"], name="fk_entry_document_case"),
        ForeignKeyConstraint(["previous_id", "application_id", "case_id"],
            ["entry_document_revisions.id", "entry_document_revisions.application_id", "entry_document_revisions.case_id"], name="fk_entry_document_previous"),
        CheckConstraint("revision BETWEEN 1 AND 150", name="ck_entry_document_revision"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)", name="ck_entry_document_previous"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_document_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer)
    application_id: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("command", "snapshot")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class EntryIssuedRevision(DomainBase):
    """Immutable post-issue verification, delivery and actual travel facts."""
    __tablename__ = "entry_issued_revisions"
    __table_args__ = (
        UniqueConstraint("id", "application_id", "case_id", name="uq_entry_issued_parent"),
        UniqueConstraint("application_id", "revision", name="uq_entry_issued_revision"),
        UniqueConstraint("application_id", "request_key", name="uq_entry_issued_request"),
        ForeignKeyConstraint(["application_id", "case_id"], ["entry_applications.id", "entry_applications.case_id"], name="fk_entry_issued_case"),
        ForeignKeyConstraint(["previous_id", "application_id", "case_id"],
            ["entry_issued_revisions.id", "entry_issued_revisions.application_id", "entry_issued_revisions.case_id"], name="fk_entry_issued_previous"),
        ForeignKeyConstraint(["approval_event_id", "application_id"], ["entry_application_events.id", "entry_application_events.application_id"], name="fk_entry_issued_approval"),
        CheckConstraint("revision BETWEEN 1 AND 250", name="ck_entry_issued_revision"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)", name="ck_entry_issued_previous"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_issued_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer)
    application_id: Mapped[int] = mapped_column(Integer)
    approval_event_id: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("command", "snapshot")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


ENTRY_APPLICATION_MODELS = (EntryApplicant, EntryApplication, EntryApplicationEvent, EntryApplicationReference)
ENTRY_STORAGE_MODELS = (StayHistory, StayInterval, WorkCalendar, WorkCalendarDay, EntryCalculation,
                        EntryCalculationInterval, EntryCalculationCalendar)
class EntryApplicantProfile(DomainBase):
    """Individual qualification snapshots; payer-level facts are never inherited."""
    __tablename__ = "entry_applicant_profiles"
    __table_args__ = (
        UniqueConstraint("id", "applicant_id", "case_id", name="uq_entry_profile_scope"),
        UniqueConstraint("applicant_id", "revision", name="uq_entry_profile_revision"),
        UniqueConstraint("applicant_id", "request_key", name="uq_entry_profile_request"),
        ForeignKeyConstraint(["applicant_id", "case_id"], ["entry_applicants.id", "entry_applicants.case_id"], name="fk_entry_profile_applicant"),
        ForeignKeyConstraint(["previous_id", "applicant_id", "case_id"],
            ["entry_applicant_profiles.id", "entry_applicant_profiles.applicant_id", "entry_applicant_profiles.case_id"], name="fk_entry_profile_previous"),
        CheckConstraint("revision BETWEEN 1 AND 250", name="ck_entry_profile_revision"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)", name="ck_entry_profile_previous"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_profile_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer)
    applicant_id: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    knowledge_version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_versions.id"))
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    input_snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    result_snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    provenance: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("input_snapshot", "result_snapshot", "provenance")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class EntryDeadlineRevision(DomainBase):
    """One source rule's deadline history within a particular application."""
    __tablename__ = "entry_deadline_revisions"
    __table_args__ = (
        UniqueConstraint("id", "application_id", "case_id", "rule_unit_id", name="uq_entry_deadline_scope"),
        UniqueConstraint("application_id", "rule_unit_id", "revision", name="uq_entry_deadline_revision"),
        UniqueConstraint("application_id", "rule_unit_id", "request_key", name="uq_entry_deadline_request"),
        ForeignKeyConstraint(["application_id", "case_id"], ["entry_applications.id", "entry_applications.case_id"], name="fk_entry_deadline_application"),
        ForeignKeyConstraint(["previous_id", "application_id", "case_id", "rule_unit_id"],
            ["entry_deadline_revisions.id", "entry_deadline_revisions.application_id", "entry_deadline_revisions.case_id", "entry_deadline_revisions.rule_unit_id"], name="fk_entry_deadline_previous"),
        ForeignKeyConstraint(["anchor_event_id", "application_id"], ["entry_application_events.id", "entry_application_events.application_id"], name="fk_entry_deadline_event"),
        ForeignKeyConstraint(["anchor_issued_id", "application_id", "case_id"],
            ["entry_issued_revisions.id", "entry_issued_revisions.application_id", "entry_issued_revisions.case_id"], name="fk_entry_deadline_travel"),
        CheckConstraint("revision BETWEEN 1 AND 250", name="ck_entry_deadline_revision"),
        CheckConstraint("anchor_event_id IS NULL OR anchor_issued_id IS NULL", name="ck_entry_deadline_anchor"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)", name="ck_entry_deadline_previous"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_deadline_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer)
    application_id: Mapped[int] = mapped_column(Integer)
    rule_unit_id: Mapped[str] = mapped_column(String(80))
    knowledge_version_id: Mapped[int] = mapped_column(ForeignKey("knowledge_versions.id"))
    anchor_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    anchor_issued_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("command", "snapshot")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class EntryDeadlineTask(DomainBase):
    """Operational task binding; lifecycle audit remains in CalendarTaskEvent."""
    __tablename__ = "entry_deadline_tasks"
    __table_args__ = (
        UniqueConstraint("application_id", "rule_unit_id", "generation", name="uq_entry_deadline_task_generation"),
        UniqueConstraint("task_id", name="uq_entry_deadline_task_identity"),
        Index("ix_entry_deadline_task_sweep", "case_id", "generation", "id"),
        ForeignKeyConstraint(["application_id", "case_id"], ["entry_applications.id", "entry_applications.case_id"], name="fk_entry_deadline_task_application"),
        ForeignKeyConstraint(["deadline_revision_id", "application_id", "case_id", "rule_unit_id"],
            ["entry_deadline_revisions.id", "entry_deadline_revisions.application_id", "entry_deadline_revisions.case_id", "entry_deadline_revisions.rule_unit_id"], name="fk_entry_deadline_task_source"),
        CheckConstraint("generation BETWEEN 1 AND 250 AND revision >= 1", name="ck_entry_deadline_task_revision"),
        CheckConstraint("length(source_hash) = 64 AND length(target_hash) = 64", name="ck_entry_deadline_task_hashes"),
        CheckConstraint("attention IN ('','unknown_date','missing_owner','claimed','schedule_conflict','generation_limit')", name="ck_entry_deadline_task_attention"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer)
    application_id: Mapped[int] = mapped_column(Integer)
    rule_unit_id: Mapped[str] = mapped_column(String(80))
    generation: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    deadline_revision_id: Mapped[int] = mapped_column(Integer)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("calendar_tasks.id"), nullable=True)
    source_hash: Mapped[str] = mapped_column(String(64))
    target_hash: Mapped[str] = mapped_column(String(64))
    expected_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    attention: Mapped[str] = mapped_column(String(32), default="")
    created_by: Mapped[str] = mapped_column(String(64))
    updated_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class KnowledgeDecision(DomainBase):
    """A reviewer's evidence record; never mutates the imported source or publishes it."""
    __tablename__ = "knowledge_decisions"
    __table_args__ = (
        UniqueConstraint("id", "version_id", "unit_id", name="uq_knowledge_decision_scope"),
        UniqueConstraint("version_id", "unit_id", "revision", name="uq_knowledge_decision_revision"),
        UniqueConstraint("version_id", "unit_id", "request_key", name="uq_knowledge_decision_request"),
        ForeignKeyConstraint(["version_id", "unit_id"], ["knowledge_units.version_id", "knowledge_units.unit_id"], name="fk_knowledge_decision_unit"),
        ForeignKeyConstraint(["previous_id", "version_id", "unit_id"], ["knowledge_decisions.id", "knowledge_decisions.version_id", "knowledge_decisions.unit_id"], name="fk_knowledge_decision_previous"),
        CheckConstraint("revision BETWEEN 1 AND 250", name="ck_knowledge_decision_revision"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)", name="ck_knowledge_decision_previous"),
        CheckConstraint("length(unit_hash) = 64 AND length(bundle_hash) = 64 AND length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_knowledge_decision_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version_id: Mapped[int] = mapped_column(Integer)
    unit_id: Mapped[str] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_hash: Mapped[str] = mapped_column(String(64))
    bundle_hash: Mapped[str] = mapped_column(String(64))
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("command")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class KnowledgePublicationEvent(DomainBase):
    """Immutable lifecycle audit; active pointer/status stay in the existing tables."""
    __tablename__ = "knowledge_publication_events"
    __table_args__ = (
        UniqueConstraint("id", "set_id", name="uq_knowledge_publication_set"),
        UniqueConstraint("id", "version_id", name="uq_knowledge_publication_version"),
        UniqueConstraint("set_id", "revision", name="uq_knowledge_publication_revision"),
        UniqueConstraint("set_id", "request_key", name="uq_knowledge_publication_request"),
        ForeignKeyConstraint(["version_id", "set_id"], ["knowledge_versions.id", "knowledge_versions.set_id"], name="fk_knowledge_publication_version"),
        ForeignKeyConstraint(["previous_id", "set_id"], ["knowledge_publication_events.id", "knowledge_publication_events.set_id"], name="fk_knowledge_publication_previous"),
        CheckConstraint("revision BETWEEN 1 AND 250", name="ck_knowledge_publication_revision"),
        CheckConstraint("action IN ('review','approve','activate','rollback','withdraw')", name="ck_knowledge_publication_action"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)", name="ck_knowledge_publication_previous"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_knowledge_publication_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("knowledge_sets.id"))
    version_id: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(16))
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("command", "snapshot")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class KnowledgePublicationUnit(DomainBase):
    __tablename__ = "knowledge_publication_units"
    __table_args__ = (
        ForeignKeyConstraint(["event_id", "version_id"], ["knowledge_publication_events.id", "knowledge_publication_events.version_id"], name="fk_knowledge_publication_unit_event"),
        ForeignKeyConstraint(["version_id", "unit_id"], ["knowledge_units.version_id", "knowledge_units.unit_id"], name="fk_knowledge_publication_unit_source"),
        ForeignKeyConstraint(["decision_id", "version_id", "unit_id"], ["knowledge_decisions.id", "knowledge_decisions.version_id", "knowledge_decisions.unit_id"], name="fk_knowledge_publication_unit_decision"),
        CheckConstraint("length(unit_hash) = 64 AND (decision_hash IS NULL OR length(decision_hash) = 64)", name="ck_knowledge_publication_unit_hashes"),
        CheckConstraint("(decision_id IS NULL) = (decision_hash IS NULL)", name="ck_knowledge_publication_unit_decision"),
    )
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    unit_id: Mapped[str] = mapped_column(Text, primary_key=True)
    version_id: Mapped[int] = mapped_column(Integer)
    decision_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    unit_hash: Mapped[str] = mapped_column(String(64))
    decision_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)


class EntryDocumentPackageEvent(DomainBase):
    """Full-package commands; the definition is pinned once, not copied per event."""
    __tablename__ = "entry_document_package_events"
    __table_args__ = (
        UniqueConstraint("id", "application_id", "case_id", name="uq_entry_package_scope"),
        UniqueConstraint("application_id", "revision", name="uq_entry_package_revision"),
        UniqueConstraint("application_id", "request_key", name="uq_entry_package_request"),
        ForeignKeyConstraint(["application_id", "case_id"], ["entry_applications.id", "entry_applications.case_id"], name="fk_entry_package_application"),
        ForeignKeyConstraint(["previous_id", "application_id", "case_id"], ["entry_document_package_events.id", "entry_document_package_events.application_id", "entry_document_package_events.case_id"], name="fk_entry_package_previous"),
        ForeignKeyConstraint(["legacy_inventory_id", "application_id", "case_id"], ["entry_document_revisions.id", "entry_document_revisions.application_id", "entry_document_revisions.case_id"], name="fk_entry_package_legacy"),
        CheckConstraint("revision BETWEEN 1 AND 500", name="ck_entry_package_revision"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL AND action = 'initialize') OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id AND action != 'initialize' AND legacy_inventory_id IS NULL)", name="ck_entry_package_initial"),
        CheckConstraint("action IN ('initialize','facts','receive','review','withdraw_document','passport_change','consent','approve','revoke','upgrade_definition')", name="ck_entry_package_action"),
        CheckConstraint("(action IN ('initialize','upgrade_definition') AND definition IS NOT NULL) OR (action NOT IN ('initialize','upgrade_definition') AND definition IS NULL)", name="ck_entry_package_definition"),
        CheckConstraint("(legacy_inventory_id IS NULL) = (legacy_inventory_hash IS NULL)", name="ck_entry_package_legacy"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64 AND length(state_hash) = 64 AND (legacy_inventory_hash IS NULL OR length(legacy_inventory_hash) = 64)", name="ck_entry_package_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer)
    application_id: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(24))
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    legacy_inventory_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    legacy_inventory_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    definition: Mapped[dict | None] = mapped_column(_ServiceJSON(none_as_null=True), nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    state_hash: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("command", "definition")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class EntryQuarantinedFile(DomainBase):
    """Immutable quarantined bytes, committed with their exact package receipt."""
    __tablename__ = "entry_quarantined_files"
    __table_args__ = (
        UniqueConstraint("application_id", "request_key", name="uq_entry_quarantine_request"),
        UniqueConstraint("package_event_id", name="uq_entry_quarantine_receipt"),
        ForeignKeyConstraint(["package_event_id", "application_id", "case_id"],
            ["entry_document_package_events.id", "entry_document_package_events.application_id", "entry_document_package_events.case_id"],
            name="fk_entry_quarantine_receipt"),
        CheckConstraint("document_version BETWEEN 1 AND 500", name="ck_entry_quarantine_version"),
        CheckConstraint("byte_size BETWEEN 8 AND 8388608 AND length(content) = byte_size", name="ck_entry_quarantine_size"),
        CheckConstraint("media_type IN ('application/pdf','image/jpeg')", name="ck_entry_quarantine_type"),
        CheckConstraint("length(fingerprint) = 64 AND length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_quarantine_hashes"),
        Index("ix_entry_quarantine_application", "application_id"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(Integer)
    application_id: Mapped[int] = mapped_column(Integer)
    package_event_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[str] = mapped_column(String(41))
    document_version: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    fingerprint: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    media_type: Mapped[str] = mapped_column(String(32))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    policy: Mapped[dict] = mapped_column(_ServiceJSON)
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    content: Mapped[bytes] = mapped_column(LargeBinary, deferred=True)

    @validates("command", "policy")
    def _freeze(self, key, value):
        return _ServiceJSON.freeze(value)


class EntryProcessEvent(DomainBase):
    """Root workflow envelope; each linked application keeps its own procedure."""
    __tablename__ = "entry_process_events"
    __table_args__ = (
        UniqueConstraint("id", "application_id", "case_id", "applicant_id", name="uq_entry_process_scope"),
        UniqueConstraint("application_id", "revision", name="uq_entry_process_revision"),
        UniqueConstraint("application_id", "request_key", name="uq_entry_process_request"),
        ForeignKeyConstraint(["application_id", "case_id", "applicant_id", "root_procedure"],
            ["entry_applications.id", "entry_applications.case_id", "entry_applications.applicant_id", "entry_applications.procedure"], name="fk_entry_process_root"),
        ForeignKeyConstraint(["active_application_id", "case_id", "applicant_id", "active_procedure"],
            ["entry_applications.id", "entry_applications.case_id", "entry_applications.applicant_id", "entry_applications.procedure"], name="fk_entry_process_active"),
        ForeignKeyConstraint(["previous_id", "application_id", "case_id", "applicant_id"],
            ["entry_process_events.id", "entry_process_events.application_id", "entry_process_events.case_id", "entry_process_events.applicant_id"], name="fk_entry_process_previous"),
        CheckConstraint("revision BETWEEN 1 AND 250", name="ck_entry_process_revision"),
        CheckConstraint("action IN ('initialize','link','attest','withdraw','transition','stop')", name="ck_entry_process_action"),
        CheckConstraint("(revision = 1 AND previous_id IS NULL AND action = 'initialize') OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id AND action != 'initialize')", name="ck_entry_process_initial"),
        CheckConstraint("length(request_hash) = 64 AND length(snapshot_hash) = 64", name="ck_entry_process_hashes"),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(Integer)
    case_id: Mapped[int] = mapped_column(Integer)
    applicant_id: Mapped[int] = mapped_column(Integer)
    root_procedure: Mapped[str] = mapped_column(String(24))
    active_application_id: Mapped[int] = mapped_column(Integer)
    active_procedure: Mapped[str] = mapped_column(String(24))
    revision: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(16))
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    policy: Mapped[dict | None] = mapped_column(_ServiceJSON(none_as_null=True), nullable=True)
    evidence: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates("command", "snapshot", "policy", "evidence")
    def _freeze(self, key, value): return _ServiceJSON.freeze(value)


class EntryProcessPin(DomainBase):
    """Relational source bindings for a process event, including dependency links."""
    __tablename__ = "entry_process_pins"
    __table_args__ = (
        ForeignKeyConstraint(["event_id", "root_id", "case_id", "applicant_id"],
            ["entry_process_events.id", "entry_process_events.application_id", "entry_process_events.case_id", "entry_process_events.applicant_id"], name="fk_entry_process_pin_parent"),
        ForeignKeyConstraint(["application_id", "case_id", "applicant_id", "procedure"],
            ["entry_applications.id", "entry_applications.case_id", "entry_applications.applicant_id", "entry_applications.procedure"], name="fk_entry_process_pin_application"),
        ForeignKeyConstraint(["application_event_id", "application_id"],
            ["entry_application_events.id", "entry_application_events.application_id"], name="fk_entry_process_pin_app_event"),
        ForeignKeyConstraint(["package_event_id", "application_id", "case_id"],
            ["entry_document_package_events.id", "entry_document_package_events.application_id", "entry_document_package_events.case_id"], name="fk_entry_process_pin_package"),
        ForeignKeyConstraint(["issued_id", "application_id", "case_id"],
            ["entry_issued_revisions.id", "entry_issued_revisions.application_id", "entry_issued_revisions.case_id"], name="fk_entry_process_pin_issued"),
        ForeignKeyConstraint(["profile_id", "applicant_id", "case_id"],
            ["entry_applicant_profiles.id", "entry_applicant_profiles.applicant_id", "entry_applicant_profiles.case_id"], name="fk_entry_process_pin_profile"),
        ForeignKeyConstraint(["attestation_id", "root_id", "case_id", "applicant_id"],
            ["entry_process_events.id", "entry_process_events.application_id", "entry_process_events.case_id", "entry_process_events.applicant_id"], name="fk_entry_process_pin_attestation"),
        CheckConstraint("ordinal BETWEEN 1 AND 160", name="ck_entry_process_pin_ordinal"),
        CheckConstraint("kind IN ('application','application_event','package','issued','profile','attestation','payment','contract')", name="ck_entry_process_pin_kind"),
        CheckConstraint("(CASE WHEN application_event_id IS NULL THEN 0 ELSE 1 END + CASE WHEN package_event_id IS NULL THEN 0 ELSE 1 END + CASE WHEN issued_id IS NULL THEN 0 ELSE 1 END + CASE WHEN profile_id IS NULL THEN 0 ELSE 1 END + CASE WHEN attestation_id IS NULL THEN 0 ELSE 1 END + CASE WHEN payment_id IS NULL THEN 0 ELSE 1 END + CASE WHEN contract_event_id IS NULL THEN 0 ELSE 1 END) = CASE WHEN kind = 'application' THEN 0 ELSE 1 END", name="ck_entry_process_pin_one_source"),
        CheckConstraint("kind = 'application' OR (kind = 'application_event' AND application_event_id IS NOT NULL) OR (kind = 'package' AND package_event_id IS NOT NULL) OR (kind = 'issued' AND issued_id IS NOT NULL) OR (kind = 'profile' AND profile_id IS NOT NULL) OR (kind = 'attestation' AND attestation_id IS NOT NULL AND attestation_id < event_id) OR (kind = 'payment' AND payment_id IS NOT NULL) OR (kind = 'contract' AND contract_event_id IS NOT NULL)", name="ck_entry_process_pin_source_kind"),
        CheckConstraint("length(source_hash) = 64", name="ck_entry_process_pin_hash"),
    )
    event_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ordinal: Mapped[int] = mapped_column(Integer, primary_key=True)
    root_id: Mapped[int] = mapped_column(Integer)
    case_id: Mapped[int] = mapped_column(Integer)
    applicant_id: Mapped[int] = mapped_column(Integer)
    application_id: Mapped[int] = mapped_column(Integer)
    procedure: Mapped[str] = mapped_column(String(24))
    fact: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(String(24))
    source_hash: Mapped[str] = mapped_column(String(64))
    application_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    package_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    issued_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    attestation_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payment_id: Mapped[int | None] = mapped_column(ForeignKey("service_payments.id"), nullable=True)
    contract_event_id: Mapped[int | None] = mapped_column(ForeignKey("service_events.id"), nullable=True)


class EntryPortalReceipt(DomainBase):
    """Untrusted structured observation, never an application decision."""
    __tablename__ = 'entry_portal_receipts'
    __table_args__ = (
        UniqueConstraint('id', 'case_id', name='uq_entry_portal_receipt_scope'),
        UniqueConstraint('case_id', 'request_key', name='uq_entry_portal_receipt_request'),
        UniqueConstraint('source_namespace', 'channel', 'transport_id', name='uq_entry_portal_receipt_transport'),
        CheckConstraint("channel IN ('paste','portal','official_document')", name='ck_entry_portal_receipt_channel'),
        CheckConstraint('raw_bytes BETWEEN 1 AND 16384', name='ck_entry_portal_receipt_size'),
        CheckConstraint('length(raw_sha256) = 64 AND length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_entry_portal_receipt_hashes'),
        Index('ix_entry_portal_receipt_case_id', 'case_id', 'id'),
        Index('ix_entry_portal_receipt_content', 'source_namespace', 'raw_sha256'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    case_id: Mapped[int] = mapped_column(ForeignKey('service_cases.id'))
    source_namespace: Mapped[str] = mapped_column(String(80))
    channel: Mapped[str] = mapped_column(String(24))
    transport_id: Mapped[str] = mapped_column(String(160))
    raw_sha256: Mapped[str] = mapped_column(String(64))
    raw_bytes: Mapped[int] = mapped_column(Integer)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    captures: Mapped[dict] = mapped_column(_ServiceJSON)
    policy: Mapped[dict] = mapped_column(_ServiceJSON)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates('command', 'captures', 'policy')
    def _freeze(self, key, value): return _ServiceJSON.freeze(value)


class EntryPortalAction(DomainBase):
    """Immutable correlation and independent confirmation, with exact cycle pins."""
    __tablename__ = 'entry_portal_actions'
    __table_args__ = (
        UniqueConstraint('id', 'receipt_id', 'case_id', name='uq_entry_portal_action_scope'),
        UniqueConstraint('receipt_id', 'revision', name='uq_entry_portal_action_revision'),
        UniqueConstraint('receipt_id', 'request_key', name='uq_entry_portal_action_request'),
        UniqueConstraint('applied_event_id', name='uq_entry_portal_applied_event'),
        UniqueConstraint('applied_content_hash', name='uq_entry_portal_applied_content'),
        ForeignKeyConstraint(['receipt_id', 'case_id'], ['entry_portal_receipts.id', 'entry_portal_receipts.case_id'], name='fk_entry_portal_action_receipt'),
        ForeignKeyConstraint(['previous_id', 'receipt_id', 'case_id'], ['entry_portal_actions.id', 'entry_portal_actions.receipt_id', 'entry_portal_actions.case_id'], name='fk_entry_portal_action_previous'),
        ForeignKeyConstraint(['application_id', 'case_id', 'applicant_id', 'procedure'], ['entry_applications.id', 'entry_applications.case_id', 'entry_applications.applicant_id', 'entry_applications.procedure'], name='fk_entry_portal_action_application'),
        ForeignKeyConstraint(['head_id', 'application_id'], ['entry_application_events.id', 'entry_application_events.application_id'], name='fk_entry_portal_action_head'),
        ForeignKeyConstraint(['cycle_id', 'application_id'], ['entry_application_events.id', 'entry_application_events.application_id'], name='fk_entry_portal_action_cycle'),
        ForeignKeyConstraint(['applied_event_id', 'application_id'], ['entry_application_events.id', 'entry_application_events.application_id'], name='fk_entry_portal_action_event'),
        CheckConstraint('revision BETWEEN 1 AND 64', name='ck_entry_portal_action_revision'),
        CheckConstraint("action IN ('correlate','confirm','dismiss')", name='ck_entry_portal_action_kind'),
        CheckConstraint('(revision = 1 AND previous_id IS NULL) OR (revision > 1 AND previous_id IS NOT NULL AND previous_id < id)', name='ck_entry_portal_action_previous'),
        CheckConstraint('(application_id IS NULL AND applicant_id IS NULL AND procedure IS NULL AND head_id IS NULL AND cycle_id IS NULL) OR (application_id IS NOT NULL AND applicant_id IS NOT NULL AND procedure IS NOT NULL AND head_id IS NOT NULL AND cycle_id IS NOT NULL)', name='ck_entry_portal_action_binding'),
        CheckConstraint("(applied_event_id IS NULL AND applied_content_hash IS NULL) OR (action = 'confirm' AND applied_event_id IS NOT NULL AND applied_content_hash IS NOT NULL AND length(applied_content_hash) = 64)", name='ck_entry_portal_action_applied'),
        CheckConstraint('length(request_hash) = 64 AND length(snapshot_hash) = 64', name='ck_entry_portal_action_hashes'),
    )
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receipt_id: Mapped[int] = mapped_column(Integer)
    case_id: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    previous_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action: Mapped[str] = mapped_column(String(16))
    application_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applicant_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    procedure: Mapped[str | None] = mapped_column(String(24), nullable=True)
    head_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cycle_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_event_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    applied_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    request_key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    snapshot_hash: Mapped[str] = mapped_column(String(64))
    command: Mapped[dict] = mapped_column(_ServiceJSON)
    snapshot: Mapped[dict] = mapped_column(_ServiceJSON)
    policy: Mapped[dict | None] = mapped_column(_ServiceJSON(none_as_null=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    @validates('command', 'snapshot', 'policy')
    def _freeze(self, key, value): return _ServiceJSON.freeze(value)


ENTRY_IMMUTABLE_MODELS = (*ENTRY_STORAGE_MODELS, EntryQualification, *ENTRY_APPLICATION_MODELS, EntryDocumentRevision, EntryIssuedRevision, EntryApplicantProfile, EntryDeadlineRevision, KnowledgeDecision, KnowledgePublicationEvent, KnowledgePublicationUnit, EntryDocumentPackageEvent, EntryQuarantinedFile, EntryProcessEvent, EntryProcessPin, EntryPortalReceipt, EntryPortalAction)


def _entry_immutable(mapper, connection, target):
    raise DomainError("entry review snapshots are immutable; create a new revision")


for _entry_model in ENTRY_IMMUTABLE_MODELS:
    event.listen(_entry_model, "before_update", _entry_immutable)
    event.listen(_entry_model, "before_delete", _entry_immutable)


@event.listens_for(Session, "do_orm_execute")
def _entry_reject_bulk(state):
    if state.is_update or state.is_delete:
        table = getattr(state.statement, "table", None)
        if table is not None and table.name in {m.__tablename__ for m in ENTRY_IMMUTABLE_MODELS}:
            raise DomainError("bulk writes bypass entry snapshot invariants")


@event.listens_for(StayInterval, "before_insert")
def _stay_interval_matches_snapshot(mapper, connection, target):
    parent = connection.execute(select(StayHistory.snapshot, StayHistory.created_by).where(
        StayHistory.id == target.history_id, StayHistory.contact_id == target.contact_id)).first()
    expected = next((r for r in parent.snapshot["intervals"] if r["ref"] == target.ref), None) if parent else None
    if expected is None:
        raise DomainError("interval must belong to its immutable history snapshot")
    for key, value in expected.items():
        actual = getattr(target, key)
        if isinstance(actual, date):
            actual = actual.isoformat()
        if actual != value:
            raise DomainError("interval must match its immutable history snapshot")
    if target.confirmed_by != (parent.created_by if target.confirmed else None):
        raise DomainError("interval confirmation must name its recording administrator")


@event.listens_for(WorkCalendarDay, "before_insert")
def _work_day_matches_snapshot(mapper, connection, target):
    document = connection.scalar(select(WorkCalendar.document).where(WorkCalendar.id == target.calendar_id))
    expected = next((r for r in document["days"] if r["date"] == target.day.isoformat()), None) if document else None
    actual = {"date": target.day.isoformat(), "is_working": target.is_working, "kind": target.kind,
              "title": target.title, "source_ref": target.source_ref}
    if actual != expected:
        raise DomainError("calendar day must match its immutable version")
