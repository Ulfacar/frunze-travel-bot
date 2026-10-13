"""Source-specific operator SOPs using real journals, not a legal classifier.

Original PDF §19.2-19.8/19.14, physical81-84. Each selected category is an
explicit synthetic specialist instruction; package approval alone never selects
it, signs a contract, pays, submits or approves a visa. Facts/required evidence
below are independently specified from the source, not first catalogue values.
"""
import asyncio
from datetime import datetime,timezone
import json
from pathlib import Path

import pytest

from app.domain import precontract_cases
from app.domain.entry_storage import _hash,EntryStorageInvalid
from app.domain.models import ServiceCase
from tests.test_work_process_v2 import base_env,env
from tests.test_admin_kg_entry import ADMIN
from tests.test_entry_applications import person,application,record,enforce_sqlite_foreign_keys,read as application_history
from tests.test_entry_interviews import admins
from tests.test_entry_channel_stops import activation
from tests.test_entry_source_scenarios import handoff,portal_decision
from tests import test_applicant_profiles as profiles
from tests import test_entry_processes as process
from tests import test_entry_document_packages as package

# All base facts are an explicit adult, abroad, short visit, personal electronic
# application; scenario deltas state the materially different circumstances.
BASE_FACTS=dict(paper_submission=False,minor=False,foreign_language_documents=False,
    foreign_public_documents=False,employer_invites=False,gambling=False,
    invitation_required=False,long_term=False,high_risk_country=False,simplified_ts=False,
    medical_purpose=False,international_representation=False,in_kg=False,
    refugee_entry_exit=False,tax_in_esuvm=False,extension=False,extradition=False,
    expulsion=False,host_is_owner=True,representative=False,registration_student=False,
    visa_free=False,registration_worker=False,eaeu_worker=False,worker_family=False,
    stateless=False,insurance_in_esuvm=False,employer_is_entity=True,
    foreign_entrepreneur=False,licensed_activity=False,resident_basis=None,sw2_category=None)
MATRIX_FALSE=('d02_0','d07_0','d08_0','d09_0','d10_0','d11_0','d13_0','d14_0','d15_0','d16_0','d17_0','d18_0','d19_0','d20_0','d21_0','d22_0','d23_0')
ALTERNATIVES=dict(g04_02='parent',g05_01='ru',g06_01='apostille',t01_03='personal',
    t03_01='residence_permit',t06_01='international',t08_03='ticket',t09_05='marriage',
    t09_06='salary',t10_01='residence',t15_02='employer',t17_04='volunteer',
    t21_03='ethnicity',t21_04='residence',t26_02='interior',t28_03='passport',
    t29_01='consent',t32_01='unified_permit',t32_02='employment',t33_01='oms',
    work13='patent',work17='apostille',g04_01_2='en')

