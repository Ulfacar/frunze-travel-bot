"""Actual pre-E writers retain original manual receipts and NULL task time."""
import asyncio
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select,text
from tests.test_entry_deadline_tasks import env,enforce_sqlite_foreign_keys
from tests import test_entry_deadline_tasks as core
from app.domain import entry_deadlines,entry_deadline_tasks as tasks
from app.domain.entry_storage import EntryStorageInvalid


def load(name):
    path=Path(__file__).with_name('operator_sop_legacy_fixtures')/(name+'.py')
    spec=importlib.util.spec_from_file_location('app.domain._audit_old_'+name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def test_actual_pre_e_writers_old_time_null_current_retry_and_next_action(env):
    old=load('entry_deadlines');old_tasks=load('entry_deadline_tasks');old_tasks.deadlines=old
    app=core.setup(env);args=core.args(env,app)
    selection=core.selection(env)
    def write(revision,key,action,data):
        request=args|dict(expected_revision=revision,request_key=key,operation=dict(action=action,data=data,confirmed=True))
        return asyncio.run(old.record_deadline_operation(env['engine'],**request)),request
    first,first_req=write(0,'old-recalculate','recalculate',selection)
    saved,request=write(1,'old-official-date','manual',core.manual())
    before=asyncio.run(old_tasks.reconcile_deadline_task(env['engine'],**args,enable=True))
    history=asyncio.run(old.read_deadline_history(env['engine'],**args))
    current=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**args))
    assert current.pop('operator_current') is None
    assert current==history
    assert asyncio.run(entry_deadlines.record_deadline_operation(env['engine'],**request))==saved
    assert asyncio.run(tasks.reconcile_deadline_task(env['engine'],**args,enable=True))==before
    assert before['task']['at'] is None and before['task']['date']=='2026-10-20'
    async def null():
        async with env['sm']() as s:return await s.scalar(text('SELECT expected_at FROM entry_deadline_tasks WHERE id=:id'),dict(id=before['binding_id']))
    assert asyncio.run(null()) is None
    # Current code deliberately refuses recomputation across a storage-module
    # hash change; this is distinct from reading/retrying the original receipt.
    with pytest.raises(EntryStorageInvalid,match='deadline_replay_runtime_changed'):
        asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**args,replay=True))
    completed=asyncio.run(tasks.act_on_deadline_task(env['engine'],**args,binding_id=before['binding_id'],expected_token=before['token'],
        request_key='new-complete',action='complete'))
    assert completed['task']['id']==before['task']['id'] and completed['task']['status']=='completed' and completed['task']['at'] is None
