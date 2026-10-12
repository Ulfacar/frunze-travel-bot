"""Explicitly isolated PostgreSQL: actual waits, atomic rollback, migration."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import threading

import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text

from tests.test_entry_process_postgres import template,env
from tests.test_work_review_tasks import clock,review_clock,connected_clock,route_clock,admins,setup,record,read,counts
from tests import test_work_review_tasks as core
from tests.test_specialist_postgres import waiting
from app.domain import work_review_tasks as service
from app.domain.entry_storage import EntryStorageConflict,EntryStorageUnavailable
from app.domain.models import DomainBase


@pytest.mark.parametrize('same',[True,False])
def test_actual_concurrent_requests_preserve_one_task(env,tmp_path,monkeypatch,same):
    setup(env,tmp_path);args=core.command(env);before=counts(env)
    entered=threading.Event();release=threading.Event();original=service._current
    async def hold(*a,**kw):
        result=await original(*a,**kw)
        if not entered.is_set():entered.set();assert await asyncio.to_thread(release.wait,30)
        return result
    monkeypatch.setattr(service,'_current',hold)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first=pool.submit(record,env,args)
        try:
            assert entered.wait(20);second=pool.submit(record,env,args if same else args|dict(request_key='COMPETING'))
            waiting(env,second)
        finally:release.set()
        saved=first.result(timeout=60)
        if same:assert second.result(timeout=60)==saved
        else:
            with pytest.raises(EntryStorageConflict):second.result(timeout=60)
    assert counts(env)==[before[0]+1,before[1]+1]


def test_bound_audit_failure_rolls_back_task_receipt_and_calendar_event(env,tmp_path,monkeypatch):
    setup(env,tmp_path);args=core.command(env);before=counts(env);original=service._log_event
    async def broken(*a,**kw):
        if len(a)>2 and a[2]=='work_review_bound':raise RuntimeError('synthetic bound audit failure')
        return await original(*a,**kw)
    with monkeypatch.context() as patch:
        patch.setattr(service,'_log_event',broken)
        with pytest.raises((RuntimeError,EntryStorageUnavailable)):record(env,args)
    assert counts(env)==before
    assert record(env,args)['revision']==1
    async def audit_count():
        async with env['engine'].connect() as conn:
            return await conn.scalar(text("SELECT count(*) FROM calendar_task_events WHERE event='work_review_bound'"))
    assert asyncio.run(audit_count())==1


def test_actual_schema_empty_cycle_constraints_and_populated_guard(env,tmp_path):
    cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_work_process_evidence_0040');command.upgrade(cfg,'head')
    async def compare():
        async with env['engine'].connect() as conn:
            return await conn.run_sync(lambda c:compare_metadata(MigrationContext.configure(c,opts={'compare_type':True}),DomainBase.metadata))
    assert asyncio.run(compare())==[]
    setup(env,tmp_path);saved=record(env,core.command(env));before=read(env)
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(cfg,'e6_work_process_evidence_0040')
    assert read(env)==before and saved['revision']==1
