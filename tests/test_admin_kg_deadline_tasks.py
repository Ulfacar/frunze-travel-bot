import asyncio
from urllib.parse import urlencode

import pytest

import app.admin.kg_deadline_tasks as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import ADMIN, Form, env
from tests.test_admin_workday import _login
from tests.test_entry_deadline_tasks import seed, read, sql
from tests.test_entry_deadlines import write, manual


def url(env,app,query=True):
    return env['url']+f"/applications/{app['id']}/deadline-tasks"+('?rule=KG.DL.TEST' if query else '')


def form(env,app,action):
    page=env['client'].get(url(env,app));assert page.status_code==200,page.text[-1000:]
    data=Form(page.text,f'kg-task-{action}').data;assert data
    return {**data,'confirmed':'yes'}


def post(env,app,data,client=None,**kwargs):
    return (client or env['client']).post(url(env,app,False),data=data,follow_redirects=False,**kwargs)


def test_native_enable_actions_and_retry_history(env):
    app=seed(env)
    assert 'Задача контроля срока' in env['client'].get(env['url']+f"/applications/{app['id']}/deadlines?rule=KG.DL.TEST").text
    initial=form(env,app,'sync');assert post(env,app,initial).status_code==303
    assert post(env,app,initial).status_code==303
    state=read(env,app)['current'];assert state['task']['owner']=='medina'
    raised=form(env,app,'escalate');raised['reason']='urgent'
    assert post(env,app,raised).status_code==303 and read(env,app)['current']['task']['priority']=='high'
    done=form(env,app,'complete')
    assert post(env,app,done).status_code==303 and post(env,app,done).status_code==303
    page=env['client'].get(url(env,app));assert 'Выполнена' in page.text and not Form(page.text,'kg-task-complete').data
    assert len(read(env,app)['history'])==1


def test_role_off_write_and_csrf_scope_gates(env,monkeypatch):
    app=seed(env);data=form(env,app,'sync')
    manager=_login('medina')
    assert manager.get(url(env,app)).status_code==403 and post(env,app,data,client=manager).status_code==403
    other=env['cases']['other'];foreign=url(env,app,False).replace(f"/case/{env['cases']['visa']}/",f'/case/{other}/')
    assert env['client'].post(foreign,data=data).status_code in (403,404)
    changed={**data,'_dt_rule':'KG.DL.OTHER'};assert post(env,app,changed).status_code==403
    assert post(env,app,{**data,'_dt_csrf':'tampered'}).status_code==403
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url(env,app)).status_code==404 and post(env,app,data).status_code==404
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    assert post(env,app,data).status_code==403
    page=env['client'].get(url(env,app));assert page.status_code==200 and 'Сохранение отключено' in page.text
    assert not read(env,app)['current']['enabled']


def test_strict_form_query_payload_confirmation_and_stale_token(env):
    app=seed(env);data=form(env,app,'sync')
    assert env['client'].get(url(env,app)+'&rule=KG.DL.TEST').status_code==422
    assert env['client'].get(url(env,app)+'&extra=1').status_code==422
    assert post(env,app,{**data,'extra':'1'}).status_code==422
    assert post(env,app,{**data,'confirmed':''}).status_code==422
    raw=urlencode(data)+'&confirmed=yes'
    assert env['client'].post(url(env,app,False),content=raw,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422
    assert env['client'].post(url(env,app,False),content='x'*4097,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(url(env,app,False),json=data).status_code==415
    assert post(env,app,data).status_code==303
    stale=form(env,app,'complete')
    write(env,app,'manual',manual(reason='corrected_date',due_on='2026-10-18'))
    assert post(env,app,stale).status_code==409 and read(env,app)['current']['task']['status']=='rescheduled'


def test_lost_response_recovery_hides_fresh_forms_and_preserves_request(env,monkeypatch):
    app=seed(env);post(env,app,form(env,app,'sync'));data=form(env,app,'cancel')
    original=ui.service.act_on_deadline_task
    async def lost(*args,**kwargs):
        await original(*args,**kwargs);raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    monkeypatch.setattr(ui.service,'act_on_deadline_task',lost)
    response=post(env,app,data)
    assert response.status_code==503 and Form(response.text,'kg-task-retry').data==data
    assert not Form(response.text,'kg-task-sync').data
    monkeypatch.setattr(ui.service,'act_on_deadline_task',original)
    assert post(env,app,Form(response.text,'kg-task-retry').data).status_code==303
    assert read(env,app)['current']['task']['status']=='cancelled'


def test_recovery_survives_failed_read_and_native_batch(env,monkeypatch):
    app=seed(env);post(env,app,form(env,app,'sync'));data=form(env,app,'complete')
    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic storage outage')
    original=ui.service.act_on_deadline_task;reader=ui.service.read_deadline_task
    monkeypatch.setattr(ui.service,'act_on_deadline_task',unavailable);monkeypatch.setattr(ui.service,'read_deadline_task',unavailable)
    result=post(env,app,data)
    assert result.status_code==503 and Form(result.text,'kg-task-retry').data==data
    monkeypatch.setattr(ui.service,'act_on_deadline_task',original);monkeypatch.setattr(ui.service,'read_deadline_task',reader)
    result=post(env,app,form(env,app,'sweep'))
    assert result.status_code==200 and 'Обработано правил: 1' in result.text
    assert 'Требуют повторной проверки: 0' in result.text


def test_native_schedule_conflict_explicit_restore(env):
    app=seed(env);post(env,app,form(env,app,'sync'))
    task=read(env,app)['current']['task']
    sql(env,"UPDATE calendar_tasks SET scheduled_date='2026-10-01' WHERE id=:id",id=task['id'])
    assert post(env,app,form(env,app,'sync')).status_code==303
    page=env['client'].get(url(env,app))
    assert 'Дата задачи изменена вручную' in page.text and not Form(page.text,'kg-task-complete').data
    assert post(env,app,form(env,app,'restore')).status_code==303
    assert read(env,app)['current']['task']['date']=='2026-10-20'
