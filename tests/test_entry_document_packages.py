"""Synthetic full-package operations on real FK-enforced SQLite transactions."""
import asyncio
import copy
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json

import pytest
from sqlalchemy import select, text, update

from app.domain import entry_document_packages as service, entry_package_rules as rules
from app.domain.entry_package_policy import PackagePolicy, policy_from_document
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable, _hash
from app.domain.models import EntryDocumentPackageEvent, DomainError
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge import complete_document_checklist as catalog_module
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import person, application, record, enforce_sqlite_foreign_keys
from tests import test_entry_documents as legacy

DIGEST=catalog_module.CATALOG_SHA256


def read(env,app,case='visa',**kwargs):
    return asyncio.run(service.read_document_package(env['engine'],actor=ADMIN,case_id=env['cases'][case],application_id=app['id'],**kwargs))


def write(env,app,action,data,*,revision=None,key=None,case='visa',actor=ADMIN,policy=None):
    if revision is None: revision=read(env,app,case)['current_revision']
    return asyncio.run(service.record_package_operation(env['engine'],actor=actor,case_id=env['cases'][case],application_id=app['id'],
        expected_revision=revision,request_key=key or f'{action}-{revision}',operation=dict(action=action,data=data,confirmed=True),policy=policy))


def setup(env,product='TR',procedure='visa',key='first',legacy_revision=0,app=None):
    if app is None: app=application(env,person(env,key+'person'),key+'app',procedure=procedure)
    write(env,app,'initialize',dict(product=product,catalog_digest=DIGEST,legacy_revision=legacy_revision),revision=0,key=key+'init')
    return app


def receive(env,app,item='t08_02',fingerprint='a'*64,**kwargs):
    return write(env,app,'receive',dict(item=item,fingerprint=fingerprint,on='2026-09-01',source='client_copy'),**kwargs)


def check(env,app,item='t08_02',fingerprint='a'*64,version=1,alternative=None,**kwargs):
    return write(env,app,'review',dict(item=item,fingerprint=fingerprint,version=version,on='2026-09-02',outcome='checked',reason=None,alternative=alternative),**kwargs)


def policy(definition,**kwargs):
    return replace(PackagePolicy(reference='SYNTHETIC-PACKAGE',proof='1'*64,catalog_digest=definition['catalog_sha256'],reviewers=('admin',),
        valid_from='2026-01-01',review_due_on='2027-01-01',privacy_reference='SYNTHETIC-PRIVACY',privacy_proof='2'*64,
        source_review_reference='SYNTHETIC-SOURCE',source_review_proof='3'*64,
        reviewed_source_items=tuple(r['id'] for r in definition['rows'] if 'verify' in r['marks'] or 'decision' in r['marks']),
        consent_required=True,practice_checks_required=True,allow_metadata_acceptance=True),**kwargs)


def complete(env,app):
    selected=read(env,app)['selected']; definition=selected['definition']
    values={k:v['values'][0] for k,v in definition['facts'].items()}
    write(env,app,'facts',dict(values=values))
    rows=[r for r in read(env,app)['selected']['summary']['rows'] if r['applicable'] and r['kind']!='recommended']
    # Receive all passport copies before checks: each new passport invalidates old checks.
    for row in rows: receive(env,app,item=row['id'],fingerprint=_hash(row['id']))
    for row in rows: check(env,app,item=row['id'],fingerprint=_hash(row['id']),alternative=next(iter(row['alternatives']),None))
    write(env,app,'consent',dict(status='granted',on='2026-09-03',reference='SYNTHETIC-CONSENT',proof='4'*64))
    return policy(definition)


def approve(env,app,policy,**kwargs):
    state=read(env,app)['selected']['snapshot']
    data=dict(expected_state_hash=_hash(state),expected_policy_hash=policy.digest if policy else '0'*64,
        on=service.applications._today().isoformat(),reference='SYNTHETIC-REVIEW',proof='5'*64)
    return write(env,app,'approve',data,policy=policy,**kwargs)


