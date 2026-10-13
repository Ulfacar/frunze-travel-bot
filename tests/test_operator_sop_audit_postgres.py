"""Independent actual PostgreSQL checks of SOP's newly timed task boundary."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import threading

import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import event, select, text, func
from sqlalchemy.exc import IntegrityError

from tests.test_entry_process_postgres import template, env
from tests.test_specialist_postgres import waiting
from tests import test_operator_sop_reviews as core
from app.config import settings
from app.domain import operator_sop_reviews as service, operator_sop_sources as sources
from app.domain import entry_deadline_tasks as tasks, task_rules
from app.domain.operator_sop_policy import from_document
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict, EntryStorageUnavailable
from app.domain.models import DomainBase, KnowledgeSet, EntryDeadlineRevision, EntrySopReviewEvidence, CalendarTask, EntryDeadlineTask


def prepared(env,tmp_path,monkeypatch):
    own=core.setup(env,tmp_path); args=core.args(env,own)
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[own[-1].document])
    saved,request=core.write(env,args)
    return own,args,saved,request,core.task_args(args)


def test_migrated_composite_scope_exact_time_and_populated_inverse(env,tmp_path,monkeypatch):
    cfg=Config('alembic.ini')
    cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_actual_anchor_events_0042');command.upgrade(cfg,'head')
    async def metadata():
        async with env['engine'].connect() as c:
            return await c.run_sync(lambda s:compare_metadata(MigrationContext.configure(s,opts={'compare_type':True}),DomainBase.metadata))
    assert asyncio.run(metadata())==[]
    own,args,saved,request,ta=prepared(env,tmp_path,monkeypatch)
    other=core.person(env,'OTHER-SOP'); other_profile=core.profiles.save(env,other)
    other_app=core.processes.setup(env,key='OTHER-APP',applicant=other)
    bound=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta,enable=True))
    async def corrupt(column,value):
        assert column in ('profile_id','applicant_id','active_application_id','process_event_id','application_event_id')
        async with env['sm']() as s:
            async with s.begin():
                await s.execute(text('UPDATE entry_sop_review_evidence SET '+column+'=:v WHERE deadline_id=:id'),dict(v=value,id=saved['id']))
    for column,value in [('profile_id',other_profile['qualification_id']),('applicant_id',other['id']),('active_application_id',other_app['id'])]:
        with pytest.raises(IntegrityError):asyncio.run(corrupt(column,value))
    with pytest.raises(RuntimeError,match='preserve populated SOP'):command.downgrade(cfg,'e6_actual_anchor_events_0042')
    loaded=asyncio.run(tasks.read_deadline_task(env['engine'],**ta))
    assert loaded['current']['task']['at']=='2026-11-01T18:30:00+00:00'
    assert loaded['current']['task']['id']==bound['task']['id']
    assert asyncio.run(service.record(env['engine'],**(request|dict(authority=None))))==saved
    async def boundary():
        async with env['sm']() as s:
            task=await s.get(CalendarTask,bound['task']['id'])
            assert task.user_id=='' and task.kind=='followup'
            early=await task_rules.due_tasks(s,now=datetime(2026,11,1,18,29,59,tzinfo=timezone.utc))
            exact=await task_rules.due_tasks(s,now=datetime(2026,11,1,18,30,tzinfo=timezone.utc))
            assert task.id not in [x.id for x in early] and task.id in [x.id for x in exact]
    asyncio.run(boundary())


def test_admission_clock_after_actual_publication_lock(env,tmp_path,monkeypatch):
    own=core.setup(env,tmp_path); args=core.args(env,own)
    day=datetime.now(timezone.utc).astimezone(core.rules.BISHKEK).date()
    doc=own[-1].document;doc['policy']['review_due_on']=day.isoformat();allowed=from_document(doc)
    args['authority']=allowed;initial=core.preview(env,args)
    assert initial['report']['status']=='available'
    request=args|dict(expected_revision=0,request_key='AUDIT-PUBLISH-CLOCK',operation=dict(action='operator_review',confirmed=True,
        evidence_hash=initial['report']['evidence_hash'],schedule=dict(on='2026-11-02',time='00:30',reason='source_followup',reference='AUDIT',proof='a'*64)))
    captured=[];current=[datetime.combine(day,datetime.min.time(),core.rules.BISHKEK).astimezone(timezone.utc)+timedelta(days=1,seconds=-1)]
    def now():captured.append(current[0]);return current[0]
    monkeypatch.setattr(service,'_now',now)
    entered=threading.Event();release=threading.Event()
    async def hold():
        async with env['sm']() as s:
            async with s.begin():
                await s.scalar(select(KnowledgeSet).where(KnowledgeSet.code=='kg_entry').with_for_update())
                entered.set();assert await asyncio.to_thread(release.wait,30)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(lambda:asyncio.run(hold()))
        try:
            assert entered.wait(15)
            second=pool.submit(lambda:asyncio.run(service.record(env['engine'],**request)))
            waiting(env,second);assert captured==[];current[0]+=timedelta(seconds=2)
        finally:release.set()
        first.result(timeout=40)
        with pytest.raises(EntryStorageInvalid,match='authority_expired'):second.result(timeout=60)
    assert len(captured)==1
    async def count():
        async with env['sm']() as s:return await s.scalar(select(func.count()).select_from(EntryDeadlineRevision))
    assert asyncio.run(count())==0


def test_task_projection_holds_profile_lock_until_selected_time_commits(env,tmp_path,monkeypatch):
    own,args,saved,request,ta=prepared(env,tmp_path,monkeypatch)
    original=service.current;entered=threading.Event();release=threading.Event()
    async def pause(*a,**kw):
        result=await original(*a,**kw)
        if not entered.is_set():entered.set();assert await asyncio.to_thread(release.wait,30)
        return result
    monkeypatch.setattr(service,'current',pause)
    def writer():
        doc=core.profiles.request();doc['profile']['purpose']='work_hire'
        return core.profiles.save(env,own[0],doc=doc,revision=own[2]['revision'],key='AUDIT-PROFILE')
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(lambda:asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta,enable=True)))
        try:
            assert entered.wait(30);second=pool.submit(writer);waiting(env,second)
        finally:release.set()
        bound=first.result(timeout=60);second.result(timeout=60)
    assert bound['task']['at']=='2026-11-01T18:30:00+00:00'
    current=asyncio.run(tasks.read_deadline_task(env['engine'],**ta))
    assert current['due_at'] is None and current['due_on'] is None
    assert asyncio.run(service.record(env['engine'],**(request|dict(authority=None))))==saved


@pytest.mark.parametrize('first',['claim','clear'])
def test_actual_claim_and_clear_race_keeps_exact_time_and_same_task(env,tmp_path,monkeypatch,first):
    own,args,saved,request,ta=prepared(env,tmp_path,monkeypatch)
    bound=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta,enable=True));task_id=bound['task']['id']
    clear=args|dict(authority=None,expected_revision=1,request_key='AUDIT-CLEAR',operation=dict(action='operator_review_clear',confirmed=True,evidence_hash=saved['snapshot_hash']))
    entered=threading.Event();release=threading.Event()
    original=tasks._task
    async def pause(*a,**kw):
        result=await original(*a,**kw)
        if first=='clear' and kw.get('lock') and not entered.is_set():
            entered.set();assert await asyncio.to_thread(release.wait,30)
        return result
    monkeypatch.setattr(tasks,'_task',pause)
    async def claim():
        async with env['sm']() as s:
            async with s.begin():
                result=await task_rules.claim_task(s,task_id,worker='AUDIT')
                if first=='claim':entered.set();assert await asyncio.to_thread(release.wait,30)
                return result
    def clear_it():return asyncio.run(service.record(env['engine'],**clear))
    def claim_it():return asyncio.run(claim())
    with ThreadPoolExecutor(max_workers=2) as pool:
        winner=pool.submit(claim_it if first=='claim' else clear_it)
        try:
            assert entered.wait(30);loser=pool.submit(clear_it if first=='claim' else claim_it);waiting(env,loser)
        finally:release.set()
        a=winner.result(timeout=60);b=loser.result(timeout=60)
    current=asyncio.run(tasks.read_deadline_task(env['engine'],**ta))['current']
    assert current['task']['id']==task_id and current['task']['at']=='2026-11-01T18:30:00+00:00'
    assert current['task']['status']==('planned' if first=='claim' else 'cancelled')
    assert current['task']['claimed']==(first=='claim')
    assert (a if first=='claim' else b).claimed==(first=='claim')
    assert asyncio.run(service.record(env['engine'],**clear))==(b if first=='claim' else a)
