"""Real native form submissions into a synthetic application register."""
import asyncio
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

import app.admin.kg_applications as ui
import app.admin.router as ar
import app.main as main
from app.domain import entry_applications as service
from tests.test_admin_kg_entry import ADMIN, Form, env
from tests.test_admin_workday import _login
from tests.test_entry_applications import application, counts, person, read, record


def url(env, case='visa'):
    return f"/admin/case/{env['cases'][case]}/kg-entry/applications"


def form(env, action='applicant', response=None, application_id=None):
    response = response or env['client'].get(url(env), params={'application_id': application_id} if application_id else {})
    assert response.status_code in (200, 409, 422, 503)
    return Form(response.text, f'kg-{action}-form').data


def post(env, values, client=None, case='visa'):
    return (client or env['client']).post(url(env, case), data=values, follow_redirects=False)


def create(env):
    values = form(env); values['role'] = 'child'
    assert post(env, values).status_code == 303
    people = asyncio.run(service.read_application_register(env['engine'], actor=ADMIN, case_id=env['cases']['visa']))['applicants']
    values = form(env, 'application'); values.update(applicant_id=str(people[-1]['id']), procedure='visa')
    response = post(env, values)
    assert response.status_code == 303
    return {'id': int(response.headers['location'].split('application_id=')[1])}


def event_values(env, app, **changes):
    values = form(env, 'event', application_id=app['id'])
    values.update(status='submitted', occurred_on='2026-09-01', source='portal', reference='AB12CD34', confirmed='yes')
    values.update(changes)
    return values


def test_get_navigation_labels_no_sql_write_and_new_people_not_inferred(env):
    queries = []
    def capture(conn, cursor, sql, params, ctx, many): queries.append(sql)
    event.listen(env['engine'].sync_engine, 'before_cursor_execute', capture)
    try: page = env['client'].get(url(env))
    finally: event.remove(env['engine'].sync_engine, 'before_cursor_execute', capture)
    assert page.status_code == 200 and 'Заявители ещё не добавлены' in page.text
    assert page.headers['cache-control'] == 'no-store' and page.headers['referrer-policy'] == 'no-referrer'
    assert not any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for sql in queries)
    assert url(env) in env['client'].get(env['url']).text and counts(env) == (0, 0, 0, 0, 0)
    for action in ('applicant', 'application'):
        parsed = Form(page.text, f'kg-{action}-form')
        controls = [a for tag, a in parsed.nodes if tag in ('input', 'select') and a.get('type') != 'hidden']
        labels = {a['for'] for tag, a in parsed.nodes if tag == 'label' and 'for' in a}
        assert all(a.get('id') in labels for a in controls)


def test_native_cycle_return_resubmit_refusal_retry_and_pinned_audit(env):
    app = create(env)
    submitted = event_values(env, app)
    assert post(env, submitted).status_code == 303
    assert post(env, submitted).status_code == 303 and counts(env) == (1, 1, 2, 1, 0)
    for status, day in [('revision_requested', '02'), ('submitted', '03'), ('refused', '04')]:
        assert post(env, event_values(env, app, status=status, occurred_on=f'2026-09-{day}')).status_code == 303
    page = env['client'].get(url(env), params={'application_id': app['id']})
    assert 'Отказ' in page.text and 'AB12CD34' in page.text
    assert not Form(page.text, 'kg-event-form').data
    old_events = read(env, app)['events']
    values = form(env, 'retry', response=page)
    response = post(env, values)
    assert response.status_code == 303 and post(env, values).headers['location'] == response.headers['location']
    next_page = env['client'].get(response.headers['location'])
    assert 'попытка 2' in next_page.text and f'Предыдущая попытка №{app["id"]}' in next_page.text
    assert read(env, app)['events'] == old_events and counts(env) == (1, 2, 6, 1, 0)


@pytest.mark.parametrize('changes', [{'occurred_on': '2099-01-01'}, {'status': 'approved'}, {'source': 'client_request'},
                                     {'confirmed': ''}, {'reference': 'BAD'}, {'reference': '<script>'}])
def test_invalid_native_event_retains_nonce_and_facts(env, changes):
    app = create(env); values = event_values(env, app, **changes)
    response = post(env, values)
    assert response.status_code == 422 and counts(env) == (1, 1, 1, 0, 0)
    echoed = form(env, 'event', response=response)
    assert echoed['_ea_key'] == values['_ea_key'] and echoed['reference'] == values['reference']
    assert '<script>' not in response.text


