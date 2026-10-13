import asyncio
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event,text

import app.admin.router as ar
import app.admin.kg_document_packages as ui
import app.main as main
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form,env
from tests.test_entry_applications import person,application,enforce_sqlite_foreign_keys
from tests.test_entry_document_packages import read,complete
from tests.test_admin_workday import _login


@pytest.fixture
def subject(env):
    app=application(env,person(env))
    return app,f'/admin/case/{env["cases"]["visa"]}/kg-entry/applications/{app["id"]}/document-package'


def form(env,url,action,item=None):
    response=env['client'].get(url,params={'item':item} if item else {})
    assert response.status_code==200,response.text[:400]
    values=Form(response.text,'kg-dp-'+action).data
    assert values,action
    return {**values,'confirmed':'yes'}


def initialize(env,url):
    values=form(env,url,'initialize');values['product']='TR'
    response=env['client'].post(url,data=values)
    assert response.status_code==200,response.text[:400]
    return response


def receive(env,url):
    values=form(env,url,'receive','t08_02')
    values.update(fingerprint='a'*64,on='2026-09-01',source='client_copy')
    return values


def test_native_full_package_facts_receipt_correction_history_and_navigation(env,subject):
    app,url=subject
    register=env['client'].get(f'{env["url"]}/applications?application_id={app["id"]}')
    assert url in register.text
    initial=initialize(env,url)
    assert 'Приёмка недоступна' in initial.text and not Form(initial.text,'kg-dp-approve').data
    assert 'id="kg-dp-fact-sw2_category"' not in initial.text and 'id="kg-dp-fact-resident_basis"' not in initial.text
    assert 'id="kg-dp-fact-minor"' in initial.text
    assert env['client'].post(url,data=receive(env,url)).status_code==200
    values=form(env,url,'review','t08_02');values.update(on='2026-09-02',outcome='checked',reason='')
    response=env['client'].post(url,data=values)
    assert response.status_code==200 and 'Проверил admin' in response.text
    checked=read(env,app)['current_revision']
    values=form(env,url,'facts');values.update(fact_minor='false')
    response=env['client'].post(url,data=values)
    assert response.status_code==200 and 'Нужна повторная проверка' in response.text
    assert read(env,app)['selected']['snapshot']['facts']['minor'] is False
    old=env['client'].get(url,params={'revision':checked})
    assert old.status_code==200 and 'id="kg-dp-historical"' in old.text
    assert not Form(old.text,'kg-dp-receive').data and not Form(old.text,'kg-dp-facts').data
    assert old.headers['cache-control']=='no-store' and old.headers['referrer-policy']=='no-referrer'
    legacy=env['client'].get(url.replace('/document-package','/documents'))
    assert 'только для просмотра истории' in legacy.text and not Form(legacy.text,'kg-di-initialize').data


def test_policy_gated_native_acceptance_stale_policy_and_revocation(env,subject,monkeypatch):
    monkeypatch.setattr(ar,'_bishkek_today',ui.service.applications._today)
    app,url=subject;initialize(env,url);allowed=complete(env,app)
    monkeypatch.setattr(ar.settings,'kg_document_package_policy',allowed.document())
    values=form(env,url,'approve');values.update(on=ui.service.applications._today().isoformat(),reference='SYNTHETIC-REVIEW',proof='a'*64)
    changed=allowed.document();changed['proof']='b'*64
    monkeypatch.setattr(ar.settings,'kg_document_package_policy',changed)
    assert env['client'].post(url,data=values).status_code==422
    monkeypatch.setattr(ar.settings,'kg_document_package_policy',allowed.document())
    response=env['client'].post(url,data=values)
    assert response.status_code==200 and 'id="kg-dp-accepted"' in response.text
    revision=read(env,app)['current_revision']
    monkeypatch.setattr(ar.settings,'kg_document_package_policy',{})
    assert env['client'].post(url,data=values).status_code==200
    assert read(env,app)['current_revision']==revision
    values=form(env,url,'revoke');values.update(on=ui.service.applications._today().isoformat(),reason='policy_changed')
    assert env['client'].post(url,data=values).status_code==200
    assert read(env,app,policy=allowed)['current_acceptance']['accepted'] is False


def test_invalid_policy_preserves_history_and_disables_acceptance(env,subject,monkeypatch):
    app,url=subject;initialize(env,url)
    monkeypatch.setattr(ar.settings,'kg_document_package_policy',{'invalid':True})
    response=env['client'].get(url)
    assert response.status_code==200 and 'Настройки политики приёмки некорректны' in response.text
    assert not Form(response.text,'kg-dp-approve').data
    assert env['client'].post(url,data=receive(env,url)).status_code==200


def test_journal_limit_keeps_only_meaningful_withdrawal_forms(env,subject,monkeypatch):
    from tests.test_entry_document_packages import approve
    app,url=subject; initialize(env,url); allowed=complete(env,app); approve(env,app,allowed)
    monkeypatch.setattr(ui.service,'MAX_REVISIONS',read(env,app)['current_revision']+2)
    response=env['client'].get(url)
    assert Form(response.text,'kg-dp-revoke').data and Form(response.text,'kg-dp-consent').data
    assert not Form(response.text,'kg-dp-receive').data and not Form(response.text,'kg-dp-approve').data
    assert 'value="granted"' not in response.text


