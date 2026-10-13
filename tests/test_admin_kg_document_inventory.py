import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event,text

import app.admin.router as ar
import app.admin.kg_document_inventory as ui
import app.main as main
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form,env
from tests.test_entry_applications import person,application,enforce_sqlite_foreign_keys
from tests.test_entry_documents import read
from tests.test_admin_workday import _login


@pytest.fixture
def subject(env):
    app=application(env,person(env))
    return app,f'/admin/case/{env["cases"]["visa"]}/kg-entry/applications/{app["id"]}/documents'


def form(env,url,action,item=None):
    response=env['client'].get(url,params={'item':item} if item else {})
    assert response.status_code==200
    values=Form(response.text,'kg-di-'+action).data
    assert values
    return {**values,'confirmed':'yes'}


def initialize(env,url):
    values=form(env,url,'initialize');values['product']='TS'
    response=env['client'].post(url,data=values)
    assert response.status_code==200
    return response


def receive(env,url):
    values=form(env,url,'receive','d03_0')
    values.update(fingerprint='a'*64,on='2026-09-01',source='client_copy')
    return values


def test_native_inventory_receive_review_passport_history_navigation(env,subject):
    app,url=subject
    register=env['client'].get(f'{env["url"]}/applications?application_id={app["id"]}')
    assert url in register.text
    initialize(env,url)
    response=env['client'].post(url,data=receive(env,url))
    assert response.status_code==200 and 'Получен, ожидает проверки' in response.text
    values=form(env,url,'review','d03_0');values.update(on='2026-09-02',outcome='checked',reason='')
    response=env['client'].post(url,data=values)
    assert response.status_code==200 and 'Обязательных проверено: 1' in response.text
    checked=read(env,app)['current_revision']
    values=form(env,url,'passport_change');values.update(on='2026-09-03',reason='replacement')
    response=env['client'].post(url,data=values)
    assert 'Нужна повторная проверка' in response.text
    old=env['client'].get(url,params={'revision':checked})
    assert 'id="kg-di-historical"' in old.text and 'Обязательных проверено: 1' in old.text
    assert not Form(old.text,'kg-di-receive').data
    assert old.headers['cache-control']=='no-store' and old.headers['referrer-policy']=='no-referrer'


def test_stale_tampered_cross_session_application_and_scope(env,subject):
    app,url=subject;initialize(env,url);values=receive(env,url)
    assert env['client'].post(url,data={**values,'_di_item':'d01_0'}).status_code==403
    other=_login('admin')
    try:assert other.post(url,data=values).status_code==403
    finally:other.close()
    foreign=url.replace('/case/'+str(env['cases']['visa'])+'/','/case/'+str(env['cases']['other'])+'/')
    assert env['client'].get(foreign).status_code==404
    assert env['client'].post(foreign,data=values).status_code==403
    app2=application(env,person(env,'second'),'second')
    cross=url.replace('/applications/'+str(app['id'])+'/','/applications/'+str(app2['id'])+'/')
    assert env['client'].post(cross,data=values).status_code==403
    stale=receive(env,url)
    assert env['client'].post(url,data=values).status_code==200
    assert env['client'].post(url,data=values).status_code==200
    assert env['client'].post(url,data={**stale,'fingerprint':'b'*64}).status_code==409
    assert read(env,app)['current_revision']==2


def test_lost_commit_ack_retries_exact_form_once(env,subject,monkeypatch):
    app,url=subject;initialize(env,url);values=receive(env,url)
    actual=ui.service.record_document_operation
    async def uncertain(*args,**kwargs):
        await actual(*args,**kwargs)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    monkeypatch.setattr(ui.service,'record_document_operation',uncertain)
    response=env['client'].post(url,data=values)
    assert response.status_code==503
    retry=Form(response.text,'kg-di-retry').data
    assert retry==values and read(env,app)['current_revision']==2
    monkeypatch.setattr(ui.service,'record_document_operation',actual)
    assert env['client'].post(url,data=retry).status_code==200
    assert read(env,app)['current_revision']==2


def test_validation_preserves_passport_reason_and_request_key(env,subject):
    app,url=subject;initialize(env,url)
    values=form(env,url,'passport_change');values.update(on='2999-01-01',reason='expiry')
    response=env['client'].post(url,data=values)
    assert response.status_code==422
    assert '<option value="expiry" selected>' in response.text
    assert Form(response.text,'kg-di-passport_change').data['_di_key']==values['_di_key']
    assert read(env,app)['current_revision']==1


def test_get_is_read_only_and_corruption_disables_forms(env,subject):
    app,url=subject;initialize(env,url);sql=[]
    def capture(conn,cursor,statement,params,ctx,many):sql.append(statement)
    event.listen(env['engine'].sync_engine,'before_cursor_execute',capture)
    try:assert env['client'].get(url).status_code==200
    finally:event.remove(env['engine'].sync_engine,'before_cursor_execute',capture)
    assert not any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','REPLACE')) for s in sql)
    async def corrupt():
        async with env['engine'].begin() as conn:await conn.execute(text('UPDATE entry_document_revisions SET snapshot_hash=:hash'),{'hash':'0'*64})
    asyncio.run(corrupt())
    response=env['client'].get(url)
    assert response.status_code==503 and not Form(response.text,'kg-di-receive').data
    assert 'id="kg-di-summary"' not in response.text


@pytest.mark.parametrize('login',[None,'medina','ademi'])
def test_access_before_domain(env,subject,monkeypatch,login):
    app,url=subject
    def forbidden():raise AssertionError('storage accessed')
    monkeypatch.setattr(ar,'_domain_sessionmaker',forbidden)
    client=_login(login) if login else TestClient(main.app,base_url='https://testserver')
    try:
        assert client.get(url).status_code==(401 if login is None else 403)
        assert client.post(url,data={}).status_code==(401 if login is None else 403)
    finally:client.close()


@pytest.mark.parametrize('flag',['admin_kg_entry_enabled','admin_workday_enabled'])
def test_off_gate(env,subject,monkeypatch,flag):
    app,url=subject;monkeypatch.setattr(ar.settings,flag,False)
    assert env['client'].get(url).status_code==404 and env['client'].post(url,data={}).status_code==404


def test_write_off_and_invalid_forms(env,subject,monkeypatch):
    app,url=subject;initialize(env,url);values=receive(env,url)
    assert env['client'].post(url,json=values).status_code==415
    assert env['client'].post(url,data={**values,'passport':'private'}).status_code==422
    assert env['client'].post(url,data={**values,'fingerprint':'<script>'}).status_code==422
    assert env['client'].post(url,content='a'*8193,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(url,content='a=1&a=2',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422
    assert env['client'].get(url+'?item=d03_0&item=d01_0').status_code==422
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    response=env['client'].get(url)
    assert response.status_code==200 and 'Запись отключена' in response.text
    assert env['client'].post(url,data=values).status_code==403
    assert read(env,app)['current_revision']==1