CASES={
    'ts_personal':dict(section='19.2',page=81,product='TS',purpose='tourism',critical='t01_03',facts={},alternatives={}),
    'ts_agency':dict(section='19.2',page=81,product='TS',purpose='tourism',critical='t01_04',facts={'matrix_d08_0_applies':True,'invitation_required':True},alternatives={'t01_03':'tour_operator'}),
    'b_medical':dict(section='19.3',page=81,product='B',purpose='medical',critical='t05_01',facts={'medical_purpose':True},alternatives={}),
    'transit':dict(section='19.4',page=81,product='TR',purpose='transit',critical='t08_03',facts={},alternatives={'t08_03':'visa'}),
    'relative':dict(section='19.5',page=81,product='RL',purpose='relatives_kg_citizen',critical='t09_05',facts={'foreign_language_documents':True,'foreign_public_documents':True,'long_term':True,'matrix_d07_0_applies':True,'matrix_d09_0_applies':True,'matrix_d10_0_applies':True,'matrix_d11_0_applies':True,'matrix_d18_0_applies':True},alternatives={}),
    'family':dict(section='19.6',page=82,product='FF',purpose='family_of_foreigner',critical='t11_05',facts={'long_term':True,'employer_invites':True,'matrix_d07_0_applies':True,'matrix_d14_0_applies':True,'matrix_d18_0_applies':True},alternatives={}),
    'student':dict(section='19.7',page=82,product='S',purpose='study',critical='t13_04',facts={'long_term':True,'tax_in_esuvm':False,'matrix_d07_0_applies':True,'matrix_d09_0_applies':True},alternatives={}),
    'equipment':dict(section='19.8',page=82,product='SW1',purpose='equipment_installation',critical='t15_06',facts={'long_term':True},alternatives={}),
    'journalist':dict(section='19.8',page=82,product='SW2',purpose='journalism',critical='t16_02',facts={'sw2_category':'journalist','long_term':True},alternatives={}),
    'volunteer':dict(section='19.8',page=82,product='SW2',purpose='volunteer',critical='t17_04',facts={'sw2_category':'volunteer'},alternatives={}),
    'fund':dict(section='19.8',page=82,product='SW2',purpose='volunteer',critical='t17_05',facts={'sw2_category':'fund'},alternatives={'t17_04':'charity'}),
    'digital_nomad':dict(section='19.14',page=84,product='DN',purpose='it_remote',critical='t19_02',facts={},alternatives={}),
    'official':dict(section='19.14',page=84,product='J',purpose='official',critical='t20_02',facts={},alternatives={}),
    'ethnic':dict(section='19.14',page=84,product='M',purpose='private_visit',critical='t21_03',facts={},alternatives={}),
    'investor':dict(section='19.14',page=84,product='I',purpose='investor',critical='t22_02',facts={},alternatives={}),
    'religious_consultation':dict(section='19.14',page=84,product='R',purpose='religious',critical='t23_02',facts={},alternatives={}),
    'driver':dict(section='19.14',page=84,product='T',purpose='driver',critical='t24_05',facts={},alternatives={}),
    'gcc_companion':dict(section='19.14',page=84,product='A',purpose='accompanying_gcc',critical='t25_04',facts={},alternatives={}),
}

# Source table rows are an independent named oracle, not the runtime's required
# row list. Other general/matrix rows remain covered by the catalogue tests.
SOURCE_ROWS={
    'TS':{'t01_01','t01_02','t01_03','t01_04','t01_05'},
    'B':{'t04_01','t04_02','t04_03','t05_01'},'TR':{'t08_01','t08_02','t08_03'},
    'RL':{'t09_01','t09_02','t09_03','t09_04','t09_05','t09_06'},
    'FF':{'t11_01','t11_02','t11_03','t11_04','t11_05'},
    'S':{'t13_01','t13_02','t13_03','t13_04','t13_05'},
    'SW1':{'t15_01','t15_02','t15_03','t15_04','t15_05','t15_06'},
    'DN':{'t19_01','t19_02'},'J':{'t20_01','t20_02'},'M':{'t21_01','t21_02','t21_03'},
    'I':{'t22_01','t22_02'},'R':{'t23_01','t23_02'},
    'T':{'t24_01','t24_02','t24_03','t24_04','t24_05'},'A':{'t25_01','t25_02','t25_03','t25_04'}}
MANUAL_CONTEXT={
    'ts_personal':dict(initiator='applicant',abroad=True,days=10,entry_point='Manas',local_work=False,extension=False),
    'ts_agency':dict(initiator='tour_operator',abroad=True,days=10,entry_point='Manas',local_work=False,extension=False),
    'b_medical':dict(initiator='clinic',purpose='documented_treatment',event_limited=True),
    'transit':dict(initiator='applicant',abroad=True,days=3,leaves_transit_zone=True,onward_visa_reviewed=True,extension=False),
    'relative':dict(initiator='kg_citizen_relative',relative_citizenship='KGZ',relative_permanent_residence='KGZ',relationship='marriage'),
    'family':dict(initiator='foreign_principal',principal_basis='resident_card',own_family_relationship_reviewed=True,investor_fee_exemption='not_asserted'),
    'student':dict(initiator='university',university_portal_submission=True,accreditation_reviewed=True),
    'equipment':dict(initiator='equipment_employer',invoice_and_assignment_reviewed=True,migration_exemption_letter=True),
    'journalist':dict(initiator='journalist',accreditation_reviewed=True,migration_exemption_letter=True),
    'volunteer':dict(initiator='host_organization',contract='volunteer'),
    'fund':dict(initiator='host_organization',contract='charity',government_fund_status=True),
    'digital_nomad':dict(initiator='digitalization_authority',government_request=True),
    'official':dict(initiator='government',first_leader_letter=True),
    'ethnic':dict(initiator='applicant',ethnicity_archive_and_notarial_evidence=True),
    'investor':dict(initiator='investment_authority',contribution_som=20000000,threshold_branch='separately_reviewed_20m'),
    'religious_consultation':dict(initiator='religious_organization',government_permission=True,abroad=True,agency_role='consultation_only'),
    'driver':dict(initiator='transport_company',license_and_vehicle_and_driver_documents=True),
    'gcc_companion':dict(initiator='gcc_citizen',principal_citizenship='SAU',own_residence_country='SAU',own_employment_contract=True),
}


