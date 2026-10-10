from copy import deepcopy
import pytest
from app.knowledge import interview_catalog as catalog,interview_rules as rules

ON='2026-10-11'
PRE=tuple(f['path'] for f in catalog.FIELDS)


def put(values,**changes):
    revision=max((r['revision'] for r in values.values()),default=0)+1
    return rules.apply_answers(values,changes,revision=revision,on=ON,pre_consent=PRE)


def changed(values,path,value):return put(values,**{path:value})


def result(values,language='ru'):return rules.analyze(values,on=ON,language=language,pre_consent=PRE)


def test_all_57_source_codes_have_atomic_types_and_two_languages():
    expected={c+str(i) for c,n in zip('ABCDEFGH',(6,8,11,5,6,10,7,4)) for i in range(1,n+1)}
    assert {f['code'] for f in catalog.FIELDS}==expected
    assert len({f['path'] for f in catalog.FIELDS})==len(catalog.FIELDS)
    assert all(f['ru'] and f['en'] and f['when'] in rules.CONDITION_INPUTS for f in catalog.FIELDS)
    for count in (0,1,20):
        a=rules.Answers(changed({},'family_count',count))
        for field in a.fields.values():a.context(field['path']);a.applicability(field)


def test_unknown_is_retained_as_gap_without_repeating_and_false_zero_empty_are_real_answers():
    values=put({},**{'citizenships':'unknown','family_count':0,'extra_services':[]})
    values=changed(values,'risk.fines',False);r=result(values)
    assert any(g['path']=='citizenships' and g['reason']=='unknown' for g in r['gaps'])
    assert 'citizenships' not in {q['path'] for q in r['questions']}
    assert all(r['field_states'][p]=='answered' for p in ('family_count','extra_services','risk.fines'))
    assert r['legal_qualification']==r['quote']=='unknown' and r['confidence'] is None


@pytest.mark.parametrize('path,value',[('citizenships',[]),('family_count',True),('family_count',21),('risk.fines',0),
    ('passport_expiry','2026-02-30'),('passport_expiry','20261011'),('contact_name','\u202eabc'),
    ('citizenships',['XXX']),('contact_name','x'*121),('employment.salary_kgs',1.2)])
def test_bad_types_and_unbounded_values_rejected(path,value):
    f=next(v for v in catalog.FIELDS if v['path']==path)
    with pytest.raises(rules.InterviewInvalid):rules.validate_value(f,value)


def test_not_applicable_requires_a_proven_false_condition():
    with pytest.raises(rules.InterviewInvalid,match='unproven'):changed({},'passport_country','not_applicable')
    values=changed({},'citizenships',['KGZ'])
    values=changed(values,'passport_country','not_applicable')
    assert result(values)['field_states']['passport_country']=='not_applicable'
    values=changed(values,'citizenships',['KGZ','KAZ'])
    assert result(values)['field_states']['passport_country']=='stale'


def test_prerequisite_change_retains_history_but_cannot_resurrect_old_answer_by_changing_back():
    values=changed({},'location','in_kg');values=changed(values,'current_basis','visa');values=changed(values,'current_visa_type','B')
    old=deepcopy(values);values=changed(values,'location','abroad')
    assert values['current_visa_type']==old['current_visa_type'] and rules.Answers(values).get('current_visa_type') is None
    values=changed(values,'location','in_kg')
    assert 'current_basis' in result(values)['stale']
    values=changed(values,'current_basis','visa')
    assert rules.Answers(values).get('current_visa_type') is None


def test_conflicting_typed_dates_are_saved_and_escalated_instead_of_lost():
    values=put({},entry_on='2026-11-10',exit_on='2026-11-01')
    r=result(values)
    assert values['exit_on']['value']=='2026-11-01'
    assert r['questions']==[] and 'conflicting_answers' in r['stops'] and r['conflicts']


def test_identical_fresh_parent_preserves_children_but_stale_reconfirmation_changes_lineage():
    values=changed({},'location','in_kg');values=changed(values,'current_basis','visa')
    values=changed(values,'current_visa_type','B');original=deepcopy(values)
    values=changed(values,'current_basis','visa')
    assert values==original and rules.Answers(values).get('current_visa_type')=='B'
    values=changed(values,'location','abroad');values=changed(values,'location','in_kg')
    assert not rules.Answers(values).fresh('current_basis')
    values=changed(values,'current_basis','visa')
    assert rules.Answers(values).fresh('current_basis') and values['current_basis']!=original['current_basis']
    assert rules.Answers(values).get('current_visa_type') is None
    values=changed(values,'current_visa_type','B')
    assert rules.Answers(values).get('current_visa_type')=='B'


