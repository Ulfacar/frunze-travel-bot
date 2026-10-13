"""Synthetic process journals: evidence semantics, scope and recoverable writes."""
import asyncio
from dataclasses import replace
from datetime import timedelta

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.orm import Session

from app.domain import entry_processes as service
from app.domain.entry_process_policy import ProcessPolicy, policy_from_document, edge_id, AUTHORITATIVE, ROOTS
from app.domain.entry_process_rules import catalog
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.models import EntryProcessEvent, EntryProcessPin
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge.process_preview import CATALOG_SHA256
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import person, application, record, enforce_sqlite_foreign_keys
from tests import test_entry_document_packages as packages
from tests import test_applicant_profiles as profiles


def policy(**changes):
    manual = (set(catalog()['facts']) - AUTHORITATIVE) | {'profile_review_complete'}
    return replace(ProcessPolicy(reference='SYNTHETIC-PROCESS', proof='1'*64, catalog_digest=CATALOG_SHA256,
        operators=('admin',), valid_from='2026-01-01', review_due_on='2027-01-01',
        source_reference='SYNTHETIC-REVIEW', source_proof='2'*64,
        allowed_edges=tuple(edge_id(e) for e in catalog()['edges']), initial_procedures=tuple(ROOTS),
        manual_sources=tuple((f, ('operator_check', 'official_document', 'portal')) for f in sorted(manual)),
        full_case_payment_procedures=('visa', 'unified_permit')), **changes)


def read(env, app, **kwargs):
    kwargs.setdefault('policy', policy())
    return asyncio.run(service.read_process_history(env['engine'], actor=ADMIN, case_id=env['cases']['visa'],
        application_id=app['id'], **kwargs))


def arguments(env, app, action, data, **kwargs):
    revision = kwargs.pop('revision', None)
    if revision is None: revision = read(env, app)['current_revision']
    return dict(actor=ADMIN, case_id=env['cases']['visa'], application_id=app['id'], expected_revision=revision,
        request_key=f'{action}-{revision}', operation=dict(action=action, data=data, confirmed=True), policy=policy()) | kwargs


def write(env, app, action, data, **kwargs):
    return asyncio.run(service.record_process_operation(env['engine'], **arguments(env, app, action, data, **kwargs)))


def today(): return service.applications._today().isoformat()


def setup(env, key='first', procedure='visa', applicant=None):
    app = application(env, applicant or person(env, key+'-person'), key+'-app', procedure=procedure)
    write(env, app, 'initialize', dict(catalog_digest=CATALOG_SHA256, on=today(),
        employer_reference='SYNTHETIC-EMPLOYER' if procedure == 'unified_permit' else None), revision=0)
    return app


def attest(env, app, fact, value=True, role='visa', **kwargs):
    data = dict(role=role, fact=fact, value=value, on=today(), valid_through='2026-12-31',
        source='operator_check', reference='SYNTHETIC-EVIDENCE', proof='3'*64, profile_id=None)
    fields = {k:kwargs.pop(k) for k in list(kwargs) if k in data}
    return write(env, app, 'attest', data | fields, **kwargs)


def transition(env, app, target, **kwargs):
    state = read(env, app, package_policy=kwargs.get('package_policy'))
    edge = next(e for e in state['readiness']['transitions'] if e['edge']['to'] == target)
    return write(env, app, 'transition', dict(edge_id=edge['edge_id'], evidence_digest=edge['evidence_digest'] or '0'*64,
        on=today()), **kwargs)