def assert_source_rows(env,app,story):
    rows={r['id']:r for r in package.read(env,app)['selected']['summary']['rows']}
    actual={k for k,v in rows.items() if v['applicable'] is True}
    if story['product']=='SW2':
        category=story['facts']['sw2_category']
        expected={'t16_01','t16_02','t16_03'} if category=='journalist' else {'t17_01','t17_02','t17_03','t17_04'}|({'t17_05'} if category=='fund' else set())
        assert actual&{'t16_01','t16_02','t16_03','t17_01','t17_02','t17_03','t17_04','t17_05'}==expected
    else:
        expected=SOURCE_ROWS[story['product']]
        assert expected<=actual,(story['product'],expected-actual)
        if story['product']=='J':assert 't20_03' not in actual
        if story['product']=='M':assert 't21_04' not in actual


def open_case(env,key):
    async def run():
        async with env['sm']() as session:
            old=await session.get(ServiceCase,env['cases']['visa'])
            opened=await precontract_cases.open_preliminary(session,by=ADMIN,request_key='SOP-'+key,
                contact_id=old.contact_id,product_id=old.product_id,workflow_version_id=old.workflow_version_id,owner_login=old.owner_login)
            await session.commit();return opened
    opened=asyncio.run(run());env['cases']['visa']=opened['case_id'];env['url']=f"/admin/case/{opened['case_id']}/kg-entry"
    return opened


def explicit_package(env,app,product,*,facts,critical,alternatives=None):
    package.setup(env,app=app,product=product)
    definition=package.read(env,app)['selected']['definition']
    specified=BASE_FACTS|{'matrix_'+k+'_applies':False for k in MATRIX_FALSE}|facts
    assert set(definition['facts'])<=set(specified),set(definition['facts'])-set(specified)
    package.write(env,app,'facts',dict(values={k:specified[k] for k in definition['facts']}))
    rows=[r for r in package.read(env,app)['selected']['summary']['rows'] if r['applicable'] and r['kind']!='recommended']
    assert critical in {r['id'] for r in rows},(product,critical)
    choices=ALTERNATIVES|(alternatives or {})
    for row in rows:package.receive(env,app,item=row['id'],fingerprint=_hash([app['id'],row['id']]))
    def check(row):
        alternative=choices[row['id']] if row['alternatives'] else None
        package.check(env,app,item=row['id'],fingerprint=_hash([app['id'],row['id']]),alternative=alternative)
    for row in rows:
        if row['id']!=critical:check(row)
    package.write(env,app,'consent',dict(status='granted',on='2026-09-03',reference='SYNTHETIC-OWN-CONSENT',proof='4'*64))
    allowed=package.policy(definition)
    with pytest.raises(EntryStorageInvalid,match='incomplete'):package.approve(env,app,allowed)
    check(next(r for r in rows if r['id']==critical))
    approved=package.approve(env,app,allowed)
    assert approved['approved_in_revision'] and approved['summary']['submission_allowed'] is False
    assert application_history(env,app)['current']['status']=='draft'
    return allowed,approved


