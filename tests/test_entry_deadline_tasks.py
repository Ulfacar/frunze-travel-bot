import asyncio
from datetime import date

import pytest
from sqlalchemy import select, text

from app.domain import entry_deadline_tasks as tasks
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.models import CalendarTask, CalendarTaskEvent
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_deadlines import write, manual
from tests.test_entry_deadline_sources import selection
from tests.test_entry_issued import setup, write as issued
from tests.test_entry_applications import enforce_sqlite_foreign_keys


def args(env, app):
    return dict(actor=ADMIN, case_id=env['cases']['visa'], application_id=app['id'], rule_unit_id='KG.DL.TEST')


def sync(env, app, **kwargs):
    return asyncio.run(tasks.reconcile_deadline_task(env['engine'], **args(env,app), **kwargs))


def read(env, app):
    return asyncio.run(tasks.read_deadline_task(env['engine'], **args(env,app)))


def act(env, app, action, state=None, key='action', **kwargs):
    state = state or read(env,app)['current']
    return asyncio.run(tasks.act_on_deadline_task(env['engine'], **args(env,app), binding_id=state['binding_id'],
        expected_token=state['token'], request_key=key, action=action, **kwargs))


def seed(env, *, confirmed=True):
    app=setup(env)
    write(env,app,'recalculate',selection(env))
    if confirmed: write(env,app,'manual',manual())
    return app


def sql(env, statement, **params):
    async def run():
        async with env['engine'].begin() as conn:
            result=await conn.execute(text(statement),params)
            return result.fetchall() if result.returns_rows else None
    return asyncio.run(run())


def test_explicit_enable_unknown_waiting_then_atomic_date_and_clear(env):
    app=seed(env,confirmed=False)
    assert not sync(env,app)['enabled']
    state=sync(env,app,enable=True)
    assert state['task'] is None and state['attention']=='unknown_date'
    assert sql(env,'SELECT count(*) FROM calendar_tasks WHERE id IN (SELECT task_id FROM entry_deadline_tasks)')[0][0]==0
    write(env,app,'manual',manual())
    current=read(env,app)['current']
    assert current['task']['date']=='2026-10-20' and current['task']['owner']=='medina'
    assert sync(env,app,enable=True)==current
    write(env,app,'clear',dict(reason='wrong_document'))
    stopped=read(env,app)['current']
    assert stopped['task']['status']=='cancelled' and stopped['attention']=='unknown_date'
    write(env,app,'manual',manual(due_on='2026-10-21'))
    new=read(env,app)
    assert new['current']['generation']==2 and new['current']['task']['id']!=current['task']['id']
    assert new['history'][1]['task']['status']=='cancelled'


def test_atomic_date_change_reuses_task_and_repeated_old_job_consumes_latest(env):
    app=seed(env);initial=sync(env,app,enable=True)
    write(env,app,'manual',manual(reason='corrected_date',due_on='2026-10-18'))
    latest=read(env,app)['current']
    assert latest['task']['id']==initial['task']['id'] and latest['task']['date']=='2026-10-18'
    assert sync(env,app,minimum_revision=1)==latest
    assert sync(env,app,minimum_revision=4)['waiting_for_revision']==4
    assert read(env,app)['current']==latest
    assert sql(env,'SELECT count(*) FROM calendar_tasks WHERE id IN (SELECT task_id FROM entry_deadline_tasks)')[0][0]==1


def test_actions_durable_receipts_and_completed_history_never_reopens_on_owner_change(env):
    app=seed(env);initial=sync(env,app,enable=True)
    escalated=act(env,app,'escalate',state=initial,reason='urgent')
    assert escalated['task']['priority']=='high' and escalated['task']['owner']=='medina'
    assert act(env,app,'escalate',state=initial,reason='urgent')==escalated
    with pytest.raises(EntryStorageConflict):act(env,app,'escalate',state=initial,reason='overdue')
    completed=act(env,app,'complete',key='done')
    sql(env,'UPDATE service_cases SET owner_login=:owner WHERE id=:id',owner='another-manager',id=env['cases']['visa'])
    assert sync(env,app)['task']==completed['task']
    assert not read(env,app)['current']['pending']
    write(env,app,'manual',manual(reason='corrected_date',due_on='2026-10-18'))
    now=read(env,app)
    assert now['current']['generation']==2 and now['current']['task']['owner']=='another-manager'
    assert now['history'][1]['task']['owner']=='medina' and now['history'][1]['task']['status']=='completed'
    assert act(env,app,'complete',state=escalated,key='done')['task']['status']=='completed'
    assert read(env,app)['current']['task']['status']=='planned'


