"""Source continuations with separate real attempts and official decisions.

Manual external observations are synthetic. These cases do not confer legal
eligibility or infer card issue, registration or consent from a visa approval.
"""
import json
from pathlib import Path

import pytest

from app.domain.entry_storage import EntryStorageInvalid, _hash
from app.knowledge.process_preview import CATALOG_SHA256
from tests.test_work_process_v2 import base_env, env
from tests.test_entry_applications import person, application, record, read as app_history, enforce_sqlite_foreign_keys
from tests.test_entry_interviews import admins
from tests.test_entry_channel_stops import activation
from tests.test_entry_source_scenarios import portal_decision, handoff
from tests.test_entry_process_dependencies import regularization_at_u06, link
from tests.test_source_sop_products import operator_sop, explicit_package,open_case
from tests import test_applicant_profiles as profiles
from tests import test_entry_document_packages as packages
from tests import test_entry_processes as process


def evidence(name, **values):
    target=Path('runs/source-aftercare');target.mkdir(parents=True,exist_ok=True)
    (target/(name+'.json')).write_text(json.dumps(values,indent=2)+'\n','utf-8')


def finish_registration(env, app, profile, allowed, *, key):
    """Independent REG journal, even when its parent is a U/visa process."""
    process.write(env,app,'initialize',dict(catalog_digest=CATALOG_SHA256,on=process.today(),employer_reference=None),revision=0)
    process.attest(env,app,'profile_review_complete',role='registration',profile_id=profile['qualification_id'])
    for fact in ('stay_basis_checked','payment_code_received','registration_payment_confirmed',
                 'registration_certificate_received','completion_reviewed','followup_completed'):
        process.attest(env,app,fact,role='registration',reference='SYNTHETIC-'+key.upper())
    for stage in ('R02','R03'):process.transition(env,app,stage,package_policy=allowed)
    if app_history(env,app)['current']['status']=='draft':
        record(env,app,key+'-submit',reference='SR'+str(app['id']).zfill(6))
    for stage in ('R04','R05'):process.transition(env,app,stage,package_policy=allowed)
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):
        process.transition(env,app,'R06',package_policy=allowed)
    portal_decision(env,app,key=key+'-approval')
    for stage in ('R06','R07','R08'):end=process.transition(env,app,stage,package_policy=allowed)
    assert end['snapshot']['root_id']==app['id'] and end['snapshot']['active_application_id']==app['id']
    return end


def test_source_19_13_special_registration_handoff_continues_child_to_r08_without_l(env):
    root,child,allowed,handed=regularization_at_u06(env,'registration','registration','REG')
    subject=person(env,'subject');profile=profiles.read(env,subject)['saved']
    end=finish_registration(env,child,profile,allowed,key='SPECIAL-REG')
    parent=process.read(env,root,package_policy=allowed)
    assert parent['selected']['snapshot']['stage']=='U06'
    assert parent['selected']['snapshot']['branch']=='registration'
    assert parent['selected']['snapshot']['active_application_id']==child['id']
    assert all(not e['ready'] and e['reason']=='process_branch_mismatch' for e in parent['readiness']['transitions'])
    assert root['applicant_id']==child['applicant_id']==subject['id']
    assert app_history(env,child)['procedure']=='registration'
    assert parent['dependencies']['registration']['facts']['registration_certificate_received']['value'] is True
    assert process.read(env,root,revision=handed['revision'])['selected']['snapshot']==handed['snapshot']
    evidence('special-registration',section='19.13',parent_id=root['id'],child_id=child['id'],
        parent_stage='U06',child_stage=end['snapshot']['stage'],exit_visa_created=False,external_delivery='not_sent')


