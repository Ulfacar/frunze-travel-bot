import asyncio
import re
from pathlib import Path
from urllib.parse import unquote

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient
from sqlalchemy import select,func,text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker

from app.config import settings,ManagerConfig
from app.crm_main import create_app,SCHEMA,COOKIE
from app.crm_intake import CrmIntakeReceipt
from app.domain.models import DomainBase,ServiceCase
from app.integrations.crm import db
from scripts.crm_initialize import bootstrap

ORIGIN='https://crm.test'
PASSWORD='SYNTHETIC-private-password-2026'


@pytest.fixture
def configured(monkeypatch,tmp_path):
    assert not Path('.env').exists()
    url='sqlite+aiosqlite:///'+str(tmp_path/'crm.db').replace('\\','/')
    values=dict(crm_standalone_enabled=True,crm_public_origin=ORIGIN,session_https_only=True,
        session_secret='SYNTHETIC-'+('x'*60),demo_login=False,admin_enabled=True,
        panel_backend='postgres',crm_backend='postgres',state_backend='memory',authz_enforce_enabled=True,
        bots=[],telegram_bots=[],database_url=url,admin_new_look_enabled=True,
        admin_workday_enabled=True,service_cases_enabled=True,admin_kg_entry_enabled=True,
        managers=[ManagerConfig(login='admin',name='Owner',password=PASSWORD,admin=True),
                  ManagerConfig(login='medina',name='Manager',password=PASSWORD),
                  ManagerConfig(login='aisina',name='Admin display name',password=PASSWORD)])
    for name in ('wappi_token','telegram_bot_token','openrouter_api_key','anthropic_api_key',
                 'stt_api_key','bitrix24_webhook_url','managers_telegram_bot_token','managers_telegram_chat_id'):
        values[name]=''
    for key,value in values.items():monkeypatch.setattr(settings,key,value)
    return url


@pytest.fixture
def crm(configured,monkeypatch):
    url=configured
    engine=create_async_engine(url)
    sm=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(db,'_engine',engine);monkeypatch.setattr(db,'_sessionmaker',sm)
    from app.integrations.panel import store
    monkeypatch.setattr(store,'_pg_store',None)
    async def prepare():
        async with engine.begin() as connection:
            await connection.run_sync(DomainBase.metadata.create_all)
            await connection.execute(text('CREATE TABLE alembic_version (version_num VARCHAR(64) PRIMARY KEY)'))
            await connection.execute(text('INSERT INTO alembic_version VALUES (:v)'),{'v':SCHEMA})
        await bootstrap(url,Path('release-source.pdf'),'admin')
    asyncio.run(prepare())
    from app.admin import ratelimit
    ratelimit.reset()
    app=create_app(test_sqlite=True)
    with TestClient(app,base_url=ORIGIN,follow_redirects=False) as client:
        yield dict(client=client,app=app,sm=sm,url=url,engine=engine)
    asyncio.run(engine.dispose())


def login(client,account='admin',password=PASSWORD):
    return client.post('/admin/login',data={'login':account,'password':password},headers={'Origin':ORIGIN})


def form(client,path):
    page=client.get(path)
    assert page.status_code==200,page.text[-500:]
    soup=BeautifulSoup(page.text,'html.parser')
    values={i['name']:i.get('value','') for i in soup.select('form input[name]')}
    for select in soup.select('form select[name]'):
        option=select.find('option',value=lambda v:bool(v))
        if option:values[select['name']]=option['value']
    return values


def submit(client,path,data):
    return client.post(path,data=data,headers={'Origin':ORIGIN})


def counts(crm):
    async def read():
        async with crm['sm']() as session:
            return {model.__tablename__:await session.scalar(select(func.count()).select_from(model))
                    for model in (db.Conversation,db.ConvMessage,CrmIntakeReceipt,ServiceCase)}
    return asyncio.run(read())