def test_explicit_edges_manual_evidence_exact_retry_and_history(env):
    app = setup(env)
    first = read(env, app)['selected']
    assert first['snapshot']['stage'] == 'V01'
    with pytest.raises(EntryStorageInvalid, match='prerequisites'): transition(env, app, 'V02')
    args = arguments(env, app, 'attest', dict(role='visa', fact='conversation_started', value=True, on=today(),
        valid_through='2026-12-31', source='operator_check', reference='SYNTHETIC', proof='3'*64, profile_id=None))
    saved = asyncio.run(service.record_process_operation(env['engine'], **args))
    assert asyncio.run(service.record_process_operation(env['engine'], **args))['id'] == saved['id']
    moved = transition(env, app, 'V02')
    assert moved['snapshot']['stage'] == 'V02' and moved['current_revision'] == 3
    assert read(env, app, revision=1)['selected'] == first
    with pytest.raises(EntryStorageConflict):
        asyncio.run(service.record_process_operation(env['engine'], **(args | {'request_key':'stale'})))


@pytest.mark.parametrize('changes', [dict(catalog_digest='0'*64), dict(operators=('bot',)),
    dict(allowed_edges=('0'*64,)), dict(initial_procedures=('exit_visa',)),
    dict(manual_sources=(('consent_confirmed', ('operator_check',)),)), dict(proof='bad')])
def test_invalid_policy_and_immutable_roundtrip(changes):
    with pytest.raises(EntryStorageInvalid): policy(**changes)
    original = policy(); document = original.document()
    assert policy_from_document(document).digest == original.digest
    document['manual_sources'].clear()
    assert original.manual_sources


def test_policy_authority_expiry_and_exact_edge_scope(env):
    app = setup(env)
    for override in (dict(policy=None), dict(actor=Actor('manager')), dict(actor=Actor('other', True))):
        with pytest.raises(PermissionDenied): attest(env, app, 'conversation_started', **override)
    with pytest.raises(EntryStorageInvalid, match='outdated'):
        attest(env, app, 'conversation_started', policy=policy(review_due_on='2026-01-02'))
    attest(env, app, 'conversation_started')
    with pytest.raises(EntryStorageInvalid, match='not_authorized'):
        transition(env, app, 'V02', policy=policy(allowed_edges=(edge_id(catalog()['edges'][1]),)))
    assert read(env, app)['current_revision'] == 2


@pytest.mark.parametrize('fact', sorted(AUTHORITATIVE))
def test_browser_cannot_attest_authoritative_facts(env, fact):
    app = setup(env)
    with pytest.raises(EntryStorageInvalid, match='authoritative'): attest(env, app, fact)
    assert read(env, app)['current_revision'] == 1


def test_dependency_scope_and_distinct_procedures(env):
    subject = person(env, 'subject'); other = person(env, 'other')
    app = setup(env, procedure='unified_permit', applicant=subject)
    wrong_person = application(env, other, 'wrong-person', procedure='resident_card')
    wrong_procedure = application(env, subject, 'wrong-procedure', procedure='visa')
    for child in (wrong_person, wrong_procedure):
        with pytest.raises(EntryStorageInvalid):
            write(env, app, 'link', dict(role='resident', application_id=child['id'], on=today()))
    child = application(env, subject, 'resident', procedure='resident_card')
    linked = write(env, app, 'link', dict(role='resident', application_id=child['id'], on=today()))
    assert linked['snapshot']['links']['resident'] == child['id']
    assert linked['snapshot']['active_application_id'] == app['id']
    with pytest.raises(EntryStorageInvalid):
        write(env, app, 'link', dict(role='permit', application_id=child['id'], on=today()))


def test_partial_profile_is_not_completeness_and_change_invalidates_review(env):
    subject = person(env, 'subject')
    app = setup(env, procedure='registration', applicant=subject)
    doc = profiles.request(); doc['profile'] = {}
    original = profiles.save(env, subject, doc=doc)
    assert not read(env, app)['readiness']['transitions'][0]['ready']
    attest(env, app, 'profile_review_complete', role='registration', profile_id=original['qualification_id'])
    moved = transition(env, app, 'R02')
    assert moved['snapshot']['stage'] == 'R02'
    profiles.save(env, subject, revision=1, key='changed')
    state = read(env, app)
    assert not state['readiness']['ready']
    assert state['readiness']['retained']['registration.profile_complete']['reason'] == 'attestation_profile_changed'
    assert read(env, app, revision=moved['revision'])['selected']['snapshot'] == moved['snapshot']


