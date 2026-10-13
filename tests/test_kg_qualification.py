"""Unified PDF route: partial facts, conservative candidates and read-only boundaries."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest
from sqlalchemy import event, text

from app.domain.entry_qualification import review_qualification
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.models import DomainError
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied, SYSTEM_ACTOR
from app.knowledge.qualification import QualificationError, QualificationReview
from app.knowledge.review import canonical
from app.knowledge.validation import load_document
from scripts.build_kg_entry_conditions import build_catalog
from tests.test_entry_storage import ADMIN, FIX, db, history, save_history

ROOT = Path(__file__).resolve().parents[1]


def request():
    return load_document(FIX/'synthetic_qualification_review.json')


@pytest.fixture(scope='module')
def bundle():
    return {k: load_document(ROOT/'knowledge/kg_entry/draft-v1.1'/f'{k}.yaml') for k in ('meta','countries','units')}


@pytest.fixture(scope='module')
def review(bundle):
    return QualificationReview(**bundle, source_hash=bundle['meta']['source_hash'], catalog=build_catalog())


def assert_no_decision(result):
    assert result['may_quote'] is False and result['publication_approved'] is False
    assert result['selected_regime'] is None and result['visa_required'] is None
    assert result['exact_deadline'] is None and result['exact_remaining_days'] is None
    assert result['calculations_performed'] is False
    assert all(r['may_quote'] is False for r in result['candidate_rules']+result['registration_rules'])


@pytest.mark.parametrize('language',['ru','en'])
def test_partial_questions_are_ordered_and_limited(review, language):
    req=request(); req.update(language=language,profile={})
    result=review.evaluate(req)
    assert result['status']=='needs_input'
    assert [q['path'] for q in result['next_questions']]==[
        'profile.citizenship','profile.entry_passport_country','profile.document_type']
    assert result['next_questions'][0]['text']==('Какие у вас гражданства?' if language=='ru' else 'What citizenships do you hold?')
    assert_no_decision(result)


def test_full_profile_explains_sources_without_deciding_entry(review):
    result=review.evaluate(request())
    assert result['status']=='knowledge_review' and result['next_questions']==[]
    assert result['candidate_rules'] and result['registration_rules']
    assert all(r['source']['page'] and r['source']['source_ref'] for r in result['candidate_rules'])
    assert result['withheld_fallbacks'] and all('all_others' in r['reason'] for r in result['withheld_fallbacks'])
    assert_no_decision(result)


def test_two_passports_never_selects_the_more_convenient_one(review):
    req=request();req['profile'].update(citizenship=['RUS','MDA']);del req['profile']['entry_passport_country']
    result=review.evaluate(req)
    assert result['next_questions'][0]['path']=='profile.entry_passport_country'
    assert result['registration_rules']==[]
    req['profile']['entry_passport_country']='MDA'
    result=review.evaluate(req)
    assert 'source_conflict' in result['blockers']
    assert any('source_conflict' in r['findings'] for r in result['candidate_rules']+result['registration_rules'])
    assert_no_decision(result)


@pytest.mark.parametrize('changes,reason',[
    ({'document_type':'diplomatic'},'special_document_review'),
    ({'document_type':'un_lp'},'special_document_review'),
    ({'document_type':'stateless'},'special_document_review'),
    ({'document_type':'unrecognized'},'special_document_review'),
    ({'purpose':'work_hire'},'work_purpose_review'),
    ({'passport_expiry':'2026-10-08'},'passport_expired'),
    ({'passport_pages_ok':False},'passport_pages_review'),
    ({'violations':{'overstay':True}},'reported_overstay'),
    ({'violations':{'deportation_or_ban':True}},'reported_deportation_or_ban'),
    ({'previous_refusals_kg':True},'reported_refusal'),
    ({'entry_date':'2026-10-08'},'planned_entry_in_past'),
])
def test_known_stops_take_priority_over_missing_questions(review,changes,reason):
    req=request();req['profile'].update(changes);del req['profile']['exit_date']
    result=review.evaluate(req)
    assert reason in result['stop_reasons'] and result['status']=='manager_review'
    assert result['next_questions']==[] and 'profile.exit_date' in result['missing_facts']
    assert_no_decision(result)


def test_unknown_does_not_mean_no_violation_or_positive_approval(review):
    req=request();req['profile']['violations']={'overstay':'unknown','deportation_or_ban':'not_applicable'}
    result=review.evaluate(req)
    assert result['status']=='needs_input'
    assert 'profile.violations.overstay' in result['missing_facts']
    assert 'profile.violations.deportation_or_ban' in result['missing_facts']
    assert result['stop_reasons']==[]


def test_in_country_basis_expiry_and_registration_are_separate(review):
    req=request();req['profile'].update(current_location='in_kg',in_kg_since='2026-09-01',
        current_basis_in_kg='visa',current_basis_until='2026-10-08',registration_until='2026-10-08')
    result=review.evaluate(req)
    assert 'profile.current_visa_type' in result['missing_facts']
    assert {'current_basis_until_passed','registration_until_passed'}.issubset(result['stop_reasons'])
    assert_no_decision(result)


@pytest.mark.parametrize('fault',['passport','country','reverse_dates','actual_future','abroad_basis','raw_name',
    'raw_contact','history','decision','stops','fact_country','override_country','override_document','cycle','nan','bad_date','bad_bool'])
def test_invalid_or_forged_profile_is_rejected_without_echo(review,fault):
    req=request();p=req['profile']
    if fault=='passport': p['entry_passport_country']='MDA'
    elif fault=='country': p.update(citizenship=['ZZZ'],entry_passport_country='ZZZ')
    elif fault=='reverse_dates': p['exit_date']='2026-10-01'
    elif fault=='actual_future': p.update(current_location='in_kg',in_kg_since='2026-10-10')
    elif fault=='abroad_basis': p['current_basis_in_kg']='visa'
    elif fault=='raw_name': p['name']='PRIVATE-DATA'
    elif fault=='raw_contact': p['contact']={'phone':'PRIVATE-DATA'}
    elif fault=='history': req['history']={'confirmed':True}
    elif fault=='decision': p['decision']={'may_quote':True}
    elif fault=='stops': p['stop_factors']=[]
    elif fault=='fact_country': req['condition_facts']={'schema_version':'kg-entry-condition-facts/1','residence_documents':{'items':[{'country':'ZZZ'}]}}
    elif fault=='override_country': req['condition_facts']={'schema_version':'kg-entry-condition-facts/1','entry_passport_country':'CHN'}
    elif fault=='override_document': req['condition_facts']={'schema_version':'kg-entry-condition-facts/1','document_type':'un_lp'}
    elif fault=='cycle': p['citizenship']=[req]
    elif fault=='nan': p['passport_pages_ok']=float('nan')
    elif fault=='bad_date': req['as_of']='2026-02-30'
    elif fault=='bad_bool': p['passport_pages_ok']=1
    with pytest.raises(QualificationError) as error: review.evaluate(req)
    assert 'PRIVATE' not in str(error.value) and len(str(error.value))<100


def test_condition_matches_are_candidates_and_preserve_unknowns(review):
    req=request();req['profile'].update(citizenship=['CHN'],entry_passport_country='CHN')
    uid='KG.SP.CHN_IND_LONGTERM_VISA'
    pending=next(r for r in review.evaluate(req)['candidate_rules'] if r['unit_id']==uid)
    assert pending['profile_match']=='unknown'
    req['condition_facts']={'schema_version':'kg-entry-condition-facts/1',
        'foreign_visas':{'items':[{'issuer':'USA','over_three_years_verified':True}],'complete':True}}
    result=review.evaluate(req)
    assert next(r for r in result['candidate_rules'] if r['unit_id']==uid)['profile_match']=='met'
    assert 'multiple_candidates_require_review' in result['blockers']
    assert_no_decision(result)
    req['condition_facts']['foreign_visas']['items'][0]['over_three_years_verified']=False
    result=review.evaluate(req)
    assert uid in result['excluded_condition_rules']
    assert uid not in [r['unit_id'] for r in result['candidate_rules']]


def test_no_catalog_no_invented_special_rule_and_owned_canonical_request(bundle):
    review=QualificationReview(**bundle,source_hash=bundle['meta']['source_hash'])
    req=request();req['condition_facts']={'schema_version':'kg-entry-condition-facts/1'}
    original=deepcopy(req); result=review.evaluate(req)
    assert req==original and result['request_hash']==hashlib.sha256(canonical(req).encode()).hexdigest()
    assert 'condition_catalog_missing' in result['blockers']
    assert all(r['profile_match']=='not_evaluated' for r in result['candidate_rules'])
    result['candidate_rules'].clear()
    assert review.evaluate(req)['candidate_rules']


def test_source_snapshot_is_owned_and_wrong_catalog_cannot_be_attached(bundle):
    data=deepcopy(bundle);catalog=build_catalog()
    review=QualificationReview(**data,source_hash=data['meta']['source_hash'],catalog=catalog)
    before=review.evaluate(request())
    data['units'].clear();catalog['rules'].clear()
    assert review.evaluate(request())==before
    wrong=build_catalog();wrong['bundle_hash']='0'*64
    with pytest.raises(ValueError):
        QualificationReview(**bundle,source_hash=bundle['meta']['source_hash'],catalog=wrong)


def test_passport_change_rebuilds_candidates_without_stale_registration(review):
    req=request();first=review.evaluate(req)
    req['profile'].update(citizenship=['RUS','MDA'],entry_passport_country='MDA')
    second=review.evaluate(req)
    assert first['request_hash']!=second['request_hash']
    assert first['registration_rules']!=second['registration_rules']
    req['profile'].update(citizenship=['RUS'],entry_passport_country='RUS')
    assert review.evaluate(req)==first


@pytest.mark.parametrize('actor',[None,{},Actor('manager'),Actor('bot',True),Actor('',True),SYSTEM_ACTOR])
def test_db_authorizes_before_engine_and_facts(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(review_qualification(None,actor=actor,contact_id=1,knowledge_version_id=1,request={}))


def test_db_uses_pinned_history_and_performs_only_selects(db):
    async def scenario():
        doc=history();doc['history_complete']=None
        doc['intervals'][0].update(confirmed=False,evidence='client_statement')
        saved=await save_history(db,doc)
        statements=[]
        def capture(conn,cursor,statement,params,ctx,many):statements.append(statement.lstrip().split()[0].upper())
        event.listen(db[0].sync_engine,'before_cursor_execute',capture)
        try:
            result=await review_qualification(db[0],actor=ADMIN,contact_id=1,knowledge_version_id=db[1],request=request(),history_id=saved['history_id'])
        finally:event.remove(db[0].sync_engine,'before_cursor_execute',capture)
        assert statements and set(statements)=={'SELECT'}
        assert result['source']['knowledge_version_id']==db[1]
        assert result['history']['revision']==1 and result['history']['unconfirmed_count']==1
        assert {'history_incomplete','history_unconfirmed','history_cutoff_differs'}.issubset(result['blockers'])
        assert_no_decision(result)
        with pytest.raises(EntryStorageInvalid):
            await review_qualification(db[0],actor=ADMIN,contact_id=2,knowledge_version_id=db[1],request=request(),history_id=saved['history_id'])
    asyncio.run(scenario())


@pytest.mark.parametrize('fault',['knowledge','projection','history','unknown_contact','unsealed'])
def test_db_rejects_corrupt_or_unavailable_sources(db,fault):
    async def scenario():
        saved=await save_history(db)
        sql={'knowledge':"UPDATE knowledge_versions SET bundle_hash=:bad",'projection':"DELETE FROM knowledge_country_links",
             'history':"UPDATE stay_intervals SET exit_date='2026-09-25'",'unsealed':"DELETE FROM knowledge_imports"}
        if fault in sql:
            async with db[0].begin() as c:await c.execute(text(sql[fault]),{'bad':'0'*64})
        with pytest.raises(DomainError):
            await review_qualification(db[0],actor=ADMIN,contact_id=99 if fault=='unknown_contact' else 1,
                knowledge_version_id=db[1],request=request(),history_id=saved['history_id'])
    asyncio.run(scenario())


def test_cli_is_read_only_and_does_not_echo_private_input(tmp_path):
    profile=tmp_path/'request.json';profile.write_text(json.dumps(request()),encoding='utf-8')
    source=FIX/'synthetic_source.txt'
    before=(source.read_bytes(),source.stat().st_mtime_ns,profile.read_bytes(),profile.stat().st_mtime_ns)
    args=[sys.executable,'-X','utf8',str(ROOT/'scripts/review_kg_qualification.py'),str(FIX/'synthetic_bundle'),
          '--source',str(source),'--request',str(profile)]
    result=subprocess.run(args,cwd=tmp_path,capture_output=True,encoding='utf-8',timeout=30)
    assert result.returncode==0 and json.loads(result.stdout)['status']=='knowledge_review'
    assert before==(source.read_bytes(),source.stat().st_mtime_ns,profile.read_bytes(),profile.stat().st_mtime_ns)
    bad=request();bad['profile']['passport_number']='PRIVATE-PAYLOAD'
    profile.write_text(json.dumps(bad),encoding='utf-8')
    result=subprocess.run(args,cwd=tmp_path,capture_output=True,encoding='utf-8',timeout=30)
    assert result.returncode==1 and json.loads(result.stdout)['ok'] is False
    assert 'PRIVATE' not in result.stdout+result.stderr
