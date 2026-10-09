import asyncio

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

import app.admin.kg_deadlines as ui
import app.admin.router as ar
import app.main as main
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form, env
from tests.test_admin_workday import _login
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_deadlines import setup, read


@pytest.fixture
def subject(env):
    app=setup(env)
    return app,ui._url(env['cases']['visa'],app['id'])


def form(env,url,action):
    response=env['client'].get(url)
    assert response.status_code==200,response.text[-1000:]
    values=Form(response.text,'kg-dl-'+action).data
    assert values
    return {**values,'confirmed':'yes'}


def test_native_unknown_manual_corrected_date_clear_and_history(env,subject):
    app,url=subject
    assert url in env['client'].get(env['url']+f"/applications?application_id={app['id']}").text
    page=env['client'].post(url,data=form(env,url,'recalculate'))
    assert page.status_code==200 and 'Точная дата пока неизвестна' in page.text
    values=form(env,url,'manual');values.update(due_on='2026-10-20',evidence_on='2026-09-10',proof='a'*64)
    page=env['client'].post(url,data=values)
    assert page.status_code==200 and '2026-10-20' in page.text
    assert read(env,app)['selected']['summary']['operational_due_on']=='2026-10-20'
    values=form(env,url,'manual');values.update(due_on='2026-10-19',evidence_on='2026-09-11',proof='b'*64,reason='corrected_date')
    assert env['client'].post(url,data=values).status_code==200
    old=env['client'].get(url+'?rule=KG.DL.TEST&revision=2')
    assert 'kg-dl-historical' in old.text and not Form(old.text,'kg-dl-manual').data
    assert '2026-10-20' in old.text and '2026-10-19' not in old.text
    assert env['client'].post(url,data=form(env,url,'clear')).status_code==200
    assert read(env,app)['selected']['summary']['operational_due_on'] is None


def test_lost_commit_retry_stale_and_cross_scope(env,subject,monkeypatch):
    app,url=subject;values=form(env,url,'recalculate');stale=form(env,url,'recalculate')
    other=_login('admin')
    try:assert other.post(url,data=values).status_code==403
    finally:other.close()
    foreign=ui._url(env['cases']['other'],app['id'])
    assert env['client'].get(foreign).status_code==404
    assert env['client'].post(foreign,data=values).status_code==403
    actual=ui.service.record_deadline_operation
    async def uncertain(*args,**kwargs):
        await actual(*args,**kwargs)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    monkeypatch.setattr(ui.service,'record_deadline_operation',uncertain)
    page=env['client'].post(url,data=values)
    assert page.status_code==503 and not Form(page.text,'kg-dl-recalculate').data
    retry=Form(page.text,'kg-dl-retry').data
    # An unselected multi-select has no successful HTML control on the wire.
    assert retry=={k:v for k,v in values.items() if v!=[]}
    monkeypatch.setattr(ui.service,'record_deadline_operation',actual)
    assert env['client'].post(url,data=retry).status_code==200
    assert env['client'].post(url,data=stale).status_code==409
    assert read(env,app)['current_revision']==1


def test_uncertain_commit_keeps_all_selected_calendars_in_recovery_form(env,subject,monkeypatch):
    from urllib.parse import urlencode
    from app.domain.entry_storage import import_work_calendars
    from tests.test_entry_storage import calendars
    from tests.test_admin_kg_entry import ADMIN
    app,url=subject
    imported=asyncio.run(import_work_calendars(env['engine'],actor=ADMIN,document=calendars()))
    values=form(env,url,'recalculate');values['calendar_id']=[str(row['calendar_id']) for row in imported]
    actual=ui.service.record_deadline_operation
    async def uncertain(*args,**kwargs):
        await actual(*args,**kwargs)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    monkeypatch.setattr(ui.service,'record_deadline_operation',uncertain)
    response=env['client'].post(url,data=values)
    assert response.status_code==503
    recovery=Form(response.text,'kg-dl-retry')
    pairs=[(a['name'],a.get('value','')) for tag,a in recovery.nodes if tag=='input' and a.get('name')]
    assert [value for key,value in pairs if key=='calendar_id']==values['calendar_id']
    monkeypatch.setattr(ui.service,'record_deadline_operation',actual)
    assert env['client'].post(url,content=urlencode(pairs),headers={'content-type':'application/x-www-form-urlencoded'}).status_code==200
    assert read(env,app)['current_revision']==1


@pytest.mark.parametrize('login',[None,'medina','ademi'])
def test_auth_before_storage(env,subject,monkeypatch,login):
    _,url=subject
    def forbidden():raise AssertionError('storage touched')
    monkeypatch.setattr(ar,'_domain_sessionmaker',forbidden)
    client=_login(login) if login else TestClient(main.app,base_url='https://testserver')
    try:
        assert client.get(url).status_code==(401 if login is None else 403)
        assert client.post(url,data={}).status_code==(401 if login is None else 403)
    finally:client.close()


def test_flags_strict_fields_and_invalid_date_preservation(env,subject,monkeypatch):
    app,url=subject;values=form(env,url,'recalculate')
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url).status_code==404 and env['client'].post(url,data=values).status_code==404
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    assert env['client'].get(url).status_code==200 and env['client'].post(url,data=values).status_code==403
    monkeypatch.setattr(ar.settings,'service_cases_enabled',True)
    assert env['client'].post(url,json=values).status_code==415
    assert env['client'].post(url,content='x'*8193,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(url,data={**values,'actual_date':'2026-01-01'}).status_code==422
    for query in ('?rule=private','?revision=1','?rule=KG.DL.TEST&revision=1&revision=2','?x=1'):
        assert env['client'].get(url+query).status_code==422
    assert env['client'].post(url,data=values).status_code==200
    values=form(env,url,'manual');values.update(due_on='bad-date',evidence_on='2026-09-10',proof='a'*64)
    page=env['client'].post(url,data=values)
    assert page.status_code==422 and Form(page.text,'kg-dl-manual').data['due_on']=='bad-date'
    assert read(env,app)['current_revision']==1


def test_corrupt_storage_hides_mutating_forms(env,subject):
    _,url=subject;env['client'].post(url,data=form(env,url,'recalculate'))
    async def corrupt():
        async with env['engine'].begin() as conn:
            await conn.execute(text("UPDATE entry_deadline_revisions SET snapshot_hash=:hash"),{'hash':'0'*64})
    asyncio.run(corrupt())
    page=env['client'].get(url+'?rule=KG.DL.TEST')
    assert page.status_code==503 and not Form(page.text,'kg-dl-recalculate').data