def test_stop_after_policy_expiry_and_reserved_capacity(env, monkeypatch):
    app = setup(env); attest(env, app, 'conversation_started')
    monkeypatch.setattr(service, 'MAX_EVENTS', 3)
    with pytest.raises(EntryStorageInvalid, match='history_limit'): transition(env, app, 'V02')
    stop = write(env, app, 'stop', dict(on=today(), reference='SYNTHETIC-STOP', proof='4'*64), policy=None)
    assert stop['snapshot']['stopped'] and not stop['readiness']['ready']
    assert read(env, app)['selected']['id'] == stop['id']


def test_pin_limit_is_visible_before_transition_and_stop_remains_available(env,monkeypatch):
    app=setup(env);attest(env,app,'conversation_started')
    monkeypatch.setattr(service,'MAX_PINS',2)
    current=read(env,app)
    edge=next(e for e in current['readiness']['transitions'] if e['edge']['to']=='V02')
    assert not edge['ready'] and edge['reason']=='process_evidence_limit'
    stopped=write(env,app,'stop',dict(on=today(),reference='SYNTHETIC-STOP',proof='4'*64),policy=None)
    assert stopped['snapshot']['stopped']


@pytest.mark.parametrize('when', ['before_commit', 'after_commit', 'before_insert'])
def test_atomic_pins_lost_ack_exact_retry(env, when):
    app = setup(env)
    args = arguments(env, app, 'attest', dict(role='visa', fact='conversation_started', value=True,
        on=today(), valid_through='2026-12-31', source='operator_check', reference='SYNTHETIC', proof='3'*64, profile_id=None))
    def fail(*args): raise RuntimeError('synthetic fault')
    target = EntryProcessPin if when == 'before_insert' else Session
    event.listen(target, when, fail)
    try:
        with pytest.raises(EntryStorageUnavailable): asyncio.run(service.record_process_operation(env['engine'], **args))
    finally: event.remove(target, when, fail)
    assert read(env, app)['current_revision'] == (2 if when == 'after_commit' else 1)
    saved = asyncio.run(service.record_process_operation(env['engine'], **args))
    assert saved['current_revision'] == 2
    assert asyncio.run(service.record_process_operation(env['engine'], **args))['id'] == saved['id']


def test_missing_relational_pin_fails_closed(env):
    app = setup(env)
    async def damage():
        async with env['engine'].begin() as conn: await conn.execute(text('DELETE FROM entry_process_pins'))
    asyncio.run(damage())
    with pytest.raises(EntryStorageInvalid, match='pin_integrity'): read(env, app)


def money(env, action='record_payment', **kwargs):
    from app.domain import service_money
    async def run():
        async with env['sm']() as session:
            row = await getattr(service_money, action)(session, env['cases']['visa'],
                by=Actor('medina',True,frozenset({'visa'})), **kwargs)
            await session.commit()
            return row.id
    return asyncio.run(run())


def visa_ready(env, fingerprint=None):
    subject=person(env,'visa-subject'); app=setup(env,applicant=subject)
    profile=profiles.save(env,subject)
    packages.setup(env,app=app); allowed=packages.complete(env,app)
    if fingerprint:
        packages.receive(env,app,fingerprint=fingerprint)
        packages.check(env,app,fingerprint=fingerprint,version=2)
    packages.approve(env,app,allowed)
    for fact,value in [('conversation_started',True),('manager_review_required',False),('eligibility','eligible'),
        ('profile_review_complete',True),('visa_required',True),('quote_sent',True),('offer_accepted',True),
        ('invoice_issued',True),('checklist_sent',True),('portal_draft_created',True),('email_verified',True),('portal_payment_confirmed',True)]:
        attest(env,app,fact,value,profile_id=profile['qualification_id'] if fact in ('eligibility','profile_review_complete','visa_required') else None)
    for target in ('V02','V04','V06','V07','V08'): transition(env,app,target,package_policy=allowed)
    return app,allowed


