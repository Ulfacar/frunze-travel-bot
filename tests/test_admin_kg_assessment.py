import asyncio

import pytest

import app.admin.router as ar
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageUnavailable
from tests.test_admin_kg_entry import env
from tests.test_connected_qualification import setup, clock, route_clock, admins, assess, POLICY, profile
from tests.test_admin_workday import _login


def configure(env, monkeypatch):
    for key, value in dict(kg_assessment_policy=env['assessment_policy'].document,
            kg_qualification_policy=env['qualification_policy'].document,
            kg_interview_policy=env['interview_policy'].document(),
            kg_knowledge_policy_ref=POLICY.reference, kg_knowledge_policy_sha256=POLICY.fingerprint,
            kg_knowledge_publishers=list(POLICY.publishers)).items():
        monkeypatch.setattr(ar.settings, key, value)
    return f"/admin/case/{env['cases']['visa']}/kg-entry/applicants/{env['person']['id']}/assessment"


def test_positive_native_no_browser_supplied_authority_and_withdrawal(env, tmp_path, monkeypatch):
    setup(env, tmp_path); url = configure(env, monkeypatch)
    response = env['client'].get(url)
    assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
    assert 'Безвизовый вариант для указанной поездки' in response.text
    assert '10 / 30' in response.text and '90 / 180' in response.text
    assert 'не гарантирует пропуск' in response.text and '<form' not in response.text.split('<main', 1)[1]
    assert env['client'].get(url + '?approved=true').status_code == 422
    assert env['client'].post(url, data={'approved': 'true'}).status_code == 405
    monkeypatch.setattr(ar.settings, 'kg_assessment_policy', {})
    unavailable = env['client'].get(url)
    assert unavailable.status_code == 200 and 'нет действующего утверждения' in unavailable.text
    assert 'Безвизовый вариант для указанной поездки' not in unavailable.text
    assert env['client'].get(url.replace('/case/1/', '/case/99999/')).status_code == 404
    with _login('medina') as manager:
        assert manager.get(url).status_code == 403


def test_native_service_failure_and_bad_authority_are_no_store(env, monkeypatch):
    import app.admin.kg_assessment as ui
    url = f"/admin/case/{env['cases']['visa']}/kg-entry/applicants/1/assessment"
    async def unavailable(*args, **kwargs):
        raise EntryStorageUnavailable('synthetic unavailable')
    monkeypatch.setattr(ui.service, 'assess', unavailable)
    response = env['client'].get(url)
    assert response.status_code == 503 and response.headers['cache-control'] == 'no-store'
    assert 'Проверка временно недоступна' in response.text
    monkeypatch.setattr(ar.settings, 'kg_assessment_policy', {'approved': True})
    assert env['client'].get(url).status_code == 503


def test_profile_field_map_covers_current_schema_and_extra_material_facts():
    from app.domain import assessment_rules
    from app.knowledge.qualification_schema import V2_REQUEST_SCHEMA
    fields = V2_REQUEST_SCHEMA['properties']['profile']['properties']
    assert set(assessment_rules.PROFILE_MAP) == set(fields)
    for change in ({'purpose_details': 'Work planned despite tourism selection'},
                   {'event_dates': {'from': '2026-11-02', 'to': '2026-11-03'}},
                   {'inviting_party': {'exists': True}}, {'new_material_fact': False}):
        assert assessment_rules.profile_scope(profile()['profile'] | change) == 'additional_profile_evidence_requires_reconciliation'
