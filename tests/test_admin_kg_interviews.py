import asyncio
import json
from html.parser import HTMLParser
from urllib.parse import urlencode

import pytest

import app.admin.kg_interviews as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_admin_workday import _login
from tests.test_entry_interviews import admins,policy,start,read,action,correct,counts
from tests.test_entry_applications import person


class Form(HTMLParser):
    def __init__(self,html,name):
        super().__init__();self.name=name;self.active=False;self.data={};self.current=None;self.feed(html)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='form':self.active=a.get('data-interview-action')==self.name
        if not self.active:return
        if tag=='input' and a.get('name') and (a.get('type')!='checkbox' or 'checked' in a):self.data[a['name']]=a.get('value','')
        if tag=='select':self.current=a.get('name')
        if tag=='option' and self.current and (self.current not in self.data or 'selected' in a):self.data[self.current]=a.get('value','')
    def handle_endtag(self,tag):
        if tag=='form':self.active=False
        if tag=='select':self.current=None


@pytest.fixture(autouse=True)
def configured(env,admins,monkeypatch):monkeypatch.setattr(ar.settings,'kg_interview_policy',policy().document())


def url(env,p):return ui._url(env['cases']['visa'],p['applicant_id'] if 'applicant_id' in p else p['id'])


def form(env,p,name,*,field=None,client=None):
    response=(client or env['client']).get(url(env,p)+(('?'+urlencode({'field':field})) if field else ''))
    assert response.status_code==200,response.text[-1500:]
    data=Form(response.text,name).data;assert data.get('_iv_action'),response.text[-1500:]
    return data


def post(env,p,data,client=None):return (client or env['client']).post(url(env,p),data=data,follow_redirects=False)


def unknown(data):
    for i in range(len(json.loads(data['_iv_paths']))):data[f'm{i}']='unknown'
    return data


def test_native_start_unknown_pause_language_resume_handoff_ack_and_manual_correction(env):
    p=person(env);before=counts(env)
    data=form(env,p,'start');data.update(owner='admin',language='en')
    assert post(env,p,data).status_code==303 and post(env,p,data).status_code==303
    current=asyncio.run(ui.service.read_interview(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],applicant_id=p['id'],policy=policy()))
    iv={'applicant_id':p['id'],'interview_id':current['interview']['id']}
    page=env['client'].get(url(env,iv));assert 'Has this applicant given consent' in page.text
    data=unknown(form(env,iv,'answer'));assert 1<=len(json.loads(data['_iv_paths']))<=3
    assert post(env,iv,data).status_code==303
    assert post(env,iv,form(env,iv,'pause')).status_code==303
    assert 'data-interview-action="answer"' not in env['client'].get(url(env,iv)).text
    assert post(env,iv,form(env,iv,'language')).status_code==303
    assert post(env,iv,form(env,iv,'resume')).status_code==303
    assert post(env,iv,form(env,iv,'handoff')).status_code==303
    frozen=read(env,iv)['state']['handoff']
    data=form(env,iv,'ack');data['confirmed']='yes';assert post(env,iv,data).status_code==303
    assert post(env,iv,data).status_code==303
    data=form(env,iv,'correct',field='contact_name');data.update(m0='value',v0='Synthetic applicant')
    assert post(env,iv,data).status_code==303
    page=env['client'].get(url(env,iv))
    assert page.status_code==200 and page.headers['cache-control']=='no-store' and page.headers['referrer-policy']=='no-referrer'
    assert 'Принято специалистом' in page.text and 'внесено после передачи' in page.text
    assert 'data-interview-action="answer"' not in page.text and '@media print' in page.text
    assert read(env,iv)['state']['handoff']==frozen
    after=counts(env)
    assert {k:v for k,v in before.items() if not k.startswith('entry_interview')}=={k:v for k,v in after.items() if not k.startswith('entry_interview')}
    assert url(env,iv) in env['client'].get(f"{env['url']}/applications").text


@pytest.mark.parametrize('key,value',[('_iv_target','999'),('_iv_revision','20'),('_iv_policy','0'*64),('_iv_paths','["contact_name"]'),('_iv_card','d'*64),('_iv_csrf','bad')])
def test_tampered_signed_form_cannot_write(env,key,value):
    iv=start(env);data=unknown(form(env,iv,'answer'));data[key]=value;before=counts(env)
    assert post(env,iv,data).status_code in (403,422) and counts(env)==before