def test_full_visa_path_payment_void_and_refund_never_keep_ready(env):
    app,allowed=visa_ready(env)
    first=money(env,amount='40000',currency='KGS',idempotency_key='part-one')
    with pytest.raises(EntryStorageInvalid,match='prerequisites'): transition(env,app,'V09',package_policy=allowed)
    second=money(env,amount='60000',currency='KGS',idempotency_key='part-two')
    paid=transition(env,app,'V09',package_policy=allowed)
    assert paid['readiness']['ready']
    money(env,'void_entry',voids_id=second,reason='synthetic cancellation',idempotency_key='void-two')
    assert not read(env,app,package_policy=allowed)['readiness']['ready']
    assert read(env,app,revision=paid['revision'],package_policy=allowed)['selected']['snapshot']==paid['snapshot']
    money(env,amount='60000',currency='KGS',idempotency_key='replacement')
    assert read(env,app,package_policy=allowed)['readiness']['ready']
    money(env,'record_refund_due',amount='10000',currency='KGS',idempotency_key='refund',reason='synthetic return')
    assert not read(env,app,package_policy=allowed)['readiness']['ready']


def test_visa_rework_requires_new_approval_and_new_submission_then_post_issue(env):
    from tests import test_entry_issued as post_issue
    app,allowed=visa_ready(env)
    money(env,amount='100000',currency='KGS',idempotency_key='full')
    for target in ('V09','V10','V12','V14','V15'): transition(env,app,target,package_policy=allowed)
    record(env,app,'first-submit',reference='VR000001')
    for target in ('V16','V17'): transition(env,app,target,package_policy=allowed)
    record(env,app,'return',status='revision_requested',occurred_on='2026-09-02',reference='VR000001')
    transition(env,app,'V18',package_policy=allowed)
    with pytest.raises(EntryStorageInvalid,match='prerequisites'): transition(env,app,'V19',package_policy=allowed)
    record(env,app,'resubmit',occurred_on='2026-09-03',reference='VR000001')
    with pytest.raises(EntryStorageInvalid,match='prerequisites'): transition(env,app,'V19',package_policy=allowed)
    packages.approve(env,app,allowed,key='new-correction-review')
    for target in ('V19','V17'): transition(env,app,target,package_policy=allowed)
    record(env,app,'approve',status='approved',occurred_on='2026-09-04',reference='VR000001')
    transition(env,app,'V20',package_policy=allowed)
    # Native helpers carry a September3 file date, so record this later file explicitly.
    post_issue.write(env,app,'file',dict(fingerprint='a'*64,passport_fingerprint='b'*64,on='2026-09-05'))
    transition(env,app,'V21',package_policy=allowed)
    post_issue.review(env,app,on='2026-09-06')
    for channel in ('messenger','email','crm'):
        post_issue.write(env,app,'delivery',dict(version=1,fingerprint='a'*64,on='2026-09-07',channel=channel,proof='c'*64,pamphlet='d'*64))
    transition(env,app,'V22',package_policy=allowed)
    post_issue.write(env,app,'receipt',dict(version=1,fingerprint='a'*64,on='2026-09-08',proof='e'*64,identity_checked=True))
    final=transition(env,app,'V23',package_policy=allowed)
    assert final['snapshot']['stage']=='V23'
    assert read(env,app,revision=1,package_policy=allowed)['selected']['snapshot']['stage']=='V01'
    # Root approval permits post-issue bookkeeping; live consent still matters.
    packages.write(env,app,'consent',dict(status='withdrawn',on=today(),reference='SYNTHETIC-WITHDRAW',proof='f'*64))
    current=read(env,app,package_policy=allowed)
    assert not current['readiness']['ready'] and current['selected']['snapshot']['stage']=='V23'


