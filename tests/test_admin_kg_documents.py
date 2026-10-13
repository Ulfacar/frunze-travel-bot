import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import app.admin.kg_documents as ui
import app.admin.router as ar
import app.main as main
from app.knowledge.document_checklist import DocumentChecklistError
from tests.test_admin_kg_entry import Form,env
from tests.test_admin_workday import _login

URL='/admin/kg-entry/documents'


def form(env,product='TS'):
    response=env['client'].get(URL,params={'product':product})
    assert response.status_code==200
    return Form(response.text,'kg-doc-check').data


def test_native_form_sources_status_retention_and_no_domain_writes(env,monkeypatch):
    queries=[]
    def capture(conn,cursor,sql,params,ctx,many):queries.append(sql)
    def forbidden():raise AssertionError('domain called')
    monkeypatch.setattr(ar,'_domain_sessionmaker',forbidden)
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    event.listen(env['engine'].sync_engine,'before_cursor_execute',capture)
    try:
        values=form(env);response=env['client'].post(URL,data=values)
        assert response.status_code==200 and 'В сценарии остались вопросы' in response.text
        values.update(current_version='true',state_d02_0='received',applies_d08_0='true')
        response=env['client'].post(URL,data=values)
        assert response.status_code==200 and 'Нужна проверка' in response.text
        restored=Form(response.text,'kg-doc-check').data
        assert restored['state_d02_0']=='received' and restored['applies_d08_0']=='true'
        assert 'Комплект не принят. Подача не разрешена.' in response.text
        assert 'Полнота комплекта не подтверждается' in response.text
        assert 'TR — транзитная' in response.text and 'согласие на открытие специального' in response.text
        assert response.headers['cache-control']=='no-store' and response.headers['referrer-policy']=='no-referrer'
        assert not queries
    finally:event.remove(env['engine'].sync_engine,'before_cursor_execute',capture)


def test_navigation_labels_no_upload_and_switch_resets(env):
    assert URL in env['client'].get(env['url']).text
    assert URL in env['client'].get('/admin/kg-entry/processes').text
    parsed=Form(env['client'].get(URL).text,'kg-doc-check')
    labels={a['for'] for tag,a in parsed.nodes if tag=='label'}
    assert all(a['id'] in labels for tag,a in parsed.nodes if tag=='select')
    assert not any(tag=='input' and a.get('type')!='hidden' for tag,a in parsed.nodes)
    assert all(v=='unknown' for k,v in form(env,'REG').items() if k.startswith('state_'))


@pytest.mark.parametrize('login',[None,'medina','ademi'])
def test_access_before_catalog(env,monkeypatch,login):
    def forbidden():raise AssertionError('catalog read')
    monkeypatch.setattr(ui,'load_document_catalog',forbidden)
    client=_login(login) if login else TestClient(main.app,base_url='https://testserver')
    try:
        assert client.get(URL).status_code==(401 if login is None else 403)
        assert client.post(URL,data={}).status_code==(401 if login is None else 403)
    finally:client.close()


@pytest.mark.parametrize('flag',['admin_kg_entry_enabled','admin_workday_enabled'])
def test_off_before_source(env,monkeypatch,flag):
    monkeypatch.setattr(ar.settings,flag,False)
    def forbidden():raise AssertionError('catalog read')
    monkeypatch.setattr(ui,'load_document_catalog',forbidden)
    assert env['client'].get(URL).status_code==404
    assert env['client'].post(URL,data={}).status_code==404


def test_csrf_session_and_stale_version(env):
    values=form(env);other=_login('admin')
    try:assert other.post(URL,data=values).status_code==403
    finally:other.close()
    assert env['client'].post(URL,data={**values,'csrf':'bad'}).status_code==403
    response=env['client'].post(URL,data={**values,'catalog_digest':'0'*64})
    assert response.status_code==409 and 'id="kg-doc-result"' not in response.text


@pytest.mark.parametrize('changes',[{'passport':'synthetic'},{'package_accepted':'true'},
    {'state_d01_0':'<script>'},{'state_d05_0':'checked'},{'applies_d01_0':'false'},
    {'applies_d08_0':'1'},{'current_version':'1'},{'product':'TR'}])
def test_invalid_answers_no_echo_or_result(env,changes):
    response=env['client'].post(URL,data={**form(env),**changes})
    assert response.status_code==422 and '<script>' not in response.text
    assert 'id="kg-doc-result"' not in response.text


def test_query_and_wire_limits(env):
    for query in ('product=TR','product=TS&product=B','passport=test'):
        assert env['client'].get(URL+'?'+query).status_code==422
    values=form(env)
    assert env['client'].post(URL,json=values).status_code==415
    assert env['client'].post(URL,content='x'*16385,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(URL,content='product=TS&product=B',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422


@pytest.mark.parametrize('code',['document_catalog_invalid','document_catalog_unavailable'])
def test_unavailable_catalog_has_no_result(env,monkeypatch,code):
    values=form(env)
    def fail():raise DocumentChecklistError(code)
    monkeypatch.setattr(ui,'load_document_catalog',fail)
    for response in (env['client'].get(URL),env['client'].post(URL,data=values)):
        assert response.status_code==503 and 'id="kg-doc-result"' not in response.text