def test_duplicate_extra_fields_and_body_bounds(env):
    iv=start(env);data=unknown(form(env,iv,'answer'));before=counts(env)
    assert env['client'].post(url(env,iv),content=urlencode(data)+'&m0=unknown',headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==422
    assert post(env,iv,data|{'v9':'ignored payload'}).status_code==422
    assert post(env,iv,data|{'v0':'must not discard hidden value'}).status_code==422
    assert env['client'].post(url(env,iv),content='x'*32769,headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(url(env,iv),json=data).status_code==415
    assert counts(env)==before


def test_scope_csrf_cross_applicant_and_stale_form(env):
    iv=start(env);second=start(env,person(env,key='SECOND'),request_key='SECOND');data=unknown(form(env,iv,'answer'))
    assert post(env,second,data).status_code==403
    action(env,iv,'language');assert post(env,iv,data).status_code==409
    assert env['client'].get(url(env,iv)+'?field=unknown').status_code==422
    assert env['client'].get(url(env,iv)+'?field=purpose&field=purpose').status_code==422
    assert env['client'].get(url(env,{'id':99999})).status_code==404


def test_default_policy_role_off_and_write_gate(env,monkeypatch):
    p=person(env);data=form(env,p,'start');data.update(owner='admin',language='ru');before=counts(env)
    monkeypatch.setattr(ar.settings,'kg_interview_policy',{})
    page=env['client'].get(url(env,p));assert page.status_code==200 and 'kg-interview-disabled' in page.text
    assert 'data-interview-action="start"' not in page.text and post(env,p,data).status_code==403
    client=_login('medina')
    try:assert client.get(url(env,p)).status_code==403
    finally:client.close()
    monkeypatch.setattr(ar.settings,'kg_interview_policy',policy().document())
    with monkeypatch.context() as scoped:
        scoped.setattr(ui.entry,'_write_on',lambda request:False)
        async def fail(*a,**kw):raise AssertionError('must not enter writer')
        scoped.setattr(ui.service,'start_interview',fail)
        assert post(env,p,data).status_code==403
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url(env,p)).status_code==404 and post(env,p,data).status_code==404
    assert counts(env)==before


@pytest.mark.parametrize('starting',[True,False])
def test_lost_ack_and_failed_reread_retains_exact_original_request(env,monkeypatch,starting):
    p=person(env) if starting else start(env,owner_login='admin')
    data=form(env,p,'start' if starting else 'handoff')
    if starting:data.update(owner='admin',language='ru')
    name='start_interview' if starting else 'record_action';original=getattr(ui.service,name)
    async def committed(*args,**kwargs):
        await original(*args,**kwargs);raise EntryStorageUnavailable('synthetic lost ACK')
    async def failed_read(*args,**kwargs):raise EntryStorageUnavailable('synthetic reread unavailable')
    with monkeypatch.context() as scoped:
        scoped.setattr(ui.service,name,committed);scoped.setattr(ui.service,'read_interview',failed_read)
        response=post(env,p,data)
    assert response.status_code==503
    retry=Form(response.text,'retry').data
    assert retry==data and post(env,p,retry).status_code==303
    assert counts(env)['entry_interviews']==1
    assert counts(env)['entry_interview_events']==(1 if starting else 2)


@pytest.mark.parametrize('field,values,expected',[
    ('extra_services',{'m0':'value'},[]),('family_count',{'m0':'value','v0':'0'},0),
    ('tickets_bought',{'m0':'value','v0':'false'},False),('citizenships',{'m0':'value','v0_0':'KGZ','v0_1':'KAZ'},['KAZ','KGZ']),
    ('entry_on',{'m0':'unknown'},'unknown')])
def test_native_typed_empty_false_zero_and_unknown_distinct(env,field,values,expected):
    iv=start(env);data=form(env,iv,'correct',field=field);data.update(values)
    response=post(env,iv,data);assert response.status_code==303,response.text[-1200:]
    assert read(env,iv)['state']['answers'][field]['value']==expected


def test_conflicting_valid_dates_are_retained_and_handoff_is_atomic(env):
    iv=start(env)
    for field,value in [('entry_on','2026-12-20'),('exit_on','2026-12-01')]:
        data=form(env,iv,'correct',field=field);data.update(m0='value',v0=value)
        assert post(env,iv,data).status_code==303
    current=read(env,iv)
    assert current['state']['phase']=='pending' and current['state']['answers']['exit_on']['value']=='2026-12-01'
    assert not Form(env['client'].get(url(env,iv)).text,'answer').data


@pytest.mark.parametrize('acknowledged',[False,True])
def test_native_withdrawal_after_handoff_blocks_future_owner_collection(env,acknowledged):
    iv=start(env,owner_login='admin');post(env,iv,form(env,iv,'handoff'))
    if acknowledged:
        data=form(env,iv,'ack');data['confirmed']='yes';assert post(env,iv,data).status_code==303
    frozen=read(env,iv)['state']['handoff'];data=form(env,iv,'withdraw')
    assert data['reason']=='consent_withdrawn' and post(env,iv,data).status_code==303
    if not acknowledged:
        data=form(env,iv,'ack');data['confirmed']='yes';assert post(env,iv,data).status_code==303
    current=read(env,iv)
    assert current['state']['handoff']==frozen and current['state']['collection_blocked']
    page=env['client'].get(url(env,iv)+'?field=contact_name')
    assert 'data-interview-action="correct"' not in page.text and 'data-interview-action="withdraw"' not in page.text


def test_native_old_signed_form_and_questions_keep_pinned_catalog_after_active_switch(env,monkeypatch):
    from tests.test_entry_interviews import switch_catalog
    old_policy=policy();iv=start(env);data=form(env,iv,'correct',field='contact_name');data.update(m0='value',v0='Synthetic historical answer')
    switch_catalog(monkeypatch)
    # Continue the still-configured older policy against its retained catalog.
    assert post(env,iv,data).status_code==303
    page=env['client'].get(url(env,iv)+'?field=contact_name')
    assert page.status_code==200 and 'Synthetic future prompt' not in page.text
    assert post(env,iv,data).status_code==303
    assert read(env,iv,policy=old_policy)['state']['answers']['contact_name']['value']=='Synthetic historical answer'