def test_signed_evidence_does_not_survive_source_change(env):
    subject=person(env,'person'); app=setup(env,procedure='registration',applicant=subject)
    profile=profiles.save(env,subject)
    attest(env,app,'profile_review_complete',role='registration',profile_id=profile['qualification_id'])
    edge=read(env,app)['readiness']['transitions'][0]
    args=arguments(env,app,'transition',dict(edge_id=edge['edge_id'],evidence_digest=edge['evidence_digest'],on=today()))
    profiles.save(env,subject,revision=1,key='changed')
    with pytest.raises(EntryStorageConflict,match='evidence_changed'):
        asyncio.run(service.record_process_operation(env['engine'],**args))
    assert read(env,app)['selected']['snapshot']['stage']=='R01'


def test_attestation_pins_dependency_before_role_is_ever_active(env):
    subject=person(env,'person'); app=setup(env,procedure='unified_permit',applicant=subject)
    first=application(env,subject,'resident-first',procedure='resident_card')
    write(env,app,'link',dict(role='resident',application_id=first['id'],on=today()))
    attest(env,app,'resident_issued_and_collected',role='resident')
    record(env,first,'resident-submit',reference='RC000001')
    record(env,first,'resident-refuse',status='refused',occurred_on='2026-09-02',reference='RC000001')
    second=application(env,subject,'resident-second',procedure='resident_card',previous=first['id'])
    with pytest.raises(EntryStorageInvalid,match='dependency_in_use'):
        write(env,app,'link',dict(role='resident',application_id=second['id'],on=today()))


def test_concurrent_same_request_and_competing_compare_and_swap(env):
    app=setup(env)
    args=arguments(env,app,'attest',dict(role='visa',fact='conversation_started',value=True,on=today(),
        valid_through='2026-12-31',source='operator_check',reference='SYNTHETIC',proof='3'*64,profile_id=None))
    async def same(): return await asyncio.gather(*(service.record_process_operation(env['engine'],**args) for _ in range(2)))
    rows=asyncio.run(same())
    assert rows[0]['id']==rows[1]['id'] and read(env,app)['current_revision']==2
    edge=read(env,app)['readiness']['transitions'][0]
    args=arguments(env,app,'transition',dict(edge_id=edge['edge_id'],evidence_digest=edge['evidence_digest'],on=today()))
    async def competing():
        return await asyncio.gather(service.record_process_operation(env['engine'],**args),
            service.record_process_operation(env['engine'],**(args|{'request_key':'other-request'})),return_exceptions=True)
    rows=asyncio.run(competing())
    assert sum(isinstance(r,dict) for r in rows)==1 and sum(isinstance(r,EntryStorageConflict) for r in rows)==1
    assert read(env,app)['current_revision']==3


def test_stage_backdating_cannot_claim_prerequisites_before_recording(env):
    app=setup(env); attest(env,app,'conversation_started')
    edge=read(env,app)['readiness']['transitions'][0]
    with pytest.raises(EntryStorageInvalid,match='recording_date'):
        write(env,app,'transition',dict(edge_id=edge['edge_id'],evidence_digest=edge['evidence_digest'],on='2026-08-01'))
    subject=person(env,'profile-subject'); other=setup(env,key='other',procedure='registration',applicant=subject)
    profile=profiles.save(env,subject)
    with pytest.raises(EntryStorageInvalid,match='predates_version'):
        attest(env,other,'profile_review_complete',role='registration',profile_id=profile['qualification_id'],on='2026-08-01')


def test_closed_active_application_is_never_currently_ready(env):
    app=setup(env)
    record(env,app,'closed',status='closed',source='client_request',occurred_on=today(),reference=None)
    state=read(env,app)
    assert not state['readiness']['ready'] and state['readiness']['reason']=='process_application_terminal'


