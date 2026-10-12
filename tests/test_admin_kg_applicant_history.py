"""Real native personal evidence flow, retry, scope and bounded row editing."""
import asyncio
from datetime import datetime,timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event,text

import app.admin.router as ar
import app.admin.kg_applicant_history as ui
import app.main as main
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form,env
from tests.test_admin_workday import _login
from tests.test_entry_applications import enforce_sqlite_foreign_keys,person
from tests.test_applicant_stay_history import clock,setup,save,read,document,interval,profiles


@pytest.fixture
def subject(env):
    subject,profile=setup(env)
    return subject,profile,f'{env["url"]}/applicants/{subject["id"]}/history'


def form(env,url,action='summary',**params):
    response=env['client'].get(url,params=params)
    assert response.status_code==200,response.text[-1200:]
    values=Form(response.text,'kg-ah-'+action).data
    assert values
    return {**values,'confirmed':'yes'}


def summary(env,url):
    values=form(env,url);values.update(history_complete='true',passport='new')
    return values


def visit(env,url,**params):
    values=form(env,url,'visit',**params)
    values.update(entry_date='2026-09-01',exit_date='2026-09-10',basis='visa_free',country='RUS',
        passport='0',evidence='passport_stamp',verified='yes')
    return values


def test_native_full_personal_history_and_immutable_views(env,subject):
    person,profile,url=subject
    assert url in env['client'].get(url.replace('/history','/qualification')).text
    response=env['client'].get(url)
    assert 'Это не означает отсутствие поездок' in response.text
    assert response.headers['cache-control']=='no-store' and response.headers['referrer-policy']=='no-referrer'
    assert env['client'].post(url,data=summary(env,url)).status_code==200
    assert read(env,person)['current']['status']=='recorded_inputs'
    assert env['client'].post(url,data=visit(env,url)).status_code==200
    current=read(env,person);assert current['current']['findings']==['history_incomplete']
    token=current['current']['passport_ref'];assert current['current']['document']['intervals'][0]['passport_ref']==token
    values=form(env,url);values['history_complete']='true'
    assert env['client'].post(url,data=values).status_code==200
    assert read(env,person)['current']['status']=='recorded_inputs'
    values=form(env,url,'remove',item=1)
    assert env['client'].post(url,data=values).status_code==200
    assert read(env,person)['current']['document']['intervals']==[]
    old=env['client'].get(url,params={'revision':3})
    assert old.status_code==200 and 'id="kg-ah-historical"' in old.text and '2026-09-10' in old.text
    assert not Form(old.text,'kg-ah-summary').data
    assert env['client'].post(url,data=form(env,url,'withdraw')).status_code==200
    assert read(env,person)['current']['status']=='withdrawn'
    assert env['client'].post(url,data=summary(env,url)).status_code==200
    assert read(env,person)['current_revision']==6


def test_cross_person_session_tampering_stale_and_exact_retry(env,subject):
    person,profile,url=subject;values=summary(env,url);stale=summary(env,url)
    for key,value in [('_ah_profile','999'),('_ah_revision','2'),('_ah_new_passport','b'*32),('_ah_today','2999-01-01')]:
        assert env['client'].post(url,data=values|{key:value}).status_code==403
    second,p2=setup(env,'other');other_url=url.replace('/applicants/'+str(person['id'])+'/', '/applicants/'+str(second['id'])+'/')
    assert env['client'].post(other_url,data=values).status_code==403
    client=_login('admin')
    try:assert client.post(url,data=values).status_code==403
    finally:client.close()
    assert env['client'].post(url,data=values).status_code==200
    assert env['client'].post(url,data=stale).status_code==409
    assert env['client'].post(url,data=visit(env,url)).status_code==200
    assert env['client'].post(url,data=values).status_code==200
    assert env['client'].post(url,data=values|{'history_complete':'false'}).status_code==409
    assert read(env,person)['current_revision']==2 and read(env,second)['current_revision']==0
    foreign=url.replace('/case/'+str(env['cases']['visa'])+'/', '/case/'+str(env['cases']['other'])+'/')
    assert env['client'].get(foreign).status_code==404


def test_lost_commit_ack_original_base_retry_after_new_profile_and_day(env,subject,monkeypatch):
    person,profile,url=subject;values=summary(env,url);actual=ui.service.record_history
    async def uncertain(*args,**kwargs):
        await actual(*args,**kwargs)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    monkeypatch.setattr(ui.service,'record_history',uncertain)
    response=env['client'].post(url,data=values)
    assert response.status_code==503
    retry=Form(response.text,'kg-ah-retry').data
    assert retry==values and read(env,person)['current_revision']==1
    profiles.save(env,person,revision=1,key='new-profile')
    monkeypatch.setattr(ui.service,'_now',lambda:datetime(2026,10,13,12,tzinfo=timezone.utc))
    monkeypatch.setattr(ui.service,'record_history',actual)
    assert env['client'].post(url,data=retry).status_code==200
    assert read(env,person)['current_revision']==1
    assert 'profile_changed' in read(env,person)['current']['findings']


