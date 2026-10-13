import asyncio
from urllib.parse import urlencode

import pytest

import app.admin.kg_notifications as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form
from tests.test_admin_workday import _login
from tests.test_entry_notifications import env,admins,policy,subject,read,counts,apps


@pytest.fixture(autouse=True)
def configured(env,admins,monkeypatch):monkeypatch.setattr(ar.settings,'kg_notification_storage_policy',policy().document())


def url(env,app):return ui._url(env['cases']['visa'],app['id'])


def form(env,app,template='KG.TPL.A06'):
    response=env['client'].get(url(env,app)+'?template='+template)
    assert response.status_code==200,response.text[-2000:]
    result=Form(response.text,'notification-preview').data
    assert result.get('_n_action')=='preview'
    return result


def post(env,app,data,client=None):return (client or env['client']).post(url(env,app),data=data,follow_redirects=False)


def save_form(env,app):
    data=form(env,app);data.update(p01='2026-10-01',p02='SYN-12',p03='5',p04='2026-10-08')
    page=post(env,app,data);assert page.status_code==200,page.text[-2000:]
    result=Form(page.text,'notification-save').data
    assert result.get('_n_action')=='save' and '_n_confirm' not in result
    result['_n_confirm']='1';return result


def test_native_preview_confirmation_retry_history_and_no_other_writes(env):
    app=subject(env);before=counts(env);data=save_form(env,app);assert counts(env)==before
    unconfirmed=data.copy();unconfirmed.pop('_n_confirm')
    assert post(env,app,unconfirmed).status_code==422 and read(env,app)['revision']==0
    assert post(env,app,data).status_code==post(env,app,data).status_code==303
    assert read(env,app)['revision']==1
    page=env['client'].get(url(env,app));assert page.status_code==200 and page.headers['cache-control']=='no-store'
    assert 'Сохранённый черновик №1' in page.text and 'Отправка не разрешена' in page.text
    assert env['client'].get(url(env,app)+'?revision=1').status_code==200
    assert env['client'].get(url(env,app)+'?revision=2').status_code==404


@pytest.mark.parametrize('value',['\U0001f642'*500,'\u044f<&"\''*100])
def test_largest_literal_unicode_preview_roundtrips_signed_save_and_exact_retry(env,value):
    app=subject(env);data=form(env,app,'KG.TPL.A07')
    slots=('p01','p02','p10','p11','p12','p20')
    data.update({key:value for key in slots})
    page=post(env,app,data);assert page.status_code==200
    saved=Form(page.text,'notification-save').data|{'_n_confirm':'1'}
    assert len(urlencode(saved).encode())<=65536
    assert post(env,app,saved).status_code==303
    assert post(env,app,saved).status_code==303
    current=read(env,app);assert current['revision']==1
    actual=current['history'][0]['receipt']['command']['parameters']['values']
    assert actual=={key:value for key in slots}


@pytest.mark.parametrize('field,value',[('_n_values','{}'),('_n_template','KG.TPL.A01'),('_n_policy','a'*64),
    ('_n_revision','99'),('_n_key','different'),('_n_renderer','kg-notification-renderer/99'),('_n_preview','b'*64)])
def test_signed_confirmation_cannot_change_pins_or_body(env,field,value):
    app=subject(env);data=save_form(env,app);data[field]=value
    assert post(env,app,data).status_code==403 and read(env,app)['revision']==0


def test_scope_session_duplicates_oversize_and_invalid_percent_utf8(env):
    app=subject(env);data=form(env,app);other=apps.application(env,apps.person(env,key='other'),key='other')
    assert post(env,other,data).status_code==403
    client=_login('admin')
    try:assert post(env,app,data,client).status_code==403
    finally:client.close()
    for suffix in ('&p01=duplicated','&unknown=1','&p01=%FF','&p01=%ED%A0%80','&bad=%','&blob='+'x'*65537):
        response=env['client'].post(url(env,app),content=urlencode(data)+suffix,headers={'Content-Type':'application/x-www-form-urlencoded'})
        assert response.status_code==422
    for key in ('_n_csrf','_n_sig'):
        changed=data|{key:'я'*64};assert post(env,app,changed).status_code==403
    assert read(env,app)['revision']==0


def test_commit_unknown_and_failed_reread_keeps_original_confirmation_after_policy_removed(env,monkeypatch):
    app=subject(env);data=save_form(env,app);save=ui.service.save_draft;read_original=ui.service.read_drafts
    async def uncertain(*a,**kw):await save(*a,**kw);raise EntryStorageUnavailable('synthetic lost ACK')
    async def unavailable(*a,**kw):raise EntryStorageUnavailable('synthetic failed reread')
    monkeypatch.setattr(ui.service,'save_draft',uncertain);monkeypatch.setattr(ui.service,'read_drafts',unavailable)
    response=post(env,app,data);assert response.status_code==503
    retry=Form(response.text,'notification-retry').data;assert retry==data
    monkeypatch.setattr(ui.service,'save_draft',save);monkeypatch.setattr(ui.service,'read_drafts',read_original)
    monkeypatch.setattr(ar.settings,'kg_notification_storage_policy',{})
    assert post(env,app,retry).status_code==303 and read(env,app)['revision']==1
    page=env['client'].get(url(env,app));assert 'Нет действующих полномочий' in page.text


def test_policy_change_stale_application_and_literal_html_are_visible(env,monkeypatch):
    app=subject(env);data=save_form(env,app);apps.record(env,app)
    assert post(env,app,data).status_code==409
    data=form(env,app);data['p02']='<script>alert(1)</script>{literal}'
    page=post(env,app,data);assert page.status_code==200
    assert '&lt;script&gt;' in page.text and '<script>alert(1)</script>' not in page.text
    save=Form(page.text,'notification-save').data|{'_n_confirm':'1'}
    monkeypatch.setattr(ar.settings,'kg_notification_storage_policy',policy(proof='e'*64).document())
    assert post(env,app,save).status_code==409 and read(env,app)['revision']==0


def test_old_preview_stays_readonly_default_off_full_admin_and_write_boundaries(env,monkeypatch):
    app=subject(env);data=form(env,app);before=counts(env)
    assert env['client'].get('/admin/kg-entry/templates').status_code==200 and counts(env)==before
    manager=_login('medina')
    try:
        assert manager.get(url(env,app)).status_code==403
        assert post(env,app,data,manager).status_code==403
    finally:manager.close()
    monkeypatch.setattr(ar.settings,'kg_notification_storage_policy',{})
    assert '_n_action' not in env['client'].get(url(env,app)).text
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url(env,app)).status_code==404 and post(env,app,data).status_code==404
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    monkeypatch.setattr(ui.entry,'_write_on',lambda request:False)
    assert post(env,app,data).status_code==403


@pytest.mark.parametrize('declared',[None,'100000','wrong','-1'])
def test_streaming_body_limit_stops_before_unbounded_buffer(declared):
    from fastapi import HTTPException
    from starlette.requests import Request
    got=[]
    async def receive():
        got.append(True);return {'type':'http.request','body':b'x'*8192,'more_body':len(got)<32}
    headers=[(b'content-type',b'application/x-www-form-urlencoded')]
    if declared is not None:headers.append((b'content-length',declared.encode()))
    request=Request({'type':'http','method':'POST','path':'/','headers':headers},receive)
    with pytest.raises(HTTPException) as error:asyncio.run(ui._form(request,None,1,1))
    assert error.value.status_code==422 and len(got)==(9 if declared is None else 0)
