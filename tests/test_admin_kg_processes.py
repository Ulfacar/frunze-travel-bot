"""Native preview boundaries and real full-admin gates; no domain access."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import app.admin.kg_processes as ui
import app.admin.router as ar
import app.main as main
from app.knowledge.process_preview import ProcessPreviewError
from tests.test_admin_kg_entry import Form, env
from tests.test_admin_workday import _login

URL='/admin/kg-entry/processes'


def form(env,stage='V14',process='visa'):
    response=env['client'].get(URL,params={'process':process,'stage':stage})
    assert response.status_code==200
    return Form(response.text,'kg-process-check').data


def complete(env):
    values=form(env)
    values.update(target='V15',fact_consent_confirmed='true',fact_documents_accepted='true',
                  fact_documents_current='true',fact_portal_draft_created='true')
    return values


def test_preview_native_missing_failed_met_no_domain_even_write_off(env,monkeypatch):
    queries=[]
    def capture(conn,cursor,sql,params,ctx,many):queries.append(sql)
    def forbidden():raise AssertionError('domain called for preview')
    monkeypatch.setattr(ar,'_domain_sessionmaker',forbidden)
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    event.listen(env['engine'].sync_engine,'before_cursor_execute',capture)
    try:
        values=form(env)
        response=env['client'].post(URL,data=values)
        assert response.status_code==200 and 'Для проверки не хватает сведений' in response.text
        values.update(target='V15',fact_consent_confirmed='true',fact_documents_accepted='true',
                      fact_documents_current='false',fact_portal_draft_created='true')
        response=env['client'].post(URL,data=values)
        assert response.status_code==200 and 'Условия чернового перехода не выполнены' in response.text
        assert Form(response.text,'kg-process-check').data['fact_documents_current']=='false'
        values['fact_documents_current']='true'
        response=env['client'].post(URL,data=values)
        assert response.status_code==200 and 'Условия чернового перехода выполнены в сценарии' in response.text
        assert 'Выполнение не разрешено' in response.text and 'Текущий этап остаётся V14' in response.text
        assert response.headers['cache-control']=='no-store' and response.headers['referrer-policy']=='no-referrer'
        assert not queries
    finally:event.remove(env['engine'].sync_engine,'before_cursor_execute',capture)


def test_source_flags_exceptions_navigation_and_labels(env):
    assert URL in env['client'].get(env['url']).text
    for process,stage,label in [('visa','V11','Параллельный'),('visa','X01','новой связанной'),
                                ('work','WX2','решения о деньгах'),('regularization','U06','отдельной регистрационной')]:
        response=env['client'].get(URL,params={'process':process,'stage':stage})
        assert response.status_code==200 and label in response.text and 'Источник:' in response.text
        if stage in ('V11','X01','WX2'):assert not Form(response.text,'kg-process-check').data
    response=env['client'].get(URL,params={'process':'visa','stage':'V14'})
    parsed=Form(response.text,'kg-process-check')
    labels={a['for'] for tag,a in parsed.nodes if tag=='label'}
    controls=[a for tag,a in parsed.nodes if tag=='select']
    assert all(a['id'] in labels for a in controls)


@pytest.mark.parametrize('login',[None,'medina','ademi'])
def test_access_before_catalog(env,monkeypatch,login):
    def forbidden():raise AssertionError('catalog read')
    monkeypatch.setattr(ui,'load_process_catalog',forbidden)
    client=_login(login) if login else TestClient(main.app,base_url='https://testserver')
    try:
        assert client.get(URL).status_code==(401 if login is None else 403)
        assert client.post(URL,data={}).status_code==(401 if login is None else 403)
    finally:client.close()


@pytest.mark.parametrize('flag',['admin_kg_entry_enabled','admin_workday_enabled'])
def test_off_before_catalog(env,monkeypatch,flag):
    monkeypatch.setattr(ar.settings,flag,False)
    def forbidden():raise AssertionError('catalog read')
    monkeypatch.setattr(ui,'load_process_catalog',forbidden)
    assert env['client'].get(URL).status_code==404 and env['client'].post(URL,data={}).status_code==404


def test_csrf_cross_session_and_stale_catalog(env):
    values=complete(env)
    other=_login('admin')
    try:assert other.post(URL,data=values).status_code==403
    finally:other.close()
    assert env['client'].post(URL,data={**values,'csrf':'bad'}).status_code==403
    response=env['client'].post(URL,data={**values,'catalog_digest':'0'*64})
    assert response.status_code==409 and 'Версия черновика изменилась' in response.text
    assert 'id="kg-process-result"' not in response.text


@pytest.mark.parametrize('changes',[{'fact_documents_current':'1'},{'fact_documents_current':'<script>'},
                                   {'publication_approved':'true'},{'passport':'synthetic'},{'target':'W11'}])
def test_untrusted_fields_refused_without_echo_or_result(env,changes):
    response=env['client'].post(URL,data={**complete(env),**changes})
    assert response.status_code==422 and '<script>' not in response.text
    assert 'id="kg-process-result"' not in response.text


@pytest.mark.parametrize('query',['process=unknown','process=visa&stage=W11','process=visa&process=work','extra=true'])
def test_invalid_selection(env,query):
    assert env['client'].get(URL+'?'+query).status_code==422


def test_wire_limits_duplicates_and_content_type(env):
    values=complete(env)
    assert env['client'].post(URL,json=values).status_code==415
    assert env['client'].post(URL,content='x'*8193,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(URL,content='process=visa&process=work',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422


@pytest.mark.parametrize('code',['process_catalog_integrity_failed','process_catalog_unavailable'])
def test_unavailable_source_fail_closed(env,monkeypatch,code):
    values=complete(env)
    def fail():raise ProcessPreviewError(code)
    monkeypatch.setattr(ui,'load_process_catalog',fail)
    for response in (env['client'].get(URL),env['client'].post(URL,data=values)):
        assert response.status_code==503 and 'id="kg-process-result"' not in response.text