def test_validation_echo_preserves_original_envelope_and_escapes(env,subject):
    person,profile,url=subject;env['client'].post(url,data=summary(env,url))
    values=visit(env,url);values['evidence']='client_statement'
    response=env['client'].post(url,data=values)
    assert response.status_code==422 and Form(response.text,'kg-ah-visit').data==values
    values['country']='<script>'
    response=env['client'].post(url,data=values)
    assert response.status_code==422 and 'value="&lt;script&gt;"' in response.text and 'value="<script>"' not in response.text
    assert read(env,person)['current_revision']==1


def test_maximum_history_preserves_undisplayed_rows_and_en_language(env,subject):
    person,profile,url=subject
    doc=profiles.request();doc['language']='en'
    profile=profiles.save(env,person,revision=1,key='en',doc=doc)
    visits=[interval(ref=f'visit-{i}') for i in range(1000)]
    save(env,person,profile,doc=document(intervals=visits,history_complete=True))
    response=env['client'].get(url,params={'page':40})
    assert response.status_code==200 and 'Stay history' in response.text and response.text.count('data-visit=')==25
    assert not Form(response.text,'kg-ah-visit').data
    before={v['ref']:v for v in read(env,person)['current']['document']['intervals']}
    values=visit(env,url,item=1000);values['exit_date']='2026-09-11';changed=values['_ah_item']
    assert env['client'].post(url,data=values).status_code==200
    current=read(env,person)['current']['document']['intervals']
    after={v['ref']:v for v in current}
    assert len(current)==1000 and after[changed]==(before[changed]|{'exit_date':'2026-09-11'})
    assert {k:v for k,v in after.items() if k!=changed}=={k:v for k,v in before.items() if k!=changed}
    assert env['client'].get(url+'?page=41').status_code==422


def test_get_read_only_and_old_corruption_disables_forms(env,subject):
    person,profile,url=subject;save(env,person,profile);statements=[]
    def capture(conn,cursor,statement,params,context,many):statements.append(statement)
    event.listen(env['engine'].sync_engine,'before_cursor_execute',capture)
    try:assert env['client'].get(url).status_code==200
    finally:event.remove(env['engine'].sync_engine,'before_cursor_execute',capture)
    assert not any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE','REPLACE')) for s in statements)
    async def corrupt():
        async with env['engine'].begin() as c:await c.execute(text('UPDATE entry_applicant_stay_history SET snapshot_hash=:h'),{'h':'0'*64})
    asyncio.run(corrupt())
    response=env['client'].get(url)
    assert response.status_code==503 and not Form(response.text,'kg-ah-summary').data
    assert 'id="kg-ah-status"' not in response.text


@pytest.mark.parametrize('login',[None,'medina','ademi'])
def test_access_before_domain(env,subject,monkeypatch,login):
    person,profile,url=subject
    def forbidden():raise AssertionError('domain called')
    monkeypatch.setattr(ar,'_domain_sessionmaker',forbidden)
    client=_login(login) if login else TestClient(main.app,base_url='https://testserver')
    try:
        assert client.get(url).status_code==(401 if login is None else 403)
        assert client.post(url,data={}).status_code==(401 if login is None else 403)
    finally:client.close()


@pytest.mark.parametrize('flag',['admin_kg_entry_enabled','admin_workday_enabled'])
def test_feature_off(env,subject,monkeypatch,flag):
    person,profile,url=subject;monkeypatch.setattr(ar.settings,flag,False)
    assert env['client'].get(url).status_code==404 and env['client'].post(url,data={}).status_code==404


def test_strict_form_fields_and_write_gate(env,subject,monkeypatch):
    person,profile,url=subject;values=summary(env,url)
    assert env['client'].post(url,json=values).status_code==415
    assert env['client'].post(url,data=values|{'passport_number':'private'}).status_code==422
    assert env['client'].post(url,data=values|{'passport':'a'*32}).status_code==422
    assert env['client'].post(url,content='a'*8193,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(url,content='a=1&a=2',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422
    assert env['client'].get(url+'?page=1&page=2').status_code==422
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    assert 'Запись отключена' in env['client'].get(url).text
    assert env['client'].post(url,data=values).status_code==403
    assert read(env,person)['current_revision']==0


def test_case_registry_failure_is_controlled_and_preserves_signed_retry(env,subject,monkeypatch):
    person,profile,url=subject;values=summary(env,url);actual=ui.entry._case
    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic case registry unavailable')
    monkeypatch.setattr(ui.entry,'_case',unavailable)
    for response in (env['client'].get(url),env['client'].post(url,data=values)):
        assert response.status_code==503 and response.headers['cache-control']=='no-store'
        assert response.headers['referrer-policy']=='no-referrer'
        assert not Form(response.text,'kg-ah-summary').data
    assert Form(response.text,'kg-ah-retry').data==values
    monkeypatch.setattr(ui.entry,'_case',actual)
    assert env['client'].post(url,data=values).status_code==200
    assert read(env,person)['current_revision']==1
