import asyncio

import pytest
from fastapi.testclient import TestClient

import app.admin.router as ar
import app.admin.kg_document_quarantine as ui
import app.main as main
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form, env
from tests.test_admin_workday import _login
from tests.test_entry_applications import enforce_sqlite_foreign_keys, person, application
from tests.test_entry_document_packages import setup, read
from tests.test_entry_quarantine import policy
from tests.test_quarantine_multipart import PDF, multipart, FILE


@pytest.fixture
def subject(env,monkeypatch):
    app=setup(env); monkeypatch.setattr(ar.settings,'kg_document_quarantine_policy',policy().document())
    return app,f'{env["url"]}/applications/{app["id"]}/quarantine'


def form(env,url):
    page=env['client'].get(url,params={'item':'t08_02'})
    assert page.status_code==200,page.text[:200]
    values=Form(page.text,'kg-q-upload').data; assert values
    values.pop('file',None)
    return values|{'confirmed':'yes','received_on':'2026-09-03','source':'client_copy'}


def post(env,url,values,*,data=PDF,filename='synthetic.pdf',media_type='application/pdf'):
    return env['client'].post(url,data=values,files={'file':(filename,data,media_type)})


def test_native_upload_receipt_history_and_quarantine_blocks_review(env,subject):
    app,url=subject; values=form(env,url)
    response=post(env,url,values)
    assert response.status_code==200,response.text[:1000]
    assert 'id="kg-q-saved"' in response.text and 'В карантине' in response.text
    assert 'synthetic.pdf' not in response.text and PDF.decode() not in response.text
    assert response.headers['cache-control']=='no-store' and response.headers['referrer-policy']=='no-referrer'
    assert post(env,url,values).status_code==200 and len(read(env,app)['quarantine'])==1
    package=env['client'].get(url.replace('/quarantine','/document-package')+'?item=t08_02')
    assert url in package.text and 'Файл в карантине' in package.text
    assert not Form(package.text,'kg-dp-review').data
    assert env['client'].get(url+'/1').status_code==404


def test_policy_and_access_gates_before_file_parser(env,subject,monkeypatch):
    app,url=subject
    async def forbidden(*args,**kwargs): raise AssertionError('request bytes parsed')
    monkeypatch.setattr(ui,'parse_upload',forbidden)
    for value in ({},{'bad':True},policy(review_due_on='2026-01-02').document(),policy(uploaders=('someone',)).document()):
        monkeypatch.setattr(ar.settings,'kg_document_quarantine_policy',value)
        page=env['client'].get(url)
        assert page.status_code==200 and 'kg-q-disabled' in page.text
        assert post(env,url,{}).status_code==403
    monkeypatch.setattr(ar.settings,'kg_document_quarantine_policy',policy().document())
    for flag in ('admin_kg_entry_enabled','admin_workday_enabled'):
        with monkeypatch.context() as off:
            off.setattr(ar.settings,flag,False)
            assert post(env,url,{}).status_code==404
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    assert post(env,url,{}).status_code==403
    assert read(env,app)['current_revision']==1


@pytest.mark.parametrize('login',[None,'medina','ademi'])
def test_role_gate_before_storage_and_parser(env,subject,monkeypatch,login):
    app,url=subject
    def forbidden(): raise AssertionError('storage accessed')
    monkeypatch.setattr(ar,'_domain_sessionmaker',forbidden)
    client=_login(login) if login else TestClient(main.app,base_url='https://testserver')
    try:
        assert client.get(url).status_code==(401 if login is None else 403)
        assert client.post(url,files={'file':('a.pdf',PDF,'application/pdf')}).status_code==(401 if login is None else 403)
    finally: client.close()


def test_signed_scope_csrf_stale_revision_and_changed_policy(env,subject,monkeypatch):
    app,url=subject; values=form(env,url)
    for field,value in (('_q_item','g02_01'),('_q_revision','0'),('_q_version','10'),('_q_policy','0'*64),('_q_csrf','0'*64)):
        assert post(env,url,values|{field:value}).status_code==403
    other=_login('admin')
    try:
        assert other.post(url,data=values,files={'file':('a.pdf',PDF,'application/pdf')}).status_code==403
    finally: other.close()
    app2=application(env,person(env,'other'),'other')
    foreign=url.replace('/applications/'+str(app['id'])+'/', '/applications/'+str(app2['id'])+'/')
    assert post(env,foreign,values).status_code==403
    changed=policy(proof='f'*64).document();monkeypatch.setattr(ar.settings,'kg_document_quarantine_policy',changed)
    assert post(env,url,values).status_code==422
    monkeypatch.setattr(ar.settings,'kg_document_quarantine_policy',policy().document())
    stale=form(env,url)
    assert post(env,url,values).status_code==200
    assert post(env,url,stale,data=PDF+b'new').status_code==409
    assert len(read(env,app)['quarantine'])==1


@pytest.mark.parametrize('read_failure',[False,True])
def test_lost_ack_preserves_signed_retry_and_pins_same_file(env,subject,monkeypatch,read_failure):
    app,url=subject; values=form(env,url); original=ui.service.record_upload; actual_read=ui.packages.read_document_package
    async def uncertain(*args,**kwargs):
        await original(*args,**kwargs)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    async def unreadable(*args,**kwargs): raise EntryStorageUnavailable('read unavailable')
    monkeypatch.setattr(ui.service,'record_upload',uncertain)
    if read_failure: monkeypatch.setattr(ui.packages,'read_document_package',unreadable)
    response=post(env,url,values)
    assert response.status_code==503
    retry=Form(response.text,'kg-q-upload').data; retry.pop('file',None)
    assert {k:v for k,v in retry.items() if k!='_q_sha256'}==values
    assert len(retry['_q_sha256'])==64
    monkeypatch.setattr(ui.service,'record_upload',original);monkeypatch.setattr(ui.packages,'read_document_package',actual_read)
    assert post(env,url,retry,data=PDF+b'changed').status_code==422
    assert post(env,url,retry).status_code==200
    assert read(env,app)['current_revision']==2 and len(read(env,app)['quarantine'])==1


def test_successful_commit_followed_by_reread_failure_retains_retry(env,subject,monkeypatch):
    app,url=subject; values=form(env,url); actual_read=ui.packages.read_document_package
    async def unreadable(*args,**kwargs): raise EntryStorageUnavailable('read unavailable')
    monkeypatch.setattr(ui.packages,'read_document_package',unreadable)
    response=post(env,url,values)
    assert response.status_code==503 and 'kg-q-saved' not in response.text
    retry=Form(response.text,'kg-q-upload').data; retry.pop('file',None)
    assert retry['_q_key']==values['_q_key'] and retry['_q_sha256']
    monkeypatch.setattr(ui.packages,'read_document_package',actual_read)
    assert post(env,url,retry).status_code==200 and len(read(env,app)['quarantine'])==1


def test_invalid_files_multipart_limits_and_unknown_fields(env,subject):
    app,url=subject; values=form(env,url)
    assert post(env,url,values,data=b'MZnot PDF').status_code==422
    assert post(env,url,values,filename='../scan.pdf').status_code==422
    assert post(env,url,values,data=PDF+b'x'*1024).status_code==413
    assert post(env,url,values|{'unexpected':'private'}).status_code==422
    body=multipart([(FILE,PDF)],closed=False)
    assert env['client'].post(url,content=body,headers={'content-type':'multipart/form-data; boundary=synthetic'}).status_code==422
    assert env['client'].post(url,json={}).status_code==415
    assert read(env,app)['current_revision']==1
