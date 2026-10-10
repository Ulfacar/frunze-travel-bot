"""Full work/regularization branches with separate real applicant attempts."""
from dataclasses import replace

import pytest

from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys, person, application, record
from tests.test_entry_processes import setup, write, read, attest, transition, today, money
from tests import test_applicant_profiles as profiles
from tests import test_entry_document_packages as packages
from tests import test_entry_issued as issued


def link(env, root, child, role):
    return write(env,root,'link',dict(role=role,application_id=child['id'],on=today()))


def submit(env, app, approve=False):
    reference=f"PS{app['id']:06}"
    record(env,app,'submit',reference=reference)
    if approve: record(env,app,'approve',status='approved',occurred_on='2026-09-02',reference=reference)
    return reference


def test_work_permit_resident_registration_have_distinct_scoped_decisions(env):
    subject=person(env,'worker'); root=setup(env,procedure='unified_permit',applicant=subject)
    resident=application(env,subject,'resident',procedure='resident_card')
    registration=application(env,subject,'registration',procedure='registration')
    visa=application(env,subject,'visa',procedure='visa')
    for role,child in [('resident',resident),('registration',registration),('visa',visa)]: link(env,root,child,role)
    profile=profiles.save(env,subject)
    attest(env,root,'profile_review_complete',role='permit',profile_id=profile['qualification_id'])
    policies=[]
    for app,product in [(root,'EP'),(resident,'RES')]:
        packages.setup(env,app=app,product=product); policies.append(packages.complete(env,app))
    allowed=replace(policies[0],reviewed_source_items=tuple(sorted(set().union(*(set(p.reviewed_source_items) for p in policies)))))
    for app in (root,resident): packages.approve(env,app,allowed)
    for fact in ('employer_qualified','quote_sent','offer_accepted','employer_authorization_confirmed',
        'account_activated','quota_applied','quota_approved','checklist_sent','permit_issued'):
        attest(env,root,fact,role='permit')
    money(env,amount='100000',currency='KGS',idempotency_key='full')
    for target in ('W02','W03','W04','W05','W06','W07','W08','W09','W10'):
        transition(env,root,target,package_policy=allowed)
    submit(env,root)
    for target in ('W11','W12'): transition(env,root,target,package_policy=allowed)
    record(env,root,'approve',status='approved',occurred_on='2026-09-02',reference=f"PS{root['id']:06}")
    transition(env,root,'W14',package_policy=allowed)
    submit(env,visa,approve=True)
    issued.write(env,visa,'travel',dict(direction='entry',on='2026-09-03',proof='6'*64,source='stamp',passport_fingerprint='7'*64))
    submit(env,registration,approve=True)
    attest(env,root,'registration_confirmed',role='registration')
    transition(env,root,'W15',package_policy=allowed)
    at_resident=transition(env,root,'W16',package_policy=allowed)
    assert at_resident['snapshot']['active_application_id']==resident['id']
    submit(env,resident)
    for target in ('W17','W18'): transition(env,root,target,package_policy=allowed)
    attest(env,root,'resident_issued_and_collected',role='resident')
    state=read(env,root,package_policy=allowed)
    approved_edge=next(e for e in state['readiness']['transitions'] if e['edge']['to']=='W19')
    assert approved_edge['facts']['resident.decision']['value']=='pending' and not approved_edge['ready']
    with pytest.raises(EntryStorageInvalid,match='prerequisites'): transition(env,root,'W19',package_policy=allowed)
    record(env,resident,'approve',status='approved',occurred_on='2026-09-04',reference=f"PS{resident['id']:06}")
    transition(env,root,'W19',package_policy=allowed)
    at_registration=transition(env,root,'W20',package_policy=allowed)
    assert at_registration['snapshot']['active_application_id']==registration['id']
    assert at_registration['snapshot']['root_id']==root['id']
    transition(env,root,'W21',package_policy=allowed)
    for fact in ('completion_reviewed','followup_completed'): attest(env,root,fact,role='registration')
    assert transition(env,root,'W22',package_policy=allowed)['snapshot']['stage']=='W22'


def regularization_at_u06(env,route,procedure,product):
    subject=person(env,'subject'); root=setup(env,procedure='violation_protocol',applicant=subject)
    child=application(env,subject,'dependent',procedure=procedure); link(env,root,child,route)
    profile=profiles.save(env,subject)
    attest(env,root,'profile_review_complete',role='protocol',profile_id=profile['qualification_id'])
    submit(env,root,approve=True)
    for fact in ('overstay_assessed','protocol_received','fine_payment_confirmed','police_letter_received'):
        attest(env,root,fact,role='protocol')
    for target in ('U02','U03','U04','U05'): transition(env,root,target)
    packages.setup(env,app=child,product=product); allowed=packages.complete(env,child); packages.approve(env,child,allowed)
    attest(env,root,'regularization_route',route,role='protocol')
    if route=='registration': attest(env,root,'stay_basis_checked',role='registration')
    submit(env,child)
    current=read(env,root,package_policy=allowed)
    edge=next(e for e in current['readiness']['transitions'] if e['edge']['requires']['regularization_route']==route)
    moved=write(env,root,'transition',dict(edge_id=edge['edge_id'],evidence_digest=edge['evidence_digest'],on=today()),package_policy=allowed)
    assert moved['snapshot']['branch']==route and moved['snapshot']['active_application_id']==child['id']
    return root,child,allowed,moved


