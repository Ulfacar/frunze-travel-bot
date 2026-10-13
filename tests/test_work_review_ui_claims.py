"""The new review binding reaches both pre-existing calendar action writers."""
import asyncio
import pytest
from datetime import datetime,timezone
from sqlalchemy import select,func
from app.domain.models import CalendarTask,CalendarTaskEvent
from app.domain.entry_storage import EntryStorageInvalid
import app.admin.router as ar
from tests import test_admin_work_review as native
from tests.test_admin_work_review import (env,clock,review_clock,connected_clock,route_clock,admins,
    enforce_sqlite_foreign_keys,core,Form)


def test_claimed_review_task_blocks_both_generic_writers(env,tmp_path,monkeypatch):
    native.setup(env,tmp_path,monkeypatch)
    request=native.form(env)
    assert native.post(env,request).status_code==303
    task_id=core.read(env)['current']['task']['id']
    async def state(claim=None):
        async with env['sm']() as session:
            task=await session.get(CalendarTask,task_id)
            if claim is not None:
                task.claimed_by='synthetic-worker' if claim else None
                task.claimed_at=datetime(2026,10,12,15,tzinfo=timezone.utc) if claim else None
                await session.commit()
            return task.status,task.scheduled_date,await session.scalar(select(func.count()).select_from(CalendarTaskEvent))
    before=asyncio.run(state(True))
    manager={'login':'admin','is_admin':True,'is_superadmin':True}
    asyncio.run(ar._apply_calendar_action(task_id,manager,'cancel'))
    asyncio.run(ar._apply_task_action('',task_id,manager,'complete'))
    assert asyncio.run(state())==before
    page=env['client'].get(native.url(env))
    assert page.status_code==200 and 'Задача находится в обработке' in page.text
    assert 'id="work-review-cancel"' not in page.text and 'id="work-review-refresh"' not in page.text
    # Restored claim permits lookup under the same lock; the guard is not a
    # blanket rejection of every new task.
    asyncio.run(state(False))
    async def allowed():
        async with env['sm']() as session:
            return (await ar._calendar_task_for_action(session,task_id)).id
    assert asyncio.run(allowed())==task_id


def test_no_restore_promise_without_current_calculation(env,tmp_path,monkeypatch):
    from datetime import date
    native.setup(env,tmp_path,monkeypatch)
    assert native.post(env,native.form(env)).status_code==303
    task_id=core.read(env)['current']['task']['id']
    async def alter():
        from app.domain.calendar_tasks import CalendarTaskService
        async with env['sm']() as session:
            task=await session.get(CalendarTask,task_id)
            await CalendarTaskService.reschedule(session,task,new_date=date(2026,10,15),actor='admin')
            await session.commit()
    asyncio.run(alter())
    # Coherent positive: a genuinely current calculation can explicitly replace
    # the manual date. Then repeat the original unavailable-calculation probe.
    restore=native.form(env,'restore',language='en')
    assert native.post(env,restore,language='en').status_code==303
    assert core.read(env)['current']['task']['date']=='2026-10-16'
    asyncio.run(alter())
    monkeypatch.setattr(ar.settings,'kg_work_review_authorities',[])
    page=env['client'].get(native.url(env,'en'))
    assert page.status_code==200
    misleading=Form(page.text,'work-review-restore').data
    if misleading:
        assert native.post(env,misleading|{'confirmed':'yes'},language='en').status_code==303
        assert core.read(env,authority=None)['current']['task']['status']=='cancelled'
    assert not misleading,'Restore is offered without a current date and its actual effect is cancellation'
    before=core.counts(env)
    with pytest.raises(EntryStorageInvalid,match='current_evidence'):
        core.record(env,core.command(env,'restore',authority=None))
    assert core.counts(env)==before
    assert core.read(env,authority=None)['current']['task']['status']=='rescheduled'
