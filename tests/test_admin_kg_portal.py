from html.parser import HTMLParser
import asyncio
from urllib.parse import urlencode

import pytest

import app.admin.router as ar
import app.admin.kg_portal as ui
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import env
from tests.test_admin_workday import _login
from tests.test_entry_portal import setup,receive,read,action,counts
from tests.test_entry_portal_parser import policy,message
from tests.test_entry_applications import read as read_application


class Form(HTMLParser):
    def __init__(self, html, name):
        super().__init__();self.name=name;self.active=False;self.data={};self.current=None;self.feed(html)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.active=a.get('data-portal-action')==self.name
        if not self.active:return
        if tag=='input' and a.get('name') and (a.get('type')!='checkbox' or 'checked' in a):self.data[a['name']]=a.get('value','')
        if tag=='select':self.current=a.get('name')
        if tag=='option' and self.current and (self.current not in self.data or 'selected' in a):self.data[self.current]=a.get('value','')
        if tag=='textarea':self.data[a['name']]=''
    def handle_endtag(self,tag):
        if tag=='form':self.active=False
        if tag=='select':self.current=None


def url(env,receipt=None):return f"{env['url']}/portal"+(f"?receipt_id={receipt['id']}" if receipt else '')


def form(env,name,receipt=None):
    response=env['client'].get(url(env,receipt));assert response.status_code==200,response.text[-1000:]
    result=Form(response.text,name).data
    assert result.get('_pn_action'),response.text[-1500:]
    return result


def post(env,data,client=None):return (client or env['client']).post(url(env),data=data,follow_redirects=False)


@pytest.fixture(autouse=True)
def configured(monkeypatch):monkeypatch.setattr(ar.settings,'kg_portal_observation_policy',policy().document())


def test_native_receive_correlate_confirm_printable_history(env):
    app=setup(env);data=form(env,'receive-paste')
    data.update(transport_id='SYN-UI-MESSAGE',archive_reference='SYN-ARCHIVE',archive_proof='d'*64,text=message())
    result=post(env,data);assert result.status_code==303
    page=env['client'].get(result.headers['location']);assert page.status_code==200
    receipt={'id':int(result.headers['location'].split('=')[-1])}
    data=form(env,'correlate',receipt);data['confirmed']='yes';assert post(env,data).status_code==303
    data=form(env,'confirm',receipt);data.update(confirmed='yes',cycle_verified='yes',on='2026-10-10',
        source='portal',verification_reference='SYN-UI-CHECK',verification_proof='e'*64)
    assert post(env,data).status_code==303 and post(env,data).status_code==303
    page=env['client'].get(url(env,receipt))
    assert page.status_code==200 and page.headers['cache-control']=='no-store'
    assert 'Подтверждение записано в заявку' in page.text and '@media print' in page.text
    assert read_application(env,app)['current']['status']=='approved'
    assert url(env) in env['client'].get(f"{env['url']}/applications").text


@pytest.mark.parametrize('key,value',[('_pn_target','999'),('_pn_revision','20'),('_pn_policy','0'*64),('_pn_namespace','OTHER'),('_pn_binding','{}'),('_pn_csrf','bad')])
def test_unsigned_form_mutations_do_not_write(env,key,value):
    data=form(env,'receive-paste');data.update(transport_id='SYN',archive_reference='SYN',archive_proof='d'*64,text=message())
    data[key]=value;before=counts(env)
    assert post(env,data).status_code in (403,422) and counts(env)==before


def test_duplicate_fields_body_bounds_and_channel_extra_fields(env):
    data=form(env,'receive-paste');data.update(transport_id='SYN',archive_reference='SYN',archive_proof='d'*64,text=message())
    duplicate=urlencode(data)+'&text=extra'
    assert env['client'].post(url(env),content=duplicate,headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==422
    assert post(env,data|{'reference':'AB12CD34'}).status_code==422
    assert env['client'].post(url(env),content='x'*65537,headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==413
    assert counts(env)['entry_portal_receipts']==0


def test_default_off_full_admin_and_workday_write_gates(env,monkeypatch):
    before=counts(env);data=form(env,'receive-paste')
    monkeypatch.setattr(ar.settings,'kg_portal_observation_policy',{})
    page=env['client'].get(url(env));assert page.status_code==200 and 'kg-portal-disabled' in page.text
    assert 'data-portal-action="receive-paste"' not in page.text
    data.update(transport_id='SYN',archive_reference='SYN',archive_proof='d'*64,text=message())
    assert post(env,data).status_code==403
    client=_login('medina')
    try:assert client.get(url(env)).status_code==403
    finally:client.close()
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url(env)).status_code==404
    assert counts(env)==before


def test_write_gate_precedes_domain_access(env,monkeypatch):
    data=form(env,'receive-paste');data.update(transport_id='SYN',archive_reference='SYN',archive_proof='d'*64,text=message())
    monkeypatch.setattr(ui.entry,'_write_on',lambda request:False)
    async def must_not_run(*args,**kwargs):raise AssertionError('write gate bypassed')
    monkeypatch.setattr(ui.service,'receive',must_not_run)
    assert post(env,data).status_code==403


def test_unknown_commit_keeps_original_envelope_even_when_reread_fails(env,monkeypatch):
    setup(env);receipt=receive(env);action(env,receipt,'correlate')
    data=form(env,'confirm',receipt);data.update(confirmed='yes',cycle_verified='yes',on='2026-10-10',
        source='portal',verification_reference='SYN-CHECK',verification_proof='e'*64)
    original=ui.service.record_action
    async def committed(*args,**kwargs):
        await original(*args,**kwargs)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    async def failed_read(*args,**kwargs):raise EntryStorageUnavailable('synthetic read unavailable')
    with monkeypatch.context() as scoped:
        scoped.setattr(ui.service,'record_action',committed);scoped.setattr(ui.service,'list_receipts',failed_read)
        response=post(env,data)
    assert response.status_code==503
    retry=Form(response.text,'retry').data
    assert retry==data and post(env,retry).status_code==303
    assert read(env,receipt)['revision']==2


def test_unavailable_history_foreign_scope_and_empty_page(env,monkeypatch):
    assert 'Пока нет сохранённых уведомлений' in env['client'].get(url(env)).text
    assert env['client'].get(url(env)+'?receipt_id=99999').status_code==404
    assert env['client'].get(url(env)+'?before=1&before=2').status_code==422
    async def unavailable(*args,**kwargs):raise RuntimeError('synthetic failure')
    monkeypatch.setattr(ui.service,'list_receipts',unavailable)
    response=env['client'].get(url(env))
    assert response.status_code==503 and 'Хранилище временно недоступно' in response.text
    assert 'data-portal-action="receive-paste"' not in response.text