def test_late_old_timestamp_quarantine_preserves_history_but_blocks_current(env,monkeypatch):
    import hashlib
    from tests.test_entry_quarantine import upload
    from tests.test_quarantine_multipart import PDF
    other=packages.setup(env,key='other-upload')
    old_time=service._now()
    app,allowed=visa_ready(env,fingerprint=hashlib.sha256(PDF).hexdigest())
    money(env,amount='100000',currency='KGS',idempotency_key='full')
    for target in ('V09','V10','V12','V14'): accepted=transition(env,app,target,package_policy=allowed)
    assert accepted['readiness']['ready']
    with monkeypatch.context() as patch:
        patch.setattr(packages.service,'_now',lambda:old_time)
        upload(env,other)
    current=read(env,app,package_policy=allowed)
    assert current['selected']['snapshot']==accepted['snapshot']
    assert not current['readiness']['ready']
    assert read(env,app,revision=accepted['revision'],package_policy=allowed)['selected']['snapshot']==accepted['snapshot']
    retry=write(env,app,'transition',accepted['operation']['data'],revision=accepted['revision']-1,package_policy=allowed)
    assert retry['id']==accepted['id'] and not retry['readiness']['ready']
    stop=write(env,app,'stop',dict(on=today(),reference='SYNTHETIC-STOP',proof='4'*64),policy=None)
    assert stop['snapshot']['stopped']


def test_late_old_timestamp_money_preserves_old_balance_and_blocks_current(env):
    from app.domain.models import ServicePayment
    app,allowed=visa_ready(env)
    money(env,amount='100000',currency='KGS',idempotency_key='full')
    old_time=service._now()
    accepted=transition(env,app,'V09',package_policy=allowed)
    def older(mapper,connection,row): row.recorded_at=old_time
    event.listen(ServicePayment,'before_insert',older)
    try: money(env,'record_refund_due',amount='10000',currency='KGS',idempotency_key='late-refund',reason='synthetic')
    finally: event.remove(ServicePayment,'before_insert',older)
    current=read(env,app,package_policy=allowed)
    assert current['selected']['snapshot']==accepted['snapshot'] and not current['readiness']['ready']


@pytest.mark.parametrize('stream',['payments','contracts'])
def test_later_money_stream_growth_preserves_history_retry_and_stop(env,stream):
    app,allowed=visa_ready(env)
    money(env,amount='100000',currency='KGS',idempotency_key='full')
    saved=transition(env,app,'V09',package_policy=allowed)
    for index in range(100):
        if stream=='payments': money(env,amount='1',currency='KGS',idempotency_key=f'growth-{index}')
        else: money(env,'correct_contract_amount',amount='100000',currency='KGS',reason=f'synthetic correction {index}')
    current=read(env,app,package_policy=allowed)
    assert not current['readiness']['ready']
    assert current['readiness']['retained']['visa.service_payment_confirmed']['reason']=='process_money_evidence_limit'
    assert read(env,app,revision=saved['revision'],package_policy=allowed)['selected']['snapshot']==saved['snapshot']
    retry=write(env,app,'transition',saved['operation']['data'],revision=saved['revision']-1,package_policy=allowed)
    assert retry['id']==saved['id'] and not retry['readiness']['ready']
    with pytest.raises(EntryStorageInvalid,match='prerequisites'): transition(env,app,'V10',package_policy=allowed)
    stopped=write(env,app,'stop',dict(on=today(),reference='SYNTHETIC-STOP',proof='4'*64),policy=None)
    assert stopped['snapshot']['stopped'] and read(env,app)['selected']['id']==stopped['id']


