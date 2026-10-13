"""Isolated actual PostgreSQL sessions; never a production connection."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timezone
from types import SimpleNamespace
import threading
import time

import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from tests.test_entry_process_postgres import template,env
from tests.test_specialist_decisions import admins,clock,setup,record_args,record,read,quote_args,withdraw_args,ADMIN
from tests import test_specialist_decisions as cases
from app.domain import specialist_decisions as service,knowledge_publication
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid
from app.domain.models import DomainBase


def call(env,args):return asyncio.run(service.record_decision(env['engine'],**args))


def waiting(env,future):
    async def check():
        async with env['engine'].connect() as conn:
            return await conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
    until=time.monotonic()+15
    while time.monotonic()<until:
        if asyncio.run(check()):
            assert not future.done();return
        if future.done():future.result();raise AssertionError('contender did not wait')
        time.sleep(.03)
    raise AssertionError('no actual PostgreSQL lock wait observed')


@pytest.mark.parametrize('same',[True,False])
def test_same_request_or_competing_revision_serializes(env,tmp_path,monkeypatch,same):
    setup(env,tmp_path);args=record_args(env);entered=threading.Event();release=threading.Event();original=service._append
    async def hold(*a,**kw):
        if not entered.is_set():
            entered.set();assert await asyncio.to_thread(release.wait,30)
        return await original(*a,**kw)
    monkeypatch.setattr(service,'_append',hold)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(call,env,args)
        try:
            assert entered.wait(20)
            second=pool.submit(call,env,args if same else args|dict(request_key='SYN-OTHER-KEY'))
            waiting(env,second)
        finally:release.set()
        saved=first.result(timeout=60)
        if same:assert second.result(timeout=60)==saved|dict(duplicate=True)
        else:
            with pytest.raises(EntryStorageConflict):second.result(timeout=60)
    assert read(env)['revision']==1


@pytest.mark.parametrize('withdraw_first',[True,False])
def test_quote_and_withdraw_compete_atomically(env,tmp_path,monkeypatch,withdraw_first):
    setup(env,tmp_path);saved=record(env);quote=quote_args(env,saved);withdraw=withdraw_args(env,saved,1)
    first_args,second_args=(withdraw,quote) if withdraw_first else (quote,withdraw)
    entered=threading.Event();release=threading.Event();original=service._append
    async def hold(*a,**kw):
        if not entered.is_set():entered.set();assert await asyncio.to_thread(release.wait,30)
        return await original(*a,**kw)
    monkeypatch.setattr(service,'_append',hold)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(call,env,first_args)
        try:
            assert entered.wait(20);second=pool.submit(call,env,second_args);waiting(env,second)
        finally:release.set()
        first.result(timeout=60)
        with pytest.raises(EntryStorageConflict):second.result(timeout=60)
    async def counts():
        async with env['engine'].connect() as c:
            return await c.scalar(text('SELECT count(*) FROM entry_quote_revisions'))
    assert asyncio.run(counts())==(0 if withdraw_first else 1)
    assert read(env)['revision']==2


@pytest.mark.parametrize('writer',['profile','history','interview','withdraw','review'])
def test_quote_keeps_fact_and_source_locks_until_atomic_link_commit(env,tmp_path,monkeypatch,writer):
    setup(env,tmp_path);saved=record(env);args=quote_args(env,saved)
    entered=threading.Event();release=threading.Event();original=knowledge_publication._runtime_context
    async def hold(session):
        result=await original(session)
        if threading.current_thread().name.startswith('reader'):
            entered.set();assert await asyncio.to_thread(release.wait,30)
        return result
    def change():
        if writer=='profile':return cases.save_profile(env,env['person'],revision=1,key='SYN-PROFILE-CHANGE',doc=env['profile_doc'])
        if writer=='history':return cases.save_history(env,env['person'],env['saved'],revision=1,key='SYN-HISTORY-CHANGE',doc=cases.history_document(history_complete=None))
        if writer=='interview':
            current=env['interview'];ip=env['interview_policy']
            return asyncio.run(cases.interviews.record_action(env['engine'],actor=cases.OWNER,case_id=env['cases']['visa'],
                applicant_id=env['person']['id'],interview_id=current['interview_id'],expected_revision=current['revision'],
                request_key='SYN-INTERVIEW-CHANGE',policy=ip,expected_policy_hash=ip.digest,
                operation=dict(action='correct',displayed=['applicant.age'],changes={'applicant.age':31})))
        if writer=='withdraw':return cases.publish(env,'withdraw',ids=['KG.VR.GENERAL'])
        return cases.review(env,decision=cases.review_data()|dict(verdict='rejected',reason='source_conflict',review_due_on=None),unit='KG.VR.GENERAL',key='SYN-SOURCE-CHANGE')
    with monkeypatch.context() as patch:
        patch.setattr(knowledge_publication,'_runtime_context',hold)
        with ThreadPoolExecutor(max_workers=1,thread_name_prefix='reader') as readers,ThreadPoolExecutor(max_workers=1) as writers:
            first=readers.submit(call,env,args)
            try:
                assert entered.wait(20);second=writers.submit(change);waiting(env,second)
            finally:release.set()
            receipt=first.result(timeout=60);second.result(timeout=60)
    current=read(env);assert current['revision']==2 and not current['current']['usable_for_internal_quote']
    assert call(env,args|dict(policy=None,interview_policy=None,publication_policy=None))==receipt|dict(duplicate=True)


def test_clock_after_case_wait_and_cancellation_leave_no_record(env,tmp_path,monkeypatch):
    setup(env,tmp_path);args=record_args(env)
    async def run():
        async with env['sm']() as blocker:
            await blocker.execute(text('SELECT id FROM service_cases WHERE id=:id FOR UPDATE'),{'id':env['cases']['visa']})
            task=asyncio.create_task(service.record_decision(env['engine'],**args))
            for _ in range(100):
                async with env['engine'].connect() as conn:
                    blocked=await conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
                if blocked:break
                await asyncio.sleep(.02)
            assert blocked and not task.done();task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            task=asyncio.create_task(service.record_decision(env['engine'],**args))
            await asyncio.sleep(.05)
            monkeypatch.setattr(service,'_now',lambda:datetime(2026,10,13,12,tzinfo=timezone.utc))
            await blocker.commit()
            with pytest.raises((EntryStorageInvalid,EntryStorageConflict)):await task
    asyncio.run(run());assert read(env)['revision']==0


def test_additive_migration_parity_constraints_and_populated_downgrade(env,tmp_path):
    cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_precontract_case_0038');command.upgrade(cfg,'head')
    async def parity():
        async with env['engine'].connect() as c:
            def compare(conn):
                ctx=MigrationContext.configure(conn,opts={'compare_type':True,'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name=='specialist_decision_events'})
                return compare_metadata(ctx,DomainBase.metadata)
            assert await c.run_sync(compare)==[]
    asyncio.run(parity());setup(env,tmp_path);record(env)
    async def invalid():
        for column,value in [('case_id',env['cases']['other']),('applicant_id',99999),('application_id',99999),('procedure',None),('revision',65),('decision_id',99999),('quote_id',99999)]:
            async with env['engine'].begin() as conn:
                with pytest.raises(IntegrityError):await conn.execute(text(f'UPDATE specialist_decision_events SET {column}=:value'),{'value':value})
    asyncio.run(invalid())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(cfg,'e6_precontract_case_0038')
    assert read(env)['revision']==1


def test_quote_clock_reversal_rolls_back_pg_transaction_and_recovers(env,tmp_path,monkeypatch):
    from tests.test_specialist_quote_clock import test_quote_to_link_clock_reversal_rolls_back_both_and_original_request_recovers
    test_quote_to_link_clock_reversal_rolls_back_both_and_original_request_recovers(env,tmp_path,monkeypatch)


def test_quote_before_decision_rolls_back_pg_and_equal_timestamps_recover(env,tmp_path,monkeypatch):
    from tests.test_specialist_quote_before_decision import test_quote_cannot_predate_decision_and_equal_boundary_recovers_same_request
    test_quote_cannot_predate_decision_and_equal_boundary_recovers_same_request(env,tmp_path,monkeypatch)