def test_fresh_login_manual_intake_preliminary_case_and_persistence(crm):
    client=crm['client']
    assert client.get('/admin/work').status_code==303
    assert login(client).status_code==303
    assert COOKIE in client.cookies
    data=form(client,'/admin/intake')|{'name':'Синтетический заявитель','phone':'+996 700 123 456'}
    result=submit(client,'/admin/intake',data)
    assert result.status_code==303,result.text
    preliminary=result.headers['location']
    assert counts(crm)=={'conversations':1,'messages':0,'crm_intake_receipts':1,'service_cases':0}
    assert submit(client,'/admin/intake',data).headers['location']==preliminary
    fields=form(client,preliminary)
    result=submit(client,preliminary,fields)
    assert result.status_code==303,result.text[-900:]
    card=result.headers['location']
    assert client.get(card).status_code==200
    assert client.get(card+'/kg-entry').status_code==200
    assert counts(crm)=={'conversations':1,'messages':0,'crm_intake_receipts':1,'service_cases':1}
    # A new ASGI instance and cookie login reads the durable same case.
    with TestClient(create_app(test_sqlite=True),base_url=ORIGIN,follow_redirects=False) as restarted:
        assert login(restarted).status_code==303
        assert restarted.get(card).status_code==200
        assert counts(crm)['service_cases']==1


def test_origin_session_revocation_and_denied_external_routes(crm,monkeypatch):
    client=crm['client']
    assert client.post('/admin/login',data={'login':'admin','password':PASSWORD}).status_code==403
    assert login(client,'администратор','пароль').status_code==401
    assert login(client).status_code==303
    before=counts(crm)
    for path in ('/admin/followup/run','/admin/conversation/none/send','/admin/conversation/none/resend/1',
                 '/admin/conversation/none/suggest','/admin/flags/admin_enabled','/admin/login/demo',
                 '/webhook/wappi','/webhook/telegram'):
        assert client.post(path,headers={'Origin':ORIGIN}).status_code in (404,405),path
    assert counts(crm)==before
    for origin in ('https://sibling.crm.test','https://evil.test','null'):
        assert client.post('/admin/logout',headers={'Origin':origin}).status_code==403
    assert client.get('/admin/work').status_code==200
    old=settings.managers[0]
    monkeypatch.setattr(settings,'managers',[old.model_copy(update={'password':'CHANGED-password-'+('p'*24)})])
    assert client.get('/admin/work').status_code==303
    assert client.post('/admin/intake',headers={'Origin':ORIGIN}).status_code==401


def test_manual_scope_retry_conflict_and_no_fake_channel(crm):
    client=crm['client'];assert login(client,'medina').status_code==303
    data=form(client,'/admin/intake')|{'name':'Synthetic manager case','phone':'+1 202 555 0123'}
    result=submit(client,'/admin/intake',data);assert result.status_code==303,result.text
    assert submit(client,'/admin/intake',data|{'name':'Other value'}).status_code==409
    assert submit(client,'/admin/intake',data|{'signature':'x'}).status_code==403
    assert submit(client,'/admin/intake',form(client,'/admin/intake')|{'name':'Wrong phone','phone':'+12025550123@g.us'}).status_code==422
    assert counts(crm)['messages']==0
    assert login(client,'aisina').status_code==303
    assert client.get('/admin/intake').status_code==403
    assert client.get(result.headers['location']).status_code==404


@pytest.mark.parametrize('change',[
    {'demo_login':True},{'session_https_only':False},{'session_secret':'short'},
    {'panel_backend':'memory'},{'authz_enforce_enabled':False},
    {'wappi_token':'SYNTHETIC'}, {'crm_public_origin':'http://crm.test'},
    {'managers':[]},
])
def test_unsafe_runtime_configuration_refused(configured,monkeypatch,change):
    for key,value in change.items():monkeypatch.setattr(settings,key,value)
    with pytest.raises(RuntimeError):create_app(test_sqlite=True)
