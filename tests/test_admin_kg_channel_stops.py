import asyncio
from urllib.parse import urlencode

import pytest

import app.admin.kg_channel_stops as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form
from tests.test_admin_workday import _login
from tests.test_entry_channel_stops import env,admins,activation,start,dialog,resolve,policy,read,action,counts,service,send


@pytest.fixture(autouse=True)
def resolver(monkeypatch):monkeypatch.setattr(ui,'resolve_dialog',resolve)


def url(env,iv):return ui._url(env['cases']['visa'],iv['applicant_id'],iv['interview_id'])


def post(env,iv,values,client=None):return (client or env['client']).post(url(env,iv),data=values,follow_redirects=False)


def select_form(env,iv):
    response=env['client'].get(url(env,iv));assert response.status_code==200,response.text[-1200:]
    return Form(response.text,'stop-select').data


def save_form(env,iv):
    response=post(env,iv,select_form(env,iv));assert response.status_code==200,response.text[-1500:]
    data=Form(response.text,'stop-save').data;assert data.get('_cs_action')=='save'
    return data|{'confirmed':'yes'}


def test_native_preview_confirmation_bound_card_ack_and_repeat(env):
    iv=start(env);dialog(env);before=counts(env);data=save_form(env,iv)
    assert counts(env)==before
    assert post(env,iv,data).status_code==303 and post(env,iv,data).status_code==303
    page=env['client'].get(url(env,iv));assert 'Автоответы остановлены' in page.text and page.headers['cache-control']=='no-store'
    assert send(env)[1]==[] and read(env,iv)['state']['phase']=='pending'
    action(env,iv,'ack');assert send(env)[1]==[]
    shown=post(env,iv,select_form(env,iv));assert 'уже остановлены' in shown.text and not Form(shown.text,'stop-save').data


@pytest.mark.parametrize('field,value',[('dialog_id','9999'),('_cs_revision','2'),('_cs_preview','f'*64),('_cs_policy','f'*64),('_cs_key','forged')])
def test_signed_save_cannot_change_target_revision_or_request(env,field,value):
    iv=start(env);dialog(env);data=save_form(env,iv);data[field]=value
    assert post(env,iv,data).status_code==403 and read(env,iv)['state']['phase']=='active'


@pytest.mark.parametrize('field',['_cs_csrf','_cs_sig'])
def test_non_ascii_security_values_rejected(env,field):
    iv=start(env);dialog(env);data=save_form(env,iv);data[field]='я'*64
    assert post(env,iv,data).status_code==403


def test_missing_confirmation_session_extra_duplicates_and_body_bounds(env):
    iv=start(env);dialog(env);data=save_form(env,iv)
    without=dict(data);without.pop('confirmed');assert post(env,iv,without).status_code==422
    second=_login('admin')
    try:assert post(env,iv,data,second).status_code==403
    finally:second.close()
    for body in (urlencode(data)+'&dialog_id=1',urlencode(data)+'&recipient=123',urlencode(data)+'&blob='+'x'*17000):
        response=env['client'].post(url(env,iv),content=body,headers={'Content-Type':'application/x-www-form-urlencoded'})
        assert response.status_code==422
    assert read(env,iv)['state']['phase']=='active'


def test_stale_card_and_policy_require_new_preview(env,monkeypatch):
    iv=start(env);dialog(env);data=save_form(env,iv);action(env,iv,'pause')
    assert post(env,iv,data).status_code==409
    data=save_form(env,iv);monkeypatch.setattr(ar.settings,'kg_channel_stop_policy',policy(proof='e'*64).document())
    assert post(env,iv,data).status_code==409


def test_lost_commit_and_failed_read_keep_exact_retry_after_policy_removal(env,monkeypatch):
    iv=start(env);dialog(env);data=save_form(env,iv);original=ui.service.bind_stop;original_read=ui.service.list_stops
    async def uncertain(*a,**kw):await original(*a,**kw);raise EntryStorageUnavailable('synthetic lost ACK')
    async def unavailable(*a,**kw):raise EntryStorageUnavailable('synthetic read unavailable')
    monkeypatch.setattr(ui.service,'bind_stop',uncertain);monkeypatch.setattr(ui.service,'list_stops',unavailable)
    response=post(env,iv,data);assert response.status_code==503
    retry=Form(response.text,'stop-retry').data;assert retry==data
    monkeypatch.setattr(ui.service,'bind_stop',original);monkeypatch.setattr(ui.service,'list_stops',original_read)
    monkeypatch.setattr(ar.settings,'kg_channel_stop_policy',{})
    assert post(env,iv,retry).status_code==303 and send(env)[1]==[]
    assert 'Автоответы остановлены' in env['client'].get(url(env,iv)).text


def test_full_admin_off_and_workday_write_gates(env,monkeypatch):
    iv=start(env);dialog(env);data=save_form(env,iv);manager=_login('medina')
    try:
        assert manager.get(url(env,iv)).status_code==403 and post(env,iv,data,manager).status_code==403
    finally:manager.close()
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url(env,iv)).status_code==404 and post(env,iv,data).status_code==404
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    monkeypatch.setattr(ui.entry,'_write_on',lambda request:False)
    assert post(env,iv,data).status_code==403


def test_deployment_deactivation_is_visible_and_different_from_policy_expiry(env,monkeypatch):
    iv=start(env);dialog(env);assert post(env,iv,save_form(env,iv)).status_code==303
    monkeypatch.setattr(ar.settings,'kg_channel_stop_policy',{})
    assert 'Автоответы остановлены' in env['client'].get(url(env,iv)).text
    monkeypatch.setattr(ar.settings,'kg_channel_guard_scopes',[])
    page=env['client'].get(url(env,iv));assert 'Защита этого профиля выключена' in page.text
    assert 'Автоответы остановлены' not in page.text


@pytest.mark.parametrize('declared',[None,'262144','-1','wrong'])
def test_stream_bounded_before_full_buffer(declared):
    from fastapi import HTTPException
    from starlette.requests import Request
    received=[]
    async def receive():
        received.append(True);return {'type':'http.request','body':b'x'*8192,'more_body':len(received)<32}
    headers=[(b'content-type',b'application/x-www-form-urlencoded')]
    if declared is not None:headers.append((b'content-length',declared.encode()))
    req=Request({'type':'http','method':'POST','path':'/','headers':headers},receive)
    with pytest.raises(HTTPException) as result:asyncio.run(ui._form(req,None,(1,1,1)))
    assert result.value.status_code==422 and len(received)==(3 if declared is None else 0)
