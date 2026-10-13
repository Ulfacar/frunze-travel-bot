"""Real downstream task failure rolls back receipt, independent pin and projection."""
import asyncio

import pytest
from sqlalchemy import event, select, func

from app.config import settings
from app.domain import conditional_deadlines as service, entry_deadline_tasks
from app.domain.entry_storage import EntryStorageUnavailable
from app.domain.models import EntryDeadlineRevision, EntryConditionalEvidence, CalendarTask, CalendarTaskEvent
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock, setup, authority, arguments, write, preview, actual


def test_task_insert_failure_rolls_back_new_receipt_and_recovers_same_command(env,tmp_path,monkeypatch):
    prepared=setup(env,tmp_path)
    rule='KG.DL.REGISTRATION_EXTENSION'; allowed=authority(env,rule)
    args=arguments(env,prepared,rule,allowed)
    first,_=write(env,args)
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[allowed.document])
    task_args={k:v for k,v in args.items() if k not in ('applicant_id','authority')}
    enabled=asyncio.run(entry_deadline_tasks.reconcile_deadline_task(env['engine'],**task_args,enable=True))
    task_id=enabled['task']['id']
    change=actual.args(env,prepared)
    change['operation']['data']['value']['valid_until']='2026-11-02'
    actual.write(env,change)
    report=preview(env,args)
    request=args|dict(expected_revision=report['revision'],request_key='REVIEWER-ATOMIC',
        operation=dict(action='conditional_review',confirmed=True,evidence_hash=report['report']['evidence_hash']))
    async def state():
        async with env['sm']() as session:
            counts=[await session.scalar(select(func.count()).select_from(model))
                    for model in (EntryDeadlineRevision,EntryConditionalEvidence,CalendarTaskEvent)]
            row=await session.get(CalendarTask,task_id)
            return counts,row.scheduled_date.isoformat(),row.status
    before=asyncio.run(state())
    visited=[]
    def interrupt(connection,cursor,statement,parameters,context,executemany):
        if statement.lstrip().upper().startswith('INSERT INTO CALENDAR_TASK_EVENTS'):
            visited.append(True)
            raise RuntimeError('synthetic downstream task event failure')
    event.listen(env['engine'].sync_engine,'before_cursor_execute',interrupt)
    try:
        with pytest.raises(EntryStorageUnavailable):
            asyncio.run(service.record(env['engine'],**request))
    finally:
        event.remove(env['engine'].sync_engine,'before_cursor_execute',interrupt)
    assert visited==[True]
    assert asyncio.run(state())==before
    saved=asyncio.run(service.record(env['engine'],**request))
    assert saved['revision']==2
    after=asyncio.run(state())
    assert after[0][:2]==[2,2] and after[1]=='2026-11-02'
    assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==saved
    assert asyncio.run(state())==after
