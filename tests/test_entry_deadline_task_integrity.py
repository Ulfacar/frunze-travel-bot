"""Regression cases promoted from independent E619 reviewer/auditor probes."""
import asyncio
import json
from datetime import date

import pytest
from sqlalchemy import text

from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_deadline_tasks import seed, sync, read, sql, args
from tests.test_entry_deadlines import write, manual
from tests.test_admin_kg_deadline_tasks import form, post


def test_restore_form_rejects_unseen_new_source(env):
    app=seed(env); initial=sync(env,app,enable=True)
    sql(env,"UPDATE calendar_tasks SET scheduled_date='2026-10-01' WHERE id=:id",id=initial['task']['id'])
    write(env,app,'manual',manual(reason='corrected_date',due_on='2026-10-19'))
    old=read(env,app); consent=form(env,app,'restore')
    assert old['due_on']=='2026-10-19' and old['current']['attention']=='schedule_conflict'
    write(env,app,'manual',manual(reason='corrected_date',due_on='2026-10-18'))
    assert read(env,app)['due_on']=='2026-10-18'
    result=post(env,app,consent)
    assert result.status_code==409, (result.status_code,read(env,app)['current'])
    assert read(env,app)['current']['task']['date']=='2026-10-01'


def test_binding_audit_rejects_boolean_identity(env):
    app=seed(env); state=sync(env,app,enable=True)
    assert state['binding_id']==1
    row=sql(env,"SELECT id,detail FROM calendar_task_events WHERE event='deadline_bound'")[0]
    evidence=json.loads(row.detail); assert type(evidence['binding']) is int
    evidence['binding']=True
    sql(env,'UPDATE calendar_task_events SET detail=:detail WHERE id=:id',detail=json.dumps(evidence),id=row.id)
    with pytest.raises(EntryStorageInvalid): read(env,app)


def calendar_cancellation_race(env,monkeypatch):
    import app.admin.router as ar
    from app.domain.calendar_tasks import CalendarTaskService
    from app.domain.entry_deadlines import record_deadline_operation
    app=seed(env); initial=sync(env,app,enable=True)
    original=CalendarTaskService.get
    async def run():
        loaded=asyncio.Event(); resume=asyncio.Event()
        async def paused_get(session,task_id):
            task=await original(session,task_id)
            loaded.set(); await asyncio.wait_for(resume.wait(),10)
            return task
        monkeypatch.setattr(CalendarTaskService,'get',paused_get)
        pending=asyncio.create_task(ar._apply_calendar_action(initial['task']['id'],{'login':'medina'},'reschedule',new_date=date(2026,10,25)))
        try:
            await asyncio.wait_for(loaded.wait(),10)
            await record_deadline_operation(env['engine'],**args(env,app),expected_revision=2,request_key='clear-race',operation=dict(action='clear',data=dict(reason='wrong_document'),confirmed=True))
            async with env['engine'].connect() as conn:
                assert (await conn.execute(text('SELECT status FROM calendar_tasks WHERE id=:id'),dict(id=initial['task']['id']))).scalar_one()=='cancelled'
        finally: resume.set()
        await asyncio.wait_for(pending,10)
    asyncio.run(run())
    state=read(env,app)
    assert state['due_on'] is None
    assert state['current']['task']['status']=='cancelled', state['current']

import asyncio
import json

import pytest

from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_deadline_tasks import seed, sync, read, sql, act


def test_existing_action_retry_rejects_typed_receipt_corruption(env):
    app=seed(env); initial=sync(env,app,enable=True)
    act(env,app,'escalate',state=initial,key='typed-receipt',reason='urgent')
    row=sql(env,"SELECT id,detail FROM calendar_task_events WHERE event='deadline_action'")[0]
    receipt=json.loads(row.detail); assert receipt['command']['binding']==1
    receipt['command']['binding']=True
    sql(env,'UPDATE calendar_task_events SET detail=:detail WHERE id=:id',detail=json.dumps(receipt),id=row.id)
    with pytest.raises(EntryStorageInvalid): act(env,app,'escalate',state=initial,key='typed-receipt',reason='urgent')


def test_generic_calendar_refuses_claimed_deadline_cancellation(env):
    app=seed(env); initial=sync(env,app,enable=True)
    sql(env,"UPDATE calendar_tasks SET claimed_by='synthetic-worker',claimed_at=CURRENT_TIMESTAMP WHERE id=:id",id=initial['task']['id'])
    response=env['client'].post(f"/admin/calendar/task/{initial['task']['id']}/cancel",data={},follow_redirects=False)
    assert response.status_code==303
    assert read(env,app)['current']['task']['status']=='planned'

import pytest

from app.domain import entry_deadline_tasks as tasks
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_deadline_tasks import seed, sync, read, act, sql


def test_missing_bound_task_pointer_fails_closed_without_duplicate(env):
    app = seed(env)
    initial = sync(env, app, enable=True)
    assert read(env, app)['current'] == initial
    sql(env, 'UPDATE entry_deadline_tasks SET task_id=NULL WHERE id=:id', id=initial['binding_id'])
    with pytest.raises(EntryStorageInvalid):
        read(env, app)
    with pytest.raises(EntryStorageInvalid):
        sync(env, app)
    assert sql(env, "SELECT count(*) FROM calendar_tasks WHERE service_case_id=:case AND kind='followup'", case=env['cases']['visa'])[0][0] == 1


