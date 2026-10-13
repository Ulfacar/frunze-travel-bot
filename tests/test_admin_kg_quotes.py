from html.parser import HTMLParser
import asyncio
from urllib.parse import urlencode

import pytest

import app.admin.kg_quotes as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_workday import _login
from tests.test_entry_quotes import env,admins,policy,subject,read,counts,recipe,na,apps


class Form(HTMLParser):
    def __init__(self,html,name):
        super().__init__();self.name=name;self.active=False;self.data={};self.current=None;self.feed(html)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.active=a.get('data-quote-action')==self.name
        if not self.active:return
        if tag=='input' and a.get('name'):self.data[a['name']]=a.get('value','')
        if tag=='select':self.current=a.get('name')
        if tag=='option' and self.current and (self.current not in self.data or 'selected' in a):self.data[self.current]=a.get('value','')
    def handle_endtag(self,tag):
        if tag=='form':self.active=False
        if tag=='select':self.current=None


@pytest.fixture(autouse=True)
def configured(env,admins,monkeypatch):monkeypatch.setattr(ar.settings,'kg_quote_policy',policy().document())


def url(env,app):return ui._url(env['cases']['visa'],app['id'])


def form(env,app,*,client=None):
    response=(client or env['client']).get(url(env,app));assert response.status_code==200,response.text[-1000:]
    value=Form(response.text,'preview').data;assert value.get('_q_action')=='preview';return value


def post(env,app,values,*,client=None):return (client or env['client']).post(url(env,app),data=values,follow_redirects=False)


def save_form(env,app,*,client=None):
    response=post(env,app,form(env,app,client=client),client=client)
    assert response.status_code==200,response.text[-1800:]
    value=Form(response.text,'save').data;assert value.get('_q_action')=='save';return value


def test_native_preview_explicit_save_retry_history_and_unknown_total(env):
    app=subject(env);before=counts(env);data=form(env,app);data['urgent']='1'
    page=post(env,app,data);assert page.status_code==200 and counts(env)==before
    assert 'Полная цена не определена' in page.text and '200.00 USD' in page.text
    save=Form(page.text,'save').data
    assert post(env,app,save).status_code==303 and post(env,app,save).status_code==303
    assert read(env,app)['revision']==1
    saved=env['client'].get(url(env,app));assert 'Сохранённый расчёт · версия 1' in saved.text
    assert 'Эту версию нельзя использовать как текущую полную цену.' in saved.text
    assert saved.headers['cache-control']=='no-store'
    assert env['client'].get(url(env,app)+'?revision=1').status_code==200
    assert env['client'].get(url(env,app)+'?revision=2').status_code==404


@pytest.mark.parametrize('field,value',[('additional_blocks','1'),('urgent','1'),('recipe_id','FORGED'),
    ('_q_revision','1'),('_q_preview','a'*64),('_q_policy','b'*64),('_q_calculator','kg-quote-calculator/99')])
def test_signed_save_binds_exact_preview_and_parameters(env,field,value):
    app=subject(env);data=save_form(env,app);data[field]=value
    assert post(env,app,data).status_code==403 and read(env,app)['revision']==0


def test_csrf_session_target_duplicate_extra_and_bounds_are_enforced(env):
    app=subject(env);data=form(env,app);data['_q_csrf']='invalid'
    assert post(env,app,data).status_code==403
    data=form(env,app);other=apps.application(env,apps.person(env,key='OTHER'),key='OTHER')
    assert post(env,other,data).status_code==403
    second=_login('admin')
    try:assert post(env,app,data,client=second).status_code==403
    finally:second.close()
    for body in (urlencode(data)+'&urgent=1',urlencode(data)+'&price=0',urlencode(data)+'&blob='+'x'*17000):
        response=env['client'].post(url(env,app),content=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
        assert response.status_code==422
    data['additional_blocks']='121';assert post(env,app,data).status_code==422
    assert read(env,app)['revision']==0


def test_current_policy_change_and_application_growth_require_new_preview(env,monkeypatch):
    app=subject(env);data=save_form(env,app);apps.record(env,app)
    assert post(env,app,data).status_code==409 and read(env,app)['revision']==0
    data=save_form(env,app);monkeypatch.setattr(ar.settings,'kg_quote_policy',policy(proof='e'*64).document())
    assert post(env,app,data).status_code==409 and read(env,app)['revision']==0


def test_lost_commit_ack_and_failed_reread_preserve_full_signed_retry(env,monkeypatch):
    app=subject(env);data=save_form(env,app);original=ui.service.save_quote;original_read=ui.service.read_quotes
    async def uncertain(*a,**kw):await original(*a,**kw);raise EntryStorageUnavailable('synthetic lost ACK')
    async def unavailable(*a,**kw):raise EntryStorageUnavailable('synthetic unavailable reread')
    monkeypatch.setattr(ui.service,'save_quote',uncertain);monkeypatch.setattr(ui.service,'read_quotes',unavailable)
    response=post(env,app,data);assert response.status_code==503
    retry=Form(response.text,'retry').data;assert retry==data
    monkeypatch.setattr(ui.service,'save_quote',original);monkeypatch.setattr(ui.service,'read_quotes',original_read)
    monkeypatch.setattr(ar.settings,'kg_quote_policy',{})
    assert post(env,app,retry).status_code==303 and read(env,app)['revision']==1
    page=env['client'].get(url(env,app));assert 'Нет действующих полномочий для использования цены' in page.text


def test_off_full_admin_and_write_gates(env,monkeypatch):
    app=subject(env);data=form(env,app)
    manager=_login('medina')
    try:
        assert manager.get(url(env,app)).status_code==403
        assert post(env,app,data,client=manager).status_code==403
    finally:manager.close()
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url(env,app)).status_code==404 and post(env,app,data).status_code==404
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    monkeypatch.setattr(ui.entry,'_write_on',lambda request:False)
    assert post(env,app,data).status_code==403


def test_complete_historical_price_is_readable_but_not_current_after_authority_removal(env,monkeypatch):
    app=subject(env);r=recipe();r['lines'][2]=na('bank');p=policy(r)
    monkeypatch.setattr(ar.settings,'kg_quote_policy',p.document());assert post(env,app,save_form(env,app)).status_code==303
    monkeypatch.setattr(ar.settings,'kg_quote_policy',{})
    page=env['client'].get(url(env,app));assert page.status_code==200
    assert '100.00 USD' in page.text and 'Новый расчёт недоступен' in page.text
    assert 'Эту версию нельзя использовать как текущую полную цену.' in page.text


@pytest.mark.parametrize('field',['_q_csrf','_q_sig'])
def test_non_ascii_security_tokens_fail_closed(env,field):
    app=subject(env);data=form(env,app);data[field]='я'*64
    assert post(env,app,data).status_code==403 and read(env,app)['revision']==0


@pytest.mark.parametrize('declared',[None,'262144','-1','wrong'])
def test_form_stops_reading_before_oversized_body_is_buffered(declared):
    from fastapi import HTTPException
    from starlette.requests import Request
    received=[]
    async def receive():
        received.append(True)
        return {'type':'http.request','body':b'x'*8192,'more_body':len(received)<32}
    headers=[(b'content-type',b'application/x-www-form-urlencoded')]
    if declared is not None:headers.append((b'content-length',declared.encode()))
    req=Request({'type':'http','method':'POST','path':'/','headers':headers},receive)
    with pytest.raises(HTTPException) as result:asyncio.run(ui._form(req,None,1,1))
    assert result.value.status_code==422
    assert len(received)==(3 if declared is None else 0)