def test_full_catalog_unknown_receive_correction_and_historical_replay(env):
    app=setup(env); first=read(env,app)['selected']
    assert len(first['summary']['rows'])>23 and first['summary']['counts']['applicability_unknown']>0
    assert first['definition']['matrix_present'] is False
    receive(env,app); checked=check(env,app)
    changed=receive(env,app,fingerprint='b'*64)
    assert changed['snapshot']['items']['t08_02']['version']==2
    assert changed['summary']['package_accepted'] is False
    assert read(env,app,revision=checked['revision'])['selected']['snapshot']==checked['snapshot']
    with pytest.raises(EntryStorageInvalid,match='version_changed'): check(env,app)
    correction=write(env,app,'review',dict(item='t08_02',version=2,fingerprint='b'*64,on='2026-09-02',outcome='correction',reason='unreadable',alternative=None))
    assert correction['snapshot']['items']['t08_02']['status']=='correction'
    check(env,app,fingerprint='b'*64,version=2)
    write(env,app,'withdraw_document',dict(item='t08_02',version=2,fingerprint='b'*64,on='2026-09-03',reason='mismatch'))
    with pytest.raises(EntryStorageInvalid,match='withdrawn'): check(env,app,fingerprint='b'*64,version=2)


def test_explicit_legacy_transfer_resets_checks_and_preserves_receipts(env):
    app=legacy.setup(env); receipt=legacy.receive(env,app,key='old-receipt',revision=1); legacy.check(env,app)
    with pytest.raises(EntryStorageConflict,match='legacy_revision'):
        setup(env,product='TS',app=app,legacy_revision=2)
    setup(env,product='TS',app=app,legacy_revision=3)
    state=read(env,app)['selected']['snapshot']; item=state['items']['matrix_d03_0']
    assert item['fingerprint']=='a'*64 and item['status']=='received' and item['reviewed_on'] is None
    assert all(v is None for v in state['facts'].values())
    assert legacy.receive(env,app,key='old-receipt',revision=1)==receipt
    with pytest.raises(EntryStorageInvalid,match='inventory_upgraded'): legacy.receive(env,app,fingerprint='b'*64)
    assert legacy.read(env,app)['current_revision']==3


def test_passport_and_fact_changes_invalidate_current_checks(env):
    app=setup(env);receive(env,app);check(env,app)
    changed=receive(env,app,item='t08_01',fingerprint='b'*64)
    row=next(r for r in changed['summary']['rows'] if r['id']=='t08_02')
    assert row['status']=='checked' and row['effective_status']=='recheck'
    check(env,app)
    changed=write(env,app,'facts',dict(values={'minor':False}))
    assert next(r for r in changed['summary']['rows'] if r['id']=='t08_02')['effective_status']=='recheck'
    with pytest.raises(EntryStorageInvalid,match='fact'): write(env,app,'facts',dict(values={'minor':'false'}))
    with pytest.raises(EntryStorageInvalid,match='fact'): write(env,app,'facts',dict(values={'invented':False}))


def test_approval_is_explicit_pinned_and_revoked_by_edits(env):
    app=setup(env); selected=read(env,app)['selected']; allowed=policy(selected['definition'])
    with pytest.raises(PermissionDenied): approve(env,app,None)
    with pytest.raises(EntryStorageInvalid,match='incomplete'): approve(env,app,allowed)
    allowed=complete(env,app); before=read(env,app)['current_revision']
    accepted=approve(env,app,allowed,key='approval',revision=before)
    assert accepted['approved_in_revision'] and accepted['summary']['submission_allowed'] is False
    assert read(env,app,policy=allowed)['current_acceptance']['accepted'] is True
    assert read(env,app)['current_acceptance']['accepted'] is False
    assert read(env,app,policy=replace(allowed,proof='6'*64))['current_acceptance']['accepted'] is False
    write(env,app,'revoke',dict(on='2026-09-03',reason='review_error'))
    assert read(env,app,policy=allowed)['current_acceptance']['accepted'] is False
    # A lost-ack retry returns its immutable receipt even after policy withdrawal/revocation.
    repeated=write(env,app,'approve',accepted['operation']['data'],revision=before,key='approval',policy=None)
    assert repeated==accepted
    approve(env,app,allowed)
    write(env,app,'passport_change',dict(on='2026-09-03',reason='replacement'))
    assert read(env,app,policy=allowed)['current_acceptance']['accepted'] is False
    with pytest.raises(EntryStorageInvalid,match='incomplete'): approve(env,app,allowed)


