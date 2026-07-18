"""Sprint 1 calendar-task service layer.

Transactional, invariant-aware operations over CalendarTask/CalendarTaskEvent.
Ownership is per ``manager_id`` (login). Every lifecycle action records a
CalendarTaskEvent (authoritative history). Times use the repo's Bishkek convention
(UTC+6, no DST): ``scheduled_date`` is the Bishkek calendar day; ``scheduled_at`` is
an exact UTC instant (NULL = no exact time). client/date/time/owner come only from
arguments the caller read from the DB; only ``ai_summary`` may be AI-written.

Takes an ``AsyncSession`` from the caller. NOT auto-wired into live takeover
(reassign_open_tasks is a service exercised by tests / future WP3).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    ACTIVE_TASK_STATUSES, TASK_KINDS, TASK_PRIORITIES, CalendarTask,
    CalendarTaskEvent, DomainError, _now,
)
from app.domain.models import DIRECTIONS

BISHKEK_UTC_OFFSET = 6      # Kyrgyzstan UTC+6, no DST (matches morning_brief/followup)


def bishkek_now(now: datetime | None = None) -> datetime:
    base = now or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(hours=BISHKEK_UTC_OFFSET)


def bishkek_today(now: datetime | None = None) -> date:
    return bishkek_now(now).date()


async def _log_event(session: AsyncSession, task: CalendarTask, event: str, *,
                     actor: str = "", from_status: str | None = None,
                     to_status: str | None = None, from_at: datetime | None = None,
                     to_at: datetime | None = None, detail: str = "") -> None:
    session.add(CalendarTaskEvent(
        task_id=task.id, event=event, actor=actor or "", from_status=from_status,
        to_status=to_status, from_at=from_at, to_at=to_at, detail=detail))
    await session.flush()


class CalendarTaskService:
    @staticmethod
    async def create(session: AsyncSession, *, manager_id: str, direction: str, kind: str,
                     scheduled_date: date, contact_id: int, scheduled_at: datetime | None = None,
                     request_id: int | None = None, assignment_id: int | None = None,
                     user_id: str = "", priority: str = "normal", comment: str = "",
                     created_by: str = "", ai_summary: str = "") -> CalendarTask:
        manager_id = (manager_id or "").strip().lower()
        if not manager_id:
            raise DomainError("task requires a manager_id")
        if direction not in DIRECTIONS:
            raise DomainError(f"unknown direction {direction!r}")
        if kind not in TASK_KINDS:
            raise DomainError(f"unknown task kind {kind!r}")
        if priority not in TASK_PRIORITIES:
            raise DomainError(f"unknown priority {priority!r}")
        task = CalendarTask(
            contact_id=contact_id, request_id=request_id, assignment_id=assignment_id,
            manager_id=manager_id, direction=direction, user_id=user_id or "", kind=kind,
            priority=priority, status="planned", comment=comment or "",
            ai_summary=ai_summary or "", scheduled_date=scheduled_date,
            scheduled_at=scheduled_at, created_by=(created_by or "").strip().lower())
        session.add(task)
        await session.flush()
        await _log_event(session, task, "created", actor=created_by,
                         to_status="planned", to_at=scheduled_at)
        return task

    @staticmethod
    async def reschedule(session: AsyncSession, task: CalendarTask, *, new_date: date,
                         new_at: datetime | None = None, actor: str = "") -> CalendarTask:
        if task.status in ("completed", "cancelled"):
            raise DomainError(f"cannot reschedule a {task.status} task")
        from_at = task.scheduled_at
        prev = task.status
        task.scheduled_date = new_date
        task.scheduled_at = new_at
        task.status = "rescheduled"          # still active (see ACTIVE_TASK_STATUSES)
        await session.flush()
        await _log_event(session, task, "rescheduled", actor=actor, from_status=prev,
                         to_status="rescheduled", from_at=from_at, to_at=new_at)
        return task

    @staticmethod
    async def complete(session: AsyncSession, task: CalendarTask, *, actor: str = "") -> CalendarTask:
        if task.status in ("completed", "cancelled"):
            raise DomainError(f"cannot complete a {task.status} task")
        prev = task.status
        task.status = "completed"
        task.completed_at = _now()
        await session.flush()
        await _log_event(session, task, "completed", actor=actor,
                         from_status=prev, to_status="completed")
        return task

    @staticmethod
    async def cancel(session: AsyncSession, task: CalendarTask, *, actor: str = "") -> CalendarTask:
        if task.status in ("completed", "cancelled"):
            raise DomainError(f"cannot cancel a {task.status} task")
        prev = task.status
        task.status = "cancelled"
        task.cancelled_at = _now()
        await session.flush()
        await _log_event(session, task, "cancelled", actor=actor,
                         from_status=prev, to_status="cancelled")
        return task

    @staticmethod
    async def reassign_open_tasks(session: AsyncSession, *, contact_id: int, direction: str,
                                  new_manager_id: str, actor: str = "") -> int:
        """Move every ACTIVE task for (contact, direction) to a new owner. Returns count.
        Service only — not wired into live takeover (WP3)."""
        new_manager_id = (new_manager_id or "").strip().lower()
        rows = (await session.scalars(select(CalendarTask).where(
            CalendarTask.contact_id == contact_id,
            CalendarTask.direction == direction,
            CalendarTask.status.in_(ACTIVE_TASK_STATUSES),
            CalendarTask.manager_id != new_manager_id))).all()
        for task in rows:
            old = task.manager_id
            task.manager_id = new_manager_id
            await session.flush()
            await _log_event(session, task, "reassigned", actor=actor,
                             detail=f"{old}->{new_manager_id}")
        return len(rows)

    # --- queries ---------------------------------------------------------------

    @staticmethod
    async def get(session: AsyncSession, task_id: int) -> CalendarTask | None:
        return await session.get(CalendarTask, task_id)

    @staticmethod
    async def list_for_manager(session: AsyncSession, manager_id: str, *, date_from: date,
                               date_to: date, include_terminal: bool = False) -> list[CalendarTask]:
        stmt = select(CalendarTask).where(
            CalendarTask.manager_id == (manager_id or "").strip().lower(),
            CalendarTask.scheduled_date >= date_from,
            CalendarTask.scheduled_date <= date_to)
        if not include_terminal:
            stmt = stmt.where(CalendarTask.status.in_(ACTIVE_TASK_STATUSES))
        stmt = stmt.order_by(CalendarTask.scheduled_date, CalendarTask.scheduled_at.nulls_last(),
                             CalendarTask.id)
        return list((await session.scalars(stmt)).all())

    @staticmethod
    async def list_all(session: AsyncSession, *, date_from: date, date_to: date,
                       include_terminal: bool = False) -> list[CalendarTask]:
        """Full-admin view: every manager's tasks in the range."""
        stmt = select(CalendarTask).where(
            CalendarTask.scheduled_date >= date_from,
            CalendarTask.scheduled_date <= date_to)
        if not include_terminal:
            stmt = stmt.where(CalendarTask.status.in_(ACTIVE_TASK_STATUSES))
        stmt = stmt.order_by(CalendarTask.scheduled_date, CalendarTask.scheduled_at.nulls_last(),
                             CalendarTask.id)
        return list((await session.scalars(stmt)).all())

    @staticmethod
    async def list_for_contact(session: AsyncSession, contact_id: int) -> list[CalendarTask]:
        return list((await session.scalars(select(CalendarTask)
            .where(CalendarTask.contact_id == contact_id)
            .order_by(CalendarTask.scheduled_date.desc(), CalendarTask.id.desc()))).all())

    @staticmethod
    async def list_for_user(session: AsyncSession, user_id: str) -> list[CalendarTask]:
        return list((await session.scalars(select(CalendarTask)
            .where(CalendarTask.user_id == user_id)
            .order_by(CalendarTask.scheduled_date.desc(), CalendarTask.id.desc()))).all())

    @staticmethod
    async def today_for_manager(session: AsyncSession, manager_id: str,
                                day: date) -> list[CalendarTask]:
        return await CalendarTaskService.list_for_manager(
            session, manager_id, date_from=day, date_to=day, include_terminal=False)
