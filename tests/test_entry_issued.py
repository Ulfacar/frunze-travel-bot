"""Post-issue facts on real FK-enforced SQLite, including stale/missing evidence."""
import asyncio
import copy
import json

import pytest
from sqlalchemy import select,text,update

from app.domain import entry_issued as service
from app.domain.entry_issued_rules import CHECKS
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid,_hash
from app.domain.models import EntryIssuedRevision,DomainError
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_entry_applications import person,application,record,enforce_sqlite_foreign_keys


def setup(env,key='first',approve=True,case='visa',procedure='visa'):
    app=application(env,person(env,key+'person',case=case),key+'app',case=case,procedure=procedure)
    if approve:
        reference=f"AP{app['id']:06}"
        record(env,app,key+'submit',case=case,reference=reference)
        record(env,app,key+'approve',case=case,status='approved',occurred_on='2026-09-02',reference=reference)
    return app


def read(env,app,case='visa',**kwargs):
    return asyncio.run(service.read_issued_history(env['engine'],actor=ADMIN,case_id=env['cases'][case],application_id=app['id'],**kwargs))


def write(env,app,action,data,*,key=None,revision=None,case='visa',actor=ADMIN,confirmed=True):
    if revision is None:revision=read(env,app,case)['current_revision']
    return asyncio.run(service.record_issued_operation(env['engine'],actor=actor,case_id=env['cases'][case],application_id=app['id'],
        expected_revision=revision,request_key=key or f'{action}-{revision}',operation=dict(action=action,data=data,confirmed=confirmed)))


def file(env,app,fingerprint='a'*64,passport='b'*64,**kwargs):
    return write(env,app,'file',dict(fingerprint=fingerprint,passport_fingerprint=passport,on='2026-09-03'),**kwargs)


def review(env,app,checks=None,fingerprint='a'*64,passport='b'*64,version=1,on='2026-09-04',**kwargs):
    return write(env,app,'review',dict(version=version,fingerprint=fingerprint,passport_fingerprint=passport,
        on=on,checks=checks if checks is not None else dict.fromkeys(CHECKS,True)),**kwargs)


def delivery(env,app,channel='email',proof='c'*64,**kwargs):
    return write(env,app,'delivery',dict(version=1,fingerprint='a'*64,on='2026-09-05',channel=channel,proof=proof,pamphlet='d'*64),**kwargs)


def test_separate_verification_delivery_receipt_and_actual_travel(env):
    app=setup(env);file(env,app)
    assert not read(env,app)['selected']['summary']['verification_current']
    with pytest.raises(EntryStorageInvalid,match='review_required'):delivery(env,app)
    checked=review(env,app)
    assert checked['summary']['verification_current'] and not checked['summary']['receipt_recorded']
    for channel in ('messenger','email','crm'):sent=delivery(env,app,channel)
    assert sent['summary']['delivery_complete'] and not sent['summary']['receipt_recorded']
    got=write(env,app,'receipt',dict(version=1,fingerprint='a'*64,on='2026-09-06',proof='e'*64,identity_checked=True))
    assert got['summary']['receipt_recorded'] and got['summary']['receipt_current_and_checked']
    assert not got['summary']['travel_permission_granted'] and not got['summary']['service_completed']
    entry=write(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,source='stamp',passport_fingerprint='b'*64))
    assert entry['summary']['actual_entries']==1 and entry['summary']['actual_exits']==0
    exit=write(env,app,'travel',dict(direction='exit',on='2026-09-08',proof='1'*64,source='official_record',passport_fingerprint='b'*64))
    assert exit['summary']['actual_exits']==1
    assert read(env,app,revision=checked['revision'])['selected']['snapshot']==checked['snapshot']