@pytest.mark.parametrize('name,basis', [('relative','RL'),('family','FF'),('student','S'),('equipment','SW1'),('journalist','SW2')])
def test_source_nonwork_visa_to_own_res_medical_and_separate_registration(env,name,basis):
    story=operator_sop(env,name);root=story['root'];subject=story['subject'];profile=story['profile']
    before=app_history(env,root)
    # A principal's (or any other person's) card cannot be linked as this one's.
    other=person(env,'principal-or-other',role='spouse')
    wrong=application(env,other,'other-resident',procedure='resident_card')
    with pytest.raises(EntryStorageInvalid,match='subject_mismatch|dependency_scope'):
        link(env,root,wrong,'resident')
    resident=application(env,subject,'own-resident',procedure='resident_card')
    link(env,root,resident,'resident')
    assert packages.read(env,resident)['selected'] is None
    allowed,accepted=explicit_package(env,resident,'RES',facts={'resident_basis':basis,'long_term':True,
        'matrix_d07_0_applies':True,'matrix_d17_0_applies':basis in ('RL','FF'),
        'matrix_d18_0_applies':basis in ('RL','FF')},critical='med01')
    rows={r['id']:r for r in packages.read(env,resident)['selected']['summary']['rows']}
    assert rows['med01']['applicable'] is True and rows['med02']['applicable'] is False
    assert app_history(env,resident)['current']['status']=='draft'
    # An explicitly recorded collection observation resolves to false until
    # this separate RES attempt has its own official approval.
    observation=process.attest(env,root,'resident_issued_and_collected',role='resident',
        reference='SYNTHETIC-RES-COLLECTION',proof=_hash([resident['id'],'card-collected']))
    fact=process.read(env,root,package_policy=allowed)['dependencies']['resident']['facts']['resident_issued_and_collected']
    assert fact['value'] is False
    record(env,resident,'res-submit',reference='RS'+str(resident['id']).zfill(6))
    portal_decision(env,resident,key='resident-'+name)
    collected=process.attest(env,root,'resident_issued_and_collected',role='resident',
        reference='SYNTHETIC-RES-COLLECTION',proof=_hash([resident['id'],'card-collected']))
    assert process.read(env,root,package_policy=allowed)['dependencies']['resident']['facts']['resident_issued_and_collected']['value'] is True
    reg=application(env,subject,'resident-reg',procedure='registration');link(env,root,reg,'registration')
    reg_policy,_=explicit_package(env,reg,'REG',facts={'host_is_owner':False,'matrix_d02_0_applies':True,'registration_student':basis=='S',
        'registration_worker':basis in ('SW1','SW2')},critical='t29_01',alternatives={'t32_01':'resident_card'})
    end=finish_registration(env,reg,profile,reg_policy,key='RES-'+name)
    assert len({root['id'],resident['id'],reg['id']})==3
    assert app_history(env,root)==before
    evidence(name,section={'RL':'19.5','FF':'19.6','S':'19.7','SW1':'19.8','SW2':'19.8'}[basis],
        case_id=root['case_id'],applicant_id=subject['id'],visa_id=root['id'],resident_id=resident['id'],
        registration_id=reg['id'],resident_approval_id=app_history(env,resident)['current']['id'],
        registration_stage=end['snapshot']['stage'],medical_package_revision=accepted['revision'],
        residence_basis=basis,selection='explicit_synthetic_specialist',automatic_parent_readiness=False,external_delivery='not_sent')


def test_source_19_10_eaeu_worker_registration_and_family_keep_own_packets_no_ep(env):
    # External tax/certificate conclusions are explicit operator observations,
    # never inferred from citizenship or the existence of a labour contract.
    worker=person(env,'EAEU-WORKER',role='employee')
    doc=profiles.request();doc['as_of']=process.today()
    doc['profile'].update(citizenship=['RUS'],entry_passport_country='RUS',purpose='work_hire',
        current_location='in_kg',in_kg_since='2026-09-01',current_basis_in_kg='visa_free')
    profile=profiles.save(env,worker,doc=doc);handoff(env,worker,purpose='work_hire')
    first=application(env,worker,'REG-TAX-PENDING',procedure='registration')
    allowed,_=explicit_package(env,first,'REG',facts={'in_kg':True,'visa_free':True,
        'registration_worker':True,'eaeu_worker':True,'tax_in_esuvm':False,'host_is_owner':False,
        'matrix_d02_0_applies':True,'matrix_d15_0_applies':True,'matrix_d16_0_applies':True},critical='t32_02')
    rows={r['id']:r for r in packages.read(env,first)['selected']['summary']['rows']}
    assert rows['t32_02']['applicable'] is True and rows['t32_01']['applicable'] is False
    assert rows['t29_01']['applicable'] is True
    initial=finish_registration(env,first,profile,allowed,key='EAEU-PENDING-TAX')
    old=app_history(env,first)
    # Later tax evidence initiates a new REG application, with its own packet,
    # submission and official decision; it does not stretch the first approval.
    renewed=application(env,worker,'REG-TAX-CONFIRMED',procedure='registration')
    assert app_history(env,renewed)['current']['status']=='draft'
    renewed_policy,_=explicit_package(env,renewed,'REG',facts={'in_kg':True,'visa_free':True,'extension':True,
        'registration_worker':True,'eaeu_worker':True,'tax_in_esuvm':True,'insurance_in_esuvm':False,
        'matrix_d02_0_applies':True,'matrix_d15_0_applies':True,'matrix_d16_0_applies':True},critical='t33_01')
    final=finish_registration(env,renewed,profile,renewed_policy,key='EAEU-CONFIRMED-TAX')
    assert app_history(env,first)==old
    spouse=person(env,'EAEU-SPOUSE',role='spouse')
    family_doc=profiles.request();family_doc['as_of']=process.today()
    family_doc['profile'].update(citizenship=['RUS'],entry_passport_country='RUS',purpose='family_of_foreigner',
        current_location='in_kg',in_kg_since='2026-09-01',current_basis_in_kg='visa_free')
    family_profile=profiles.save(env,spouse,doc=family_doc)
    family=application(env,spouse,'FAMILY-REG',procedure='registration')
    assert packages.read(env,family)['selected'] is None
    family_policy,_=explicit_package(env,family,'REG',facts={'in_kg':True,'visa_free':True,
        'eaeu_worker':True,'worker_family':True,'matrix_d02_0_applies':True,'matrix_d17_0_applies':True},critical='t32_03')
    family_end=finish_registration(env,family,family_profile,family_policy,key='EAEU-FAMILY')
    assert len({first['id'],renewed['id'],family['id']})==3 and spouse['id']!=worker['id']
    import asyncio
    from tests.test_admin_kg_entry import ADMIN
    from app.domain import entry_applications
    register=asyncio.run(entry_applications.read_application_register(env['engine'],actor=ADMIN,case_id=first['case_id']))
    assert {a['procedure'] for a in register['applications']}=={'registration'}
    evidence('eaeu-worker-family',section='19.10',worker_id=worker['id'],family_id=spouse['id'],
        pending_tax_registration_id=first['id'],confirmed_tax_registration_id=renewed['id'],family_registration_id=family['id'],
        stages=[initial['snapshot']['stage'],final['snapshot']['stage'],family_end['snapshot']['stage']],
        source_pending_term_days=60,source_confirmed_term='up_to_one_year',
        actual_period_adapter='not_implemented',tax_determination='explicit_synthetic_operator',
        ep_created=False,external_delivery='not_sent')