@pytest.mark.parametrize('field', ['_ea_action', '_ea_target', '_ea_revision', '_ea_key', '_ea_csrf', '_ea_signature'])
def test_sealed_form_forgery_is_rejected(env, field):
    values = form(env)
    values[field] = 'application' if field == '_ea_action' else '5' if field in ('_ea_target', '_ea_revision') else 'f' * 48
    response = post(env, values)
    assert response.status_code in (403, 422) and counts(env) == (0, 0, 0, 0, 0)


def test_cross_session_case_form_and_foreign_subject_rejected(env):
    values = form(env)
    assert post(env, values, case='other').status_code == 403
    other_client = _login('admin')
    try: assert post(env, values, client=other_client).status_code == 403
    finally: other_client.close()
    applicant = person(env, case='other')
    values = form(env, 'application'); values.update(applicant_id=str(applicant['id']), procedure='visa')
    assert post(env, values).status_code == 404
    other_app = application(env, applicant, case='other')
    assert env['client'].get(url(env), params={'application_id': other_app['id']}).status_code == 404
    assert env['client'].get(url(env, 'tours')).status_code == 404
    values = form(env); values['passport_number'] = 'private'
    assert post(env, values).status_code == 422


@pytest.mark.parametrize('login', [None, 'medina', 'ademi'])
def test_permissions_precede_domain(env, monkeypatch, login):
    def forbidden(): raise AssertionError('domain accessed')
    monkeypatch.setattr(ar, '_domain_sessionmaker', forbidden)
    client = _login(login) if login else TestClient(main.app, base_url='https://testserver')
    try:
        assert client.get(url(env)).status_code == (401 if login is None else 403)
        assert post(env, {}, client=client).status_code == (401 if login is None else 403)
    finally: client.close()


@pytest.mark.parametrize('flag', ['admin_kg_entry_enabled', 'admin_workday_enabled'])
def test_off_gate_before_storage(env, monkeypatch, flag):
    monkeypatch.setattr(ar.settings, flag, False)
    def forbidden(): raise AssertionError('domain accessed')
    monkeypatch.setattr(ar, '_domain_sessionmaker', forbidden)
    assert env['client'].get(url(env)).status_code == 404 and post(env, {}).status_code == 404


def test_write_off_keeps_read_only(env, monkeypatch):
    values = form(env)
    monkeypatch.setattr(ar.settings, 'service_cases_enabled', False)
    assert env['client'].get(url(env)).status_code == 200 and post(env, values).status_code == 403


def test_stale_form_reference_collision_and_same_key_changed_payload(env):
    app = create(env); values = event_values(env, app)
    assert post(env, values).status_code == 303
    changed = {**values, 'occurred_on': '2026-09-02'}
    assert post(env, changed).status_code == 409
    fresh = event_values(env, app, status='approved', occurred_on='2026-09-02')
    stale = {**fresh, '_ea_key': fresh['_ea_key']}  # signed same base; another valid tab wins
    record(env, app, 'other-tab', status='revision_requested', occurred_on='2026-09-02')
    response = post(env, stale)
    assert response.status_code == 409 and form(env, 'event', response=response)['_ea_key'] == stale['_ea_key']
    second = create(env)
    assert post(env, event_values(env, second)).status_code == 409


def test_lost_commit_echo_and_retry_even_if_register_read_fails(env, monkeypatch):
    app = create(env); values = event_values(env, app)
    original = service.read_application_register
    async def unavailable(*args, **kwargs): raise RuntimeError('synthetic unavailable')
    def lost(session): raise OperationalError('synthetic lost ack', {}, RuntimeError('synthetic'))
    event.listen(Session, 'after_commit', lost)
    monkeypatch.setattr(service, 'read_application_register', unavailable)
    try: response = post(env, values)
    finally: event.remove(Session, 'after_commit', lost)
    assert response.status_code == 503
    echoed = form(env, 'event', response=response)
    assert echoed['_ea_key'] == values['_ea_key'] and echoed['reference'] == 'AB12CD34'
    monkeypatch.setattr(service, 'read_application_register', original)
    assert post(env, echoed).status_code == 303 and counts(env) == (1, 1, 2, 1, 0)


@pytest.mark.parametrize('fault', ['duplicate', 'extra', 'oversize', 'encoding', 'json'])
def test_malformed_wire_no_write(env, fault):
    body = urlencode(form(env)).encode(); headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    if fault == 'duplicate': body += b'&role=child'
    if fault == 'extra': body += b'&name=unexpected'
    if fault == 'oversize': body += b'&x=' + b'x' * 8192
    if fault == 'encoding': body += b'&x=%FF'
    if fault == 'json': headers['Content-Type'] = 'application/json'
    response = env['client'].post(url(env), content=body, headers=headers)
    assert response.status_code in (413, 415, 422) and counts(env) == (0, 0, 0, 0, 0)