@pytest.mark.parametrize('path,value,stop',[('document_type','diplomatic','special_document'),
    ('purpose','work_hire','work_specialist'),('party_type','company','group_or_company'),
    ('applicants_count',6,'group_or_company'),('risk.fines',True,'reported_risk.fines'),
    ('consent.given',False,'consent_not_granted'),('previous_refusal',True,'reported_previous_refusal')])
def test_stop_facts_take_precedence_over_questions(path,value,stop):
    r=result(changed({},path,value));assert stop in r['stops'] and r['questions']==[]


def test_complete_consent_requires_own_evidence_and_terms_do_not_substitute():
    values=changed({},'terms.accepted',True)
    assert not result(values)['consent_complete']
    values=changed(values,'consent.given',True)
    assert not result(values)['consent_complete']
    values=put(values,**{'consent.on':ON,'consent.evidence_ref':'SYN-CONSENT','consent.evidence_sha256':'a'*64})
    assert result(values)['consent_complete']
    assert values['terms.accepted']['value'] is True


def test_pre_consent_policy_blocks_unapproved_personal_fields():
    with pytest.raises(rules.InterviewInvalid,match='consent_required'):
        rules.apply_answers({}, {'contact_name':'Synthetic'},revision=1,on=ON,pre_consent=('consent.given',))
    r=rules.analyze({},on=ON,language='en',pre_consent=('consent.given',))
    assert [q['path'] for q in r['questions']]==['consent.given']


def test_family_slot_identity_and_child_specific_branches_survive_growth():
    values=put({},family_count=1,applicants_count=3,purpose='family_of_foreigner')
    values=changed(values,'family.1.relation','child');values=changed(values,'family.1.age',0)
    assert result(values)['field_states']['family.1.both_parents']=='missing'
    values=changed(values,'family.1.both_parents',False)
    assert 'minor_without_both_parents' in result(values)['stops']
    old=deepcopy(values);values=changed(values,'family_count',2)
    assert values['family.1.age']==old['family.1.age']
    assert rules.Answers(values).get('family.1.age') is None
    assert rules.Answers(values).get('family.2.age') is None
    values=changed(values,'family_count',0)
    assert values['family.1.age']==old['family.1.age']
    assert result(values)['field_states']['family.1.age']=='not_applicable'


def test_ru_en_bounded_batches_never_request_parent_and_dependent_together():
    values={}
    for i in range(150):
        r=result(values,'ru' if i%2 else 'en')
        assert len(r['questions'])<=3
        if not r['questions']:break
        changes={q['path']:'unknown' for q in r['questions']}
        values=rules.apply_answers(values,changes,revision=i+1,on=ON,pre_consent=PRE)
    else:pytest.fail('unknown answers looped')
    assert r['gaps'] and not r['questions']


def test_required_work_and_commercial_subfields_are_editable_without_legal_math():
    values=put({},purpose='work_hire')
    values=changed(values,'inviter.exists','unknown')
    # Dependent facts in one batch require an explicit separate step.
    values=changed(values,'inviter.exists',True)
    values=put(values,**{'inviter.tax_debt_absent':True,'inviter.social_debt_absent':False,'employment.salary_kgs':'0.00'})
    r=result(values)
    assert r['field_states']['inviter.social_debt_absent']=='answered'
    assert rules.Answers(values).get('employment.salary_kgs')=='0.00'
    assert r['legal_qualification']=='unknown' and r['questions']==[]


def test_solo_family_applicant_has_own_relationship_and_minor_questions():
    values=put({},purpose='family_of_foreigner',family_count=0,**{'applicant.age':16})
    values=changed(values,'applicant.family_relation','child')
    values=changed(values,'relationship_document.exists',True)
    values=put(values,**{'relationship_document.country':'KGZ','relationship_document.apostille':False,'relationship_document.translation':True})
    r=result(values)
    assert r['field_states']['relationship_document.country']=='answered'
    assert r['field_states']['applicant.both_parents']=='missing' and r['field_states']['principal.status']=='missing'
    values=changed(values,'applicant.both_parents',False)
    assert 'minor_applicant_without_both_parents' in result(values)['stops'] and not result(values)['questions']


