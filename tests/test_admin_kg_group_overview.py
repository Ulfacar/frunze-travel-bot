"""Read-only native overview, same existing gates, real synthetic domain data."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import app.admin.kg_applications as ui
import app.admin.router as ar
import app.main as main
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_admin_workday import _login
from tests.test_entry_applications import application, counts, person
from tests.test_entry_group_overview import group


def url(env, case='visa'):
    return f"/admin/case/{env['cases'][case]}/kg-entry/applications/overview"


def test_navigation_all_totals_filter_links_and_read_only_even_write_off(env, monkeypatch):
    first, second, missing, approved, old, retry, registration, independent = group(env)
    before = counts(env)
    monkeypatch.setattr(ar.settings, 'service_cases_enabled', False)
    queries = []
    def capture(conn, cursor, sql, params, ctx, many): queries.append(sql)
    event.listen(env['engine'].sync_engine, 'before_cursor_execute', capture)
    try: response = env['client'].get(url(env), params={'selection': 'draft'})
    finally: event.remove(env['engine'].sync_engine, 'before_cursor_execute', capture)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store' and response.headers['referrer-policy'] == 'no-referrer'
    assert 'Заявителей: 3' in response.text and 'текущих заявок: 4' in response.text and 'прежних попыток: 1' in response.text
    assert f'data-applicant="{second["id"]}"' in response.text and f'data-applicant="{first["id"]}"' not in response.text
    for row in (retry, registration, independent): assert f'data-application="{row["id"]}"' in response.text
    assert 'Одобрение не подтверждает' in response.text and 'всю услугу' in response.text
    # The shared shell retains its existing logout POST; this view has only a
    # GET filter, no application mutation forms or signed mutation envelope.
    assert '<form method="get"' in response.text and '_ea_signature' not in response.text and counts(env) == before
    assert not any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for sql in queries)
    assert url(env) in env['client'].get(url(env).removesuffix('/overview')).text


def test_empty_and_no_matching_filter_are_distinct(env):
    response = env['client'].get(url(env))
    assert 'Заявители ещё не добавлены' in response.text
    p = person(env); application(env, p)
    response = env['client'].get(url(env), params={'selection': 'attention'})
    assert response.status_code == 200 and 'Есть неподанные заявки' in response.text
    assert 'По выбранному фильтру заявителей нет' in response.text and '0–0 из 0' in response.text


@pytest.mark.parametrize('login', [None, 'medina', 'ademi'])
def test_access_before_domain(env, monkeypatch, login):
    def forbidden(): raise AssertionError('domain accessed')
    monkeypatch.setattr(ar, '_domain_sessionmaker', forbidden)
    client = _login(login) if login else TestClient(main.app, base_url='https://testserver')
    try: assert client.get(url(env)).status_code == (401 if login is None else 403)
    finally: client.close()


@pytest.mark.parametrize('flag', ['admin_kg_entry_enabled', 'admin_workday_enabled'])
def test_off_before_domain(env, monkeypatch, flag):
    monkeypatch.setattr(ar.settings, flag, False)
    def forbidden(): raise AssertionError('domain accessed')
    monkeypatch.setattr(ar, '_domain_sessionmaker', forbidden)
    assert env['client'].get(url(env)).status_code == 404


@pytest.mark.parametrize('params', [{'selection': '<script>'}, {'selection': 'x' * 100}, {'page': 0}, {'page': 100001}])
def test_bad_filter_and_page_rejected(env, params):
    assert env['client'].get(url(env), params=params).status_code == 422


def test_post_not_supported_and_other_direction_denied(env):
    assert env['client'].post(url(env), data={}).status_code == 405
    assert env['client'].get(url(env, 'tours')).status_code == 404
    assert env['client'].get('/admin/case/2147483647/kg-entry/applications/overview').status_code == 404


@pytest.mark.parametrize('kind', ['group_overview_too_large', 'application_integrity_failed', 'storage'])
def test_error_has_no_partial_or_success_summary_and_no_exception_details(env, monkeypatch, kind):
    group(env)
    async def fail(*args, **kwargs):
        if kind == 'storage': raise RuntimeError('synthetic internal detail')
        raise EntryStorageInvalid(kind)
    monkeypatch.setattr(ui.groups, 'read_group_overview', fail)
    response = env['client'].get(url(env))
    assert response.status_code == 503 and 'Сводка недоступна' in response.text
    assert 'id="kg-group-summary"' not in response.text and 'synthetic internal detail' not in response.text
    assert response.headers['cache-control'] == 'no-store' and 'Открыть реестр заявок' in response.text


def test_filtered_pagination_keeps_filter_and_whole_case_counts(env):
    for i in range(21): person(env, f'p{i}')
    response = env['client'].get(url(env), params={'selection': 'without_applications'})
    assert 'selection=without_applications&amp;page=2' in response.text and '1–20 из 21' in response.text
    response = env['client'].get(url(env), params={'selection': 'without_applications', 'page': 2})
    assert '21–21 из 21' in response.text and 'Заявителей: 21' in response.text
