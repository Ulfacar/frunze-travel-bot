"""Source coverage and meaningful synthetic transition/negative scenarios."""
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import re

import pytest

from app.knowledge.process_preview import ProcessCatalog, ProcessPreviewError, evaluate_transition, load_process_catalog
from scripts.build_kg_process_catalog import build


@pytest.fixture
def catalog(): return load_process_catalog()


def check(catalog,current,target,facts,process='visa',**changes):
    args=dict(process=process,current=current,target=target,facts=facts,expected_digest=catalog.digest)
    args.update(changes)
    result=evaluate_transition(catalog,**args)
    assert result['execution_allowed'] is False and result['publication_approved'] is False
    assert result['current_stage_unchanged']==current and result['facts_hypothetical'] is True
    return result


def test_reproducible_catalog_and_all_source_codes(catalog):
    data=catalog.document()
    assert data==build()
    source=Path('docs/kb-visa-inbound-v1.1-derived.md').read_text('utf-8')
    section=source[source.index('## 14.2.'):source.index('## 14.7.')]
    codes=set(re.findall(r'\b(?:V\d{2}|X\d{2}|W\d{2}|WX\d|R\d{2}|RX\d|U\d{2}|UX\d)\b',section))
    assert codes=={row['code'] for row in data['stages']} and len(codes)==87
    assert {row['code'] for row in data['stages'] if row['kind']=='flag'}=={'V11','X10','X12'}
    assert data['source_sha256']=='141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'


def test_stale_document_acceptance_cannot_pass_submission(catalog):
    facts=dict(consent_confirmed=True,documents_accepted=True,documents_current=False,portal_draft_created=True)
    result=check(catalog,'V14','V15',facts)
    assert result['status']=='conditions_not_met'
    assert [(r['fact'],r['state']) for r in result['alternatives'][0]['checks'] if r['state']!='met']==[('documents_current','not_met')]
    facts['documents_current']=True
    assert check(catalog,'V14','V15',facts)['status']=='draft_conditions_met'
    facts['consent_confirmed']=None
    assert check(catalog,'V14','V15',facts)['status']=='missing_facts'


def test_portal_submission_needs_each_material_confirmation(catalog):
    facts=dict(consent_confirmed=True,documents_accepted=True,documents_current=True,email_verified=True,
               portal_payment_confirmed=True,submission_recorded=True,application_reference_recorded=True)
    assert check(catalog,'V15','V16',facts)['status']=='draft_conditions_met'
    for key in ('consent_confirmed','documents_accepted','portal_payment_confirmed','email_verified','submission_recorded','application_reference_recorded'):
        result=check(catalog,'V15','V16',{**facts,key:False})
        assert result['status']=='conditions_not_met'


def test_unknown_eligibility_does_not_mean_impossible_product(catalog):
    for facts in ({},{'eligibility':'needs_review'}):
        assert check(catalog,'V03','X08',facts)['status']!='draft_conditions_met'
    assert check(catalog,'V03','X08',{'eligibility':'ineligible'})['status']=='draft_conditions_met'
    assert check(catalog,'V03','V04',{'eligibility':'ineligible','profile_complete':True,'product_defined':True})['status']=='conditions_not_met'


def test_manager_stop_factor_cannot_take_bot_shortcut(catalog):
    facts={'profile_complete':True,'product_defined':True,'eligibility':'eligible','manager_review_required':True}
    assert check(catalog,'V02','V04',facts)['status']=='conditions_not_met'
    assert check(catalog,'V02','V03',facts)['status']=='draft_conditions_met'


def test_revision_is_same_attempt_and_refusal_has_no_back_transition(catalog):
    facts=dict(corrections_completed=True,documents_accepted=True,documents_current=True,submission_recorded=True)
    result=check(catalog,'V18','V19',facts)
    assert result['status']=='draft_conditions_met'
    assert result['alternatives'][0]['proposed_effect']=='same_attempt_resubmission'
    refused=check(catalog,'X01','V17',facts)
    assert refused['status']=='not_in_draft' and 'новой связанной' in refused['notice']


