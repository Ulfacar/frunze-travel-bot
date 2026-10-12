"""Independent connected E630B receipt and unavailable-authority controls."""
import asyncio
from copy import deepcopy
import json
from types import SimpleNamespace

import pytest
from sqlalchemy import select,text

from app.domain import specialist_decisions as service
from app.domain.entry_storage import _hash,_plain,EntryStorageInvalid,EntryStorageUnavailable
from app.domain.models import SpecialistDecisionEvent
from tests.test_specialist_decisions import (
    env,admins,enforce_sqlite_foreign_keys,clock,setup,record_args,record,read,
    quote_preview,quote_args,options,withdraw_args,ON)


def test_removed_publication_authority_returns_unusable_not_uncaught_exception(env,tmp_path):
    setup(env,tmp_path);saved=record(env)
    assert read(env)['current']['usable_for_internal_quote']
    without=read(env,publication_policy=None)
    assert not without['current']['usable_for_internal_quote']
    assert without['history'][0]==saved['receipt']
    assert read(env)['current']['usable_for_internal_quote']


def test_rehashed_history_cannot_claim_preexisting_interview_was_absent(env,tmp_path):
    setup(env,tmp_path)
    args=record_args(env)
    args['operation'].update(disposition='needs_evidence',findings=None,
        reason=dict(code='evidence_missing',reference='SYN-NEEDS-EVIDENCE',proof='a'*64,on=ON))
    saved=asyncio.run(service.record_decision(env['engine'],**args))['receipt']
    assert saved['provenance']['pins']['interview'] is not None
    assert read(env)['history'][0]==saved
    async def rewrite():
        async with env['engine'].begin() as conn:
            found=(await conn.execute(text('SELECT * FROM specialist_decision_events WHERE id=:id'),{'id':saved['id']})).mappings().one()
        values=dict(found)
        for key in ('command','provenance','result'):
            values[key]=json.loads(values[key]) if isinstance(values[key],str) else deepcopy(values[key])
        from datetime import datetime
        if isinstance(values['created_at'],str):values['created_at']=datetime.fromisoformat(values['created_at'])
        values['provenance']['pins']['interview']=None
        values['command']['operation']['expected_context_hash']=_hash(values['provenance']['pins'])
        values['result']['assessment']['reasons']=['evidence_missing','specialist_interview_missing']
        values['request_hash']=_hash(values['command'])
        values['snapshot_hash']=_hash(service._payload(SimpleNamespace(**values)))
        async with env['engine'].begin() as conn:
            await conn.execute(text('UPDATE specialist_decision_events SET command=:command,provenance=:provenance,result=:result,request_hash=:request_hash,snapshot_hash=:snapshot_hash WHERE id=:id'),
                {k:json.dumps(values[k]) if k in ('command','provenance','result') else values[k]
                 for k in ('command','provenance','result','request_hash','snapshot_hash','id')})
    asyncio.run(rewrite())
    with pytest.raises(EntryStorageInvalid):read(env)


def test_quote_and_link_rollback_then_exact_recovery(env,tmp_path,monkeypatch):
    setup(env,tmp_path);original=record_args(env)
    saved=asyncio.run(service.record_decision(env['engine'],**original))
    args=quote_args(env,saved);append=service._append
    async def fail_link(*a,**kw):
        if kw['command']['operation']['action']=='quote':raise RuntimeError('reviewer injected link failure')
        return await append(*a,**kw)
    monkeypatch.setattr(service,'_append',fail_link)
    with pytest.raises(EntryStorageUnavailable,match='entry_storage_unavailable'):
        asyncio.run(service.record_decision(env['engine'],**args))
    async def counts():
        async with env['engine'].connect() as c:
            return (await c.scalar(text('SELECT count(*) FROM entry_quote_revisions')),
                    await c.scalar(text('SELECT count(*) FROM specialist_decision_events')))
    assert asyncio.run(counts())==(0,1)
    monkeypatch.setattr(service,'_append',append)
    quoted=asyncio.run(service.record_decision(env['engine'],**args))
    assert asyncio.run(counts())==(1,2)
    withdrawal=withdraw_args(env,saved,2)
    asyncio.run(service.record_decision(env['engine'],**withdrawal))
    for request,answer in ((original,saved),(args,quoted)):
        replay=asyncio.run(service.record_decision(env['engine'],**(request|dict(policy=None,interview_policy=None,publication_policy=None))))
        assert replay['duplicate'] and replay['receipt']==answer['receipt']
    assert not read(env)['current']['usable_for_internal_quote']


def test_future_dated_decision_is_not_currently_usable(env,tmp_path):
    setup(env,tmp_path);saved=record(env)['receipt']
    assert read(env)['current']['usable_for_internal_quote']
    async def rewrite():
        from datetime import datetime,timedelta
        async with env['engine'].begin() as conn:
            found=(await conn.execute(text('SELECT * FROM specialist_decision_events WHERE id=:id'),{'id':saved['id']})).mappings().one()
        values=dict(found)
        for key in ('command','provenance','result'):
            values[key]=json.loads(values[key]) if isinstance(values[key],str) else deepcopy(values[key])
        if isinstance(values['created_at'],str):values['created_at']=datetime.fromisoformat(values['created_at'])
        values['created_at']+=timedelta(hours=1)
        digest=_hash(service._payload(SimpleNamespace(**values)))
        async with env['engine'].begin() as conn:
            await conn.execute(text('UPDATE specialist_decision_events SET created_at=:at,snapshot_hash=:digest WHERE id=:id'),
                dict(at=values['created_at'].isoformat(),digest=digest,id=saved['id']))
    asyncio.run(rewrite())
    try:current=read(env)
    except EntryStorageInvalid:return
    assert not current['current']['usable_for_internal_quote']
