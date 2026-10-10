"""Synthetic binary quarantine, real transactions/FKs and failure recovery."""
import asyncio
from dataclasses import replace
import hashlib

import pytest
from sqlalchemy import event, select, text, update, delete
from sqlalchemy.orm import Session

from app.domain import entry_quarantine as service
from app.domain.entry_quarantine_policy import QuarantinePolicy, policy_from_document, validate_file
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.models import EntryQuarantinedFile, DomainError
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import enforce_sqlite_foreign_keys, person, application, record
from tests.test_entry_document_packages import setup, read, receive, check, complete, approve, write
from tests.test_quarantine_multipart import PDF


def policy(**changes):
    return replace(QuarantinePolicy(reference='SYNTHETIC-UPLOAD',proof='1'*64,storage='domain_database',uploaders=('admin',),
        allowed_types=('application/pdf','image/jpeg'),valid_from='2026-01-01',review_due_on='2027-01-01',
        max_file_bytes=1024,max_application_files=3,max_application_bytes=3072,
        privacy_reference='SYNTHETIC-PRIVACY',privacy_proof='2'*64,retention_reference='SYNTHETIC-RETENTION',retention_proof='3'*64),**changes)


def arguments(env,app,**changes):
    current=read(env,app)
    return dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],expected_revision=current['current_revision'],
        expected_document_version=current['selected']['snapshot']['items']['t08_02']['version'],item_id='t08_02',
        request_key='upload-'+str(current['current_revision']),received_on='2026-09-03',source='client_copy',
        data=PDF,filename='synthetic.pdf',media_type='application/pdf',policy=policy())|changes


def upload(env,app,**changes):
    return asyncio.run(service.record_upload(env['engine'],**arguments(env,app,**changes)))


def test_atomic_receipt_exact_retry_versions_and_internal_integrity(env):
    app=setup(env); args=arguments(env,app)
    row=asyncio.run(service.record_upload(env['engine'],**args))
    assert row['status']=='quarantined' and not row['release_allowed'] and 'content' not in row
    assert asyncio.run(service.record_upload(env['engine'],**args))==row
    current=read(env,app)
    assert current['current_revision']==2 and len(current['quarantine'])==1
    assert current['selected']['snapshot']['items']['t08_02']['fingerprint']==hashlib.sha256(PDF).hexdigest()
    assert current['current_acceptance']==dict(accepted=False,reason='document_in_quarantine')
    assert asyncio.run(service.verify_file(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],file_id=row['id']))==row
    newer=upload(env,app,data=PDF+b'new revision')
    assert newer['document_version']==2 and len(read(env,app)['quarantine'])==2
    assert asyncio.run(service.record_upload(env['engine'],**args))==row
    for changes in (dict(data=PDF+b'changed'),dict(policy=policy(proof='9'*64)),dict(item_id='g02_01')):
        with pytest.raises(EntryStorageConflict,match='request_key_reused'):
            asyncio.run(service.record_upload(env['engine'],**(args|changes)))


def test_quarantine_cannot_be_checked_or_laundered_through_another_item(env):
    app=setup(env); row=upload(env,app); digest=row['fingerprint']
    with pytest.raises(EntryStorageInvalid,match='document_in_quarantine'):
        write(env,app,'review',dict(item='t08_02',fingerprint=digest,version=1,on='2026-09-03',outcome='checked',reason=None,alternative=None))


def test_quarantine_blocks_cross_item_metadata_and_package_approval(env):
    app=setup(env); allowed=complete(env,app); row=upload(env,app)
    receive(env,app,item='g02_01',fingerprint=row['fingerprint'])
    with pytest.raises(EntryStorageInvalid,match='document_in_quarantine'):
        check(env,app,item='g02_01',fingerprint=row['fingerprint'])
    with pytest.raises(EntryStorageInvalid,match='document_in_quarantine'): approve(env,app,allowed)
    current=read(env,app,policy=allowed)
    assert sum(r['quarantined'] for r in current['selected']['summary']['rows'])==2
    assert current['current_acceptance']['accepted'] is False