def test_case_owner_change_and_missing_owner_waiting(env):
    app=seed(env);initial=sync(env,app,enable=True)
    sql(env,'UPDATE service_cases SET owner_login=:owner WHERE id=:id',owner='next-manager',id=env['cases']['visa'])
    with pytest.raises(EntryStorageConflict):act(env,app,'complete',state=initial)
    state=sync(env,app)
    assert state['task']['id']==initial['task']['id'] and state['task']['owner']=='next-manager'
    sql(env,"UPDATE service_cases SET owner_login='' WHERE id=:id",id=env['cases']['visa'])
    state=sync(env,app)
    assert state['attention']=='missing_owner' and state['task']['status']=='cancelled'
    sql(env,'UPDATE service_cases SET owner_login=:owner WHERE id=:id',owner='restored',id=env['cases']['visa'])
    restored=sync(env,app)
    assert restored['generation']==2 and restored['task']['owner']=='restored'


def test_claimed_unknown_outcome_never_blindly_cancelled_or_duplicated(env):
    app=seed(env);initial=sync(env,app,enable=True)
    sql(env,"UPDATE calendar_tasks SET claimed_by='worker',claimed_at=CURRENT_TIMESTAMP WHERE id=:id",id=initial['task']['id'])
    write(env,app,'clear',dict(reason='wrong_document'))
    state=read(env,app)['current']
    assert state['attention']=='claimed' and state['pending'] and state['task']['status']=='planned'
    with pytest.raises(EntryStorageConflict):act(env,app,'cancel')
    assert sync(env,app,enable=True)['task']['id']==initial['task']['id']
    sql(env,'UPDATE calendar_tasks SET claimed_at=NULL,claimed_by=NULL WHERE id=:id',id=initial['task']['id'])
    assert sync(env,app)['task']['status']=='cancelled'
    assert sql(env,'SELECT count(*) FROM calendar_tasks WHERE id IN (SELECT task_id FROM entry_deadline_tasks)')[0][0]==1


def test_manual_schedule_conflict_requires_explicit_current_token(env):
    app=seed(env);initial=sync(env,app,enable=True)
    sql(env,"UPDATE calendar_tasks SET scheduled_date='2026-10-01' WHERE id=:id",id=initial['task']['id'])
    write(env,app,'manual',manual(reason='corrected_date',due_on='2026-10-19'))
    conflict=read(env,app)['current']
    assert conflict['attention']=='schedule_conflict' and conflict['task']['date']=='2026-10-01'
    assert sync(env,app)['task']['date']=='2026-10-01'
    with pytest.raises(EntryStorageConflict):sync(env,app,restore=True,expected_token=initial['token'])
    restored=sync(env,app,restore=True,expected_token=conflict['token'])
    assert restored['task']['date']=='2026-10-19' and not restored['attention']
    with pytest.raises(EntryStorageConflict):act(env,app,'complete',state=initial)


def test_actual_travel_hook_invalidates_task_in_same_transaction(env):
    app=setup(env)
    travel=issued(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,source='stamp',passport_fingerprint='b'*64))
    write(env,app,'recalculate',selection(env,dict(kind='travel',id=travel['id'])))
    write(env,app,'manual',manual());sync(env,app,enable=True)
    issued(env,app,'travel',dict(direction='entry',on='2026-09-09',proof='c'*64,source='stamp',passport_fingerprint='b'*64))
    state=read(env,app)
    assert state['due_on'] is None and state['current']['task']['status']=='cancelled'


def test_cross_case_task_corruption_and_source_tamper_fail_closed(env):
    app=seed(env);state=sync(env,app,enable=True)
    sql(env,'UPDATE calendar_tasks SET service_case_id=:case WHERE id=:id',case=env['cases']['other'],id=state['task']['id'])
    with pytest.raises(EntryStorageInvalid,match='scope'):read(env,app)
    with pytest.raises(EntryStorageInvalid,match='scope'):sync(env,app)
    sql(env,'UPDATE calendar_tasks SET service_case_id=:case WHERE id=:id',case=env['cases']['visa'],id=state['task']['id'])
    sql(env,"UPDATE entry_deadline_revisions SET snapshot_hash=:hash",hash='0'*64)
    with pytest.raises(EntryStorageInvalid):act(env,app,'complete',state=state)
    assert sql(env,'SELECT status FROM calendar_tasks')[0][0]=='planned'