def operator_sop(env,name):
    story=CASES[name];opening=open_case(env,name);subject=person(env,name)
    doc=profiles.request();doc['as_of']=process.today();doc['format']='kg-qualification-review-input/2'
    doc['profile'].update(citizenship=['IND'],entry_passport_country='IND',purpose=story['purpose'],
        current_location='abroad',entry_date='2026-12-01',exit_date='2026-12-03' if name=='transit' else '2026-12-10',
        purpose_details='SYNTHETIC MANUAL SOURCE REVIEW: '+json.dumps(MANUAL_CONTEXT[name],sort_keys=True))
    saved=profiles.save(env,subject,doc=doc)
    iv,_=handoff(env,subject,purpose=story['purpose'],language='en' if name in ('transit','official','student') else 'ru')
    root=process.setup(env,applicant=subject)
    process.attest(env,root,'profile_review_complete',profile_id=saved['qualification_id'])
    process.attest(env,root,'conversation_started');process.transition(env,root,'V02')
    process.attest(env,root,'manager_review_required');process.transition(env,root,'V03')
    allowed,approved=explicit_package(env,root,story['product'],facts=story['facts'],critical=story['critical'],alternatives=story['alternatives'])
    assert_source_rows(env,root,story)
    assert saved['result']['selected_regime'] is None and not saved['result']['may_quote']
    if story['product']=='R':
        # Source agency boundary: consultation and retained evidence, no agency
        # submission or automatic eligibility despite complete document packet.
        assert process.read(env,root)['selected']['snapshot']['stage']=='V03'
        assert application_history(env,root)['current']['status']=='draft'
        with pytest.raises(EntryStorageInvalid,match='prerequisites'):process.transition(env,root,'V04',package_policy=allowed)
        target=Path('runs/source-sops');target.mkdir(parents=True,exist_ok=True)
        (target/(name+'.json')).write_text(json.dumps(dict(source_section=story['section'],scenario=name,
            case_id=root['case_id'],applicant_id=subject['id'],application_id=root['id'],stage='V03',
            scope='manual_consultation_only_no_product_specific_prohibition_claim',delivery='not_sent'),indent=2)+'\n','utf-8')
        return dict(root=root,subject=subject,profile=saved,policy=allowed,stage='V03',interview=iv)
    process.attest(env,root,'eligibility','eligible',profile_id=saved['qualification_id'],reference='SYNTHETIC-SPECIALIST-'+story['product'],
        proof=_hash(dict(manual_context=MANUAL_CONTEXT[name],profile_hash=saved['snapshot_hash'])))
    process.attest(env,root,'visa_required',True,profile_id=saved['qualification_id'])
    for fact in ('quote_sent','offer_accepted','invoice_issued','checklist_sent','portal_draft_created','email_verified','portal_payment_confirmed'):
        process.attest(env,root,fact,reference='SYNTHETIC-'+MANUAL_CONTEXT[name]['initiator'].upper(),proof=_hash(MANUAL_CONTEXT[name]))
    for stage in ('V04','V06','V07','V08'):process.transition(env,root,stage,package_policy=allowed)
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):process.transition(env,root,'V09',package_policy=allowed)
    async def sign():
        async with env['sm']() as session:
            result=await precontract_cases.record_signed_contract(session,by=ADMIN,case_id=opening['case_id'],expected_revision=opening['revision'],
                request_key='SOP-SIGN',reference='SYNTHETIC-CONTRACT',signed_at=datetime.now(timezone.utc),amount='100000',currency='KGS')
            await session.commit();return result
    assert asyncio.run(sign())['case_id']==root['case_id']
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):process.transition(env,root,'V09',package_policy=allowed)
    process.money(env,amount='100000',currency='KGS',idempotency_key='SOP-PAYMENT')
    for stage in ('V09','V10','V12','V14','V15'):process.transition(env,root,stage,package_policy=allowed)
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):process.transition(env,root,'V16',package_policy=allowed)
    reference='SC'+str(root['id']).zfill(6)
    record(env,root,'submit',reference=reference)
    for stage in ('V16','V17'):process.transition(env,root,stage,package_policy=allowed)
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):process.transition(env,root,'V20',package_policy=allowed)
    decision=portal_decision(env,root,key='decision-'+name)
    end=process.transition(env,root,'V20',package_policy=allowed)
    assert end['snapshot']['root_id']==root['id'] and root['applicant_id']==subject['id']
    target=Path('runs/source-sops');target.mkdir(parents=True,exist_ok=True)
    (target/(name+'.json')).write_text(json.dumps(dict(source_section=story['section'],source_page=story['page'],
        scenario=name,case_id=root['case_id'],applicant_id=subject['id'],application_id=root['id'],
        profile_id=saved['qualification_id'],interview_id=iv['interview_id'],package_revision=approved['revision'],
        process_revision=end['revision'],stage='V20',category_selection='explicit_synthetic_operator_review',
        manual_context=MANUAL_CONTEXT[name],automatic_legal_qualification=False,delivery='not_sent'),indent=2)+'\n','utf-8')
    return dict(root=root,subject=subject,profile=saved,policy=allowed,stage='V20',interview=iv)


@pytest.mark.parametrize('name',CASES)
def test_operator_source_category_own_intake_conditional_documents_and_separate_decision(env,name):
    operator_sop(env,name)