@pytest.mark.parametrize('skip_middle',[False,True])
def test_rehashed_package_observation_cannot_use_wrong_revision_consent(env,skip_middle):
    from types import SimpleNamespace
    from app.domain.models import EntryDocumentPackageEvent
    from app.domain.entry_storage import _hash
    subject=person(env,'subject'); app=setup(env,procedure='registration',applicant=subject)
    profile=profiles.save(env,subject)
    attest(env,app,'profile_review_complete',role='registration',profile_id=profile['qualification_id'])
    transition(env,app,'R02')
    packages.setup(env,app=app,product='REG')
    for index,status in enumerate(('granted','withdrawn','granted')):
        packages.write(env,app,'consent',dict(status=status,on=today(),reference='SYNTHETIC-CONSENT',proof='4'*64),key=f'consent-{index}')
    attest(env,app,'stay_basis_checked',role='registration')
    saved=transition(env,app,'R03')
    async def corrupt():
        async with env['sm']() as session:
            original=await session.get(EntryProcessEvent,saved['id'])
            row=SimpleNamespace(**{c.name:service._plain(getattr(original,c.name)) if c.name in
                ('command','snapshot','policy','evidence') else getattr(original,c.name) for c in EntryProcessEvent.__table__.columns})
            sources=list((await session.scalars(select(EntryDocumentPackageEvent).where(
                EntryDocumentPackageEvent.application_id==app['id']).order_by(EntryDocumentPackageEvent.revision))).all())
            withdrawn=sources[2]
            selected=[sources[0],withdrawn] if skip_middle else sources[:3]
            row.evidence['observed']['streams'][f"packages:{app['id']}"]=[r.id for r in selected]
            for packet in row.evidence['facts'].values():
                for pin in packet['pins']:
                    if pin['kind']=='package': pin.update(package_event_id=withdrawn.id,source_hash=withdrawn.snapshot_hash)
            row.command['operation']['data']['evidence_digest']=_hash(row.evidence)
            row.request_hash=_hash(row.command);row.snapshot_hash=_hash(service._payload(row))
            changed={k:getattr(row,k) for k in ('evidence','command','request_hash','snapshot_hash')}
            source_id,source_hash=withdrawn.id,withdrawn.snapshot_hash
        async with env['engine'].begin() as conn:
            await conn.execute(EntryProcessEvent.__table__.update().where(EntryProcessEvent.id==row.id).values(**changed))
            await conn.execute(EntryProcessPin.__table__.update().where(EntryProcessPin.event_id==row.id,
                EntryProcessPin.kind=='package').values(package_event_id=source_id,source_hash=source_hash))
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid,match='observed_prefix_invalid|evidence_changed'): read(env,app)


@pytest.mark.parametrize('stream',['payments','contracts'])
def test_corrective_transition_with_ledger_overflow_remains_replayable(env,stream):
    app,allowed=visa_ready(env)
    money(env,amount='100000',currency='KGS',idempotency_key='full')
    for target in ('V09','V10','V12','V14','V15'): transition(env,app,target,package_policy=allowed)
    record(env,app,'submitted',reference='RC000001')
    for target in ('V16','V17'): transition(env,app,target,package_policy=allowed)
    record(env,app,'returned',status='revision_requested',occurred_on='2026-09-02',reference='RC000001')
    for index in range(100):
        if stream=='payments': money(env,amount='1',currency='KGS',idempotency_key=f'growth-{index}')
        else: money(env,'correct_contract_amount',amount='100000',currency='KGS',reason=f'synthetic {index}')
    corrected=transition(env,app,'V18',package_policy=allowed)
    assert corrected['snapshot']['stage']=='V18' and not corrected['readiness']['ready']
    assert len(corrected['evidence']['observed']['streams'][stream])==101
    payment=corrected['evidence']['facts']['visa.service_payment_confirmed']
    assert payment['value'] is None and payment['reason']=='process_money_evidence_limit'
    assert not any(p['kind']=='payment' for p in payment['pins'])
    assert read(env,app,revision=corrected['revision'],package_policy=allowed)['selected']['snapshot']==corrected['snapshot']
    retry=write(env,app,'transition',corrected['operation']['data'],revision=corrected['revision']-1,package_policy=allowed)
    assert retry['id']==corrected['id'] and not retry['readiness']['ready']
    stopped=write(env,app,'stop',dict(on=today(),reference='SYNTHETIC-STOP',proof='4'*64),policy=None)
    assert stopped['snapshot']['stopped'] and read(env,app)['selected']['id']==stopped['id']
