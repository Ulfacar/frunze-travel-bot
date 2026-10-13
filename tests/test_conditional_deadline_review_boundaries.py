"""Source-shaped connected negatives for retained-current and restore semantics."""
import asyncio
from datetime import date,datetime,timedelta,timezone

import pytest

from app.config import settings
from app.domain import conditional_deadlines as service,conditional_deadline_sources as sources
from app.domain import entry_deadlines,entry_deadline_tasks
from app.domain.calendar_tasks import CalendarTaskService
from app.domain.models import CalendarTask
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock,setup,authority,arguments,write,actual


def task_args(args):
    return {k:v for k,v in args.items() if k not in ('applicant_id','authority')}


def test_future_retained_review_is_not_current_after_clock_rollback(env,tmp_path,monkeypatch):
    prepared=setup(env,tmp_path)
    rule='KG.DL.INTERNAL_EAEU_REG_REVIEW'; allowed=authority(env,rule)
    args=arguments(env,prepared,rule,allowed)
    at=datetime(2026,10,13,10,tzinfo=timezone.utc)
    monkeypatch.setattr(service,'_now',lambda:at+timedelta(seconds=2))
    monkeypatch.setattr(sources,'_now',lambda:at+timedelta(seconds=2))
    saved,request=write(env,args)
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[allowed.document])
    current=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**task_args(args)))
    assert current['conditional_current']['review_due_on']==saved['summary']['review_due_on']
    monkeypatch.setattr(service,'_now',lambda:at+timedelta(seconds=1))
    monkeypatch.setattr(sources,'_now',lambda:at+timedelta(seconds=1))
    reversed_view=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**task_args(args)))
    assert reversed_view['conditional_current']['review_due_on'] is None, reversed_view['conditional_current']
    assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==saved


def test_restore_with_missing_actual_anchor_cannot_cancel_manual_schedule(env,tmp_path,monkeypatch):
    prepared=setup(env,tmp_path)
    rule='KG.DL.INTERNAL_EAEU_REG_REVIEW'; allowed=authority(env,rule)
    args=arguments(env,prepared,rule,allowed)
    write(env,args)
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[allowed.document])
    task=asyncio.run(entry_deadline_tasks.reconcile_deadline_task(env['engine'],**task_args(args),enable=True))
    task_id=task['task']['id']
    async def move():
        async with env['sm']() as session:
            async with session.begin():
                row=await session.get(CalendarTask,task_id)
                await CalendarTaskService.reschedule(session,row,new_date=date(2026,11,2),actor='admin')
    asyncio.run(move())
    withdrawal=actual.args(env,prepared,policy=None)
    withdrawal['operation']=dict(action='withdraw',confirmed=True,data=dict(on='2026-10-13',reason='wrong_document',proof='d'*64))
    actual.write(env,withdrawal)
    view=asyncio.run(entry_deadline_tasks.read_deadline_task(env['engine'],**task_args(args)))
    assert view['due_on'] is None and view['current']['attention']=='schedule_conflict'
    with pytest.raises((EntryStorageInvalid,EntryStorageConflict,PermissionDenied)):
        asyncio.run(entry_deadline_tasks.reconcile_deadline_task(env['engine'],**task_args(args),restore=True,expected_token=view['current']['token']))
    restored=asyncio.run(entry_deadline_tasks.read_deadline_task(env['engine'],**task_args(args)))
    assert restored['current']['task']['status']=='rescheduled'
    assert restored['current']['task']['date']=='2026-11-02'