def test_unknown_failed_checks_correction_and_new_file_require_full_review(env):
    app=setup(env);file(env,app)
    checks=dict.fromkeys(CHECKS,True);checks['photo']=None
    assert not review(env,app,checks)['summary']['verification_current']
    checks['photo']=False
    assert not review(env,app,checks)['summary']['verification_current']
    fixed=write(env,app,'correction',dict(version=1,fingerprint='a'*64,on='2026-09-05',cause='authority',proof='2'*64))
    assert fixed['summary']['correction_pending']
    assert not review(env,app)['summary']['verification_current']
    with pytest.raises(EntryStorageInvalid):delivery(env,app)
    assert not file(env,app,fingerprint='3'*64)['summary']['correction_pending']
    with pytest.raises(EntryStorageInvalid,match='version_changed'):review(env,app)
    checks=dict.fromkeys(CHECKS,True);checks['passport_dates']='not_present'
    assert review(env,app,checks,fingerprint='3'*64,version=2)['summary']['verification_current']


def test_passport_change_back_does_not_resurrect_old_reviews_or_delivery(env):
    app=setup(env);file(env,app);old=review(env,app);delivery(env,app)
    for passport in ('4'*64,'b'*64):
        changed=write(env,app,'passport_change',dict(passport_fingerprint=passport,on='2026-09-06'))
        assert not changed['summary']['verification_current']
    assert read(env,app,revision=old['revision'])['selected']['summary']['verification_current']
    with pytest.raises(EntryStorageInvalid,match='invalid_issued_date'):review(env,app)
    assert review(env,app,on='2026-09-07')['summary']['verification_current']
    assert not read(env,app)['selected']['summary']['delivery_complete']


def test_actual_travel_can_be_backfilled_without_inventing_verification(env):
    app=setup(env)
    data=dict(direction='entry',on='2026-08-01',proof='f'*64,source='stamp',passport_fingerprint='b'*64)
    actual=write(env,app,'travel',data)
    assert actual['summary']['actual_entries']==1 and actual['summary']['version']==0
    assert not actual['summary']['verification_current']
    with pytest.raises(EntryStorageInvalid,match='duplicate_actual'):write(env,app,'travel',data,key='different-key')
    data['proof']='1'*64
    with pytest.raises(EntryStorageInvalid,match='duplicate_actual'):write(env,app,'travel',data,key='different-proof')
    assert file(env,app)['summary']['actual_entries']==1


def test_receipt_does_not_invent_client_identity_check(env):
    app=setup(env);file(env,app);review(env,app);delivery(env,app)
    data=dict(version=1,fingerprint='a'*64,on='2026-09-06',proof='2'*64,identity_checked=None)
    got=write(env,app,'receipt',data)
    assert got['summary']['receipt_recorded'] and not got['summary']['receipt_current_and_checked']
    data.update(proof='3'*64,identity_checked=True)
    assert write(env,app,'receipt',data)['summary']['receipt_current_and_checked']


def test_replacement_cannot_undo_current_passport_binding(env):
    app=setup(env);file(env,app);review(env,app)
    write(env,app,'passport_change',dict(passport_fingerprint='4'*64,on='2026-09-06'))
    with pytest.raises(EntryStorageInvalid,match='passport_mismatch'):file(env,app,fingerprint='3'*64)
    file(env,app,fingerprint='3'*64,passport='4'*64)
    with pytest.raises(EntryStorageInvalid,match='invalid_issued_date'):
        review(env,app,fingerprint='3'*64,passport='4'*64,version=2)
    assert review(env,app,fingerprint='3'*64,passport='4'*64,version=2,on='2026-09-07')['summary']['verification_current']


def test_approval_scope_authorization_and_exact_retry(env):
    pending=setup(env,approve=False)
    assert not read(env,pending)['approval_available']
    with pytest.raises(EntryStorageInvalid,match='approval_required'):file(env,pending)
    app=setup(env,'approved');first=file(env,app,key='same',revision=0)
    assert file(env,app,key='same',revision=0)==first
    with pytest.raises(EntryStorageConflict):file(env,app,key='same',revision=0,fingerprint='c'*64)
    with pytest.raises(EntryStorageConflict):file(env,app,key='stale',revision=0,fingerprint='c'*64)
    with pytest.raises(EntryStorageInvalid):read(env,app,case='other')
    with pytest.raises(EntryStorageInvalid):file(env,app,case='other',revision=1)
    with pytest.raises(PermissionDenied):file(env,app,actor=Actor('medina',False),revision=1)
    unrelated=setup(env,'other',procedure='registration')
    with pytest.raises(EntryStorageInvalid,match='approval_required'):file(env,unrelated)