@pytest.mark.parametrize('actor',[None,{},Actor('manager'),Actor('bot',True)])
def test_auth_before_engine_and_payload(actor):
    values=dict(actor=actor,case_id=1,application_id=1,rule_unit_id='bad')
    for fn, extra in ((tasks.read_deadline_task,{}),(tasks.reconcile_deadline_task,{}),
        (tasks.act_on_deadline_task,dict(binding_id=1,expected_token='',request_key='',action='complete'))):
        with pytest.raises(PermissionDenied):asyncio.run(fn(None,**values,**extra))
    with pytest.raises(PermissionDenied):asyncio.run(tasks.reconcile_case_deadline_tasks(None,actor=actor,case_id=1))


def test_concurrent_enable_is_one_task_and_source_hook_rolls_back_atomically(env,monkeypatch):
    app=seed(env)
    async def race():
        return await asyncio.gather(*(tasks.reconcile_deadline_task(env['engine'],**args(env,app),enable=True) for _ in range(2)),return_exceptions=True)
    results=asyncio.run(race())
    assert any(isinstance(r,dict) for r in results)
    assert all(isinstance(r,(dict,EntryStorageConflict)) for r in results),results
    assert sql(env,'SELECT count(*) FROM calendar_tasks WHERE id IN (SELECT task_id FROM entry_deadline_tasks)')[0][0]==1
    original=tasks._log_event
    async def fail(session,task,event,**kwargs):
        if event=='deadline_bound':raise RuntimeError('synthetic crash before commit')
        return await original(session,task,event,**kwargs)
    monkeypatch.setattr(tasks,'_log_event',fail)
    with pytest.raises(EntryStorageUnavailable):write(env,app,'manual',manual(reason='corrected_date',due_on='2026-10-18'))
    assert read(env,app)['current']['task']['date']=='2026-10-20'
    assert sql(env,'SELECT count(*) FROM entry_deadline_revisions')[0][0]==2


def test_lost_commit_ack_retry_action_uses_existing_receipt(env,monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSessionTransaction
    app=seed(env);initial=sync(env,app,enable=True)
    original=AsyncSessionTransaction.__aexit__;once=True
    async def lost(self,*args_):
        nonlocal once
        result=await original(self,*args_)
        if once:
            once=False;raise RuntimeError('synthetic lost acknowledgement')
        return result
    monkeypatch.setattr(AsyncSessionTransaction,'__aexit__',lost)
    with pytest.raises(EntryStorageUnavailable,match='outcome_unknown'):act(env,app,'complete',state=initial)
    assert act(env,app,'complete',state=initial)['task']['status']=='completed'
    assert sql(env,"SELECT count(*) FROM calendar_task_events WHERE event='completed'")[0][0]==1


def test_batch_partial_failure_resume_and_cursor(env,monkeypatch):
    first=seed(env);sync(env,first,enable=True)
    second=setup(env,key='second')
    write(env,second,'recalculate',selection(env));write(env,second,'manual',manual());sync(env,second,enable=True)
    original=tasks.reconcile_deadline_task
    async def fail(engine,**kwargs):
        if kwargs['application_id']==first['id']:raise EntryStorageConflict('synthetic retry')
        return await original(engine,**kwargs)
    monkeypatch.setattr(tasks,'reconcile_deadline_task',fail)
    def batch(**kwargs):return asyncio.run(tasks.reconcile_case_deadline_tasks(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],**kwargs))
    result=batch()
    assert [r['status'] for r in result['results']]==['failed','ok'] and len(result['retry_cursors'])==1
    monkeypatch.setattr(tasks,'reconcile_deadline_task',original)
    one=batch(limit=1);two=batch(limit=1,after_binding_id=one['next_cursor'])
    assert len(one['results'])==len(two['results'])==1 and two['next_cursor'] is None
    assert all(r['status']=='ok' for r in batch()['results'])
    assert sql(env,'SELECT count(*) FROM calendar_tasks WHERE id IN (SELECT task_id FROM entry_deadline_tasks)')[0][0]==2