def test_quarantine_cannot_be_laundered_through_another_application(env):
    first=setup(env); second=setup(env,key='second'); allowed=complete(env,second)
    digest=hashlib.sha256(PDF).hexdigest()
    receive(env,second,fingerprint=digest)
    check(env,second,fingerprint=digest,version=2)
    approve(env,second,allowed)
    assert read(env,second,policy=allowed)['current_acceptance']['accepted']
    upload(env,first)
    assert read(env,second,policy=allowed)['current_acceptance']==dict(accepted=False,reason='document_in_quarantine')
    with pytest.raises(EntryStorageInvalid,match='document_in_quarantine'):
        check(env,second,fingerprint=digest,version=2,key='recheck-other-application')
    with pytest.raises(EntryStorageInvalid,match='document_in_quarantine'): approve(env,second,allowed)
    # Even loss of the binary row must not turn the surviving receipt into approval.
    async def damage():
        async with env['engine'].begin() as conn: await conn.execute(text('DELETE FROM entry_quarantined_files'))
    asyncio.run(damage())
    assert read(env,second,policy=allowed)['current_acceptance']['accepted'] is False


def test_legacy_inventory_also_blocks_globally_quarantined_content(env):
    from tests import test_entry_documents as legacy
    first=setup(env); old=legacy.setup(env,key='legacy'); digest=hashlib.sha256(PDF).hexdigest()
    legacy.receive(env,old,fingerprint=digest); legacy.check(env,old,fingerprint=digest)
    upload(env,first)
    with pytest.raises(EntryStorageInvalid,match='document_in_quarantine'):
        legacy.check(env,old,fingerprint=digest,key='after-quarantine')
    current=legacy.read(env,old)['selected']
    assert next(r for r in current['summary']['items'] if r['id']=='d03_0')['effective_status']=='quarantined'
    assert current['summary']['counts']['required_checked']==0


@pytest.mark.parametrize('changes',[
    {'filename':'../scan.pdf'},{'filename':'C:\\fakepath\\scan.pdf'},{'filename':'scan.pdf.exe'},
    {'filename':'scan.pdf '},{'filename':'scan.jpg'},{'media_type':'text/html'},
    {'data':b'MZfake executable'},{'data':b''},{'data':PDF+b'x'*1024},{'expected_sha256':'a'*64},
])
def test_invalid_files_never_create_package_receipt(env,changes):
    app=setup(env)
    with pytest.raises(EntryStorageInvalid): upload(env,app,**changes)
    assert read(env,app)['current_revision']==1 and read(env,app)['quarantine']==[]


@pytest.mark.parametrize('changes',[
    {'storage':'/arbitrary/path'},{'uploaders':('system',)},{'allowed_types':(['pdf'],)},
    {'max_file_bytes':True},{'max_application_files':0},{'max_application_bytes':1},
    {'privacy_reference':'private free text'},{'retention_proof':'bad'},{'valid_from':'2028-01-01'},
])
def test_invalid_policy_and_roundtrip(changes):
    with pytest.raises(EntryStorageInvalid): policy(**changes)
    allowed=policy(); assert policy_from_document(allowed.document()).digest==allowed.digest


def test_access_policy_dates_closed_application_and_scope(env):
    app=setup(env)
    for changes in (dict(actor=Actor('admin',False)),dict(actor=Actor('someone',True)),dict(policy=None)):
        with pytest.raises(PermissionDenied): upload(env,app,**changes)
    with pytest.raises(EntryStorageInvalid,match='outdated'): upload(env,app,policy=policy(review_due_on='2026-01-02'))
    with pytest.raises(EntryStorageInvalid): upload(env,app,case_id=env['cases']['other'])
    with pytest.raises(EntryStorageConflict): upload(env,app,expected_document_version=1)
    with pytest.raises(EntryStorageConflict): upload(env,app,expected_revision=2)
    record(env,app); record(env,app,'closed',status='closed',occurred_on='2026-09-02')
    with pytest.raises(EntryStorageInvalid,match='closed'): upload(env,app)


