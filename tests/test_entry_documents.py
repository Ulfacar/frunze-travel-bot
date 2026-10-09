"""Real FK-enforced SQLite transactions for per-application document history."""
import asyncio
import copy

import pytest
from sqlalchemy import select,text,update

from app.domain import entry_documents as service
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid
from app.domain.models import EntryDocumentRevision,DomainError
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge.document_checklist import load_document_catalog
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_entry_applications import person,application,record,enforce_sqlite_foreign_keys


def setup(env,product='TS',procedure='visa',case='visa',key='first'):
    subject=person(env,key+'person',case=case)
    app=application(env,subject,key+'app',case=case,procedure=procedure)
    write(env,app,'initialize',dict(product=product,catalog_digest=load_document_catalog().digest),key=key+'init',case=case)
    return app


def read(env,app,case='visa',**kwargs):
    return asyncio.run(service.read_document_inventory(env['engine'],actor=ADMIN,case_id=env['cases'][case],application_id=app['id'],**kwargs))


def write(env,app,action,data,*,key=None,revision=None,case='visa',actor=ADMIN,confirmed=True):
    if revision is None:revision=read(env,app,case)['current_revision']
    return asyncio.run(service.record_document_operation(env['engine'],actor=actor,case_id=env['cases'][case],application_id=app['id'],
        expected_revision=revision,request_key=key or f'{action}-{revision}',operation=dict(action=action,data=data,confirmed=confirmed)))


def receive(env,app,item='d03_0',fingerprint='a'*64,**kwargs):
    return write(env,app,'receive',dict(item=item,fingerprint=fingerprint,on='2026-09-01',source='client_copy'),**kwargs)


def check(env,app,item='d03_0',fingerprint='a'*64,version=1,**kwargs):
    return write(env,app,'review',dict(item=item,fingerprint=fingerprint,version=version,on='2026-09-02',outcome='checked',reason=None),**kwargs)


def test_receipt_review_replace_history_and_no_package_acceptance(env):
    app=setup(env)
    received=receive(env,app);assert received['snapshot']['items']['d03_0']['status']=='received'
    checked=check(env,app);assert checked['summary']['counts']['required_checked']==1
    assert checked['summary']['package_accepted'] is False and checked['summary']['submission_allowed'] is False
    replace=receive(env,app,fingerprint='b'*64)
    assert replace['snapshot']['items']['d03_0']['version']==2
    assert replace['summary']['counts']['required_checked']==0
    assert read(env,app,revision=checked['revision'])['selected']['snapshot']==checked['snapshot']
    with pytest.raises(EntryStorageInvalid,match='version_changed'):check(env,app)
    assert read(env,app)['current_revision']==4
    check(env,app,fingerprint='b'*64,version=2)
    assert read(env,app)['current_revision']==5


def test_passport_change_invalidates_other_checks_without_erasing_them(env):
    app=setup(env);receive(env,app);old=check(env,app)
    changed=receive(env,app,item='d02_0',fingerprint='c'*64)
    photo=next(r for r in changed['summary']['items'] if r['id']=='d03_0')
    assert photo['status']=='checked' and photo['effective_status']=='recheck'
    assert read(env,app,revision=old['revision'])['selected']['summary']['counts']['required_checked']==1
    check(env,app)
    changed=write(env,app,'passport_change',{'on':'2026-09-03','reason':'replacement'})
    assert changed['summary']['counts']['required_checked']==0


def test_correction_withdraw_and_conditional_unknown(env):
    app=setup(env);receive(env,app)
    result=write(env,app,'review',dict(item='d03_0',version=1,fingerprint='a'*64,on='2026-09-02',outcome='correction',reason='unreadable'))
    assert result['snapshot']['items']['d03_0']['status']=='correction'
    check(env,app)
    result=write(env,app,'withdraw',dict(item='d03_0',version=1,fingerprint='a'*64,on='2026-09-03',reason='mismatch'))
    assert result['snapshot']['items']['d03_0']['status']=='withdrawn'
    with pytest.raises(EntryStorageInvalid):check(env,app)
    initial=result['summary']['counts']['applicability_unknown']
    result=write(env,app,'applicability',dict(item='d08_0',applicable=False))
    assert result['summary']['counts']['applicability_unknown']==initial-1
    assert result['summary']['package_accepted'] is False
    with pytest.raises(EntryStorageInvalid,match='applicability_fixed'):
        write(env,app,'applicability',dict(item='d01_0',applicable=False))


def test_retry_payload_conflict_stale_and_terminal_application(env):
    app=setup(env);first=receive(env,app,key='same',revision=1)
    assert receive(env,app,key='same',revision=1)==first
    with pytest.raises(EntryStorageConflict):receive(env,app,key='same',revision=1,fingerprint='b'*64)
    with pytest.raises(EntryStorageConflict):receive(env,app,key='stale',revision=1,fingerprint='b'*64)
    record(env,app);record(env,app,'approved',status='approved',occurred_on='2026-09-02')
    assert receive(env,app,key='same',revision=1)==first
    with pytest.raises(EntryStorageInvalid,match='application_closed'):check(env,app)


def test_distinct_case_application_scope_and_admin_authority(env):
    app=setup(env);other=setup(env,key='second')
    receive(env,app)
    assert read(env,other)['selected']['snapshot']['items']['d03_0']['version']==0
    with pytest.raises(EntryStorageInvalid):read(env,app,case='other')
    with pytest.raises(EntryStorageInvalid):receive(env,app,case='other',revision=1)
    with pytest.raises(PermissionDenied):receive(env,app,actor=Actor('medina',False),revision=2)
    with pytest.raises(PermissionDenied):asyncio.run(service.read_document_inventory(env['engine'],actor=Actor('medina',False),case_id=env['cases']['visa'],application_id=app['id']))