def test_approval_cannot_bypass_consent_source_or_review_authority(env):
    app=setup(env,product='EP',procedure='unified_permit'); allowed=complete(env,app)
    with pytest.raises(PermissionDenied): approve(env,app,replace(allowed,reviewers=('another-admin',)))
    with pytest.raises(PermissionDenied): approve(env,app,replace(allowed,allow_metadata_acceptance=False))
    with pytest.raises(EntryStorageInvalid,match='source_unverified'): approve(env,app,replace(allowed,reviewed_source_items=()))
    with pytest.raises(EntryStorageInvalid,match='source_scope'): approve(env,app,replace(allowed,reviewed_source_items=('invented',)))
    with pytest.raises(EntryStorageInvalid,match='outdated'): approve(env,app,replace(allowed,review_due_on='2026-02-01'))
    write(env,app,'consent',dict(status='withdrawn',on='2026-09-04',reference='SYNTHETIC-WITHDRAWAL',proof='7'*64))
    with pytest.raises(EntryStorageInvalid,match='consent_required'): approve(env,app,allowed)


def test_retry_payload_stale_scope_and_named_admin(env):
    app=setup(env); result=receive(env,app,key='same',revision=1)
    assert receive(env,app,key='same',revision=1)==result
    with pytest.raises(EntryStorageConflict): receive(env,app,key='same',revision=1,fingerprint='b'*64)
    with pytest.raises(EntryStorageConflict): receive(env,app,key='stale',revision=1,fingerprint='b'*64)
    with pytest.raises(EntryStorageInvalid): read(env,app,case='other')
    with pytest.raises(PermissionDenied): receive(env,app,revision=2,actor=Actor('medina',False))
    record(env,app);record(env,app,'approved',status='approved',occurred_on='2026-09-02')
    assert receive(env,app,key='same',revision=1)==result
    with pytest.raises(EntryStorageInvalid,match='closed'): check(env,app)


def test_concurrent_duplicate_and_conflicting_writers(env):
    app=setup(env)
    async def run():
        args=dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],expected_revision=1,
            operation=dict(action='receive',data=dict(item='t08_02',fingerprint='a'*64,on='2026-09-01',source='client_copy'),confirmed=True))
        both=await asyncio.gather(*(service.record_package_operation(env['engine'],request_key='same',**args) for _ in range(2)))
        assert both[0]==both[1]
        args['expected_revision']=2; other=copy.deepcopy(args)
        args['operation']['data']['fingerprint']='b'*64;other['operation']['data']['fingerprint']='c'*64
        results=await asyncio.gather(service.record_package_operation(env['engine'],request_key='b',**args),
                                    service.record_package_operation(env['engine'],request_key='c',**other),return_exceptions=True)
        assert sum(isinstance(r,dict) for r in results)==1
        assert sum(isinstance(r,EntryStorageConflict) for r in results)==1
    asyncio.run(run());assert read(env,app)['current_revision']==3


def test_immutable_journal_and_rehashed_false_state_are_rejected(env):
    app=setup(env); receive(env,app)
    async def corrupt():
        async with env['sm']() as session:
            row=await session.scalar(select(EntryDocumentPackageEvent).where(EntryDocumentPackageEvent.revision==2))
            row.state_hash='f'*64
            with pytest.raises(DomainError): await session.commit()
        async with env['sm']() as session:
            with pytest.raises(DomainError): await session.execute(update(EntryDocumentPackageEvent).values(state_hash='a'*64))
        async with env['sm']() as session:
            row=await session.scalar(select(EntryDocumentPackageEvent).where(EntryDocumentPackageEvent.revision==2))
            payload=service._payload(row);payload['state_hash']='f'*64;digest=_hash(payload)
        async with env['engine'].begin() as connection:
            await connection.execute(text('UPDATE entry_document_package_events SET state_hash=:state,snapshot_hash=:hash WHERE revision=2'),dict(state='f'*64,hash=digest))
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid,match='integrity'): read(env,app)