@pytest.mark.parametrize('when',['before_commit','after_commit','before_insert'])
def test_rollback_lost_ack_and_retry_keep_exactly_one_pair(env,when):
    app=setup(env); args=arguments(env,app)
    def fail(*args): raise RuntimeError('synthetic fault')
    target=EntryQuarantinedFile if when=='before_insert' else Session
    event.listen(target,when,fail)
    try:
        with pytest.raises(EntryStorageUnavailable): asyncio.run(service.record_upload(env['engine'],**args))
    finally: event.remove(target,when,fail)
    state=read(env,app)
    assert state['current_revision']==(2 if when=='after_commit' else 1)
    assert len(state['quarantine'])==(1 if when=='after_commit' else 0)
    result=asyncio.run(service.record_upload(env['engine'],**args))
    assert len(read(env,app)['quarantine'])==1 and result['document_version']==1


def test_retained_quotas_and_concurrent_requests(env):
    app=setup(env); args=arguments(env,app,policy=policy(max_application_files=1))
    async def run():
        same=await asyncio.gather(*(service.record_upload(env['engine'],**args) for _ in range(2)))
        assert same[0]==same[1]
    asyncio.run(run())
    with pytest.raises(EntryStorageInvalid,match='quota'):
        upload(env,app,data=PDF+b'new',policy=args['policy'])
    assert read(env,app)['current_revision']==2 and len(read(env,app)['quarantine'])==1


def test_two_distinct_uploads_race_for_last_slot(env):
    app=setup(env); args=arguments(env,app,policy=policy(max_application_files=1))
    async def run():
        results=await asyncio.gather(service.record_upload(env['engine'],**args),
            service.record_upload(env['engine'],**(args|dict(request_key='other',data=PDF+b'other'))),return_exceptions=True)
        assert sum(isinstance(v,dict) for v in results)==1
        assert sum(isinstance(v,EntryStorageConflict) for v in results)==1
    asyncio.run(run())
    assert len(read(env,app)['quarantine'])==1


def test_jpeg_and_retained_byte_quota(env):
    app=setup(env); data=b'\xff\xd8\xff'+b'synthetic jpeg'
    allowed=policy(max_file_bytes=len(data),max_application_bytes=len(data))
    upload(env,app,data=data,filename='synthetic.jpeg',media_type='image/jpeg',policy=allowed)
    with pytest.raises(EntryStorageInvalid,match='quota'):
        upload(env,app,data=data[:-1]+b'X',filename='replacement.jpg',media_type='image/jpeg',policy=allowed)


def test_package_read_does_not_load_blobs_and_immutability_and_corruption(env):
    app=setup(env); row=upload(env,app); sql=[]
    def capture(conn,cursor,statement,params,ctx,many): sql.append(statement)
    event.listen(env['engine'].sync_engine,'before_cursor_execute',capture)
    try: assert len(read(env,app)['quarantine'])==1
    finally: event.remove(env['engine'].sync_engine,'before_cursor_execute',capture)
    assert not any('entry_quarantined_files.content' in s for s in sql)
    async def corrupt():
        for statement in (update(EntryQuarantinedFile).values(fingerprint='a'*64),delete(EntryQuarantinedFile)):
            async with env['sm']() as session:
                with pytest.raises(DomainError): await session.execute(statement)
        async with env['engine'].begin() as connection:
            await connection.execute(text('UPDATE entry_quarantined_files SET content=:content WHERE id=:id'),dict(content=b'x'*len(PDF),id=row['id']))
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid,match='integrity'):
        asyncio.run(service.verify_file(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],file_id=row['id']))


