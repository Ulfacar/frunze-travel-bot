"""Real loopback PostgreSQL: stop/send linearization and retained journal recovery."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy import event

from tests.test_entry_process_postgres import connection,db_url,database,template,env
from tests.test_entry_channel_stops import admins,activation
from tests.test_entry_channel_postgres import waiting_lock
from tests import test_dialogue_stops as cases
from app.domain.models import EntryDialogueStopCause


def test_connected_stop_retry(env):cases.test_atomic_cause_handoff_latch_and_exact_retry(env)


@pytest.mark.parametrize('phase',['paused','pending','acked'])
def test_retained_card_and_terminal_collection_stop(env,phase):
    cases.test_existing_handoff_and_later_privacy_stop_with_expired_policy(env,phase)


@pytest.mark.parametrize('model',[cases.EntryDialogueStopCause,cases.EntryChannelStop,cases.EntryInterviewEvent])
def test_atomic_failure(env,model):cases.test_failure_rolls_back_all_three_connected_writes(env,model)


def test_cause_corruption_restoration(env):cases.test_cause_corruption_fails_closed_and_restores(env)


def test_reserved_terminal_capacity(env,monkeypatch):cases.test_reserved_terminal_collection_stop_at_registry_capacity(env,monkeypatch)


def test_send_first_finishes_once_then_atomic_trigger_blocks_next(env):
    iv=cases.start(env);did=cases.dialog(env);params=cases.parameters(env,iv,did)
    admitted=threading.Event();release=threading.Event();calls=[]
    from app.domain import entry_channel_stops as stops
    async def callback():
        calls.append('once');admitted.set();assert await asyncio.to_thread(release.wait,8)
    with ThreadPoolExecutor(max_workers=2) as pool:
        sent=pool.submit(lambda:asyncio.run(stops.guarded_send(env['engine'],cases.ROUTE,callback)))
        assert admitted.wait(8)
        trigger=pool.submit(cases.run,env,params)
        try:
            waiting_lock(env);assert not trigger.done()
        finally:release.set()
        assert sent.result(timeout=10).invoked
        assert trigger.result(timeout=10)['suppressed']
    assert calls==['once'] and cases.send(env)[1]==[]


def test_trigger_first_sender_waits_until_commit_and_is_suppressed(env):
    iv=cases.start(env);did=cases.dialog(env);params=cases.parameters(env,iv,did)
    inserted=threading.Event();release=threading.Event();calls=[]
    from app.domain import entry_channel_stops as stops
    def held(*a):inserted.set();assert release.wait(8)
    async def callback():calls.append('unexpected')
    event.listen(EntryDialogueStopCause,'after_insert',held)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            trigger=pool.submit(cases.run,env,params);assert inserted.wait(8)
            sent=pool.submit(lambda:asyncio.run(stops.guarded_send(env['engine'],cases.ROUTE,callback)))
            try:
                waiting_lock(env);assert not sent.done()
            finally:release.set()
            assert trigger.result(timeout=10)['suppressed']
            assert not sent.result(timeout=10).invoked
    finally:release.set();event.remove(EntryDialogueStopCause,'after_insert',held)
    assert calls==[]


def test_real_migration_parity_scope_and_populated_downgrade(env):
    from alembic import command
    from alembic.config import Config
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from types import SimpleNamespace
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from app.domain.models import DomainBase
    cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_applicant_stay_0035');command.upgrade(cfg,'head')
    async def compare():
        async with env['engine'].connect() as conn:
            def check(sync):
                return compare_metadata(MigrationContext.configure(sync,opts={'compare_type':True,
                    'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name=='entry_dialogue_stop_causes'}),DomainBase.metadata)
            assert await conn.run_sync(check)==[]
    asyncio.run(compare())
    iv=cases.start(env);did=cases.dialog(env);args=cases.parameters(env,iv,did);saved=cases.run(env,args)
    async def invalid():
        for column,value in [('case_id',env['cases']['other']),('applicant_id',99999),('event_id',99999),
                             ('stop_id',99999),('revision',3),('previous_id',99999)]:
            async with env['engine'].begin() as c:
                with pytest.raises(IntegrityError):
                    await c.execute(text(f'UPDATE entry_dialogue_stop_causes SET {column}=:v'),{'v':value})
    asyncio.run(invalid())
    with pytest.raises(RuntimeError,match='preserve populated'):
        command.downgrade(cfg,'e6_applicant_stay_0035')
    assert cases.run(env,args)==saved and cases.send(env)[1]==[]


@pytest.mark.parametrize('when',['before_commit','after_commit'])
def test_lost_commit_ack_retry_returns_one_immutable_connected_receipt(env,when):
    from sqlalchemy.orm import Session
    from app.domain.entry_storage import EntryStorageUnavailable
    iv=cases.start(env);did=cases.dialog(env);args=cases.parameters(env,iv,did);seen=[]
    def fail(session):
        if not seen:seen.append(True);raise RuntimeError('synthetic commit acknowledgement')
    event.listen(Session,when,fail)
    try:
        with pytest.raises(EntryStorageUnavailable):cases.run(env,args)
    finally:event.remove(Session,when,fail)
    saved=cases.run(env,args)
    assert saved['suppressed'] and cases.counts(env)['entry_dialogue_stop_causes']==1
    assert cases.run(env,args)==saved and cases.send(env)[1]==[]
