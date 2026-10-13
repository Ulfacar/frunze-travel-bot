"""Synthetic executable approval, individual scope and conservative route boundary."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import shutil

import pytest
import yaml
from sqlalchemy import event

from app.domain import applicant_profiles, approved_qualification as service
from app.domain import entry_applications, knowledge_decisions, knowledge_publication
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.knowledge_import import create_kg_entry_set, import_bundle
from app.domain.permissions import Actor
from app.domain.qualification_policy import QualificationPolicy
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, FIX, env
from tests.test_applicant_profiles import save, read
from tests.test_entry_applications import person, enforce_sqlite_foreign_keys
from tests.test_kg_intake import intake_request
from tests.test_knowledge_decisions import write as review
from tests.test_knowledge_publication import POLICY, activate, publish, preview


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    current = datetime(2026, 10, 12, 6, tzinfo=timezone.utc)
    def now():
        nonlocal current
        current += timedelta(microseconds=1)
        return current
    for module in (entry_applications, applicant_profiles, knowledge_decisions, knowledge_publication):
        monkeypatch.setattr(module, '_now', now)


def profile():
    value = intake_request()
    value['as_of'] = '2026-10-12'
    value['profile'].update(requested_process='visa', escalation=dict(complaint=False, refund_question=False,
        legal_question=False, conflicting_answers=False))
    return value


def load(env, tmp_path, *, tag='route', extra=None, changes=None):
    folder = tmp_path / tag
    shutil.copytree(FIX/'synthetic_bundle', folder)
    units = yaml.safe_load((folder/'units.yaml').read_text('utf-8'))
    units = [u for u in units if u['kind'] not in ('special_regime', 'visa_required_regime')]
    if extra:
        units.append(deepcopy(extra))
    for unit in units:
        if unit['kind'] in ('visa_free_regime', 'visa_required_regime', 'deadline', 'special_regime'):
            unit.update(effective_from='2026-01-01', verified_at='2026-09-01T00:00:00Z',
                verified_by='synthetic-reviewer', review_due_at='2026-12-01T00:00:00Z', owner='synthetic-owner',
                source_ref='Synthetic route fixture only')
        if changes and unit['unit_id'] in changes:
            unit.update(changes[unit['unit_id']])
    (folder/'units.yaml').write_text(yaml.safe_dump(units, allow_unicode=True), 'utf-8')
    async def seed():
        set_id = await create_kg_entry_set(env['engine'], actor=ADMIN)
        return await import_bundle(env['engine'], actor=ADMIN, set_id=set_id, directory=folder,
                                   source=FIX/'synthetic_source.txt')
    imported = asyncio.run(seed())
    assert imported.accepted, imported.report
    for unit in units:
        if unit['kind'] in ('visa_free_regime', 'visa_required_regime', 'deadline', 'special_regime'):
            review(env, unit=unit['unit_id'], version=imported.version_id, key='synthetic-'+unit['unit_id'])
    return imported.version_id, units


def policy(env, units):
    manifest = preview(env)['manifest']
    async def source():
        from app.domain.models import KnowledgeVersion
        async with env['sm']() as session:
            return (await session.get(KnowledgeVersion, env['release'])).source_hash
    return QualificationPolicy(dict(format='kg-qualification-policy/1', algorithm=service.FORMAT,
        reference='SYNTHETIC-ROUTE-ONLY', proof='a'*64, source_hash=asyncio.run(source()),
        bundle_hash=manifest['bundle_hash'], projection_hash=manifest['projection_hash'],
        catalog_hash=manifest['catalog_hash'], valid_from='2026-01-01', review_due_on='2026-12-01',
        complete_regime_set=True, rules=[dict(unit_id=u['unit_id'], all=[
            dict(type='passport_country_in', countries=u['value']['countries']),
            dict(type='document_type_is', value='ordinary')], routes=[dict(purpose='tourism', product='NO_VISA')])
            for u in units if u['kind']=='visa_free_regime']))


def setup(env, tmp_path, **kwargs):
    version, units = load(env, tmp_path, **kwargs)
    env.update(release=version, version=version)
    activate(env)
    env['person'] = person(env)
    env['saved'] = save(env, env['person'], doc=profile())
    env['policy'] = policy(env, units)
    return env


@pytest.fixture
def ready(env, tmp_path):
    return setup(env, tmp_path)


def propose(env, **kwargs):
    args = dict(actor=ADMIN, case_id=env['cases']['visa'], applicant_id=env['person']['id'],
        qualification_policy=env['policy'], publication_policy=POLICY)
    args.update(kwargs)
    return asyncio.run(service.propose_route(env['engine'], **args))


def test_candidate_has_current_exact_identity_but_no_eligibility_or_writes(ready):
    statements = []
    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement.lstrip().split()[0].upper())
    event.listen(ready['engine'].sync_engine, 'before_cursor_execute', capture)
    try:
        result = propose(ready)
    finally:
        event.remove(ready['engine'].sync_engine, 'before_cursor_execute', capture)
    assert result['status'] == 'candidate_for_review', result
    assert result['candidate']['unit_id'] == 'KG.VF.TEST'
    assert result['source']['version_id'] == ready['release']
    assert result['profile']['snapshot_hash'] == ready['saved']['snapshot_hash']
    assert result['policy_hash'] == ready['policy'].digest
    assert result['visa_required'] is result['selected_regime'] is result['selected_product'] is None
    assert result['exact_remaining_days'] is None and result['requires_specialist']
    assert not result['may_quote'] and not result['calculations_performed']
    assert statements and not set(statements) & {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER'}
    assert read(ready, ready['person'], replay=True)['saved'] == ready['saved']


@pytest.mark.parametrize('field,value,reason', [
    ('source_hash', 'b'*64, 'qualification_policy_source_changed'),
    ('projection_hash', 'b'*64, 'qualification_policy_source_changed'),
    ('review_due_on', '2026-10-11', 'qualification_policy_outside_validity'),
    ('review_due_on', '2026-11-05', 'qualification_policy_does_not_cover_trip'),
    ('valid_from', '2026-11-01', 'qualification_policy_outside_validity')])
def test_policy_binding_and_both_date_boundaries(ready, field, value, reason):
    doc = ready['policy'].document
    doc[field] = value
    result = propose(ready, qualification_policy=QualificationPolicy(doc))
    assert result['candidate'] is None and reason in result['reasons']


def test_no_executable_authority_or_publication_authority(ready):
    assert propose(ready, qualification_policy=None)['reasons'] == ['qualification_policy_missing']
    assert propose(ready, publication_policy=None)['reasons'] == ['competing_regime_unavailable']
    publish(ready, 'withdraw')
    assert propose(ready)['reasons'] == ['no_active_publication']


@pytest.mark.parametrize('change,reason', [
    ({'passport_expiry':'2026-11-03'}, 'passport_expires_before_departure'),
    ({'entry_date':'2026-10-11'}, 'profile_stop_requires_specialist'),
    ({'violations':{'overstay':True, 'deportation_or_ban':False, 'fines':False}}, 'profile_stop_requires_specialist'),
    ({'escalation':{'complaint':True}}, 'profile_stop_requires_specialist'),
    ({'escalation':{}}, 'individual_route_scope_requires_specialist'),
    ({'client_type':'b2b'}, 'individual_route_scope_requires_specialist'),
    ({'multiple_entries_needed':True}, 'individual_route_scope_requires_specialist'),
    ({'family':'unknown'}, 'individual_profile_incomplete')])
def test_stops_expiry_and_unknown_are_never_negative_answers(ready, change, reason):
    value = profile(); value['profile'].update(change)
    save(ready, ready['person'], revision=1, key='changed', doc=value)
    result = propose(ready)
    assert result['candidate'] is None and reason in result['reasons']
    if result['stop_reasons']:
        assert result['next_questions'] == []


def test_latest_personal_scope_and_current_confirmation(ready):
    another = person(ready, 'another')
    assert propose(ready, applicant_id=another['id'])['reasons'] == ['individual_profile_missing']
    with pytest.raises(EntryStorageInvalid):
        propose(ready, case_id=ready['cases']['other'])
    previous = ready['saved']
    value = profile(); value['as_of'] = '2026-10-11'
    save(ready, ready['person'], revision=1, key='yesterday', doc=value)
    assert propose(ready, expected_profile_id=previous['qualification_id'])['reasons'] == ['individual_profile_changed']
    assert propose(ready)['reasons'] == ['individual_profile_needs_current_confirmation']


@pytest.mark.parametrize('actor', [None, {}, Actor('medina'), Actor('bot',True)])
def test_access_before_engine_or_data(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(service.propose_route(None, actor=actor, case_id=1, applicant_id=1))


def test_complete_competing_set_and_partial_publication(env, tmp_path):
    units = yaml.safe_load((FIX/'synthetic_bundle/units.yaml').read_text('utf-8'))
    extra = deepcopy(units[0]); extra['unit_id'] = 'KG.VF.OTHER'; extra['value']['countries'] = ['CHN']
    ready = setup(env, tmp_path, extra=extra, changes={'KG.REG.DEFAULT': {'value':
        dict(deadline_working_days_from_border=4, not_in_list=['RUS','CHN'])}})
    assert propose(ready)['reasons'] == ['competing_regime_unavailable']
    document = ready['policy'].document
    document['rules'] = document['rules'][:1]
    assert propose(ready, qualification_policy=QualificationPolicy(document))['reasons'] == ['qualification_regime_set_incomplete']
    publish(ready, 'withdraw')
    for action in ('review', 'approve', 'activate'):
        publish(ready, action, ids=['KG.DL.TEST', 'KG.VF.TEST', 'KG.VF.OTHER'])
    assert propose(ready)['candidate']['unit_id'] == 'KG.VF.TEST'


def test_overlapping_visa_and_visa_free_routes_require_specialist(env, tmp_path):
    units = yaml.safe_load((FIX/'synthetic_bundle/units.yaml').read_text('utf-8'))
    extra = deepcopy(next(u for u in units if u['kind']=='visa_required_regime'))
    extra.update(unit_id='KG.VR.OTHER', value=dict(procedure='simplified',scope='all_types',
        gknb_approval=False,countries=['RUS']))
    ready = setup(env, tmp_path, extra=extra)
    publish(ready, 'withdraw')
    for action in ('review', 'approve', 'activate'):
        publish(ready, action, ids=['KG.DL.TEST','KG.VF.TEST','KG.VR.OTHER'])
    document = ready['policy'].document
    document['rules'].append(dict(unit_id='KG.VR.OTHER',all=[dict(type='passport_country_in',countries=['RUS']),
        dict(type='document_type_is',value='ordinary')],routes=[dict(purpose='tourism',product='TS')]))
    assert propose(ready,qualification_policy=QualificationPolicy(document))['reasons']==['competing_regimes_match']


def test_predicate_cannot_silently_remove_source_country_guard(ready):
    doc = ready['policy'].document
    doc['rules'][0]['all'] = [dict(type='document_type_is', value='ordinary')]
    assert propose(ready, qualification_policy=QualificationPolicy(doc))['reasons'] == ['qualification_predicates_do_not_cover_source']


def test_future_source_expiry_and_review_change(env, tmp_path):
    ready = setup(env, tmp_path, changes={'KG.VF.TEST': {'effective_to':'2026-11-05'}})
    assert propose(ready)['reasons'] == ['source_does_not_cover_trip']
    from tests.test_knowledge_decisions import data
    review(ready, {**data(), 'verdict':'rejected', 'reason':'withdrawn', 'review_due_on':None},
        unit='KG.VF.TEST', version=ready['release'], key='revoked')
    assert propose(ready)['reasons'] == ['competing_regime_unavailable']


def test_missing_questions_bounded_in_both_languages(ready):
    for revision, language in enumerate(('ru', 'en'), 1):
        value = profile(); value.update(language=language, profile={})
        save(ready, ready['person'], revision=revision, key=language, doc=value)
        result = propose(ready)
        assert result['candidate'] is None and len(result['next_questions']) == 3
        assert ('гражданства' if language=='ru' else 'citizenships') in result['next_questions'][0]['text']


def test_native_page_defaults_approval_gates_query_scope_and_safe_print(ready, monkeypatch):
    import app.admin.router as ar
    url = f"/admin/case/{ready['cases']['visa']}/kg-entry/applicants/{ready['person']['id']}/route"
    assert 'kg-route-fallback' in ready['client'].get(url).text
    monkeypatch.setattr(ar.settings, 'kg_qualification_policy', ready['policy'].document)
    monkeypatch.setattr(ar.settings, 'kg_knowledge_policy_ref', POLICY.reference)
    monkeypatch.setattr(ar.settings, 'kg_knowledge_policy_sha256', POLICY.fingerprint)
    monkeypatch.setattr(ar.settings, 'kg_knowledge_publishers', list(POLICY.publishers))
    response = ready['client'].get(url)
    assert response.status_code == 200 and 'kg-route-candidate' in response.text
    assert 'Необходимость визы и возможность въезда пока не определены' in response.text
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['referrer-policy'] == 'no-referrer'
    assert 'https://fonts.' not in response.text and 'https://unpkg.com/' not in response.text
    assert ready['client'].get(url+'?policy=anything').status_code == 422
    assert ready['client'].get(url.replace('/case/1/', '/case/9999/')).status_code == 404
    monkeypatch.setattr(ar.settings, 'admin_kg_entry_enabled', False)
    assert ready['client'].get(url).status_code == 404


def test_existing_typed_interview_cannot_be_silently_bypassed(ready, monkeypatch):
    from app.domain import entry_interviews
    from tests.test_entry_interviews import policy as interview_policy
    approval = interview_policy(operators=('admin',))
    asyncio.run(entry_interviews.start_interview(ready['engine'], actor=ADMIN,
        case_id=ready['cases']['visa'], applicant_id=ready['person']['id'], owner_login='admin',
        language='ru', request_key='interview', expected_policy_hash=approval.digest, policy=approval))
    assert propose(ready)['reasons'] == ['interview_reconciliation_required']


def test_policy_keeps_immutable_copy_and_rejects_ambiguous_shapes(ready):
    document = ready['policy'].document
    document['rules'][0]['routes'].append(dict(purpose='tourism', product='TS'))
    with pytest.raises(EntryStorageInvalid): QualificationPolicy(document)
    assert len(ready['policy'].document['rules'][0]['routes']) == 1
    document = ready['policy'].document; document['algorithm'] = 'unreviewed/2'
    with pytest.raises(EntryStorageInvalid): QualificationPolicy(document)


def test_route_product_cannot_change_literal_visa_requirement(ready):
    document = ready['policy'].document
    document['rules'][0]['routes'][0]['product'] = 'TS'
    assert propose(ready, qualification_policy=QualificationPolicy(document))['reasons'] == ['qualification_product_does_not_cover_source']