def test_native_alternative_selection_and_validation(env,subject):
    app,url=subject;initialize(env,url)
    values=form(env,url,'receive','t08_03');values.update(fingerprint='a'*64,on='2026-09-01',source='client_copy')
    assert env['client'].post(url,data=values).status_code==200
    values=form(env,url,'review','t08_03');values.update(on='2026-09-02',outcome='checked',reason='',alternative='')
    assert env['client'].post(url,data=values).status_code==422
    values['alternative']='ticket'
    response=env['client'].post(url,data=values)
    assert response.status_code==200 and 'Выбранное подтверждение: Билет' in response.text
    assert read(env,app)['selected']['snapshot']['items']['t08_03']['alternative']=='ticket'


def test_closed_application_exposes_withdrawal_forms_only(env,subject,monkeypatch):
    from tests.test_entry_document_packages import approve
    from tests.test_entry_applications import record
    app,url=subject;initialize(env,url);allowed=complete(env,app);approve(env,app,allowed)
    record(env,app);record(env,app,'approved',status='approved',occurred_on='2026-09-02')
    response=env['client'].get(url)
    assert response.status_code==200 and Form(response.text,'kg-dp-revoke').data
    assert not Form(response.text,'kg-dp-receive').data and not Form(response.text,'kg-dp-approve').data
    values=form(env,url,'consent');values.update(status='granted',on='2026-09-04',reference='SYNTHETIC-CONSENT',proof='a'*64)
    assert env['client'].post(url,data=values).status_code==422
    values['status']='withdrawn'
    assert env['client'].post(url,data=values).status_code==200
    assert read(env,app,policy=allowed)['current_acceptance']['accepted'] is False


def test_stale_tampered_cross_session_application_and_scope(env,subject):
    app,url=subject;initialize(env,url);values=receive(env,url)
    for field,value in (('_dp_item','g01_01'),('_dp_state','0'*64),('_dp_catalog','0'*64),('_dp_policy','0'*64)):
        assert env['client'].post(url,data={**values,field:value}).status_code==403
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


@pytest.mark.parametrize('read_fails',[False,True])
def test_lost_ack_preserves_exact_retry_even_when_reread_fails(env,subject,monkeypatch,read_fails):
    app,url=subject;initialize(env,url);values=receive(env,url)
    actual=ui.service.record_package_operation;actual_read=ui.service.read_document_package
    async def uncertain(*args,**kwargs):
        await actual(*args,**kwargs)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    async def unavailable(*args,**kwargs): raise EntryStorageUnavailable('read unavailable')
    monkeypatch.setattr(ui.service,'record_package_operation',uncertain)
    if read_fails:monkeypatch.setattr(ui.service,'read_document_package',unavailable)
    response=env['client'].post(url,data=values)
    assert response.status_code==503
    retry=Form(response.text,'kg-dp-retry').data
    assert retry==values
    monkeypatch.setattr(ui.service,'record_package_operation',actual)
    monkeypatch.setattr(ui.service,'read_document_package',actual_read)
    assert read(env,app)['current_revision']==2
    assert env['client'].post(url,data=retry).status_code==200
    assert read(env,app)['current_revision']==2


def test_get_is_read_only_corruption_and_invalid_forms(env,subject):
    app,url=subject;initialize(env,url);sql=[]
    def capture(conn,cursor,statement,params,ctx,many):sql.append(statement)
    event.listen(env['engine'].sync_engine,'before_cursor_execute',capture)
    try:assert env['client'].get(url).status_code==200
    finally:event.remove(env['engine'].sync_engine,'before_cursor_execute',capture)
    assert not any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','REPLACE')) for s in sql)
    values=receive(env,url)
    assert env['client'].post(url,json=values).status_code==415
    assert env['client'].post(url,data={**values,'passport':'private'}).status_code==422
    assert env['client'].post(url,data={**values,'fingerprint':'<script>'}).status_code==422
    assert env['client'].post(url,content='a'*16385,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(url,content='a=1&a=2',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422
    assert env['client'].get(url+'?item=g01_01&item=g02_01').status_code==422
    values=form(env,url,'facts')
    assert env['client'].post(url,data={**values,'fact_minor':'0'}).status_code==422
    assert env['client'].post(url,data={**values,'fact_invented':'false'}).status_code==422
    async def corrupt():
        async with env['engine'].begin() as conn:await conn.execute(text('UPDATE entry_document_package_events SET snapshot_hash=:hash'),{'hash':'0'*64})
    asyncio.run(corrupt())
    response=env['client'].get(url)
    assert response.status_code==503 and not Form(response.text,'kg-dp-receive').data
    assert 'id="kg-dp-summary"' not in response.text


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


def test_write_off_preserves_read_and_rejects_post(env,subject,monkeypatch):
    app,url=subject;initialize(env,url);values=receive(env,url)
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    response=env['client'].get(url)
    assert response.status_code==200 and 'Запись отключена' in response.text
    assert env['client'].post(url,data=values).status_code==403
    assert read(env,app)['current_revision']==1
