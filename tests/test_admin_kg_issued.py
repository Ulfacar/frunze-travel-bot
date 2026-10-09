import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event,text

import app.admin.kg_issued as ui
import app.admin.router as ar
import app.main as main
from app.domain.entry_issued_rules import CHECKS
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form,env
from tests.test_admin_workday import _login
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_issued import setup,read


@pytest.fixture
def subject(env):
    app=setup(env)
    return app,f'/admin/case/{env["cases"]["visa"]}/kg-entry/applications/{app["id"]}/issued'


def form(env,url,action):
    response=env['client'].get(url)
    assert response.status_code==200
    values=Form(response.text,'kg-is-'+action).data
    assert values
    return {**values,'confirmed':'yes'}


def file(env,url):
    values=form(env,url,'file');values.update(fingerprint='a'*64,passport_fingerprint='b'*64,on='2026-09-03')
    return values


def test_native_full_postissue_flow_history_navigation_and_print_contract(env,subject):
    app,url=subject
    response=env['client'].get(f'{env["url"]}/applications?application_id={app["id"]}')
    assert url in response.text
    response=env['client'].post(url,data=file(env,url))
    assert response.status_code==200
    values=form(env,url,'review');values.update(on='2026-09-04',**{'check_'+key:'true' for key in CHECKS})
    response=env['client'].post(url,data=values)
    assert response.status_code==200 and read(env,app)['selected']['summary']['verification_current']
    for channel in ('messenger','email','crm'):
        values=form(env,url,'delivery');values.update(on='2026-09-05',channel=channel,proof='c'*64,pamphlet='d'*64)
        assert env['client'].post(url,data=values).status_code==200
    assert read(env,app)['selected']['summary']['delivery_complete']
    assert not read(env,app)['selected']['summary']['receipt_recorded']
    values=form(env,url,'receipt');values.update(on='2026-09-06',proof='e'*64,identity_checked='true')
    assert env['client'].post(url,data=values).status_code==200
    values=form(env,url,'travel');values.update(on='2026-09-07',direction='entry',proof='f'*64,source='stamp',passport_fingerprint='b'*64)
    response=env['client'].post(url,data=values)
    assert response.status_code==200 and 'Фактических въездов: 1' in response.text
    old=env['client'].get(url+'?revision=2')
    assert 'id="kg-is-historical"' in old.text and not Form(old.text,'kg-is-file').data
    assert 'Получение клиентом: не подтверждено' in old.text
    assert old.headers['cache-control']=='no-store' and old.headers['referrer-policy']=='no-referrer'


def test_stale_metadata_cross_session_case_application_and_duplicate(env,subject):
    app,url=subject;values=file(env,url)
    assert env['client'].post(url,data={**values,'_is_version':'99'}).status_code==403
    other=_login('admin')
    try:assert other.post(url,data=values).status_code==403
    finally:other.close()
    foreign=url.replace('/case/'+str(env['cases']['visa'])+'/','/case/'+str(env['cases']['other'])+'/')
    assert env['client'].get(foreign).status_code==404
    assert env['client'].post(foreign,data=values).status_code==403
    second=setup(env,'second');cross=url.replace('/applications/'+str(app['id'])+'/','/applications/'+str(second['id'])+'/')
    assert env['client'].post(cross,data=values).status_code==403
    stale=file(env,url)
    assert env['client'].post(url,data=values).status_code==200
    assert env['client'].post(url,data=values).status_code==200
    assert env['client'].post(url,data={**stale,'fingerprint':'c'*64}).status_code==409
    assert read(env,app)['current_revision']==1


def test_lost_commit_ack_has_exact_recovery_request(env,subject,monkeypatch):
    app,url=subject;values=file(env,url);actual=ui.service.record_issued_operation
    async def uncertain(*args,**kwargs):
        await actual(*args,**kwargs)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    monkeypatch.setattr(ui.service,'record_issued_operation',uncertain)
    response=env['client'].post(url,data=values)
    assert response.status_code==503
    retry=Form(response.text,'kg-is-retry').data
    assert retry==values and read(env,app)['current_revision']==1
    assert not Form(response.text,'kg-is-file').data
    monkeypatch.setattr(ui.service,'record_issued_operation',actual)
    assert env['client'].post(url,data=retry).status_code==200 and read(env,app)['current_revision']==1


def test_validation_retains_actual_fact_and_no_false_success(env,subject):
    app,url=subject
    values=form(env,url,'travel');values.update(on='2999-01-01',direction='exit',proof='f'*64,source='official_record',passport_fingerprint='b'*64)
    response=env['client'].post(url,data=values)
    assert response.status_code==422
    assert Form(response.text,'kg-is-travel').data==values
    assert read(env,app)['current_revision']==0
    pending=setup(env,'pending',approve=False)
    pending_url=url.replace('/applications/'+str(app['id'])+'/','/applications/'+str(pending['id'])+'/')
    response=env['client'].get(pending_url)
    assert response.status_code==200 and not Form(response.text,'kg-is-file').data


@pytest.mark.parametrize('login',[None,'medina','ademi'])
def test_auth_before_storage(env,subject,monkeypatch,login):
    _,url=subject
    def forbidden():raise AssertionError('storage access')
    monkeypatch.setattr(ui.entry,'_engine',forbidden)
    client=_login(login) if login else TestClient(main.app,base_url='https://testserver')
    try:
        assert client.get(url).status_code==(401 if login is None else 403)
        assert client.post(url,data={}).status_code==(401 if login is None else 403)
    finally:client.close()


def test_off_write_gate_body_query_limits_and_get_no_writes(env,subject,monkeypatch):
    _,url=subject;values=file(env,url)
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url).status_code==404
    assert env['client'].post(url,data=values).status_code==404
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    assert env['client'].get(url).status_code==200
    assert env['client'].post(url,data=values).status_code==403
    monkeypatch.setattr(ar.settings,'service_cases_enabled',True)
    assert env['client'].post(url,json=values).status_code==415
    assert env['client'].post(url,content='x'*8193,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(url,data={**values,'legal_permission':'true'}).status_code==422
    for query in ('?revision=1&revision=2','?revision=-1','?revision=251','?x=true'):
        assert env['client'].get(url+query).status_code==422
    queries=[]
    def capture(conn,cursor,sql,params,ctx,many):queries.append(sql)
    event.listen(env['engine'].sync_engine,'before_cursor_execute',capture)
    try:assert env['client'].get(url).status_code==200
    finally:event.remove(env['engine'].sync_engine,'before_cursor_execute',capture)
    assert not any(q.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for q in queries)


def test_corrupt_storage_does_not_offer_mutating_forms(env,subject):
    app,url=subject;env['client'].post(url,data=file(env,url))
    async def corrupt():
        async with env['engine'].begin() as conn:await conn.execute(text("UPDATE entry_issued_revisions SET snapshot_hash=:hash"),{'hash':'0'*64})
    asyncio.run(corrupt())
    response=env['client'].get(url)
    assert response.status_code==503 and not Form(response.text,'kg-is-file').data
