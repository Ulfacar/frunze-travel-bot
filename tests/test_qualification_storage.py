"""Resumable qualification with real local transactions and synthetic people only."""
import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import Session

from app.domain import qualification_storage as storage
from app.domain.entry_qualification import review_qualification
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.models import DomainError, EntryQualification
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied, SYSTEM_ACTOR
from tests.test_entry_storage import ADMIN, FIX, db, save_history
from app.knowledge.validation import load_document


def request():
    return load_document(FIX / 'synthetic_qualification_review.json')


async def save(db, *, doc=None, key='qualification-1', revision=0, contact=1, history_id=None):
    return await storage.save_qualification(db[0], actor=ADMIN, contact_id=contact,
        knowledge_version_id=db[1], expected_revision=revision, request_key=key,
        request=request() if doc is None else doc, history_id=history_id)


async def read(db, qid=None, contact=1):
    return await storage.read_qualification(db[0], actor=ADMIN, contact_id=contact, qualification_id=qid)


async def count(db):
    async with async_sessionmaker(db[0])() as session:
        return await session.scalar(select(func.count()).select_from(EntryQualification))


def test_resume_revisions_retry_and_replay_survive_sessions(db):
    async def scenario():
        assert await read(db) is None
        doc=request();doc['profile']={};original=deepcopy(doc)
        first=await save(db,doc=doc)
        assert doc==original and first['revision']==1 and first['previous_id'] is None
        assert first['result']['status']=='needs_input' and len(first['result']['next_questions'])<=3
        assert await read(db)==first
        second=await save(db,key='next',revision=1)
        assert second['revision']==2 and second['previous_id']==first['qualification_id']
        assert await read(db)==second and await read(db,first['qualification_id'])==first
        reused=await save(db,doc=doc)
        assert reused=={**first,'reused':True}
        replay=await storage.replay_qualification(db[0],actor=ADMIN,contact_id=1,qualification_id=second['qualification_id'])
        assert replay['replay_verified'] and replay['result']==second['result']
        direct=await review_qualification(db[0],actor=ADMIN,contact_id=1,knowledge_version_id=db[1],request=request())
        assert direct==second['result']
        assert second['result']['may_quote'] is False and second['result']['selected_regime'] is None
        second['input']['profile'].clear();second['result']['blockers'].clear()
        assert (await read(db))['input']==request() and (await read(db))['result']['blockers']
        assert await count(db)==2
    asyncio.run(scenario())


def test_full_replacement_removes_answers_and_recomputes_stops(db):
    async def scenario():
        doc=request();doc['profile']['purpose']='work_hire'
        first=await save(db,doc=doc)
        assert first['result']['status']=='manager_review'
        doc['profile']={'citizenship':['RUS','CHN'],'entry_passport_country':'CHN'}
        second=await save(db,doc=doc,key='changed',revision=1)
        assert second['input']==doc and 'profile.purpose' in second['result']['missing_facts']
        assert second['result']['status']=='needs_input'
        assert second['result']['request_hash']!=first['result']['request_hash']
        assert (await read(db,first['qualification_id']))['result']==first['result']
    asyncio.run(scenario())


@pytest.mark.parametrize('operation',['save','read','replay'])
@pytest.mark.parametrize('actor',[None,{},Actor('manager'),Actor('bot',True),Actor('',True),SYSTEM_ACTOR])
def test_authorization_precedes_engine_or_payload(operation,actor):
    kwargs=dict(actor=actor,contact_id=1)
    if operation=='save':kwargs.update(expected_revision=0,request_key='x',knowledge_version_id=1,request={})
    else:kwargs.update(qualification_id=1)
    with pytest.raises(PermissionDenied):
        asyncio.run(getattr(storage,operation+'_qualification')(None,**kwargs))


@pytest.mark.parametrize('bad',['contact','decision','history','condition_country','bool','date','country','nan','cycle'])
def test_invalid_payload_is_bounded_and_never_persisted(db,bad):
    async def scenario():
        doc=request()
        if bad in ('contact','decision','history'):doc['profile'][bad]={'private':'PRIVATE-PAYLOAD'}
        elif bad=='condition_country':doc['condition_facts']={'schema_version':'kg-entry-condition-facts/1','entry_passport_country':'CHN'}
        elif bad=='bool':doc['profile']['passport_pages_ok']=1
        elif bad=='date':doc['profile']['exit_date']='2026-01-01'
        elif bad=='country':doc['profile']['entry_passport_country']='ZZZ'
        elif bad=='nan':doc['profile']['passport_pages_ok']=float('nan')
        else:doc['profile']['cycle']=doc
        with pytest.raises(EntryStorageInvalid) as error:await save(db,doc=doc)
        assert 'PRIVATE' not in str(error.value) and await count(db)==0
    asyncio.run(scenario())