def test_source_19_11_in_country_new_b_same_clinic_own_decision_delivery_and_registration(env):
    """Manual specialist path: new B, never stretch the old approved attempt."""
    from tests import test_entry_interviews as interviews,test_entry_issued as issued
    story=operator_sop(env,'b_medical');old=story['root'];subject=story['subject'];iv=story['interview']
    old_history=app_history(env,old);doc=profiles.request();doc['as_of']=process.today();doc['format']='kg-qualification-review-input/2'
    doc['profile'].update(citizenship=['IND'],entry_passport_country='IND',purpose='medical',
        current_location='in_kg',in_kg_since='2026-10-01',current_basis_in_kg='visa',current_basis_until='2026-12-10',
        purpose_details='SYNTHETIC: same clinic, continuing the documented course of treatment; new B specialist review')
    profile=profiles.save(env,subject,doc=doc,revision=1,key='RENEWAL-CURRENT-BASIS')
    # A dependent answer is confirmed only after its basis has been saved.
    # Use the real interview sequencing rather than bypassing its stale-answer guard.
    batches=[{'location':'in_kg','purpose':'medical'}, {'current_basis':'visa'},
        {'current_visa_type':'B','current_until':'2026-12-10','current_inviter':'SYNTHETIC-SAME-CLINIC'},
        {'inviter.exists':True}, {'inviter.type':'clinic'},
        {'inviter.name':'SYNTHETIC-SAME-CLINIC','inviter.letter':True}]
    for changes in batches:
        interviews.correct(env,iv,changes,actor=interviews.OWNER)
        if interviews.read(env,iv)['state']['phase']=='pending':interviews.action(env,iv,'ack')
    answers=interviews.read(env,iv)['state']['answers']
    assert answers['current_inviter']['value']==answers['inviter.name']['value']
    assert answers['current_visa_type']['value']=='B'
    # A new processing request is distinct from a retry of a refused/closed
    # attempt. Existing approved attempts remain terminal and immutable.
    with pytest.raises(EntryStorageInvalid,match='previous_application_not_retryable'):
        application(env,subject,'ILLEGAL-EXTEND-OLD',previous=old['id'])
    renewal=process.setup(env,key='NEW-B-IN-KG',applicant=subject)
    assert app_history(env,renewal)['current']['status']=='draft'
    allowed,_=explicit_package(env,renewal,'B',facts={'in_kg':True,'extension':True,'medical_purpose':True},critical='t05_01')
    process.attest(env,renewal,'profile_review_complete',profile_id=profile['qualification_id'])
    process.attest(env,renewal,'conversation_started');process.transition(env,renewal,'V02')
    process.attest(env,renewal,'manager_review_required');process.transition(env,renewal,'V03')
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):process.transition(env,renewal,'V04',package_policy=allowed)
    process.attest(env,renewal,'eligibility','eligible',profile_id=profile['qualification_id'],
        reference='SYNTHETIC-SAME-HOST-NEW-B',proof=_hash(dict(previous_application=old['id'],profile=profile['snapshot_hash'],answers=answers)))
    process.attest(env,renewal,'visa_required',True,profile_id=profile['qualification_id'])
    for fact in ('quote_sent','offer_accepted','invoice_issued','checklist_sent','portal_draft_created','email_verified','portal_payment_confirmed'):
        process.attest(env,renewal,fact,reference='SYNTHETIC-NEW-B-CLINIC')
    for stage in ('V04','V06','V07','V08','V09','V10','V12','V14','V15'):process.transition(env,renewal,stage,package_policy=allowed)
    record(env,renewal,'new-b-submit',reference='NB'+str(renewal['id']).zfill(6))
    for stage in ('V16','V17'):process.transition(env,renewal,stage,package_policy=allowed)
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):process.transition(env,renewal,'V20',package_policy=allowed)
    portal_decision(env,renewal,key='NEW-B-OWN-APPROVAL');process.transition(env,renewal,'V20',package_policy=allowed)
    on=process.today();issued.write(env,renewal,'file',dict(fingerprint='a'*64,passport_fingerprint='b'*64,on=on))
    process.transition(env,renewal,'V21',package_policy=allowed);issued.review(env,renewal,on=on)
    for channel in ('messenger','email','crm'):
        issued.write(env,renewal,'delivery',dict(version=1,fingerprint='a'*64,on=on,channel=channel,proof='c'*64,pamphlet='d'*64))
    process.transition(env,renewal,'V22',package_policy=allowed)
    issued.write(env,renewal,'receipt',dict(version=1,fingerprint='a'*64,on=on,proof='e'*64,identity_checked=True))
    process.transition(env,renewal,'V23',package_policy=allowed)
    registration=application(env,subject,'NEW-B-REG',procedure='registration');link(env,renewal,registration,'registration')
    reg_policy,_=explicit_package(env,registration,'REG',facts={'in_kg':True,'extension':True,'host_is_owner':False,
        'matrix_d02_0_applies':True},critical='t29_01',alternatives={'t32_01':'visa'})
    end=finish_registration(env,registration,profile,reg_policy,key='NEW-B-REG')
    assert app_history(env,old)==old_history
    assert len({old['id'],renewal['id'],registration['id']})==3
    assert process.read(env,renewal)['selected']['snapshot']['stage']=='V23'
    evidence('in-country-new-b',section='19.11',previous_application=old['id'],new_application=renewal['id'],
        registration_id=registration['id'],registration_stage=end['snapshot']['stage'],host='same_clinic',
        basis_and_issuer='recorded_own_profile_and_interview',selection='explicit_synthetic_specialist',
        calculated_five_day_deadline='separate_capability_not_claimed',external_delivery='not_sent')


