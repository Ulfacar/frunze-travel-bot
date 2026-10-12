"""Real signed native forms to the conditional reminder service."""
from urllib.parse import urlencode

import pytest

import app.admin.kg_work_review as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests import test_work_review_tasks as core
from tests.test_work_review_tasks import env,clock,review_clock,connected_clock,route_clock,admins,enforce_sqlite_foreign_keys
from tests.test_admin_kg_entry import Form
from tests.test_admin_workday import _login


def setup(env,tmp_path,monkeypatch):
    core.setup(env,tmp_path)
    monkeypatch.setattr(ar.settings,'kg_work_review_authorities',[env['review_authority'].document()])


def url(env,language='ru'):
    return ui._url((env['cases']['visa'],env['person']['id'],env['permit']['id']),language)


def form(env,action='refresh',language='ru'):
    page=env['client'].get(url(env,language));assert page.status_code==200,page.text[-1200:]
    fields=Form(page.text,'work-review-'+action).data;assert fields
    return fields|{'confirmed':'yes'}


def post(env,data,language='ru'):
    return env['client'].post(url(env,language),data=data,follow_redirects=False)


def test_native_scope_security_defaults_and_actual_task(env,tmp_path,monkeypatch):
    setup(env,tmp_path,monkeypatch)
    before=core.counts(env);data=form(env)
    assert env['client'].get(url(env)).headers['cache-control']=='no-store'
    assert core.counts(env)==before
    manager=_login('medina');assert manager.get(url(env)).status_code==403;manager.close()
    for change in ({'_wr_csrf':'0'*64},{'_wr_action':'cancel'},{'_wr_token':'0'*64}):
        assert post(env,data|change).status_code==403
    assert post(env,data|{'confirmed':'no'}).status_code==422
    assert post(env,data|{'extra':'bad'}).status_code==422
    assert env['client'].post(url(env),content=urlencode(data)+'&confirmed=yes',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422
    assert env['client'].post(url(env),content='x'*4097,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].get(url(env)+'&language=en').status_code==422
    assert post(env,data).status_code==303 and post(env,data).status_code==303
    assert core.counts(env)==[before[0]+1,before[1]+1]
    english=env['client'].get(url(env,'en'));assert 'Conditional date' in english.text and 'Create or reconcile reminder' in english.text
    monkeypatch.setattr(ar.settings,'kg_work_review_authorities',[])
    page=env['client'].get(url(env));assert 'Актуальное основание расчёта не подтверждено' in page.text
    assert post(env,data).status_code==303
    assert post(env,form(env,'cancel')).status_code==303
    assert core.read(env,authority=None)['current']['task']['status']=='cancelled'
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    assert post(env,data).status_code==403
    assert 'Сохранение отключено' in env['client'].get(url(env)).text
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url(env)).status_code==404


def test_native_lost_response_exact_retry_survives_failed_read(env,tmp_path,monkeypatch):
    setup(env,tmp_path,monkeypatch);data=form(env,language='en');before=core.counts(env)
    original=ui.service.record;reader=ui.service.read
    async def lost(*args,**kwargs):
        await original(*args,**kwargs)
        raise EntryStorageUnavailable('synthetic response lost')
    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic reader unavailable')
    monkeypatch.setattr(ui.service,'record',lost);monkeypatch.setattr(ui.service,'read',unavailable)
    response=post(env,data,'en');assert response.status_code==503 and 'save outcome is unknown' in response.text
    assert Form(response.text,'work-review-retry').data==data
    assert not Form(response.text,'work-review-refresh').data
    monkeypatch.setattr(ui.service,'record',original);monkeypatch.setattr(ui.service,'read',reader)
    assert post(env,Form(response.text,'work-review-retry').data,'en').status_code==303
    assert core.counts(env)==[before[0]+1,before[1]+1]
