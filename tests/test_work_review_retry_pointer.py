"""Historical pointer/audit verification must also protect exact retries."""
import asyncio
from datetime import date

import pytest

from app.domain.calendar_tasks import CalendarTaskService
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.models import ServiceCase
from tests import test_work_review_tasks as baseline
from tests.test_work_review_regressions import rewrite
from tests.test_work_review_tasks import (
    env, clock, review_clock, connected_clock, route_clock, admins,
    enforce_sqlite_foreign_keys,
)


def test_exact_retry_rejects_rehashed_pointer_to_unrelated_same_case_task(env, tmp_path):
    baseline.setup(env, tmp_path)
    request = baseline.command(env)
    saved = baseline.record(env, request)
    async def other_task():
        async with env['sm']() as session:
            case = await session.get(ServiceCase, env['cases']['visa'])
            task = await CalendarTaskService.create(
                session, manager_id=case.owner_login, direction='visa', kind='followup',
                contact_id=case.contact_id, scheduled_date=date(2026, 10, 16),
                comment='Unrelated retained-pointer negative control', created_by='admin')
            task.service_case_id = case.id
            await session.commit()
            return task.id
    unrelated_id = asyncio.run(other_task())
    assert unrelated_id != saved['task_id']
    def change(payload):
        payload['task_id'] = unrelated_id
        payload['snapshot']['task']['id'] = unrelated_id
    rewrite(env, saved['id'], change)
    with pytest.raises(EntryStorageInvalid):
        baseline.record(env, request | {'authority': None})
