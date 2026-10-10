import pytest

import app.admin.kg_knowledge_publication as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form, env
from tests.test_admin_workday import _login
from tests.test_knowledge_publication import POLICY, IDS, release, preview, runtime


@pytest.fixture
def publisher(release, monkeypatch):
    monkeypatch.setattr(ar.settings, 'kg_knowledge_publishers', list(POLICY.publishers))
    monkeypatch.setattr(ar.settings, 'kg_knowledge_policy_ref', POLICY.reference)
    monkeypatch.setattr(ar.settings, 'kg_knowledge_policy_sha256', POLICY.fingerprint)
    return release


def url(env):
    return ui.URL + f"?version={env['release']}&units=" + ','.join(IDS)


def form(env, action):
    page = env['client'].get(url(env)); assert page.status_code == 200, page.text[-1500:]
    data = Form(page.text, 'kg-publication-'+action).data; assert data
    data['confirmed'] = 'yes'
    return data


def post(env, values, client=None):
    return (client or env['client']).post(ui.URL, data=values, follow_redirects=False)


def test_native_review_approve_activate_withdraw_and_retry(publisher):
    assert ui.URL in publisher['client'].get('/admin/kg-entry/reviews').text
    for action in ('review', 'approve', 'activate'):
        values = form(publisher, action)
        assert post(publisher, values).status_code == 303
        assert post(publisher, values).status_code == 303
    page = publisher['client'].get(url(publisher))
    assert 'Состояние: активна' in page.text and 'основания и сроки проверены' in page.text
    assert len(runtime(publisher)['available']) == 2
    assert post(publisher, form(publisher, 'withdraw')).status_code == 303
    assert runtime(publisher)['version_id'] is None
    assert preview(publisher)['current_revision'] == 4


def test_publication_default_authority_absent(release):
    page = release['client'].get(url(release))
    assert page.status_code == 200 and 'Полномочия публикации не назначены' in page.text
    assert not Form(page.text, 'kg-publication-review').data
    assert post(release, {}).status_code == 403
    assert preview(release)['current_revision'] == 0


def test_auth_off_write_policy_change_csrf_and_pinned_selection(publisher, monkeypatch):
    values = form(publisher, 'review'); manager = _login('medina')
    assert manager.get(ui.URL).status_code == 403 and post(publisher, values, client=manager).status_code == 403
    for changes in ({'_kp_units':IDS[0]}, {'_kp_version':'999'}, {'_kp_action':'activate'}, {'_kp_manifest':'0'*64},
                    {'_kp_policy':'0'*64}, {'_kp_revision':'8'}, {'_kp_csrf':'bad'}):
        assert post(publisher, {**values, **changes}).status_code == 403
    monkeypatch.setattr(ar.settings, 'kg_knowledge_policy_sha256', 'b'*64)
    assert post(publisher, values).status_code == 409
    monkeypatch.setattr(ar.settings, 'kg_knowledge_policy_sha256', POLICY.fingerprint)
    monkeypatch.setattr(ar.settings, 'admin_kg_entry_enabled', False)
    assert publisher['client'].get(ui.URL).status_code == 404 and post(publisher, values).status_code == 404
    monkeypatch.setattr(ar.settings, 'admin_kg_entry_enabled', True)
    monkeypatch.setattr(ar.settings, 'service_cases_enabled', False)
    assert post(publisher, values).status_code == 403
    assert preview(publisher)['current_revision'] == 0


def test_fields_conflicts_and_source_changed(publisher):
    from urllib.parse import urlencode
    values = form(publisher, 'review'); stale = form(publisher, 'review')
    for suffix in ('&version=1', '&extra=x', '&units=KG.VF.TEST'):
        assert publisher['client'].get(url(publisher)+suffix).status_code == 422
    assert publisher['client'].get(ui.URL+'?units=bad').status_code == 422
    assert post(publisher, {**values,'extra':'unknown'}).status_code == 422
    assert post(publisher, {**values,'confirmed':'no'}).status_code == 422
    assert publisher['client'].post(ui.URL, json=values).status_code == 415
    assert publisher['client'].post(ui.URL, content='x'*24001, headers={'content-type':'application/x-www-form-urlencoded'}).status_code == 413
    assert publisher['client'].post(ui.URL, content=urlencode(values)+'&confirmed=yes', headers={'content-type':'application/x-www-form-urlencoded'}).status_code == 422
    assert post(publisher, values).status_code == 303
    assert post(publisher, stale).status_code == 409
    assert preview(publisher)['current_revision'] == 1


def test_lost_ack_and_read_failure_keep_original_command(publisher, monkeypatch):
    values = form(publisher, 'review'); original = ui.service.publish_knowledge; reader = ui.service.publication_preview
    async def lost(*args, **kwargs):
        await original(*args, **kwargs); raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    async def unreadable(*args, **kwargs): raise EntryStorageUnavailable('synthetic read failure')
    monkeypatch.setattr(ui.service, 'publish_knowledge', lost); monkeypatch.setattr(ui.service, 'publication_preview', unreadable)
    response = post(publisher, values)
    assert response.status_code == 503 and Form(response.text, 'kg-publication-retry').data == values
    assert not Form(response.text, 'kg-publication-review').data
    monkeypatch.setattr(ui.service, 'publish_knowledge', original); monkeypatch.setattr(ui.service, 'publication_preview', reader)
    assert post(publisher, Form(response.text, 'kg-publication-retry').data).status_code == 303
    assert preview(publisher)['current_revision'] == 1


def test_active_screen_explains_changed_evidence_and_withdraws_pinned_manifest(publisher):
    from tests.test_knowledge_decisions import data, write as review
    for action in ('review', 'approve', 'activate'):
        assert post(publisher, form(publisher, action)).status_code == 303
    review(publisher, {**data(), 'proof':'b'*64}, unit=IDS[0], version=publisher['release'], key='new-evidence')
    page = publisher['client'].get(url(publisher))
    assert 'Решение изменилось после утверждения' in page.text
    assert 'Прежнее утверждение на них не переносится' in page.text
    assert len(runtime(publisher)['available']) == 1
    assert post(publisher, form(publisher, 'withdraw')).status_code == 303
