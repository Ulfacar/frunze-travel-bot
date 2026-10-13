"""Source preservation and failure paths for the draft matrix, not legal acceptance."""
from dataclasses import FrozenInstanceError
from pathlib import Path
import re

import pytest

from app.knowledge.document_checklist import (DocumentCatalog,DocumentChecklistError,
    checklist,load_document_catalog,review_checklist)
from scripts.build_kg_document_catalog import build


@pytest.fixture
def catalog():return load_document_catalog()


def review(catalog,product='TS',**changes):
    args=dict(product=product,states={},conditions={},current_version=None,expected_digest=catalog.digest)
    args.update(changes);result=review_checklist(catalog,**args)
    assert all(result[key] is False for key in ('package_accepted','submission_allowed','publication_approved','supplementary_requirements_assessed'))
    assert result['facts_hypothetical'] is True
    return result


def checked(catalog,product='TS'):
    items=checklist(catalog,product)
    return dict(states={r['id']:'checked' for r in items if r['kind']!='not_listed'},
        conditions={r['id']:False for r in items if r['kind']=='conditional'},current_version=True)


def test_catalog_reproduces_all_source_rows_and_additions(catalog):
    data=catalog.document();assert data==build()
    source=Path('docs/kb-visa-inbound-v1.1-derived.md').read_text('utf-8')
    section=source[source.index('## 5.2.'):source.index('## 5.3.')]
    rows=[line for line in section.splitlines() if re.match(r'^\| \d',line)]
    assert len(rows)==23 and rows==[row['source_text'] for row in data['rows']]
    assert set(data['products'])=={'TS','B','RL','FF','S','EP','RES','L','REG'}
    assert {row['page'] for row in data['rows']}=={36,37}
    assert 'заключение об отсутствии антител к ВИЧ' in data['sections']['5.2']['text']
    assert 'TR — транзитная' in data['sections']['5.3']['text']
    assert 'Срок хранения сканов' in data['sections']['5.5']['text']
    assert 'согласие на открытие специального банковского счёта' in data['sections']['11.4']['text']


def test_every_product_has_unique_items_with_original_cells(catalog):
    for product in catalog.document()['products']:
        items=checklist(catalog,product)
        assert len({row['id'] for row in items})==len(items)
        assert {row['id'].split('_')[0] for row in items}=={f'd{i:02}' for i in range(1,24)}
        assert all(row['source_cell'] and row['page'] in (36,37) for row in items)


def test_mixed_address_booking_and_dash_annotation(catalog):
    rows=[r for r in checklist(catalog,'TS') if r['id'].startswith('d06_')]
    assert [(r['kind'],r['note']) for r in rows]==[('required','адрес'),('recommended','бронь')]
    photo=next(r for r in checklist(catalog,'REG') if r['id']=='d03_0')
    assert photo['kind']=='not_listed' and 'Face ID' in photo['note'] and 'онлайн' in photo['note']


def test_receipt_not_verification_and_no_package_acceptance(catalog):
    args=checked(catalog)
    args['states']['d02_0']='received'
    result=review(catalog,**args)
    assert result['counts']['required_pending']==1
    assert next(r for r in result['rows'] if r['id']=='d02_0')['outcome']=='received'
    args['states']['d02_0']='checked'
    assert review(catalog,**args)['status']=='draft_rows_checked'


@pytest.mark.parametrize('current',[False,None])
def test_new_or_unknown_document_version_invalidates_review(catalog,current):
    args=checked(catalog);args['current_version']=current
    result=review(catalog,**args)
    assert result['counts']['required_checked']==0 and result['counts']['required_pending']>0
    assert next(r for r in result['rows'] if r['id']=='d01_0')['outcome']=='not_current'


def test_conditional_unknown_not_silently_excluded(catalog):
    args=checked(catalog);args['conditions']['d08_0']=None
    result=review(catalog,**args)
    assert result['counts']['applicability_unknown']==1 and result['status']=='needs_attention'
    args['conditions']['d08_0']=True;args['states']['d08_0']='missing'
    assert review(catalog,**args)['counts']['required_pending']==1
    args['conditions']['d08_0']=False
    result=review(catalog,**args)
    assert result['counts']['required_pending']==0
    assert next(r for r in result['rows'] if r['id']=='d08_0')['outcome']=='not_applicable'


def test_recommended_hotel_is_not_mandatory_address_and_correction_blocks(catalog):
    args=checked(catalog);args['states']['d06_1']='missing'
    result=review(catalog,**args)
    assert result['counts']['required_pending']==0 and result['counts']['recommended_pending']==1
    args['states']['d06_0']='correction'
    assert review(catalog,**args)['counts']['required_pending']==1


def test_unverified_source_photo_cannot_be_approved_by_form(catalog):
    result=review(catalog,'EP',**checked(catalog,'EP'))
    assert result['counts']['source_review']==1 and result['status']=='needs_attention'
    assert next(r for r in result['rows'] if r['id']=='d03_0')['outcome']=='source_review'


@pytest.mark.parametrize('changes',[
    {'states':{'d05_0':'checked'}},{'states':{'d01_0':True}},{'states':{'d01_0':'accepted'}},
    {'conditions':{'d01_0':False}},{'conditions':{'d08_0':'false'}},{'conditions':{'d08_0':1}},
    {'current_version':'true'},{'current_version':1},{'states':[]},{'conditions':None},
    {'states':{'passport_number':'synthetic'}},{'product':'TR'},
    {'expected_digest':'0'*64}])
def test_bad_fields_types_products_and_stale_revision(catalog,changes):
    with pytest.raises(DocumentChecklistError):review(catalog,**changes)


def test_catalog_detached_frozen_digest_and_integrity(catalog,tmp_path):
    copy=catalog.document();copy['publication_approved']=True;copy['rows'].clear()
    assert len(catalog.document()['rows'])==23
    with pytest.raises(FrozenInstanceError):catalog._raw=b'changed'
    assert DocumentCatalog(catalog._raw.replace(b'\n',b'\r\n')).digest==catalog.digest
    assert review(catalog)['input_sha256']==review(catalog)['input_sha256']
    assert review(catalog)['input_sha256']!=review(catalog,current_version=True)['input_sha256']
    for bad in (b'{}',b'x'*524289,catalog._raw.replace(b'false',b'true',1)):
        with pytest.raises(DocumentChecklistError):DocumentCatalog(bad)
    with pytest.raises(DocumentChecklistError):load_document_catalog(tmp_path/'absent.json')
