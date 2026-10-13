"""Independent real HTTP security, stale-head and retained-retry controls."""
import asyncio
from pathlib import Path
from urllib.parse import urlencode
from sqlalchemy import func,select
from app.domain.models import EntryDeadlineRevision,CalendarTask
from app.domain.entry_storage import EntryStorageUnavailable
from tests import test_admin_operator_sop as native,test_entry_interviews as interviews
from tests.test_admin_operator_sop import env,enforce_sqlite_foreign_keys
from tests.test_entry_interviews import admins
from tests.test_admin_kg_entry import Form
from tests.test_admin_workday import _login

def counts(env):
    async def read():
        async with env['sm']() as session:
            return [await session.scalar(select(func.count()).select_from(t)) for t in (EntryDeadlineRevision,CalendarTask)]
    return asyncio.run(read())

def save_html(name,response):
    p=Path('runs/reviewer-http');p.mkdir(parents=True,exist_ok=True)
    (p/(name+'.html')).write_text(response.text,encoding='utf-8')

def test_security_actual_stale_source_date_only_and_privacy(env,tmp_path,monkeypatch):
    native.setup(env,tmp_path,monkeypatch);data=native.schedule(env,'en');before=counts(env)
    for key in ('csrf','signature'):
        for value in ('я'*64,'A'*64,'0'*63):assert native.post(env,data|{key:value},'en').status_code==403
    for key in ('key','evidence_hash','revision'):
        assert native.post(env,data|{key:'1'*64 if key!='revision' else '77'},'en').status_code==403
    assert native.post(env,data|{'time':'24:00'},'en').status_code==422
    assert native.post(env,data|{'on':'2026-02-30'},'en').status_code==422
    assert native.post(env,data|{'confirmed':'no'},'en').status_code==422
    for field,value in [('reference','FAKE-OFFICIAL'),('proof','f'*64)]:
        assert native.post(env,data|{field:value},'en').status_code==422
    headers={'content-type':'application/x-www-form-urlencoded'}
    assert env['client'].post(native.url(env,'en'),content=urlencode(data)+'&confirmed=yes',headers=headers).status_code==422
    assert env['client'].post(native.url(env,'en'),content=b'x'*8193,headers=headers).status_code==413
    assert env['client'].get(native.url(env,'en')+'&language=ru').status_code==422
    assert env['client'].get(native.url(env,'en')+'&extra=value').status_code==422
    ids=env['ids'];other=native.core.processes.setup(env,applicant=native.core.person(env,'OTHER'),key='OTHER')
    for wrong in ((ids[0],other['applicant_id'],ids[2]),(ids[0],ids[1],2147483647),(env['cases']['other'],ids[1],ids[2])):
        assert env['client'].get(native.ui.url(wrong,'en',env['rule'])).status_code==404
        assert env['client'].post(native.ui.url(wrong,'en',env['rule']),data=data).status_code==403
    for login,expected in (('admin',403),('medina',403)):
        client=_login(login)
        try:assert client.post(native.url(env,'en'),data=data).status_code==expected
        finally:client.close()
    assert counts(env)==before
    # The corrected wait guard deliberately ends LEAD_RESPONSE after a real
    # conversation; change only the own profile revision to keep V01 eligible.
    native.core.profiles.save(env,env['prepared'][0],revision=1,key='REVIEWER-PROFILE-HEAD')
    response=native.post(env,data,'en');assert response.status_code==409;save_html('stale-head',response)
    assert counts(env)==before
    data=native.schedule(env,'en')|{'time':''}
    assert native.post(env,data,'en').status_code==303
    assert native.post(env,native.form(env,'reconcile','en'),'en').status_code==303
    page=env['client'].get(native.url(env,'en'));assert 'No exact time' in page.text
    iv=interviews.start(env,env['prepared'][0])
    interviews.action(env,iv,'interrupt',operation={'action':'interrupt','reason':'consent_withdrawn'},policy=None)
    page=env['client'].get(native.url(env,'en'));save_html('privacy-stopped',page)
    assert page.status_code==200 and 'id="sop-operator_review"' not in page.text
    assert 'id="sop-operator_review_clear"' in page.text
    assert native.post(env,native.form(env,'operator_review_clear','en'),'en').status_code==303
    assert 'Cancelled' in env['client'].get(native.url(env,'en')).text

def test_registry_outage_and_lost_commit_with_healthy_reader_keep_original(env,tmp_path,monkeypatch):
    native.setup(env,tmp_path,monkeypatch);data=native.schedule(env,'en');before=counts(env)
    original_case=native.ui.service.sources.apps._case
    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic-case-unavailable')
    monkeypatch.setattr(native.ui.service.sources.apps,'_case',unavailable)
    page=env['client'].get(native.url(env,'en'));assert page.status_code==503
    assert 'id="sop-operator_review"' not in page.text
    response=native.post(env,data,'en');assert response.status_code==503
    assert Form(response.text,'sop-retry').data==data
    assert 'id="sop-operator_review"' not in response.text
    save_html('registry-post-retry',response)
    monkeypatch.setattr(native.ui.service.sources.apps,'_case',original_case)
    assert counts(env)==before
    original_record=native.ui.service.record
    async def lost(*args,**kwargs):
        await original_record(*args,**kwargs)
        raise EntryStorageUnavailable('synthetic-committed-ack-lost')
    monkeypatch.setattr(native.ui.service,'record',lost)
    response=native.post(env,data,'en');assert response.status_code==503
    assert response.headers['cache-control']=='no-store'
    assert Form(response.text,'sop-retry').data==data
    assert 'id="sop-operator_review"' not in response.text and 'id="sop-reconcile"' not in response.text
    save_html('lost-commit-healthy-reader',response)
    assert counts(env)==[before[0]+1,before[1]]
    monkeypatch.setattr(native.ui.service,'record',original_record)
    monkeypatch.setattr(native.ar.settings,'kg_operator_sop_authorities',[])
    assert native.post(env,data,'en').status_code==303
    assert native.post(env,data,'en').status_code==303
    assert counts(env)==[before[0]+1,before[1]]