@pytest.mark.parametrize('action', ['complete', 'cancel'])
def test_escalation_capacity_preserves_terminal_action(env, monkeypatch, action):
    app = seed(env)
    initial = sync(env, app, enable=True)
    monkeypatch.setattr(tasks, 'MAX_ACTIONS', 2)
    raised = act(env, app, 'escalate', state=initial, key='raise-1', reason='urgent')
    raised = act(env, app, 'escalate', state=raised, key='raise-2', reason='needs_review')
    final = act(env, app, action, state=raised, key='terminal')
    assert final['task']['status'] == {'complete':'completed', 'cancel':'cancelled'}[action]
    assert act(env, app, action, state=raised, key='terminal') == final
    assert sql(env,"SELECT count(*) FROM calendar_task_events WHERE event='deadline_action'")[0][0] == 3
    with pytest.raises(EntryStorageInvalid, match='action_limit'):
        act(env, app, 'escalate', state=final, key='overflow', reason='urgent')
    # Even an old exact retry must not bypass an over-limit materialized history.
    sql(env,"INSERT INTO calendar_task_events(task_id,event,actor,detail,created_at) SELECT task_id,event,actor,detail,created_at FROM calendar_task_events WHERE event='deadline_action' ORDER BY id LIMIT 1")
    with pytest.raises(EntryStorageInvalid, match='action_limit'):
        act(env, app, 'escalate', state=initial, key='raise-1', reason='urgent')

import pytest
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_deadline_tasks import seed, sync, read, sql


def test_active_binding_cannot_be_replaced_by_null_waiting_pair(env):
    app=seed(env)
    initial=sync(env,app,enable=True)
    assert initial['attention']=='' and initial['task']
    sql(env,'UPDATE entry_deadline_tasks SET task_id=NULL,expected_date=NULL WHERE id=:id',id=initial['binding_id'])
    with pytest.raises(EntryStorageInvalid):read(env,app)
    with pytest.raises(EntryStorageInvalid):sync(env,app)
    assert sql(env,'SELECT count(*) FROM calendar_tasks WHERE service_case_id=:case',case=env['cases']['visa'])[0][0]==1


@pytest.mark.parametrize('mode',['unknown_date','missing_owner'])
def test_legitimate_no_task_waiting_remains_readable_and_idempotent(env,mode):
    app=seed(env,confirmed=mode!='unknown_date')
    if mode=='missing_owner':
        sql(env,"UPDATE service_cases SET owner_login='' WHERE id=:id",id=env['cases']['visa'])
    current=sync(env,app,enable=True)
    assert current['task'] is None and current['attention']==mode
    assert read(env,app)['current']==current
    assert sync(env,app)==current


@pytest.mark.parametrize('field', ['binding', 'deadline', 'task'])
def test_binding_audit_rejects_integral_float_identity(env, field):
    app=seed(env); state=sync(env,app,enable=True)
    row=sql(env,"SELECT id,detail FROM calendar_task_events WHERE event='deadline_bound'")[0]
    evidence=json.loads(row.detail)
    if field == 'binding': evidence['binding']=float(evidence['binding'])
    elif field == 'deadline': evidence['after']['deadline']=float(evidence['after']['deadline'])
    else: evidence['after']['task']['id']=float(evidence['after']['task']['id'])
    sql(env,'UPDATE calendar_task_events SET detail=:detail WHERE id=:id',detail=json.dumps(evidence),id=row.id)
    with pytest.raises(EntryStorageInvalid): read(env,app)


def test_stale_restore_owner_change_requires_fresh_consent(env):
    app=seed(env); initial=sync(env,app,enable=True)
    sql(env,"UPDATE calendar_tasks SET scheduled_date='2026-10-01' WHERE id=:id",id=initial['task']['id'])
    consent=form(env,app,'restore')
    sql(env,"UPDATE service_cases SET owner_login='next-manager' WHERE id=:id",id=env['cases']['visa'])
    assert post(env,app,consent).status_code == 409
    assert read(env,app)['current']['task']['date']=='2026-10-01'
    assert post(env,app,form(env,app,'restore')).status_code == 303
    state=read(env,app)['current']['task']
    assert state['owner']=='next-manager' and state['date']=='2026-10-20'


@pytest.mark.parametrize('writer', ['calendar', 'conversation'])
@pytest.mark.parametrize('action', ['complete', 'cancel', 'reschedule'])
def test_both_calendar_writers_refuse_claimed_bound_task(env, writer, action):
    import app.admin.router as ar
    app=seed(env); initial=sync(env,app,enable=True)
    sql(env,"UPDATE calendar_tasks SET user_id='synthetic-user',claimed_by='synthetic-worker',claimed_at=CURRENT_TIMESTAMP WHERE id=:id",id=initial['task']['id'])
    call=ar._apply_calendar_action if writer=='calendar' else ar._apply_task_action
    positional=[] if writer=='calendar' else ['synthetic-user']
    asyncio.run(call(*positional,initial['task']['id'],{'login':'medina'},action,new_date=date(2026,10,25)))
    current=read(env,app)['current']['task']
    assert current['status']=='planned' and current['date']=='2026-10-20'