def test_scope_history_and_version_are_pinned(db):
    async def scenario():
        history=await save_history(db)
        first=await save(db,history_id=history['history_id'])
        other=await save(db,contact=2)
        assert other['revision']==1
        with pytest.raises(EntryStorageInvalid):await read(db,first['qualification_id'],contact=2)
        with pytest.raises(EntryStorageInvalid):await save(db,contact=2,revision=1,key='foreign',history_id=history['history_id'])
        with pytest.raises(EntryStorageInvalid):await save(db,contact=99)
        assert (await read(db))['result']['history']['snapshot_hash']==history['snapshot_hash']
        assert await count(db)==2
    asyncio.run(scenario())


def test_database_itself_rejects_foreign_history_and_previous_revision(db):
    async def scenario():
        h=await save_history(db,contact=2)
        other=await save(db,contact=2)
        await save(db)
        current=await save(db,key='second',revision=1)
        for field,value in [('history_id',h['history_id']),('previous_id',other['qualification_id'])]:
            with pytest.raises(IntegrityError):
                async with db[0].begin() as conn:
                    await conn.execute(text(f'UPDATE entry_qualifications SET {field}=:value WHERE id=:id'),
                                       {'value':value,'id':current['qualification_id']})
        assert await read(db)==current
    asyncio.run(scenario())


def test_unknown_and_false_remain_distinct_when_resuming(db):
    async def scenario():
        doc=request();doc['profile']['violations']['overstay']='unknown'
        first=await save(db,doc=doc)
        assert 'profile.violations.overstay' in first['result']['missing_facts']
        assert (await read(db))['input']['profile']['violations']['overstay']=='unknown'
        doc['profile']['violations']['overstay']=False
        second=await save(db,doc=doc,key='answered',revision=1)
        assert 'profile.violations.overstay' not in second['result']['missing_facts']
        assert (await read(db))['input']['profile']['violations']['overstay'] is False
    asyncio.run(scenario())


@pytest.mark.parametrize('field,value',[('contact_id',True),('knowledge_version_id',0),('history_id',True),
    ('expected_revision',True),('expected_revision',-1),('request_key','PRIVATE key')])
def test_invalid_identifiers_rejected_before_engine(field,value):
    kwargs=dict(actor=ADMIN,contact_id=1,knowledge_version_id=1,expected_revision=0,request_key='x',request=request())
    kwargs[field]=value
    with pytest.raises(EntryStorageInvalid) as error:asyncio.run(storage.save_qualification(None,**kwargs))
    assert 'PRIVATE' not in str(error.value)


@pytest.mark.parametrize('change',['request','revision','history','version'])
def test_request_key_cannot_be_reused_for_changed_payload(db,change):
    async def scenario():
        await save(db)
        kwargs=dict(actor=ADMIN,contact_id=1,expected_revision=0,request_key='qualification-1',knowledge_version_id=db[1],request=request())
        if change=='request':kwargs['request']['language']='en'
        elif change=='revision':kwargs['expected_revision']=1
        elif change=='history':kwargs['history_id']=(await save_history(db))['history_id']
        else:kwargs['knowledge_version_id']=db[1]+999
        with pytest.raises(EntryStorageConflict,match='request_key_conflict'):
            await storage.save_qualification(db[0],**kwargs)
        assert await count(db)==1
    asyncio.run(scenario())


def test_concurrent_identical_retry_and_conflicting_writers(db):
    async def scenario():
        a,b=await asyncio.gather(save(db),save(db))
        assert a['qualification_id']==b['qualification_id'] and a['reused']!=b['reused']
        results=await asyncio.gather(save(db,key='a',revision=1),save(db,key='b',revision=1),return_exceptions=True)
        assert sum(isinstance(r,dict) for r in results)==1
        assert sum(isinstance(r,EntryStorageConflict) for r in results)==1
        assert await count(db)==2 and (await read(db))['revision']==2
    asyncio.run(scenario())


