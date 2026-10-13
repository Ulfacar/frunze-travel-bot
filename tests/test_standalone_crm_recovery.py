"""Independent connected controls; synthetic records in the review archive only."""
import asyncio
from contextlib import asynccontextmanager

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select,update
from sqlalchemy.exc import OperationalError

from tests.test_standalone_crm import configured,crm,login,form,submit,counts,ORIGIN,PASSWORD
from app.config import settings
from app.crm_intake import CrmIntakeReceipt
from app.domain.models import ContactIdentity,ServiceCase
from app.integrations.crm.db import Conversation


@pytest.fixture(autouse=True)
def reviewer_current_panel_database(crm,monkeypatch):
    # Each synthetic database must own its panel store; production's singleton
    # otherwise retains the previous fixture's sessionmaker across tests.
    from app.integrations.panel import store
    monkeypatch.setattr(store,'_pg_store',store.PostgresConversationStore(crm['sm']))


@pytest.mark.parametrize('phone',['+372555123','+12345678'])
def test_manual_international_identity_survives_actual_case_open(crm,phone):
    client=crm['client'];assert login(client).status_code==303
    fields=form(client,'/admin/intake')|{'name':'Synthetic international person','phone':phone}
    saved=submit(client,'/admin/intake',fields);assert saved.status_code==303
    target=saved.headers['location']
    card=submit(client,target,form(client,target))
    assert card.status_code==303,card.text[-900:]
    case_id=int(card.headers['location'].rsplit('/',1)[1])
    async def actual():
        async with crm['sm']() as s:
            case=await s.get(ServiceCase,case_id)
            return list((await s.scalars(select(ContactIdentity.normalized_value).where(ContactIdentity.contact_id==case.contact_id))).all())
    assert asyncio.run(actual())==[phone[1:]],'Explicit international country code changed during native opening'


def test_intake_lost_commit_ack_has_original_signed_retry(crm,monkeypatch):
    import app.crm_intake as intake
    client=crm['client'];assert login(client).status_code==303
    fields=form(client,'/admin/intake')|{'name':'Synthetic uncertain intake','phone':'+996700222111'}
    sm=crm['sm'];state={'raise':True}
    class Proxy:
        def __init__(self,s):self.s=s
        def __getattr__(self,k):return getattr(self.s,k)
        async def __aenter__(self):await self.s.__aenter__();return self
        async def __aexit__(self,*args):return await self.s.__aexit__(*args)
        @asynccontextmanager
        async def begin(self):
            async with self.s.begin():yield
            if state['raise']:
                state['raise']=False
                raise OperationalError('synthetic commit ACK unavailable',{},Exception('synthetic'))
    monkeypatch.setattr(intake,'get_sessionmaker',lambda:lambda:Proxy(sm()))
    client.raise_server_exceptions=False
    client._transport.raise_server_exceptions=False
    response=submit(client,'/admin/intake',fields)
    assert counts(crm)['crm_intake_receipts']==1,'Fault must happen after actual commit'
    assert response.status_code==503,response.text
    soup=BeautifulSoup(response.text,'html.parser')
    retained={n['name']:n.get('value','') for n in soup.select('form[action="/admin/intake"] input[name]')}
    assert retained==fields
    assert submit(client,'/admin/intake',retained).status_code==303
    assert counts(crm)['conversations']==counts(crm)['crm_intake_receipts']==1


def test_exact_retry_refuses_changed_receipt_person_pointer(crm):
    client=crm['client'];assert login(client).status_code==303
    first=form(client,'/admin/intake')|{'name':'Synthetic first person','phone':'+996700111111'}
    second=form(client,'/admin/intake')|{'name':'Synthetic second person','phone':'+996700222222'}
    a=submit(client,'/admin/intake',first);b=submit(client,'/admin/intake',second)
    assert a.status_code==b.status_code==303
    async def corrupt():
        async with crm['sm']() as s,s.begin():
            other=await s.scalar(select(Conversation.id).where(Conversation.user_id=='manual_visa:996700222222'))
            await s.execute(update(CrmIntakeReceipt).where(CrmIntakeReceipt.request_key==first['request_key']).values(conversation_id=other))
    asyncio.run(corrupt())
    replay=submit(client,'/admin/intake',first)
    assert replay.status_code in (409,503),'Old exact request silently redirected to another person: '+str(replay.headers.get('location'))


def test_peer_scope_revocation_and_external_denial_are_server_enforced(crm,monkeypatch):
    from app.channels import outbound
    client=crm['client'];assert login(client,'medina').status_code==303
    fields=form(client,'/admin/intake')|{'name':'Synthetic owned intake','phone':'+996700333333'}
    saved=submit(client,'/admin/intake',fields);assert saved.status_code==303
    path=saved.headers['location'];before=counts(crm)
    called=[]
    async def never(*a,**kw):called.append((a,kw));raise AssertionError('Outbound reached')
    monkeypatch.setattr(outbound,'send_to_client',never)
    for route in ['/admin/conversation/manual_visa:996700333333/send','/admin/conversation/manual_visa:996700333333/resend/1','/admin/followup/run']:
        assert client.post(route,data={'text':'synthetic'},headers={'Origin':ORIGIN}).status_code in (404,405)
    assert not called and counts(crm)==before
    assert client.post('/admin/intake',data=fields,headers={'Origin':'https://sibling.crm.test'}).status_code==403
    from app.config import ManagerConfig
    original=list(settings.managers)
    monkeypatch.setattr(settings,'managers',original+[ManagerConfig(login='eliza',name='Synthetic peer',password=PASSWORD)])
    assert login(client,'eliza').status_code==303
    assert client.get(path).status_code==404
    assert submit(client,'/admin/intake',form(client,'/admin/intake')|{'name':'Peer','phone':fields['phone']}).status_code==409
    monkeypatch.setattr(settings,'managers',original)
    assert client.get('/admin/work').status_code==303
    assert client.post('/admin/intake',headers={'Origin':ORIGIN}).status_code==401
    assert counts(crm)==before


def test_visible_calendar_internal_task_create_is_connected(crm):
    from datetime import date,timedelta
    client=crm['client'];assert login(client).status_code==303
    page=client.get('/admin/calendar');assert page.status_code==200
    soup=BeautifulSoup(page.text,'html.parser')
    assert soup.select_one('form[action="/admin/calendar/task/create"]') is not None
    result=submit(client,'/admin/calendar/task/create',{
        'phone':'+996700444444','kind':'call','scheduled_date':(date.today()+timedelta(days=1)).isoformat(),
        'scheduled_time':'','priority':'normal','comment':'Synthetic internal review','view':'day','day':''})
    assert result.status_code==303,result.text
    from app.domain.models import CalendarTask
    async def actual():
        async with crm['sm']() as s:return list((await s.scalars(select(CalendarTask))).all())
    tasks=asyncio.run(actual());assert len(tasks)==1 and tasks[0].created_by=='admin'