def test_source_19_9_preliminary_own_work_intake_partial_quote_contract_and_full_followup(env,monkeypatch):
    import asyncio
    from datetime import datetime,timezone
    from app.domain import precontract_cases
    from tests.test_admin_kg_entry import ADMIN
    from tests import test_work_process_v2 as work,test_entry_quotes as quotes
    opening=open_case(env,'WORK-FULL-SOURCE')
    prepared=work.setup(env);subject,root,profile=prepared
    iv,_=handoff(env,subject,purpose='work_hire')
    recipe=quotes.recipe(procedure='unified_permit');policy=quotes.policy(recipe)
    shown=quotes.preview(env,root,policy=policy)
    quote=quotes.save(env,root,policy=policy,previewed=shown)
    assert quote['receipt']['applicant_id']==subject['id'] and quote['receipt']['application_id']==root['id']
    assert quote['receipt']['result']['totals_by_currency'] is None and quote['receipt']['result']['payment']=='not_created'
    async def sign():
        async with env['sm']() as session:
            value=await precontract_cases.record_signed_contract(session,by=ADMIN,case_id=opening['case_id'],
                expected_revision=opening['revision'],request_key='WORK-SAME-CASE-CONTRACT',reference='SYNTHETIC-WORK-CONTRACT',
                signed_at=datetime.now(timezone.utc),amount='100000',currency='KGS')
            await session.commit();return value
    assert asyncio.run(sign())['case_id']==root['case_id']
    completed,entered,moved,allowed=work.complete_work_flow(env,monkeypatch,prepared=prepared)
    assert completed['id']==root['id'] and entered['snapshot']['root_id']==root['id']
    for fact in ('completion_reviewed','followup_completed'):work.attest(env,root,fact,role='resident_registration')
    end=work.transition(env,root,'W22',package_policy=allowed)
    assert quotes.read(env,root,policy=policy)['history'][0]['receipt']==quote['receipt']
    evidence('work-full-source',section='19.9',case_id=opening['case_id'],applicant_id=subject['id'],permit_id=root['id'],
        profile_id=profile['qualification_id'],interview_id=iv['interview_id'],quote_id=quote['receipt']['id'],
        stage=end['snapshot']['stage'],visa_free_presence='own_retained_open_stay',
        resident_registration_id=moved['snapshot']['active_application_id'],external_delivery='not_sent')