def test_clock_rollback_and_bounded_history(env,monkeypatch):
    app=setup(env)
    now=datetime.fromisoformat(read(env,app)['selected']['created_at'])
    monkeypatch.setattr(service,'_now',lambda:now-timedelta(seconds=1))
    with pytest.raises(EntryStorageInvalid,match='clock_reversed'): receive(env,app)
    monkeypatch.setattr(service,'_now',lambda:now+timedelta(seconds=1))
    receive(env,app)
    monkeypatch.setattr(service,'MAX_BYTES',10)
    with pytest.raises(EntryStorageInvalid,match='history_limit'): read(env,app)


def test_definition_upgrade_is_explicit_and_old_version_replays(env,tmp_path,monkeypatch):
    app=setup(env);receive(env,app);old=check(env,app)
    raw=json.loads(catalog_module.CATALOG_PATH.read_text(encoding='utf-8'));raw['version']='synthetic-next'
    encoded=json.dumps(raw,ensure_ascii=False).encode();digest=hashlib.sha256(encoded).hexdigest()
    path=tmp_path/'catalog.json';path.write_bytes(encoded)
    monkeypatch.setitem(catalog_module.KNOWN_CATALOGS,digest,path)
    upgraded=write(env,app,'upgrade_definition',dict(catalog_digest=digest))
    assert upgraded['definition']['version']=='synthetic-next'
    assert all(v['status']=='missing' for v in upgraded['snapshot']['items'].values())
    assert upgraded['snapshot']['last_invalidation']=='definition_changed'
    assert read(env,app,revision=old['revision'])['selected']['snapshot']==old['snapshot']
    with pytest.raises(EntryStorageInvalid,match='unchanged'): write(env,app,'upgrade_definition',dict(catalog_digest=digest))
    with pytest.raises(EntryStorageInvalid,match='source_unavailable'): write(env,app,'upgrade_definition',dict(catalog_digest='0'*64))


@pytest.mark.parametrize('field,value',[('allow_metadata_acceptance',1),('reviewers',['admin']),('reference','private free text'),
    ('proof','x'*64),('review_due_on','2020-01-01'),('reviewed_source_items',('some item',))])
def test_policy_has_no_untyped_authority_or_freeform_data(field,value):
    with pytest.raises(EntryStorageInvalid): policy(catalog_module.load_definition(DIGEST,'TR'),**{field:value})


def test_policy_roundtrip_is_canonical_and_pure_reducer_never_submits():
    definition=catalog_module.load_definition(DIGEST,'TR'); allowed=policy(definition)
    assert policy_from_document(allowed.document()).digest==allowed.digest
    op=dict(action='initialize',data=dict(product='TR',catalog_digest=DIGEST,legacy_revision=0),confirmed=True)
    state=rules.apply_operation(None,op,actor='admin',definition=definition)
    assert rules.summarize(state,definition)['submission_allowed'] is False


@pytest.mark.parametrize('when',['before_commit','after_commit'])
def test_transaction_rollback_or_lost_ack_and_exact_retry(env,when):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    app=setup(env)
    def fail(session): raise RuntimeError('synthetic transaction fault')
    event.listen(Session,when,fail)
    try:
        with pytest.raises(EntryStorageUnavailable): receive(env,app,key='uncertain',revision=1)
    finally:event.remove(Session,when,fail)
    assert read(env,app)['current_revision']==(1 if when=='before_commit' else 2)
    received=receive(env,app,key='uncertain',revision=1)
    assert received['revision']==2 and read(env,app)['current_revision']==2