def test_approval_does_not_imply_delivery_or_actual_entry(catalog):
    assert check(catalog,'V17','V20',{'decision':'approved'})['status']=='draft_conditions_met'
    assert check(catalog,'V21','V22',{'decision':'approved'})['status']=='missing_facts'
    assert check(catalog,'V21','V22',{'issued_document_checked':True,'delivered_to_client':True})['status']=='draft_conditions_met'
    assert check(catalog,'V23','V24',{})['status']=='missing_facts'
    assert check(catalog,'V23','V24',{'actual_entry_confirmed':False})['status']=='conditions_not_met'


def test_resident_card_is_separate_application_not_a_mutated_permit(catalog):
    result=check(catalog,'W15','W16',{'permit_issued':True,'resident_package_received':True},process='work')
    assert result['status']=='draft_conditions_met'
    assert result['alternatives'][0]['proposed_effect']=='separate_resident_application'
    assert result['alternatives'][0]['basis']=='draft_proposal'


def test_registration_path_cannot_produce_an_exit_visa(catalog):
    facts=dict(regularization_route='registration',stay_basis_checked=True,receiving_party_docs_accepted=True,documents_current=True,submission_recorded=True)
    result=check(catalog,'U05','U06',facts,process='regularization')
    ready=[r for r in result['alternatives'] if r['status']=='draft_conditions_met']
    assert len(ready)==1 and ready[0]['proposed_effect']=='separate_registration_application'
    assert check(catalog,'U06','U07',{**facts,'decision':'approved','exit_visa_issued':True},process='regularization')['status']=='conditions_not_met'
    assert check(catalog,'U06','U07',{'regularization_route':'exit_visa','decision':'approved','exit_visa_issued':True},process='regularization')['status']=='draft_conditions_met'


@pytest.mark.parametrize('a,b', [('V01','V25'),('V11','V12'),('X10','V24'),('V25','V01')])
def test_stage_jumps_flags_and_terminal_restart_not_in_draft(catalog,a,b):
    assert check(catalog,a,b,{})['status']=='not_in_draft'


@pytest.mark.parametrize('facts',[{'consent_confirmed':'true'},{'consent_confirmed':1},{'decision':True},{'decision':'anything'},
                                {'execute':True},{'publication_approved':True},{'passport_number':'synthetic'},[],None])
def test_invalid_or_unauthorized_fact_types(catalog,facts):
    with pytest.raises(ProcessPreviewError,match='invalid_process_facts'): check(catalog,'V14','V15',facts)


def test_bad_process_cross_flow_and_stale_version(catalog):
    with pytest.raises(ProcessPreviewError,match='invalid_process_stage'): check(catalog,'V14','W11',{})
    with pytest.raises(ProcessPreviewError,match='invalid_process'): check(catalog,'V14','V15',{},process='unknown')
    with pytest.raises(ProcessPreviewError,match='stale_process_catalog'): check(catalog,'V14','V15',{},expected_digest='0'*64)


def test_detached_catalog_and_deterministic_scenario_hash(catalog):
    data=catalog.document();data['publication_approved']=True;data['edges'].clear()
    with pytest.raises(FrozenInstanceError): catalog._raw=b'{}'
    one=check(catalog,'V14','V15',{'consent_confirmed':True,'documents_current':False})
    two=check(catalog,'V14','V15',{'documents_current':False,'consent_confirmed':True})
    assert one==two and one['publication_approved'] is False
    assert check(catalog,'V14','V15',{'consent_confirmed':True})['input_sha256']!=one['input_sha256']


def test_corrupt_or_republished_catalog_and_windows_checkout(catalog,tmp_path):
    crlf=ProcessCatalog(catalog._raw.replace(b'\n',b'\r\n'))
    assert crlf.digest==catalog.digest
    path=tmp_path/'catalog.json'
    data=catalog.document();data['publication_approved']=True
    path.write_text(json.dumps(data),'utf-8')
    with pytest.raises(ProcessPreviewError,match='integrity'):load_process_catalog(path)
    path.write_bytes(b'x'*524289)
    with pytest.raises(ProcessPreviewError,match='integrity'):load_process_catalog(path)
    with pytest.raises(ProcessPreviewError,match='unavailable'):load_process_catalog(tmp_path/'absent.json')
