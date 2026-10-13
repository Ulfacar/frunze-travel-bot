"""A valid generic-calendar edit cannot poison an explicit cancellation receipt."""
import asyncio
from datetime import date, datetime, timezone

from app.domain.calendar_tasks import CalendarTaskService
from app.domain.models import CalendarTask
from tests import test_work_review_tasks as baseline
from tests.test_work_review_tasks import (
    env, clock, review_clock, connected_clock, route_clock, admins, enforce_sqlite_foreign_keys,
)


def test_cancel_after_external_exact_time_stays_readable_and_retryable(env, tmp_path):
    baseline.setup(env, tmp_path)
    original = baseline.record(env, baseline.command(env))
    async def reschedule():
        async with env['sm']() as session:
            task = await session.get(CalendarTask, original['task_id'])
            await CalendarTaskService.reschedule(session, task, new_date=date(2026, 10, 15),
                new_at=datetime(2026, 10, 15, 9, tzinfo=timezone.utc), actor=task.manager_id)
            await session.commit()
    asyncio.run(reschedule())
    assert baseline.read(env)['current']['attention'] == 'schedule_conflict'
    request = baseline.command(env, 'cancel')
    cancelled = baseline.record(env, request)
    assert cancelled['snapshot']['task']['status'] == 'cancelled'
    assert baseline.record(env, request | {'authority': None}) == cancelled
    assert baseline.read(env, authority=None)['current']['task']['status'] == 'cancelled'