def test_wrong_product_source_marker_dates_and_unchanged_content(env):
    p=person(env);app=application(env,p,procedure='registration')
    with pytest.raises(EntryStorageInvalid,match='product_mismatch'):
        write(env,app,'initialize',dict(product='TS',catalog_digest=load_document_catalog().digest),revision=0)
    ep=setup(env,product='EP',procedure='unified_permit',key='ep')
    receive(env,ep)
    with pytest.raises(EntryStorageInvalid,match='source_unverified'):check(env,ep)
    with pytest.raises(EntryStorageInvalid,match='content_unchanged'):receive(env,ep)
    with pytest.raises(EntryStorageInvalid,match='invalid_document_date'):
        write(env,ep,'review',dict(item='d03_0',version=1,fingerprint='a'*64,on='2026-08-31',outcome='checked',reason=None))


@pytest.mark.parametrize('operation',[
    {'action':'receive','data':{'item':'d03_0','fingerprint':'passport-number','on':'2026-09-01','source':'client_copy'},'confirmed':True},
    {'action':'receive','data':{'item':'d03_0','fingerprint':'a'*64,'on':'2026-09-01','source':[]},'confirmed':True},
    {'action':'applicability','data':{'item':'d08_0','applicable':'false'},'confirmed':True},
    {'action':'passport_change','data':{'on':'2999-01-01','reason':'replacement'},'confirmed':True},
    {'action':'passport_change','data':{'on':'2026-09-01','reason':'replacement'},'confirmed':1},
    {'action':'initialize','data':{'product':'TS','catalog_digest':'a'*64,'publication_approved':True},'confirmed':True},
])
def test_bad_operations_do_not_append(env,operation):
    app=setup(env)
    with pytest.raises(EntryStorageInvalid):asyncio.run(service.record_document_operation(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],
        application_id=app['id'],expected_revision=1,request_key='bad',operation=operation))
    assert read(env,app)['current_revision']==1


def test_parallel_duplicate_and_conflicting_changes(env):
    app=setup(env)
    async def run():
        args=dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],expected_revision=1,
            operation={'action':'receive','data':dict(item='d03_0',fingerprint='a'*64,on='2026-09-01',source='client_copy'),'confirmed':True})
        both=await asyncio.gather(*(service.record_document_operation(env['engine'],request_key='same',**args) for _ in range(2)))
        assert both[0]==both[1]
        args['expected_revision']=2
        second=copy.deepcopy(args);second['operation']['data']['fingerprint']='b'*64
        third=copy.deepcopy(args);third['operation']['data']['fingerprint']='c'*64
        results=await asyncio.gather(service.record_document_operation(env['engine'],request_key='b',**second),
                                    service.record_document_operation(env['engine'],request_key='c',**third),return_exceptions=True)
        assert sum(isinstance(r,dict) for r in results)==1
        assert sum(isinstance(r,EntryStorageConflict) for r in results)==1
    asyncio.run(run());assert read(env,app)['current_revision']==3


def test_corruption_and_orm_bulk_mutation_denied(env):
    app=setup(env);receive(env,app)
    async def corrupt():
        async with env['sm']() as s:
            row=await s.scalar(select(EntryDocumentRevision).where(EntryDocumentRevision.revision==1))
            row.snapshot_hash='x'*64
            with pytest.raises(DomainError):await s.commit()
        async with env['sm']() as s:
            with pytest.raises(DomainError):await s.execute(update(EntryDocumentRevision).values(snapshot_hash='b'*64))
        async with env['engine'].begin() as conn:
            await conn.execute(text('UPDATE entry_document_revisions SET snapshot_hash=:h WHERE revision=1'),{'h':'0'*64})
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):read(env,app)
    with pytest.raises(EntryStorageInvalid):check(env,app,revision=2)


def test_historical_reads_and_existing_operations_do_not_need_current_catalog(env,monkeypatch):
    app=setup(env);receive(env,app)
    def unavailable():
        raise AssertionError('Historical definition must come from saved revision')
    monkeypatch.setattr(service,'load_document_catalog',unavailable)
    assert read(env,app,revision=1)['selected']['revision']==1
    assert check(env,app)['summary']['counts']['required_checked']==1


@pytest.mark.parametrize('limit,value',[('MAX_HISTORY_BYTES',10),('MAX_REVISIONS',1)])
def test_oversized_history_is_not_partially_returned_or_extended(env,monkeypatch,limit,value):
    app=setup(env);receive(env,app)
    monkeypatch.setattr(service,limit,value)
    with pytest.raises(EntryStorageInvalid):read(env,app)
    with pytest.raises(EntryStorageInvalid):check(env,app,revision=2)


def test_rehashed_snapshot_still_cannot_forge_review(env):
    import json
    from app.domain.entry_storage import _hash
    app=setup(env);receive(env,app)
    async def corrupt():
        async with env['sm']() as session:
            row=await session.scalar(select(EntryDocumentRevision).where(EntryDocumentRevision.revision==2))
            payload=service._payload(row)
            payload['snapshot']['items']['d03_0']['status']='checked'
            changed=json.dumps(payload['snapshot'])
            digest=_hash(payload)
        async with env['engine'].begin() as conn:
            await conn.execute(text('UPDATE entry_document_revisions SET snapshot=:snapshot,snapshot_hash=:hash WHERE revision=2'),
                               dict(snapshot=changed,hash=digest))
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid,match='document_integrity_failed'):read(env,app)
    with pytest.raises(EntryStorageInvalid):check(env,app,revision=2)