GOLDENS={
    'tourism':{'purpose':'tourism','citizenships':['CHN'],'long_visa.exists':True,'long_visa.country':'USA',
        'long_visa.from':'2025-01-01','long_visa.until':'2030-01-01','previous_visits':True,'history_count':1,
        'history.1.entry':'2026-05-01','history.1.exit':'2026-05-10','previous_visa_count':1,
        'previous_visa.1.from':'2026-01-01','previous_visa.1.until':'2026-01-20','reported_window':'60','reported_days':0},
    'current_stay':{'purpose':'study','location':'in_kg','actual_entry.on':'2026-10-01','current_basis':'visa',
        'registration.exists':True,'registration.until':'2026-12-01','current_until':'2026-12-01',
        'inviter.exists':True,'inviter.type':'university','inviter.social_debt_absent':True},
    'family':{'purpose':'family_of_foreigner','applicants_count':3,'family_count':2,'applicant.family_relation':'spouse',
        'relationship_document.exists':True,'principal.status':'ep','family.1.relation':'spouse','family.2.relation':'child',
        'family.2.age':8,'family.1.relationship_document':True,'family.2.relationship_document':True,
        'family.2.both_parents':True,'family.2.born_in_kg':True,'family.2.birth_on':'2018-01-01',
        'family.1.together':True,'family.2.together':True,'inviter.exists':True,'inviter.type':'relative'},
    'employer':{'purpose':'work_hire','location':'in_kg','actual_entry.on':'2026-10-01','current_basis':'ep',
        'current_until':'2026-12-01','inviter.exists':True,'inviter.type':'company','employment.garment':True,
        'employment.salary_kgs':'0.00','inviter.tax_debt_absent':True,'inviter.social_debt_absent':False,
        'permit.exists':True,'permit.until':'2026-12-01','employment.contract_from':'2026-10-01',
        'employment.contract_until':'2027-10-01'},
    'company_investor':{'purpose':'investor','party_type':'company','applicants_count':6,'inviter.exists':True,
        'company.exists':False,'company.planned':True,'company.form':'company','investment.amount_kgs':'10000000.00',
        'investment.authority_letter':True,'payer':'company','commercial.company_invoice':True,'commercial.closing_documents':True},
}


def golden_value(field,overrides):
    path=field['path'];kind=field['kind']
    values={'consent.given':True,'consent.on':ON,'location':'abroad','purpose':'tourism','document_type':'ordinary',
        'applicants_count':1,'applicant.age':35,'entry_on':'2026-12-01','exit_on':'2026-12-15','passport_expiry':'2030-01-01'}|overrides
    if path in values:return values[path]
    if kind=='boolean':return False
    if kind=='integer':return 0
    if kind=='countries':return ['KAZ']
    if kind=='country':return 'KAZ'
    if kind=='choices':return []
    if kind=='choice':return field['choices'][0]
    if kind=='date':return '2026-12-01'
    if kind=='decimal':return '0.00'
    if kind=='proof':return 'a'*64
    if kind=='opaque':return 'SYN-EVIDENCE'
    return 'Synthetic value'


@pytest.mark.parametrize('scenario',list(GOLDENS))
@pytest.mark.parametrize('language',['ru','en'])
def test_connected_golden_typed_intakes_cover_details_and_keep_legal_result_unknown(scenario,language):
    values={};seen=set()
    for revision in range(1,150):
        analyzed=result(values,language);questions=analyzed['manual_questions']
        if not questions:break
        assert len(questions)<=3
        fields=rules.Answers(values).fields
        changes={q['path']:golden_value(fields[q['path']],GOLDENS[scenario]) for q in questions}
        seen.update(changes)
        values=rules.apply_answers(values,changes,revision=revision,on=ON,pre_consent=PRE)
    else:pytest.fail('golden intake did not converge')
    analyzed=result(values,language)
    assert not analyzed['conflicts'] and not analyzed['gaps'],analyzed['gaps']
    assert analyzed['legal_qualification']==analyzed['quote']=='unknown' and analyzed['confidence'] is None
    expected={
        'tourism':{'long_visa.until','history.1.passport_country','previous_visa.1.type','reported_days','organized_group.exists'},
        'current_stay':{'current_visa_type','current_inviter','registration.address','inviter.social_debt_absent','declared_purpose'},
        'family':{'relationship_document.country','family.2.apostille','family.2.passport_received','principal.until'},
        'employer':{'inviter.tax_debt_absent','inviter.social_debt_absent','employment.salary_kgs','employment.workplace',
                    'employment.chamber_member','employment.quota','permit.number','permit.until'},
        'company_investor':{'company.form','investment.amount_kgs','investment.authority_letter','commercial.closing_documents'},
    }[scenario]
    assert expected<=seen
    assert {'payer','payment_preference','extra_services','referral'}<=seen
    if scenario in ('employer','company_investor'):assert analyzed['stops'] and not analyzed['questions']


def test_past_visa_date_conflict_is_a_retained_gap_for_specialist():
    values=changed({},'previous_visits',True);values=changed(values,'previous_visa_count',1)
    values=put(values,**{'previous_visa.1.from':'2025-02-01','previous_visa.1.until':'2025-01-01'})
    assert 'previous_visa.1.date_conflict' in result(values)['conflicts']
