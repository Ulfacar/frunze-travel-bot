"""Real PostgreSQL transaction boundaries, same-request and competing CAS."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy import event,select,func

from tests.test_entry_process_postgres import template,env
from tests.test_conditional_deadlines import clock
from tests import test_conditional_deadlines as core
from tests.test_specialist_postgres import waiting
from app.domain import conditional_deadlines as service
from app.domain.entry_storage import EntryStorageConflict,EntryStorageUnavailable
from app.domain.models import EntryDeadlineRevision,EntryConditionalEvidence


def setup(env,tmp_path):
    prepared=core.setup(env,tmp_path);rule='KG.DL.INTERNAL_EAEU_REG_REVIEW';allowed=core.authority(env,rule)
    env['conditional_args']=core.arguments(env,prepared,rule,allowed)
    return env


def command(env):
    preview=core.preview(env,env['conditional_args'])
    return env['conditional_args']|dict(expected_revision=preview['revision'],request_key='conditional-original',
        operation=dict(action='conditional_review',confirmed=True,evidence_hash=preview['report']['evidence_hash']))


def record(env,args):return asyncio.run(service.record(env['engine'],**args))


def read(env):
    args={k:v for k,v in env['conditional_args'].items() if k not in ('authority','applicant_id')}
    return asyncio.run(core.entry_deadlines.read_deadline_history(env['engine'],**args,replay=True))


def counts(env):
    async def run():
        async with env['sm']() as session:
            return tuple([await session.scalar(select(func.count()).select_from(model)) for model in (EntryDeadlineRevision,EntryConditionalEvidence)])
    return asyncio.run(run())


@pytest.mark.parametrize('same',[True,False])
def test_conditional_actual_pg_waited_same_request_or_competing_cas(env,tmp_path,monkeypatch,same):
    setup(env,tmp_path);args=command(env);entered=threading.Event();release=threading.Event();original=service.sources.evaluate
    async def hold(*a,**kw):
        result=await original(*a,**kw)
        if not entered.is_set():entered.set();assert await asyncio.to_thread(release.wait,30)
        return result
    monkeypatch.setattr(service.sources,'evaluate',hold)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(record,env,args)
        try:
            assert entered.wait(30);second=pool.submit(record,env,args if same else args|{'request_key':'competing'})
            waiting(env,second)
        finally:release.set()
        saved=first.result(timeout=60)
        if same:assert second.result(timeout=60)==saved
        else:
            with pytest.raises(EntryStorageConflict):second.result(timeout=60)
    assert counts(env)==(1,1)


def test_conditional_pin_insert_failure_rolls_back_deadline_and_retries(env,tmp_path):
    setup(env,tmp_path);args=command(env)
    def broken(conn,cursor,statement,parameters,context,many):
        if statement.lstrip().lower().startswith('insert into entry_conditional_evidence'):raise RuntimeError('synthetic pin failure')
    event.listen(env['engine'].sync_engine,'before_cursor_execute',broken)
    try:
        with pytest.raises(EntryStorageUnavailable):record(env,args)
    finally:event.remove(env['engine'].sync_engine,'before_cursor_execute',broken)
    assert counts(env)==(0,0)
    assert record(env,args)['revision']==1 and counts(env)==(1,1)
