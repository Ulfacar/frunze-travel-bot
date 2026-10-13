import asyncio
from datetime import date,timedelta
from urllib.parse import unquote

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from tests.test_standalone_crm import configured,crm,login,form,submit,ORIGIN,PASSWORD
from tests.test_standalone_crm_recovery import reviewer_current_panel_database
from app.config import settings,ManagerConfig
from app.domain.models import CalendarTask,ContactIdentity


def task_rows(crm):
    async def read():
        async with crm['sm']() as s:
            rows=list((await s.scalars(select(CalendarTask).order_by(CalendarTask.id))).all())
            return [(r.id,r.manager_id,r.direction,r.user_id,r.status,r.scheduled_date,r.scheduled_at,
                     await s.scalar(select(ContactIdentity.normalized_value).where(ContactIdentity.contact_id==r.contact_id))) for r in rows]
    return asyncio.run(read())


def task_fields(phone,**kw):
    return dict(phone=phone,kind='call',scheduled_date=(date.today()+timedelta(days=3)).isoformat(),
                scheduled_time='00:30',priority='normal',comment='Synthetic owned calendar task',view='day',day='',**kw)


def test_real_foreign_calendar_and_card_tasks_keep_identity_and_owner(crm,monkeypatch):
    client=crm['client'];assert login(client,'medina').status_code==303
    for phone in ('+372555123','+12345678'):
        assert submit(client,'/admin/calendar/task/create',task_fields(phone)).status_code==303
        f=form(client,'/admin/intake')|dict(name='Synthetic task subject',phone=phone)
        opened=submit(client,'/admin/intake',f);assert opened.status_code==303
        uid=unquote(opened.headers['location'].split('/conversation/')[1].split('/preliminary')[0])
        data=task_fields(phone);data.pop('phone');data.pop('view');data.pop('day')
        assert submit(client,f'/admin/conversation/{uid}/task/create',data).status_code==200
        assert submit(client,f'/admin/conversation/{uid}/task/create',data|{'direction':'tours'}).status_code==403
    before=task_rows(crm);assert len(before)==4
    assert [r[7] for r in before]==['372555123','372555123','12345678','12345678']
    assert all(r[1:3]==('medina','visa') for r in before)
    monkeypatch.setattr(settings,'managers',list(settings.managers)+[ManagerConfig(login='eliza',name='Peer',password=PASSWORD)])
    assert login(client,'eliza').status_code==303
    for row in before:
        assert submit(client,f'/admin/calendar/task/{row[0]}/complete',{}).status_code in (303,403,404)
        assert submit(client,f'/admin/calendar/task/{row[0]}/cancel',{}).status_code in (303,403,404)
        assert submit(client,f'/admin/calendar/task/{row[0]}/reschedule',{'scheduled_date':'2030-01-01'}).status_code in (303,403,404)
    assert task_rows(crm)==before
    assert submit(client,'/admin/calendar/task/create',task_fields('+372555123')).status_code==404
    assert 'Synthetic owned calendar task' not in client.get('/admin/calendar').text
    assert login(client,'aisina').status_code==303
    assert submit(client,'/admin/calendar/task/create',task_fields('+996700888888')).status_code==403
    assert task_rows(crm)==before
    assert login(client,'medina').status_code==303
    quick,card=before[:2]
    next_day=(date.today()+timedelta(days=5)).isoformat()
    assert submit(client,f'/admin/calendar/task/{quick[0]}/reschedule',{'scheduled_date':next_day,'scheduled_time':'00:30'}).status_code==303
    moved=task_rows(crm)[0];assert moved[4]=='rescheduled' and moved[5].isoformat()==next_day
    assert moved[6].hour==18 and moved[6].minute==30 and moved[6].date()==date.fromisoformat(next_day)-timedelta(days=1)
    assert submit(client,f'/admin/calendar/task/{quick[0]}/complete',{}).status_code==303
    assert submit(client,f'/admin/conversation/{card[3]}/task/{card[0]}/cancel',{}).status_code==200
    final=task_rows(crm);assert final[0][4]=='completed' and final[1][4]=='cancelled'


def test_task_action_storage_failure_is_not_reported_as_normal_redirect(crm,monkeypatch):
    from app.domain.calendar_tasks import CalendarTaskService
    client=crm['client'];assert login(client,'medina').status_code==303
    assert submit(client,'/admin/calendar/task/create',task_fields('+996700555555')).status_code==303
    old=task_rows(crm);assert len(old)==1
    async def unavailable(*a,**kw):raise OperationalError('synthetic unavailable',{},Exception('synthetic'))
    monkeypatch.setattr(CalendarTaskService,'complete',unavailable)
    result=submit(client,f'/admin/calendar/task/{old[0][0]}/complete',{})
    assert task_rows(crm)==old
    assert result.status_code==503,result.text