def test_insert_failure_rolls_back_and_lost_commit_ack_is_recoverable(db):
    async def scenario():
        def fail(conn,cursor,statement,params,context,many):
            if statement.startswith('INSERT INTO entry_qualifications'):raise RuntimeError('PRIVATE-INSERT')
        event.listen(db[0].sync_engine,'before_cursor_execute',fail)
        try:
            with pytest.raises(EntryStorageUnavailable,match='^entry_storage_unavailable$'):await save(db)
        finally:event.remove(db[0].sync_engine,'before_cursor_execute',fail)
        assert await count(db)==0
        def lost_ack(session):raise RuntimeError('PRIVATE-ACK')
        event.listen(Session,'after_commit',lost_ack)
        try:
            with pytest.raises(EntryStorageUnavailable,match='commit_outcome_unknown_retry_same_request'):await save(db)
        finally:event.remove(Session,'after_commit',lost_ack)
        recovered=await save(db)
        assert recovered['reused'] and recovered['revision']==1 and await count(db)==1
    asyncio.run(scenario())


@pytest.mark.parametrize('operation',['update','delete','bulk_update','bulk_delete','nested'])
def test_orm_snapshots_are_immutable(db,operation):
    async def scenario():
        saved=await save(db)
        async with async_sessionmaker(db[0])() as session:
            row=await session.get(EntryQualification,saved['qualification_id'])
            with pytest.raises(DomainError):
                if operation=='nested':row.input_snapshot['profile']['purpose']='work_hire'
                elif operation=='bulk_update':await session.execute(update(EntryQualification).values(created_by='changed'))
                elif operation=='bulk_delete':await session.execute(delete(EntryQualification))
                else:
                    if operation=='update':row.created_by='changed'
                    else:await session.delete(row)
                    await session.flush()
            await session.rollback()
        assert await read(db)==saved
    asyncio.run(scenario())


@pytest.mark.parametrize('fault',['input','result','provenance','author','time','previous','history','projection','knowledge','journal'])
def test_raw_sql_corruption_rejected_without_private_details(db,fault):
    async def scenario():
        h=await save_history(db)
        await save(db,history_id=h['history_id'])
        second=await save(db,key='second',revision=1,history_id=h['history_id'])
        sql={
            'input':"UPDATE entry_qualifications SET input_snapshot='{}' WHERE revision=2",
            'result':"UPDATE entry_qualifications SET result_snapshot='{}' WHERE revision=2",
            'provenance':"UPDATE entry_qualifications SET provenance='{}' WHERE revision=2",
            'author':"UPDATE entry_qualifications SET created_by='PRIVATE' WHERE revision=2",
            'time':"UPDATE entry_qualifications SET created_at='2026-01-01' WHERE revision=2",
            'previous':"UPDATE entry_qualifications SET result_snapshot='{}' WHERE revision=1",
            'history':"UPDATE stay_intervals SET exit_date='2026-09-25'",
            'projection':"DELETE FROM knowledge_country_links",
            'knowledge':"UPDATE knowledge_versions SET bundle_hash=:bad",
            'journal':"DELETE FROM knowledge_imports",
        }
        async with db[0].begin() as conn:await conn.execute(text(sql[fault]),{'bad':'0'*64})
        with pytest.raises(DomainError) as error:await read(db,second['qualification_id'])
        assert 'PRIVATE' not in str(error.value)
    asyncio.run(scenario())


def test_runtime_and_result_drift_refuse_replay_without_destroying_old_result(db,monkeypatch):
    async def scenario():
        saved=await save(db)
        with monkeypatch.context() as patch:
            patch.setattr(storage,'_runtime',lambda:{'algorithm':'changed'})
            assert await read(db)==saved
            assert (await save(db))['reused']
            with pytest.raises(EntryStorageInvalid,match='runtime_changed'):
                await storage.replay_qualification(db[0],actor=ADMIN,contact_id=1,qualification_id=saved['qualification_id'])
        with monkeypatch.context() as patch:
            patch.setattr(storage,'_evaluate_qualification',lambda *args:{'different':True})
            with pytest.raises(EntryStorageInvalid,match='result_changed'):
                await storage.replay_qualification(db[0],actor=ADMIN,contact_id=1,qualification_id=saved['qualification_id'])
        assert await read(db)==saved
    asyncio.run(scenario())
