import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text

import app.admin.kg_applicant_profiles as ui
import app.admin.router as ar
import app.main as main
from app.admin.kg_entry_form import values_from_request
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form, env
from tests.test_admin_workday import _login
from tests.test_applicant_profiles import person, application, request, read, enforce_sqlite_foreign_keys


@pytest.fixture
def subject(env):
    applicant = person(env)
    return applicant, ui._url(env['cases']['visa'], applicant['id'])


def values(env, url):
    response = env['client'].get(url)
    assert response.status_code == 200
    return Form(response.text).data


def test_register_profile_save_resume_old_revision_and_person_separation(env, subject):
    applicant, url = subject
    app = application(env, applicant)
    register = env['client'].get(env['url']+'/applications')
    assert url in register.text
    assert url in env['client'].get(env['url']+f"/applications?application_id={app['id']}").text
    form = values(env, url)
    assert form['_kg_history'] == '0' and not form.get('purpose')
    form.update(values_from_request(request()))
    response = env['client'].post(url, data=form, follow_redirects=False)
    assert response.status_code == 303
    first = read(env, applicant)['saved']
    page = env['client'].get(response.headers['location'])
    assert f'заявитель №{applicant["id"]}' in page.text
    assert 'Плательщик и заявитель могут быть разными людьми' in page.text
    assert 'Анкета общая для визовых услуг' not in page.text
    assert page.headers['cache-control'] == 'no-store' and page.headers['referrer-policy'] == 'no-referrer'
    updated = values(env, url); updated['purpose'] = 'work_hire'
    assert env['client'].post(url, data=updated).status_code == 200
    assert read(env, applicant)['saved']['revision'] == 2
    old = env['client'].get(url+f'?qualification_id={first["qualification_id"]}')
    assert 'Предыдущая версия доступна для просмотра' in old.text
    assert not any(tag == 'button' and a.get('type') == 'submit' for tag,a in Form(old.text).nodes)
    child = person(env, 'child', role='child')
    child_values = values(env, ui._url(env['cases']['visa'], child['id']))
    assert not child_values.get('purpose') and child_values['_kg_revision'] == '0'
    assert read(env, child)['saved'] is None


def test_cross_person_case_session_and_legacy_signatures_rejected(env, subject):
    applicant, url = subject
    form = values(env, url)
    child = person(env, 'child', role='child')
    assert env['client'].post(ui._url(env['cases']['visa'], child['id']), data=form).status_code == 403
    foreign = ui._url(env['cases']['other'], applicant['id'])
    assert env['client'].get(foreign).status_code == 404
    assert env['client'].post(foreign, data=form).status_code == 403
    other = _login('admin')
    try: assert other.post(url, data=form).status_code == 403
    finally: other.close()
    legacy = values(env, env['url'])
    assert env['client'].post(url, data=legacy).status_code == 403
    assert env['client'].post(env['url'], data=form).status_code == 403
    assert env['client'].post(url, data={**form, '_kg_history': '1'}).status_code == 403
    assert read(env, applicant)['current_revision'] == 0


def test_exact_retry_stale_forms_and_validation_preserve_values(env, subject):
    applicant, url = subject
    first = values(env, url); stale = values(env, url)
    assert env['client'].post(url, data=first).status_code == 200
    assert env['client'].post(url, data=first).status_code == 200
    assert read(env, applicant)['current_revision'] == 1
    stale['purpose'] = 'tourism'
    response = env['client'].post(url, data=stale)
    assert response.status_code == 409 and Form(response.text).data['purpose'] == 'tourism'
    invalid = values(env, url); invalid.update(passport_expiry_state='value', passport_expiry='not-a-date')
    response = env['client'].post(url, data=invalid)
    assert response.status_code == 422 and Form(response.text).data['passport_expiry'] == 'not-a-date'
    assert read(env, applicant)['current_revision'] == 1


def test_uncertain_commit_preserves_exact_signed_request_even_if_reread_fails(env, subject, monkeypatch):
    applicant, url = subject
    form = values(env, url); form.update(values_from_request(request()))
    actual = ui.save_applicant_profile
    actual_read = ui.read_applicant_profile
    async def unavailable(*args, **kwargs): raise EntryStorageUnavailable('unavailable')
    async def uncertain(*args, **kwargs):
        await actual(*args, **kwargs)
        monkeypatch.setattr(ui, 'read_applicant_profile', unavailable)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    monkeypatch.setattr(ui, 'save_applicant_profile', uncertain)
    response = env['client'].post(url, data=form)
    assert response.status_code == 503
    retry = Form(response.text).data
    assert all(retry[k] == form[k] for k in ui.interview.META + tuple(ui.interview.SECURITY))
    assert retry['purpose'] == form['purpose'] and read(env, applicant)['current_revision'] == 1
    monkeypatch.setattr(ui, 'save_applicant_profile', actual)
    monkeypatch.setattr(ui, 'read_applicant_profile', actual_read)
    assert env['client'].post(url, data=retry).status_code == 200
    assert read(env, applicant)['current_revision'] == 1


@pytest.mark.parametrize('login', [None, 'medina', 'ademi'])
def test_auth_before_storage(env, subject, monkeypatch, login):
    _, url = subject
    def forbidden(): raise AssertionError('storage access')
    monkeypatch.setattr(ar, '_domain_sessionmaker', forbidden)
    client = _login(login) if login else TestClient(main.app, base_url='https://testserver')
    try:
        assert client.get(url).status_code == (401 if login is None else 403)
        assert client.post(url, data={}).status_code == (401 if login is None else 403)
    finally: client.close()


def test_flags_limits_and_read_only(env, subject, monkeypatch):
    _, url = subject; form = values(env, url)
    monkeypatch.setattr(ar.settings, 'admin_kg_entry_enabled', False)
    assert env['client'].get(url).status_code == 404
    assert env['client'].post(url, data=form).status_code == 404
    monkeypatch.setattr(ar.settings, 'admin_kg_entry_enabled', True)
    monkeypatch.setattr(ar.settings, 'service_cases_enabled', False)
    assert env['client'].get(url).status_code == 200
    assert env['client'].post(url, data=form).status_code == 403
    monkeypatch.setattr(ar.settings, 'service_cases_enabled', True)
    assert env['client'].post(url, json=form).status_code == 415
    assert env['client'].post(url, content='x'*65537, headers={'content-type':'application/x-www-form-urlencoded'}).status_code == 413
    assert env['client'].post(url, data={**form, 'applicant_id':'3'}).status_code == 422
    for query in ('?qualification_id=1&qualification_id=2', '?qualification_id=-1', '?other=1'):
        assert env['client'].get(url+query).status_code == 422
    queries = []
    def capture(conn,cursor,sql,params,ctx,many): queries.append(sql)
    event.listen(env['engine'].sync_engine, 'before_cursor_execute', capture)
    try: assert env['client'].get(url).status_code == 200
    finally: event.remove(env['engine'].sync_engine, 'before_cursor_execute', capture)
    assert not any(q.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for q in queries)


def test_corrupt_history_refuses_forms(env, subject):
    applicant, url = subject
    env['client'].post(url, data=values(env, url))
    async def corrupt():
        async with env['engine'].begin() as conn:
            await conn.execute(text("UPDATE entry_applicant_profiles SET snapshot_hash=:hash"), {'hash':'0'*64})
    asyncio.run(corrupt())
    page = env['client'].get(url)
    assert page.status_code == 503 and not Form(page.text).data
