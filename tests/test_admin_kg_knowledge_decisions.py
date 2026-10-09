import pytest

import app.admin.kg_knowledge_decisions as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form, env
from tests.test_admin_workday import _login
from tests.test_knowledge_decisions import read


def url(env):return ui.URL+f"?version={env['version']}&unit=KG.DL.TEST"


def form(env,verdict='confirmed'):
    page=env['client'].get(url(env));assert page.status_code==200,page.text[-1000:]
    data=Form(page.text,'kg-review-'+verdict).data;assert data
    data.update(evidence_ref='SYNTHETIC-01',proof='a'*64,verified_on='2026-09-01',confirmed='yes')
    if verdict=='confirmed':data['review_due_on']='2026-12-01'
    return data


def post(env,data,client=None):return (client or env['client']).post(ui.URL,data=data,follow_redirects=False)


def test_catalog_native_confirmation_rejection_history_and_exact_retry(env):
    assert ui.URL in env['client'].get('/admin/kg-entry/knowledge').text
    catalog=env['client'].get(ui.URL);assert catalog.status_code==200 and 'KG.DL.TEST' in catalog.text
    first=form(env);assert post(env,first).status_code==303
    assert post(env,first).status_code==303 and read(env)['current_revision']==1
    second=form(env,'rejected');second['reason']='outdated'
    assert post(env,second).status_code==303
    page=env['client'].get(url(env));assert 'Сведения устарели' in page.text
    old=env['client'].get(url(env)+'&revision=1')
    assert old.status_code==200 and 'Предыдущая запись доступна' in old.text
    assert not Form(old.text,'kg-review-confirmed').data and '2026-12-01' in old.text
    assert read(env)['unit']['value'] is not None and not read(env)['publication_approved']


def test_auth_off_write_csrf_and_source_scope(env,monkeypatch):
    data=form(env);manager=_login('medina')
    assert manager.get(ui.URL).status_code==403 and post(env,data,client=manager).status_code==403
    for changed in ({'_kd_unit':'KG.DL.OTHER'},{'_kd_version':'999'},{'_kd_verdict':'rejected'},{'_kd_csrf':'wrong'}):
        assert post(env,{**data,**changed}).status_code==403
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(ui.URL).status_code==404 and post(env,data).status_code==404
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True);monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    assert post(env,data).status_code==403
    page=env['client'].get(url(env));assert page.status_code==200 and 'Сохранение отключено' in page.text
    assert read(env)['current_revision']==0


def test_strict_fields_invalid_evidence_echo_and_conflict(env):
    from urllib.parse import urlencode
    data=form(env)
    for suffix in ('&version=1','&extra=x','&page=2','&q=%0A'):
        assert env['client'].get(url(env)+suffix).status_code==422
    assert env['client'].get(ui.URL+'?unit=KG.DL.TEST').status_code==422
    assert post(env,{**data,'extra':'unknown'}).status_code==422
    assert env['client'].post(ui.URL,content=urlencode(data)+'&confirmed=yes',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422
    assert env['client'].post(ui.URL,json=data).status_code==415
    assert env['client'].post(ui.URL,content='x'*4097,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    bad={**data,'review_due_on':''}
    page=post(env,bad);assert page.status_code==422
    echo=Form(page.text,'kg-review-confirmed').data
    assert echo['_kd_key']==data['_kd_key'] and echo['proof']==data['proof']
    assert post(env,data).status_code==303
    stale={**data,'_kd_key':'f'*48};assert post(env,stale).status_code==403
    # A second independently signed form from revision zero cannot overwrite one.
    fresh=form(env,'needs_changes');assert post(env,fresh).status_code==303
    other={**data,'proof':'b'*64};assert post(env,other).status_code==409


def test_lost_ack_recovery_and_failed_reread_keep_exact_request(env,monkeypatch):
    data=form(env);original=ui.service.record_knowledge_decision;reader=ui.service.read_knowledge_decisions
    async def lost(*args,**kwargs):
        await original(*args,**kwargs);raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    async def unreadable(*args,**kwargs):raise EntryStorageUnavailable('synthetic read failure')
    monkeypatch.setattr(ui.service,'record_knowledge_decision',lost);monkeypatch.setattr(ui.service,'read_knowledge_decisions',unreadable)
    response=post(env,data)
    assert response.status_code==503 and Form(response.text,'kg-review-retry').data==data
    assert not Form(response.text,'kg-review-confirmed').data
    monkeypatch.setattr(ui.service,'record_knowledge_decision',original);monkeypatch.setattr(ui.service,'read_knowledge_decisions',reader)
    assert post(env,Form(response.text,'kg-review-retry').data).status_code==303 and read(env)['current_revision']==1


def test_corrupt_source_disables_review_and_get_never_writes(env):
    from tests.test_knowledge_decisions import sql
    page=env['client'].get(url(env));assert page.status_code==200
    assert read(env)['current_revision']==0
    sql(env,'UPDATE knowledge_versions SET bundle_hash=:hash WHERE id=:id',hash='0'*64,id=env['version'])
    page=env['client'].get(url(env));assert page.status_code==503 and not Form(page.text,'kg-review-confirmed').data