def test_policy_expiry_changes_effective_acceptance_without_breaking_history(env,monkeypatch):
    from datetime import date
    app=setup(env);allowed=complete(env,app);accepted=approve(env,app,allowed)
    assert read(env,app,policy=allowed)['current_acceptance']['accepted'] is True
    monkeypatch.setattr(service.applications,'_today',lambda:date(2027,1,2))
    current=read(env,app,policy=allowed)
    assert current['selected']['snapshot']==accepted['snapshot']
    assert current['current_acceptance']==dict(accepted=False,reason='package_policy_outdated')


@pytest.mark.parametrize('action,data',[
    ('receive',dict(item='t08_02',fingerprint='a'*64,on='2026-09-01',source=[])),
    ('review',dict(item='t08_02',fingerprint='a'*64,version=True,on='2026-09-02',outcome='checked',reason=None,alternative=None)),
    ('receive',dict(item='quality04',fingerprint='a'*64,on='2026-09-01',source='manager_check')),
    ('review',dict(item='t08_02',fingerprint='a'*64,version=1,on='2026-08-31',outcome='checked',reason=None,alternative=None)),
    ('facts',dict(values={'passport_number':'private'})),
])
def test_untyped_or_out_of_order_or_policy_check_operations_do_not_append(env,action,data):
    app=setup(env);receive(env,app)
    with pytest.raises(EntryStorageInvalid):write(env,app,action,data,revision=2)
    assert read(env,app)['current_revision']==2


def test_alternative_requires_explicit_valid_choice_and_replacement_resets_it(env):
    app=setup(env);receive(env,app,item='t08_03')
    with pytest.raises(EntryStorageInvalid,match='alternative_required'):check(env,app,item='t08_03')
    with pytest.raises(EntryStorageInvalid,match='alternative_invalid'):check(env,app,item='t08_03',alternative='invented')
    checked=check(env,app,item='t08_03',alternative='ticket')
    assert checked['snapshot']['items']['t08_03']['alternative']=='ticket'
    changed=receive(env,app,item='t08_03',fingerprint='b'*64)
    assert changed['snapshot']['items']['t08_03']['alternative'] is None
    assert read(env,app,revision=checked['revision'])['selected']['snapshot']['items']['t08_03']['alternative']=='ticket'


@pytest.mark.parametrize('action',['revoke','consent'])
def test_closed_application_still_allows_withdrawal_not_reapproval(env,action):
    app=setup(env);allowed=complete(env,app);approve(env,app,allowed)
    record(env,app);record(env,app,'approved',status='approved',occurred_on='2026-09-02')
    data=dict(on=service.applications._today().isoformat(),reason='policy_changed') if action=='revoke' else dict(
        status='withdrawn',on='2026-09-04',reference='SYNTHETIC-WITHDRAWAL',proof='9'*64)
    write(env,app,action,data)
    assert read(env,app,policy=allowed)['current_acceptance']['accepted'] is False
    with pytest.raises(EntryStorageInvalid,match='closed'):approve(env,app,allowed)


def test_selected_tourist_letter_conflicts_with_suppressed_letter_details(env):
    app=setup(env,product='TS');definition=read(env,app)['selected']['definition']
    write(env,app,'facts',dict(values={k:v['values'][0] for k,v in definition['facts'].items()}))
    receive(env,app,item='t01_03');check(env,app,item='t01_03',alternative='tour_operator')
    with pytest.raises(EntryStorageInvalid,match='invitation_conflict'):approve(env,app,policy(definition))


def test_passport_replacement_invalidates_checks_despite_duplicate_fingerprints(env):
    app=setup(env,product='TS')
    receive(env,app,item='matrix_d01_0',fingerprint='a'*64)
    receive(env,app,item='g02_01',fingerprint='a'*64)
    receive(env,app,item='matrix_d02_0',fingerprint='b'*64)
    receive(env,app,item='t01_02',fingerprint='c'*64)
    check(env,app,item='t01_02',fingerprint='c'*64)
    before=read(env,app)['selected']['snapshot']['passport_revision']
    receive(env,app,item='matrix_d01_0',fingerprint='b'*64)
    current=read(env,app)['selected']
    assert current['snapshot']['passport_revision']==before+1
    assert next(r for r in current['summary']['rows'] if r['id']=='t01_02')['effective_status']=='recheck'


