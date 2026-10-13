"""Source-shaped fixtures are observations only; every approval here is synthetic."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from app.domain import specialist_facts as facts
from app.domain.entry_storage import _hash,EntryStorageInvalid
from app.domain.specialist_policy import SpecialistPolicy,FORMAT,ALGORITHM
from app.knowledge import interview_catalog,interview_rules,specialist_catalog
from app.knowledge.quote_rules import QuoteInvalid
from tests.test_entry_interviews import policy as interview_policy
from tests.test_approved_qualification import profile

ROOT=Path(__file__).resolve().parents[1]
ON='2026-10-12'


def source():
    bundle={k:json.loads((ROOT/'knowledge/kg_entry/draft-v1.1'/f'{k}.yaml').read_text('utf8')) for k in ('meta','countries','units')}
    conditions=json.loads((ROOT/'knowledge/kg_entry/conditions_v1_1/catalog.json').read_text('utf8'))
    ids={r['unit_id'] for r in specialist_catalog.capability(facts.CAPABILITY)['regime_applicability']}
    pins=[dict(unit_id=u['unit_id'],unit_hash=_hash(u)) for u in bundle['units'] if u['unit_id'] in ids]
    return bundle,conditions,pins


def policy_document():
    bundle,conditions,pins=source();ip=interview_policy()
    return dict(format=FORMAT,algorithm=ALGORITHM,reference='SYN-SPECIALIST',proof='a'*64,operators=['admin'],
        valid_from='2026-01-01',review_due_on='2026-12-31',source_hash=specialist_catalog.load()['source_sha256'],
        bundle_hash='b'*64,projection_hash='c'*64,condition_catalog_hash=_hash(conditions),
        specialist_catalog_hash=specialist_catalog.CATALOG_SHA256,interview_policy_hash=ip.digest,
        interview_catalog_hash=ip.catalog_hash,capabilities=[dict(id=facts.CAPABILITY,
        source_pin_hash=_hash(specialist_catalog.source_pin(facts.CAPABILITY)),review_reference='SYN-CLAUSE-INTERPRETATION',
        review_proof='d'*64,review_on='2026-01-01',quote_policy_hash='e'*64,
        recipes=[dict(id='SYN-B',hash='f'*64,minimum_days=1,maximum_days=30,urgent=False)],unit_pins=pins)])


def example(language='ru'):
    p=profile();p['language']=language
    p['profile'].update(citizenship=['IND'],entry_passport_country='IND',purpose='business_meeting',
        purpose_details='Synthetic non-employment business meeting',event_dates={'from':'2026-11-02','to':'2026-11-09'},
        inviting_party=dict(exists=True,type='company',can_issue_letter=True,has_portal_cabinet=False))
    values=dict(language=language,contact_name='Synthetic applicant',contact_phone='synthetic',contact_messenger='synthetic',
        contact_role='applicant',contact_email='synthetic@example.invalid',party_type='individual',applicants_count=1,
        citizenships=['IND'],document_type='ordinary',passport_expiry='2030-01-01',passport_two_blank_pages=True,
        passport_undamaged=True,residence_country='IND',location='abroad',current_country='IND',purpose='business_meeting',
        purpose_detail=p['profile']['purpose_details'],entry_on='2026-11-01',exit_on='2026-11-10',multiple_entries=False,
        planned_entry_point='manas',tickets_bought=False,accommodation_address='Synthetic hotel',previous_visits=False,
        previous_refusal=False,family_count=0,payer='self',payment_preference='cash',extra_services=[],referral='Synthetic')
    values.update({'consent.given':True,'consent.on':ON,'consent.evidence_ref':'SYN-CONSENT','consent.evidence_sha256':'a'*64,
        'terms.accepted':False,'foreign_residence.exists':False,'long_visa.exists':False,'hard_deadline.exists':False,
        'applicant.age':30,'risk.overstay':False,'risk.fines':False,'risk.deportation':False,'risk.entry_ban':False,
        'commercial.contract':False,'commercial.company_invoice':False,'commercial.closing_documents':False,
        'event.from':'2026-11-02','event.to':'2026-11-09','inviter.exists':True,'inviter.type':'company',
        'inviter.name':'Synthetic host','inviter.tax_id':'SYN-HOST','inviter.contact':'Synthetic representative',
        'inviter.phone':'Synthetic phone','inviter.email':'host@example.invalid','inviter.letter':False,
        'inviter.constituent_documents':False,'inviter.portal_account':False,'company.exists':False,'company.planned':False})
    ip=interview_policy();catalog=interview_catalog.document();answers={}
    for revision in range(1,101):
        analysis=interview_rules.analyze(answers,on=ON,language=language,pre_consent=ip.pre_consent,catalog_document=catalog)
        if not analysis['questions']:break
        changes={q['path']:values[q['path']] for q in analysis['questions']}
        answers=interview_rules.apply_answers(answers,changes,revision=revision,on=ON,pre_consent=ip.pre_consent,catalog_document=catalog)
    assert not analysis['gaps'] and not analysis['stops'],analysis
    card=dict(reasons=['manual_review_requested'],answers=deepcopy(answers))
    state=dict(answers=answers,language=language,phase='acked',collection_blocked=False,consent_withdrawal=None,
        handoff=dict(card=card,hash=_hash(card)),ack=dict(card_hash=_hash(card)))
    history=dict(status='recorded_inputs',passport_ref='a'*32,document=dict(intervals=[]))
    findings=dict(reviewed_on=ON,meeting_nonprofit=True,local_work=False,host_legal_entity_in_kg=True,
        host_identity_hash=_hash({k:v for k,v in values.items() if k in
            ('inviter.name','inviter.tax_id','inviter.contact','inviter.phone','inviter.email')}),
        purpose_detail_hash=_hash(p['profile']['purpose_details']),evidence=[dict(fact=k,reference='SYN-'+k.upper(),
            proof='a'*64,on=ON) for k in ('alternatives','host','nonemployment','purpose')])
    return dict(request=p,state=state,history=history,catalog=catalog,interview_policy=ip,findings=findings,on=ON)


def change_answers(example,changes):
    state=example['state']
    for key,value in changes.items():
        state['answers']=interview_rules.apply_answers(state['answers'],{key:value},revision=101,
            on=ON,pre_consent=example['interview_policy'].pre_consent,catalog_document=example['catalog'])


def test_catalog_exact_rebuild_and_default_empty_authority():
    from scripts.build_kg_specialist_catalog import build,encoded
    from app.config import settings
    assert encoded(build())==specialist_catalog.PATH.read_bytes().replace(b'\r\n',b'\n')
    assert settings.kg_specialist_policy=={}
    policy=SpecialistPolicy(policy_document())
    assert policy.document()['source_hash']==specialist_catalog.load()['source_sha256']
    assert specialist_catalog.load()['approval']=='unapproved_source_evidence'


@pytest.mark.parametrize('language',['ru','en'])
def test_india_business_ten_days_with_pending_documents_is_internal_only(language):
    result=facts.reconcile(**example(language))
    assert result['reasons']==[] and result['planned_days']==10
    assert {'document_package','invitation_letter','host_constituent_documents',
        'passport_six_calendar_months_after_visa_end'}<=set(result['pending'])
    assert result['source_eligibility']=='not_determined'
    assert not result['permission_to_work'] and not result['permission_to_stay']
    assert result['alternatives']['qualifying_long_visa']=='explicit_negative'


@pytest.mark.parametrize('path,value',[
    ('foreign_residence.exists',True),('foreign_residence.exists','unknown'),
    ('long_visa.exists',True),('long_visa.exists','unknown'),('company.planned',True),
    ('applicant.age',17),('risk.fines',True),('inviter.exists',False),('inviter.type','relative'),
    ('event.to','2026-11-11'),('purpose','work_hire'),('passport_undamaged',False),
    ('previous_visits',True),('current_country','KGZ'),('consent.given',False)])
def test_positive_cannot_ignore_applicable_or_conflicting_facts(path,value):
    data=example();change_answers(data,{path:value});assert facts.reconcile(**data)['reasons']


@pytest.mark.parametrize('field,value',[
    ('purpose','tourism'),('event_dates',{'from':'2026-11-02','to':'2026-11-11'}),
    ('entry_passport_country','USA'),('purpose_details','Changed activity'),('urgency_deadline','2026-11-05'),
    ('in_kg_since','2026-10-01'),('applicants_count',2),('family',[{}])])
def test_material_profile_fields_are_reconciled(field,value):
    data=example();data['request']['profile'][field]=value;assert facts.reconcile(**data)['reasons']


@pytest.mark.parametrize('condition',[
    {'residence_documents':{'complete':True,'items':[{'country':'HKG','kind':'resident_card','permanent':True}]}},
    {'residence_documents':{'complete':True,'items':[{'country':'BRN','kind':'residence_permit','permanent':False}]}},
    {'foreign_visas':{'complete':True,'items':[{'issuer':'USA','over_three_years_verified':True}]}},
    {'foreign_visas':{'complete':False,'items':[]}},
    {'requested_visa_type':'TS'},
])
def test_profile_alternative_evidence_cannot_be_hidden_by_negative_interview(condition):
    data=example();data['request']['condition_facts']={'schema_version':'kg-entry-condition-facts/1',**condition}
    assert facts.reconcile(**data)['reasons']


def test_nonqualifying_visa_is_not_falsely_rewritten_as_no_foreign_visas():
    data=example();data['request']['condition_facts']={'schema_version':'kg-entry-condition-facts/1',
        'foreign_visas':{'complete':True,'items':[{'issuer':'USA','over_three_years_verified':False}]}}
    assert not facts.reconcile(**data)['reasons']


def test_old_ack_is_retained_but_latest_material_answers_need_explicit_findings():
    data=example();old=deepcopy(data['state']['handoff']);change_answers(data,{'inviter.name':'Changed host'})
    assert facts.reconcile(**data)['reasons']==['specialist_findings_conflict']
    a=interview_rules.Answers(data['state']['answers'],catalog_document=data['catalog'])
    data['findings']['host_identity_hash']=_hash({k:a.get(k) for k in
        ('inviter.name','inviter.tax_id','inviter.contact','inviter.phone','inviter.email')})
    assert not facts.reconcile(**data)['reasons'] and data['state']['handoff']==old


def test_future_evidence_and_unsafe_handoff_cannot_be_confirmed():
    data=example();data['findings']['evidence'][0]['on']='2026-10-13'
    with pytest.raises(QuoteInvalid,match='future_evidence'):facts.reconcile(**data)
    data=example();data['state']['handoff']['card']['reasons']=['unsafe_request']
    data['state']['handoff']['hash']=_hash(data['state']['handoff']['card'])
    data['state']['ack']['card_hash']=data['state']['handoff']['hash']
    assert facts.reconcile(**data)['reasons']==['specialist_handoff_outside_scope']


def test_source_census_and_applicability_drift_fail_even_with_rehashed_policy_pins():
    bundle,conditions,pins=source();assert facts.source_scope(bundle,conditions,pins) is None
    bad=deepcopy(bundle);u=next(u for u in bad['units'] if u['unit_id']=='KG.VF.ANNEX1_30_60')
    u['value']['countries'].append('IND');newpins=[p|{'unit_hash':_hash(u)} if p['unit_id']==u['unit_id'] else p for p in pins]
    assert facts.source_scope(bad,conditions,newpins)=='specialist_country_partition_changed'
    bad=deepcopy(conditions);bad['rules'][0]['all'][1]['validity_years_gt']=4
    assert facts.source_scope(bundle,bad,pins)=='specialist_condition_changed'
    assert facts.source_scope(bundle,conditions,pins[:-1])=='specialist_regime_census_changed'
    bad=deepcopy(bundle);u=next(u for u in bad['units'] if u['unit_id']=='KG.VF.GCC')
    u['value']=dict(countries=['IND'],days=180,window_days=360,work_needs_unified_permit=False)
    newpins=[p|{'unit_hash':_hash(u)} if p['unit_id']==u['unit_id'] else p for p in pins]
    assert facts.source_scope(bad,conditions,newpins)=='specialist_condition_changed'


@pytest.mark.parametrize('mutation',['fee_only','missing_regime','unreviewed_clause','recipe_scope','unknown_capability'])
def test_separate_authority_requires_closed_reviewed_capability(mutation):
    doc=policy_document();cap=doc['capabilities'][0]
    if mutation=='fee_only':cap['unit_pins']=[dict(unit_id='KG.FEE.SERVICE.B',unit_hash='a'*64)]
    if mutation=='missing_regime':cap['unit_pins'].pop()
    if mutation=='unreviewed_clause':cap['source_pin_hash']='0'*64
    if mutation=='recipe_scope':cap['recipes'][0]['maximum_days']=365
    if mutation=='unknown_capability':cap['id']='EP'
    with pytest.raises(EntryStorageInvalid):SpecialistPolicy(doc)
