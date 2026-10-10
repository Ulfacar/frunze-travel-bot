from pathlib import Path
import re

import pytest

from app.knowledge.complete_document_checklist import (CompleteDocumentCatalog, assess_complete_checklist,
    complete_definition, load_complete_document_catalog)
from app.knowledge.document_checklist import DocumentChecklistError, load_document_catalog
from scripts.build_kg_complete_document_catalog import build, digest


@pytest.fixture
def catalog(): return load_complete_document_catalog()


def assess(catalog, product, facts=None, states=None, **changes):
    args=dict(product=product, facts=facts or {}, states=states or {},current_version=True,expected_digest=catalog.digest)
    result=assess_complete_checklist(catalog,**{**args,**changes})
    assert not result['source_approved'] and not result['package_accepted'] and not result['submission_allowed']
    return result


def row(result, identifier): return next(r for r in result['rows'] if r['id']==identifier)


def test_full_source_reproducibility_and_fragment_provenance(catalog):
    document=catalog.document(); assert document==build()
    source=load_document_catalog().document()
    assert document['source_sha256']==source['source_sha256']
    for clause in document['clauses']:
        assert clause['source_fragment'] in clause['source_paragraph']
        assert clause['paragraph_sha256']==digest(clause['source_paragraph'])
        assert clause['source_section_sha256']==source['sections'][clause['section']]['sha256']
        normalized=re.sub(r'<!--.*?-->','',source['sections'][clause['section']]['text'],flags=re.S)
        assert clause['source_paragraph'] in normalized
    assert set(document['products'])==set(source['products'])|{'TR','SW1','SW2','DN','J','M','I','R','T','A'}
    for product in document['products']:
        definition=complete_definition(catalog,product)
        assert len({r['id'] for r in definition['rows']})==len(definition['rows'])
        assert {r['section'] for r in definition['rows']}>={'5.1','5.4','5.5'}
        assert any(r['section'] in ('5.3','11.4') for r in definition['rows'])


def test_unknown_source_conditions_are_not_false_and_mandatory_rows_cannot_be_disabled(catalog):
    before=assess(catalog,'TS')
    assert row(before,'t01_01')['applicable'] is True
    assert row(before,'t03_01')['applicable'] is None and 'simplified_ts' in before['missing_facts']
    known=assess(catalog,'TS',{'simplified_ts':False,'gambling':True})
    assert row(known,'t03_01')['outcome']=='not_applicable'
    assert row(known,'t03_02')['applicable'] is True
    with pytest.raises(DocumentChecklistError): assess(catalog,'TS',{'t01_01_applies':False})


def test_transit_alternatives_remain_one_requirement_without_invented_matrix(catalog):
    result=assess(catalog,'TR')
    assert not result['definition']['matrix_present']
    alternative=row(result,'t08_03')
    assert 'билет' in alternative['text'] and 'или виза' in alternative['text'] and 'или разрешение' in alternative['text']
    assert len([r for r in result['rows'] if r['id'].startswith('t08_')])==3
    checked=assess(catalog,'TR',states={'t08_03':'checked'})
    assert row(checked,'t08_03')['outcome']=='checked' and not checked['assessments_complete']


def test_medical_study_resident_and_work_scopes_are_distinct(catalog):
    student=assess(catalog,'RES',{'resident_basis':'S'})
    assert row(student,'med01')['applicable'] is True
    assert row(student,'t14_01')['applicable'] is True
    assert row(student,'med02')['applicable'] is False
    assert row(student,'work15')['applicable'] is False
    worker=assess(catalog,'RES',{'resident_basis':'work'})
    assert row(worker,'med01')['applicable'] is False and row(worker,'med02')['applicable'] is True
    assert row(worker,'work15')['applicable'] is True and row(worker,'t14_01')['applicable'] is False
    with pytest.raises(DocumentChecklistError): assess(catalog,'RES',{'resident_basis':'work','resident_after_ep':False})


def test_employer_esuvm_and_entrepreneur_conditions(catalog):
    result=assess(catalog,'EP',{'tax_in_esuvm':True,'employer_is_entity':False,'foreign_entrepreneur':True,'licensed_activity':None})
    assert row(result,'work01')['applicable'] is True
    assert row(result,'work06')['applicable'] is False and row(result,'work05')['applicable'] is False
    assert row(result,'work07')['applicable'] is True and row(result,'work08')['applicable'] is None
    assert 'licensed_activity' in result['missing_facts']


def test_journalist_and_volunteer_are_not_cumulative(catalog):
    result=assess(catalog,'SW2',{'sw2_category':'journalist','long_term':False})
    assert row(result,'t16_01')['applicable'] is True
    assert row(result,'t16_02')['applicable'] is False
    assert all(r['applicable'] is False for r in result['rows'] if r['id'].startswith('t17_'))
    unknown=assess(catalog,'SW2',{'long_term':True})
    assert row(unknown,'t16_02')['applicable'] is None


def test_registration_students_workers_representative_and_insurance(catalog):
    result=assess(catalog,'REG',{'registration_student':True,'visa_free':False,'registration_worker':False,
        'eaeu_worker':True,'worker_family':True,'representative':False,'host_is_owner':None,
        'extension':True,'stateless':True,'insurance_in_esuvm':False})
    assert row(result,'t31_01_1')['applicable'] is False and row(result,'t31_01_2')['applicable'] is True
    assert row(result,'t32_01')['applicable'] is False and row(result,'t32_03')['applicable'] is True
    assert row(result,'t30_01')['applicable'] is False and row(result,'t29_01')['applicable'] is None
    assert row(result,'t33_01')['applicable'] is True


def test_recommendations_minor_paper_and_version_recheck(catalog):
    result=assess(catalog,'TS',{'paper_submission':False,'minor':True},states={'t01_01':'checked'},current_version=False)
    assert row(result,'g03_01_2')['applicable'] is False
    assert row(result,'g03_01_3')['kind']=='recommended'
    assert row(result,'g04_02')['applicable'] is False
    assert row(result,'t01_01')['outcome']=='not_current'
    assert row(result,'quality04')['outcome']=='policy_required'
    with pytest.raises(DocumentChecklistError): assess(catalog,'TS',states={'quality04':'checked'})


@pytest.mark.parametrize('facts',[{'long_term':1},{'sw2_category':'other'},{'passport_number':'private'}, {'long_term':[]}, {'long_term':'true'}])
def test_typed_nonpersonal_fact_boundary(catalog,facts):
    with pytest.raises(DocumentChecklistError): assess(catalog,'SW2',facts)


def test_source_integrity_stale_definition_and_result_independence(catalog):
    with pytest.raises(DocumentChecklistError): CompleteDocumentCatalog(catalog._raw.replace(b'SW1',b'BAD',1))
    with pytest.raises(DocumentChecklistError): assess(catalog,'TS',expected_digest='0'*64)
    first=complete_definition(catalog,'TS'); first['rows'].clear()
    assert complete_definition(catalog,'TS')['rows']