@pytest.mark.parametrize('route,procedure,product', [('registration','registration','REG'),('exit_visa','exit_visa','L')])
def test_regularization_uses_distinct_branch_application_and_never_turns_registration_into_l(env,route,procedure,product):
    root,child,allowed,moved=regularization_at_u06(env,route,procedure,product)
    if route=='registration':
        assert all(not e['ready'] and e['reason']=='process_branch_mismatch' for e in moved['readiness']['transitions'])
        assert read(env,root)['application']['procedure']=='violation_protocol'
    else:
        record(env,child,'approve',status='approved',occurred_on='2026-09-02',reference=f"PS{child['id']:06}")
        issued.file(env,child); issued.review(env,child)
        transition(env,root,'U07',package_policy=allowed)
        issued.write(env,child,'travel',dict(direction='exit',on='2026-09-05',proof='7'*64,source='official_record',passport_fingerprint='b'*64))
        transition(env,root,'U08',package_policy=allowed)
        attest(env,root,'completion_reviewed',role='exit_visa')
        assert transition(env,root,'U09',package_policy=allowed)['snapshot']['stage']=='U09'


@pytest.mark.parametrize('invalidate',['quarantine','passport'])
def test_exit_visa_verification_remains_required_after_u07(env,invalidate):
    import asyncio
    import hashlib
    from tests.test_entry_processes import arguments,service
    from tests.test_entry_quarantine import upload
    from tests.test_quarantine_multipart import PDF
    root,child,allowed,_=regularization_at_u06(env,'exit_visa','exit_visa','L')
    record(env,child,'approve',status='approved',occurred_on='2026-09-02',reference=f"PS{child['id']:06}")
    fingerprint=hashlib.sha256(PDF).hexdigest()
    issued.file(env,child,fingerprint=fingerprint); issued.review(env,child,fingerprint=fingerprint)
    state=read(env,root,package_policy=allowed)
    edge=next(e for e in state['readiness']['transitions'] if e['edge']['to']=='U07')
    args=arguments(env,root,'transition',dict(edge_id=edge['edge_id'],evidence_digest=edge['evidence_digest'],on=today()),package_policy=allowed)
    saved=asyncio.run(service.record_process_operation(env['engine'],**args))
    assert saved['readiness']['ready']
    if invalidate=='quarantine':
        other=packages.setup(env,key='another-case-independent-file')
        upload(env,other)
    else:
        issued.write(env,child,'passport_change',dict(passport_fingerprint='c'*64,on='2026-09-05'))
    assert not issued.read(env,child)['selected']['summary']['verification_current']
    current=read(env,root,package_policy=allowed)
    assert not current['readiness']['ready']
    assert current['readiness']['retained']['exit_visa.exit_visa_issued']['value'] is False
    assert read(env,root,revision=saved['revision'],package_policy=allowed)['selected']['snapshot']==saved['snapshot']
    retry=asyncio.run(service.record_process_operation(env['engine'],**args))
    assert retry['id']==saved['id'] and not retry['readiness']['ready']
    issued.write(env,child,'travel',dict(direction='exit',on='2026-09-06',proof='7'*64,source='official_record',
        passport_fingerprint='c'*64 if invalidate=='passport' else 'b'*64))
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):
        transition(env,root,'U08',package_policy=allowed)


@pytest.mark.parametrize('change',['withdraw','false','expired','source_scope'])
def test_consumed_official_manual_evidence_keeps_dependent_stages_blocked(env,change,monkeypatch):
    from tests.test_entry_processes import policy
    subject=person(env,'subject');root=setup(env,procedure='violation_protocol',applicant=subject)
    profile=profiles.save(env,subject)
    attest(env,root,'profile_review_complete',role='protocol',profile_id=profile['qualification_id'])
    submit(env,root,approve=True)
    for fact in ('overstay_assessed','protocol_received','fine_payment_confirmed'): attest(env,root,fact,role='protocol')
    transition(env,root,'U02');saved=transition(env,root,'U03')
    chosen=policy()
    if change=='withdraw':
        write(env,root,'withdraw',dict(role='protocol',fact='protocol_received',on=today(),reference='SYNTHETIC-WITHDRAW',proof='4'*64))
    elif change=='false': attest(env,root,'protocol_received',False,role='protocol')
    elif change=='expired':
        from datetime import timedelta
        from tests.test_entry_processes import service
        attest(env,root,'protocol_received',role='protocol',valid_through=today())
        tomorrow=service._now()+timedelta(days=1)
        monkeypatch.setattr(service,'_now',lambda:tomorrow)
        monkeypatch.setattr(service.applications,'_today',lambda:service.applications._local_day(tomorrow))
    else:
        chosen=replace(chosen,manual_sources=tuple((f,('official_document',) if f=='protocol_received' else sources)
            for f,sources in chosen.manual_sources))
    current=read(env,root,policy=chosen)
    assert not current['readiness']['ready']
    assert not current['readiness']['retained']['protocol.protocol_received']['satisfied']
    assert read(env,root,revision=saved['revision'],policy=chosen)['selected']['snapshot']==saved['snapshot']
    edge=next(e for e in current['readiness']['transitions'] if e['edge']['to']=='U04')
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):
        write(env,root,'transition',dict(edge_id=edge['edge_id'],evidence_digest=edge['evidence_digest'],on=today()),policy=chosen)
    stopped=write(env,root,'stop',dict(on=today(),reference='SYNTHETIC-STOP',proof='4'*64),policy=None)
    assert stopped['snapshot']['stopped']