@pytest.mark.parametrize('operation',[
    dict(action='travel',data=dict(direction='entry',on='2999-01-01',proof='f'*64,source='stamp',passport_fingerprint='b'*64),confirmed=True),
    dict(action='travel',data=dict(direction='entry',on='2026-09-01',proof='f'*64,source='planned',passport_fingerprint='b'*64),confirmed=True),
    dict(action='file',data=dict(fingerprint='passport-number',passport_fingerprint='b'*64,on='2026-09-03'),confirmed=True),
    dict(action='file',data=dict(fingerprint='a'*64,passport_fingerprint='b'*64,on='2026-09-01'),confirmed=True),
    dict(action='file',data=dict(fingerprint='a'*64,passport_fingerprint='b'*64,on='2026-09-03'),confirmed=1),
])
def test_invalid_actual_facts_never_append(env,operation):
    app=setup(env)
    with pytest.raises(EntryStorageInvalid):asyncio.run(service.record_issued_operation(env['engine'],actor=ADMIN,
        case_id=env['cases']['visa'],application_id=app['id'],expected_revision=0,request_key='bad',operation=operation))
    assert read(env,app)['current_revision']==0


def test_concurrent_same_request_and_conflicting_versions(env):
    app=setup(env)
    async def run():
        args=dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],expected_revision=0,
            operation=dict(action='file',data=dict(fingerprint='a'*64,passport_fingerprint='b'*64,on='2026-09-03'),confirmed=True))
        results=await asyncio.gather(*(service.record_issued_operation(env['engine'],request_key='same',**args) for _ in range(2)))
        assert results[0]==results[1]
        args['expected_revision']=1
        left=copy.deepcopy(args);left['operation']['data']['fingerprint']='c'*64
        right=copy.deepcopy(args);right['operation']['data']['fingerprint']='d'*64
        results=await asyncio.gather(service.record_issued_operation(env['engine'],request_key='left',**left),
            service.record_issued_operation(env['engine'],request_key='right',**right),return_exceptions=True)
        assert sum(isinstance(r,dict) for r in results)==1
        assert sum(isinstance(r,EntryStorageConflict) for r in results)==1
    asyncio.run(run());assert read(env,app)['current_revision']==2


def test_orm_guards_and_rehashed_forged_review_are_rejected(env):
    app=setup(env);file(env,app)
    async def corrupt():
        async with env['sm']() as session:
            row=await session.scalar(select(EntryIssuedRevision));payload=service._payload(row)
            row.snapshot_hash='0'*64
            with pytest.raises(DomainError):await session.commit()
        async with env['sm']() as session:
            with pytest.raises(DomainError):await session.execute(update(EntryIssuedRevision).values(snapshot_hash='0'*64))
        payload['snapshot']['review']={'checks':dict.fromkeys(CHECKS,True)}
        async with env['engine'].begin() as conn:
            await conn.execute(text('UPDATE entry_issued_revisions SET snapshot=:snapshot,snapshot_hash=:hash'),
                dict(snapshot=json.dumps(payload['snapshot']),hash=_hash(payload)))
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):read(env,app)
    with pytest.raises(EntryStorageInvalid):review(env,app,revision=1)


@pytest.mark.parametrize('limit,value',[('MAX_BYTES',10),('MAX_REVISIONS',1)])
def test_history_limits_fail_closed_before_new_facts(env,monkeypatch,limit,value):
    app=setup(env);file(env,app);review(env,app)
    monkeypatch.setattr(service,limit,value)
    with pytest.raises(EntryStorageInvalid):read(env,app)
    with pytest.raises(EntryStorageInvalid):delivery(env,app,revision=2)
