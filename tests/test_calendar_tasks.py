"""Sprint 1: calendar-task domain services. In-memory SQLite; WP0 guard active."""
import asyncio
from datetime import date, datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.calendar_tasks import CalendarTaskService, bishkek_today
from app.domain.models import CalendarTask, CalendarTaskEvent, Contact, DomainError

DAY = date(2026, 7, 20)


def run_with_db(scenario):
    async def _main():
        engine = create_async_engine("sqlite+aiosqlite://",
                                     connect_args={"check_same_thread": False},
                                     poolclass=StaticPool)
        async with engine.begin() as conn:
            from app.domain.models import DomainBase
            await conn.run_sync(DomainBase.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await scenario(sm)
        finally:
            await engine.dispose()
    asyncio.run(_main())


async def _contact(session) -> int:
    c = Contact()
    session.add(c)
    await session.flush()
    return c.id


async def _count(session, model) -> int:
    return await session.scalar(select(func.count()).select_from(model))


# --- create -------------------------------------------------------------------

def test_create_task_records_event_and_defaults():
    async def scenario(sm):
        async with sm() as s:
            cid = await _contact(s)
            t = await CalendarTaskService.create(
                s, manager_id="Medina", direction="visa", kind="call",
                scheduled_date=DAY, contact_id=cid, user_id="getvisa:996700111",
                comment="перезвонить", created_by="Medina")
            await s.commit()
            assert t.status == "planned" and t.manager_id == "medina"   # lowercased
            assert t.scheduled_at is None                                # no exact time
            ev = await s.scalar(select(CalendarTaskEvent).where(CalendarTaskEvent.task_id == t.id))
            assert ev.event == "created" and ev.to_status == "planned"
    run_with_db(scenario)


def test_create_with_exact_time():
    async def scenario(sm):
        async with sm() as s:
            cid = await _contact(s)
            at = datetime(2026, 7, 20, 8, 0, tzinfo=timezone.utc)   # 14:00 Bishkek
            t = await CalendarTaskService.create(
                s, manager_id="medina", direction="visa", kind="meeting",
                scheduled_date=DAY, scheduled_at=at, contact_id=cid, priority="high")
            assert t.scheduled_at == at and t.priority == "high"
    run_with_db(scenario)


@pytest.mark.parametrize("bad", [
    {"direction": "banking"}, {"kind": "teleport"}, {"priority": "urgent"},
    {"manager_id": "  "},
])
def test_create_validation(bad):
    async def scenario(sm):
        async with sm() as s:
            cid = await _contact(s)
            kw = dict(manager_id="medina", direction="visa", kind="call",
                      scheduled_date=DAY, contact_id=cid)
            kw.update(bad)
            with pytest.raises(DomainError):
                await CalendarTaskService.create(s, **kw)
    run_with_db(scenario)


# --- lifecycle transitions ----------------------------------------------------

def test_reschedule_complete_cancel():
    async def scenario(sm):
        async with sm() as s:
            cid = await _contact(s)
            t = await CalendarTaskService.create(
                s, manager_id="medina", direction="visa", kind="call",
                scheduled_date=DAY, contact_id=cid)
            new_at = datetime(2026, 7, 21, 5, 0, tzinfo=timezone.utc)
            await CalendarTaskService.reschedule(s, t, new_date=date(2026, 7, 21), new_at=new_at)
            assert t.status == "rescheduled" and t.scheduled_date == date(2026, 7, 21)
            await CalendarTaskService.complete(s, t)
            assert t.status == "completed" and t.completed_at is not None
            with pytest.raises(DomainError):        # cannot act on a terminal task
                await CalendarTaskService.cancel(s, t)
            await s.commit()
            events = (await s.scalars(select(CalendarTaskEvent.event)
                      .where(CalendarTaskEvent.task_id == t.id)
                      .order_by(CalendarTaskEvent.id))).all()
            assert events == ["created", "rescheduled", "completed"]
    run_with_db(scenario)


# --- reassignment moves active tasks ------------------------------------------

def test_reassign_open_tasks_moves_only_active():
    async def scenario(sm):
        async with sm() as s:
            cid = await _contact(s)
            active = await CalendarTaskService.create(
                s, manager_id="medina", direction="visa", kind="call",
                scheduled_date=DAY, contact_id=cid)
            done = await CalendarTaskService.create(
                s, manager_id="medina", direction="visa", kind="call",
                scheduled_date=DAY, contact_id=cid)
            await CalendarTaskService.complete(s, done)
            # other direction must NOT move
            other = await CalendarTaskService.create(
                s, manager_id="medina", direction="tours", kind="call",
                scheduled_date=DAY, contact_id=cid)
            moved = await CalendarTaskService.reassign_open_tasks(
                s, contact_id=cid, direction="visa", new_manager_id="Eliza", actor="admin")
            await s.commit()
            assert moved == 1
            assert active.manager_id == "eliza"      # active visa task moved (lowercased)
            assert done.manager_id == "medina"       # terminal task untouched
            assert other.manager_id == "medina"      # other direction untouched
            ev = await s.scalar(select(CalendarTaskEvent).where(
                CalendarTaskEvent.event == "reassigned"))
            assert ev.detail == "medina->eliza"
    run_with_db(scenario)


# --- queries ------------------------------------------------------------------

def test_list_for_manager_range_and_isolation():
    async def scenario(sm):
        async with sm() as s:
            cid = await _contact(s)
            await CalendarTaskService.create(s, manager_id="medina", direction="visa",
                                             kind="call", scheduled_date=DAY, contact_id=cid)
            await CalendarTaskService.create(s, manager_id="eliza", direction="visa",
                                             kind="call", scheduled_date=DAY, contact_id=cid)
            await CalendarTaskService.create(s, manager_id="medina", direction="visa",
                                             kind="call", scheduled_date=date(2026, 8, 1),
                                             contact_id=cid)
            await s.commit()
            mine = await CalendarTaskService.list_for_manager(
                s, "medina", date_from=DAY, date_to=DAY)
            assert len(mine) == 1 and mine[0].manager_id == "medina"
            today = await CalendarTaskService.today_for_manager(s, "eliza", DAY)
            assert len(today) == 1
            all_range = await CalendarTaskService.list_all(
                s, date_from=DAY, date_to=date(2026, 8, 31))
            assert len(all_range) == 3
    run_with_db(scenario)


def test_bishkek_today_offset():
    # 2026-07-20 20:00 UTC = 2026-07-21 02:00 Bishkek → next day
    assert bishkek_today(datetime(2026, 7, 20, 20, 0, tzinfo=timezone.utc)) == date(2026, 7, 21)
    assert bishkek_today(datetime(2026, 7, 20, 5, 0, tzinfo=timezone.utc)) == date(2026, 7, 20)