@pytest.mark.parametrize('quarantine_target',['file','passport'])
def test_issued_document_cannot_reuse_quarantined_content(env,quarantine_target):
    from tests import test_entry_issued as issued
    from tests.test_admin_kg_entry import Form
    digest=hashlib.sha256(PDF).hexdigest()
    fingerprint=digest if quarantine_target=='file' else 'a'*64
    passport=digest if quarantine_target=='passport' else 'b'*64
    app=issued.setup(env,key='issued-quarantine')
    issued.file(env,app,fingerprint=fingerprint,passport=passport)
    checked=issued.review(env,app,fingerprint=fingerprint,passport=passport)
    assert checked['summary']['verification_current']
    upload(env,setup(env))
    selected=issued.read(env,app)['selected']
    assert selected['snapshot']==checked['snapshot']
    assert selected['summary']['quarantined'] and not selected['summary']['verification_current']
    assert not selected['summary']['delivery_complete'] and not selected['summary']['receipt_current_and_checked']
    retry=issued.review(env,app,fingerprint=fingerprint,passport=passport,revision=1,key='review-1')
    assert retry['snapshot']==checked['snapshot'] and not retry['summary']['verification_current']
    historical=issued.read(env,app,revision=checked['revision'])['selected']
    assert historical['snapshot']==checked['snapshot'] and historical['summary']['quarantined']
    with pytest.raises(EntryStorageInvalid,match='document_in_quarantine'):
        issued.review(env,app,fingerprint=fingerprint,passport=passport,key='review-again')
    for action,extra in [('delivery',dict(channel='email',proof='c'*64,pamphlet='d'*64)),
                         ('receipt',dict(proof='e'*64,identity_checked=True))]:
        with pytest.raises(EntryStorageInvalid,match='document_in_quarantine'):
            issued.write(env,app,action,dict(version=1,fingerprint=fingerprint,on='2026-09-05',**extra))
    page=env['client'].get(env['url']+'/applications/'+str(app['id'])+'/issued')
    assert page.status_code==200 and 'kg-is-quarantine' in page.text
    for action in ('review','delivery','receipt'):assert not Form(page.text,'kg-is-'+action).data
    assert Form(page.text,'kg-is-correction').data


@pytest.mark.parametrize('field',['version','timestamp'])
def test_rehashed_metadata_must_match_actual_receipt_snapshot(env,field):
    from datetime import timedelta
    from types import SimpleNamespace
    from app.domain.entry_storage import _hash
    app=setup(env); saved=upload(env,app)
    async def corrupt():
        async with env['sm']() as session:
            row=await session.get(EntryQuarantinedFile,saved['id'])
            fake=SimpleNamespace(**{column.name:getattr(row,column.name) for column in EntryQuarantinedFile.__table__.columns if column.name!='content'})
            fake.command=service._plain(fake.command)
            if field=='version':
                fake.document_version=399;fake.command['expected_document_version']=398
            else: fake.created_at+=timedelta(seconds=1)
            fake.request_hash=_hash(fake.command); fake.snapshot_hash=_hash(service._payload(fake))
        async with env['engine'].begin() as conn:
            await conn.execute(EntryQuarantinedFile.__table__.update().where(EntryQuarantinedFile.id==saved['id']).values(
                document_version=fake.document_version,command=fake.command,created_at=fake.created_at,
                request_hash=fake.request_hash,snapshot_hash=fake.snapshot_hash))
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid,match='quarantine_integrity_failed'): read(env,app)


@pytest.mark.parametrize('damage',['missing_row','missing_table'])
def test_missing_binary_half_of_atomic_pair_blocks_read_and_review(env,damage):
    app=setup(env); saved=upload(env,app)
    async def corrupt():
        async with env['engine'].begin() as conn:
            await conn.execute(text('DELETE FROM entry_quarantined_files' if damage=='missing_row' else 'DROP TABLE entry_quarantined_files'))
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid,match='quarantine_integrity_failed'): read(env,app)
    operation=dict(action='review',data=dict(item='t08_02',fingerprint=saved['fingerprint'],version=1,
        on='2026-09-03',outcome='checked',reason=None,alternative=None),confirmed=True)
    with pytest.raises(EntryStorageInvalid,match='quarantine_integrity_failed'):
        asyncio.run(service.packages.record_package_operation(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],
            application_id=app['id'],expected_revision=2,request_key='review-after-corruption',operation=operation))