def test_new_submission_event_atomically_invalidates_bound_task(env):
    from tests.test_entry_applications import record
    from app.domain import entry_applications as applications
    app=setup(env,approve=False)
    submitted=record(env,app,'submit',reference='DL123456')
    write(env,app,'recalculate',selection(env,dict(kind='application_event',id=submitted['id'])))
    write(env,app,'manual',manual());sync(env,app,enable=True)
    record(env,app,'return',status='revision_requested',occurred_on='2026-09-03',reference='DL123456')
    record(env,app,'resubmit',status='submitted',occurred_on='2026-09-04',reference='DL123456')
    assert read(env,app)['current']['task']['status']=='cancelled'
    assert read(env,app)['current']['attention']=='unknown_date'


def test_binding_audit_cannot_be_repointed_to_an_unrelated_same_case_task(env):
    app=seed(env);state=sync(env,app,enable=True)
    sql(env,'UPDATE entry_deadline_tasks SET target_hash=:hash WHERE id=:id',hash='0'*64,id=state['binding_id'])
    with pytest.raises(EntryStorageInvalid,match='binding_audit'):sync(env,app)
    assert sql(env,'SELECT status FROM calendar_tasks WHERE id=:id',id=state['task']['id'])[0][0]=='planned'


def test_generation_limit_does_not_discard_new_source_fact(env,monkeypatch):
    app=seed(env);sync(env,app,enable=True);act(env,app,'complete')
    monkeypatch.setattr(tasks,'MAX_GENERATIONS',1)
    write(env,app,'manual',manual(reason='corrected_date',due_on='2026-10-17'))
    state=read(env,app)
    assert state['due_on']=='2026-10-17' and state['current']['attention']=='generation_limit'
    assert state['current']['task']['status']=='completed'


def test_lost_creation_ack_retry_does_not_duplicate_task(env,monkeypatch):
    from sqlalchemy.ext.asyncio import AsyncSessionTransaction
    app=seed(env);original=AsyncSessionTransaction.__aexit__;once=True
    async def lost(self,*args_):
        nonlocal once
        result=await original(self,*args_)
        if once:once=False;raise RuntimeError('synthetic lost acknowledgement')
        return result
    monkeypatch.setattr(AsyncSessionTransaction,'__aexit__',lost)
    with pytest.raises(EntryStorageUnavailable):sync(env,app,enable=True)
    assert sync(env,app,enable=True)['task']['date']=='2026-10-20'
    assert sql(env,'SELECT count(*) FROM calendar_tasks WHERE id IN (SELECT task_id FROM entry_deadline_tasks)')[0][0]==1


def test_two_rules_same_application_have_independent_dates_and_actions(env,tmp_path):
    import copy
    import shutil
    import yaml
    from app.domain.knowledge_import import create_kg_entry_set, import_bundle
    from tests.test_admin_kg_entry import FIX
    app=seed(env);first=sync(env,app,enable=True)
    folder=tmp_path/'two-rules';shutil.copytree(FIX/'synthetic_bundle',folder)
    units=yaml.safe_load((folder/'units.yaml').read_text('utf-8'))
    rule=copy.deepcopy(next(r for r in units if r['unit_id']=='KG.DL.TEST'));rule['unit_id']='KG.DL.SECOND';units.append(rule)
    (folder/'units.yaml').write_text(yaml.safe_dump(units,allow_unicode=True),'utf-8')
    async def run():
        set_id=await create_kg_entry_set(env['engine'],actor=ADMIN)
        imported=await import_bundle(env['engine'],actor=ADMIN,set_id=set_id,directory=folder,source=FIX/'synthetic_source.txt')
        assert imported.accepted,imported.report
        args_=dict(**args(env,app));args_['rule_unit_id']='KG.DL.SECOND'
        data=selection(env);data['knowledge_version_id']=imported.version_id
        await tasks.deadlines.record_deadline_operation(env['engine'],**args_,expected_revision=0,request_key='source',operation=dict(action='recalculate',data=data,confirmed=True))
        await tasks.deadlines.record_deadline_operation(env['engine'],**args_,expected_revision=1,request_key='date',operation=dict(action='manual',data=manual(due_on='2026-10-25'),confirmed=True))
        return await tasks.reconcile_deadline_task(env['engine'],**args_,enable=True)
    second=asyncio.run(run())
    assert second['task']['id']!=first['task']['id'] and second['task']['date']=='2026-10-25'
    act(env,app,'cancel')
    assert sql(env,'SELECT status FROM calendar_tasks WHERE id=:id',id=second['task']['id'])[0][0]=='planned'