def test_v1_passport_gap_preserves_history_but_requires_definition_upgrade(env,monkeypatch):
    import sys
    original_payload=service._payload; original_apply=service.apply_operation
    old_digest='f176ab74144a593fd9ff644ba219d6731205c5fd232f1a661616c0223d40ad1a'
    def old_payload(row):
        if row.id is None: row.command={k:v for k,v in row.command.items() if k!='rules_version'}
        return original_payload(row)
    def old_apply(*args,**kwargs):
        kwargs['rules_version']=1
        return original_apply(*args,**kwargs)
    with monkeypatch.context() as old:
        old.setattr(sys.modules[__name__],'DIGEST',old_digest)
        old.setattr(service,'_payload',old_payload); old.setattr(service,'apply_operation',old_apply)
        old.setattr(service,'_legacy_passport_gap',lambda rows,states:False)
        app=setup(env,product='TS'); allowed=complete(env,app)
        for item,digest in [('matrix_d01_0','a'),('g02_01','a'),('matrix_d02_0','b')]:
            receive(env,app,item=item,fingerprint=digest*64)
        for item in read(env,app)['selected']['summary']['rows']:
            if item['fingerprint']:
                check(env,app,item=item['id'],fingerprint=item['fingerprint'],version=item['version'],alternative=item['alternative'])
        receive(env,app,item='matrix_d01_0',fingerprint='b'*64)
        changed=read(env,app)['selected']['snapshot']['items']['matrix_d01_0']
        check(env,app,item='matrix_d01_0',fingerprint='b'*64,version=changed['version'])
        approved=approve(env,app,allowed)
        assert read(env,app,policy=allowed)['current_acceptance']['accepted']
    preserved=read(env,app,policy=allowed)
    assert preserved['selected']['snapshot_hash']==approved['snapshot_hash']
    assert preserved['selected']['snapshot']==approved['snapshot']
    assert preserved['current_acceptance']==dict(accepted=False,reason='package_passport_recheck_required')
    with pytest.raises(EntryStorageInvalid,match='passport_recheck_required'): approve(env,app,allowed)
    write(env,app,'upgrade_definition',dict(catalog_digest=DIGEST))
    allowed=complete(env,app); approve(env,app,allowed)
    assert read(env,app,policy=allowed)['current_acceptance']['accepted']


@pytest.mark.parametrize('limit',['revisions','bytes'])
def test_full_journal_preserves_revocation_and_consent_withdrawal(env,monkeypatch,limit):
    app=setup(env); allowed=complete(env,app)
    before=read(env,app)['current_revision']
    if limit=='revisions': monkeypatch.setattr(service,'MAX_REVISIONS',before+3)
    approval=approve(env,app,allowed)
    if limit=='bytes':
        async def size():
            async with env['sm']() as session:
                rows=(await session.scalars(select(EntryDocumentPackageEvent))).all()
                return sum(service._bytes(row) for row in rows)
        monkeypatch.setattr(service,'MAX_BYTES',asyncio.run(size())+service.WITHDRAWAL_BYTES)
    assert read(env,app)['ordinary_writes_available'] is False
    with pytest.raises(EntryStorageInvalid,match='history_limit'):
        receive(env,app,fingerprint='b'*64)
    data=dict(on=service.applications._today().isoformat(),reason='policy_changed')
    write(env,app,'revoke',data,key='terminal-revoke')
    assert read(env,app,policy=allowed)['current_acceptance']['accepted'] is False
    with pytest.raises(EntryStorageInvalid,match='history_limit'):
        write(env,app,'revoke',data,key='repeated-revoke')
    consent=dict(status='withdrawn',on='2026-09-04',reference='SYNTHETIC-WITHDRAWAL',proof='9'*64)
    row=write(env,app,'consent',consent,key='terminal-consent')
    retry=write(env,app,'consent',consent,key='terminal-consent',revision=row['revision']-1)
    assert retry==row and row['snapshot']['consent']['status']=='withdrawn'
    assert read(env,app,revision=approval['revision'])['selected']['snapshot']['approval'] is not None
