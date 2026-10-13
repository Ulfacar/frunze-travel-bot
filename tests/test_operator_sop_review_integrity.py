"""Independent R1 evidence binding and actual task atomicity controls."""
import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import event, select, update

from app.config import settings
from app.domain import entry_deadlines, task_rules
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageUnavailable, _hash, _plain
from app.domain.models import EntryDeadlineRevision, EntrySopReviewEvidence, CalendarTask
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests import test_operator_sop_reviews as core


def test_rehashed_schedule_and_pin_failure_preserve_original_claimed_task(env,tmp_path,monkeypatch):
    prepared=core.setup(env,tmp_path);args=core.args(env,prepared);ta=core.task_args(args)
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[prepared[-1].document])
    saved,old_request=core.write(env,args)
    first=asyncio.run(core.tasks.reconcile_deadline_task(env['engine'],**ta,enable=True))

    async def mutate(restore=None):
        async with env['sm']() as session:
            row=await session.get(EntryDeadlineRevision,saved['id'])
            old=(_plain(row.command),_plain(row.snapshot),row.request_hash,row.snapshot_hash)
            if restore:
                command,snapshot,request_hash,snapshot_hash=restore
            else:
                command=_plain(row.command);snapshot=_plain(row.snapshot)
                command['operation']['schedule']['time']='00:31'
                snapshot['schedule']=core.rules.selected_schedule(command['operation']['schedule'])
                request_hash=_hash(command)
                payload=entry_deadlines._payload(row)|dict(command=command,snapshot=snapshot,request_hash=request_hash)
                snapshot_hash=_hash(payload)
            connection=await session.connection()
            await connection.execute(update(EntryDeadlineRevision.__table__).where(EntryDeadlineRevision.id==row.id).values(
                command=command,snapshot=snapshot,request_hash=request_hash,snapshot_hash=snapshot_hash))
            await session.commit();return old
    original=asyncio.run(mutate())
    with pytest.raises(EntryStorageInvalid,match='independent_pin'):
        asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**ta))
    asyncio.run(mutate(original))
    assert asyncio.run(core.service.record(env['engine'],**(old_request|{'authority':None})))==saved

    p=core.preview(env,args)
    request=args|dict(expected_revision=1,request_key='SECOND-EXACT-TIME',operation=dict(
        action='operator_review',confirmed=True,evidence_hash=p['report']['evidence_hash'],
        schedule=dict(on='2026-11-02',time='01:30',reason='source_followup',reference='SECOND',proof='a'*64)))
    def fail_pin(*_):raise RuntimeError('independent injected pin failure')
    event.listen(EntrySopReviewEvidence,'before_insert',fail_pin)
    try:
        with pytest.raises(EntryStorageUnavailable):asyncio.run(core.service.record(env['engine'],**request))
    finally:event.remove(EntrySopReviewEvidence,'before_insert',fail_pin)
    assert core.preview(env,args)['revision']==1
    intact=asyncio.run(core.tasks.read_deadline_task(env['engine'],**ta))['current']
    assert intact['task']['id']==first['task']['id'] and intact['task']['at']==first['task']['at']
    corrected=asyncio.run(core.service.record(env['engine'],**request))
    projected=asyncio.run(core.tasks.read_deadline_task(env['engine'],**ta))['current']
    assert projected['task']['id']==first['task']['id']
    assert projected['task']['at']=='2026-11-01T19:30:00+00:00'
    async def claim():
        async with env['sm']() as session:
            claimed=await task_rules.claim_task(session,first['task']['id'],worker='admin')
            await session.commit();return claimed
    assert asyncio.run(claim()).claimed
    cleared=asyncio.run(core.service.record(env['engine'],**(args|dict(authority=None,
        expected_revision=2,request_key='CLEAR-CLAIMED',operation=dict(action='operator_review_clear',
            confirmed=True,evidence_hash=corrected['snapshot_hash'])))))
    assert cleared['summary']['review_due_on'] is None
    retained=asyncio.run(core.tasks.read_deadline_task(env['engine'],**ta))['current']
    assert retained['task']['id']==first['task']['id']
    assert retained['attention']=='claimed' and retained['task']['status'] not in ('cancelled','completed')
