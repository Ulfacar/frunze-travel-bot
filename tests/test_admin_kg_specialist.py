"""Native forms use the actual retained source and synthetic explicit policies."""
import asyncio
import json
from urllib.parse import urlencode

import pytest

import app.admin.kg_specialist as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form
from tests.test_admin_workday import _login
from tests.test_specialist_decisions import env,admins,clock,enforce_sqlite_foreign_keys,setup,read,ON,POLICY


def configure(env,monkeypatch):
    monkeypatch.setattr(ar.settings,'kg_specialist_policy',env['policy'].document())
    monkeypatch.setattr(ar.settings,'kg_interview_policy',env['interview_policy'].document())
    monkeypatch.setattr(ar.settings,'kg_quote_policy',env['quote_policy'].document())
    monkeypatch.setattr(ar.settings,'kg_knowledge_policy_ref',POLICY.reference)
    monkeypatch.setattr(ar.settings,'kg_knowledge_policy_sha256',POLICY.fingerprint)
    monkeypatch.setattr(ar.settings,'kg_knowledge_publishers',list(POLICY.publishers))


def url(env,language='ru'):
    return ui._url(env['cases']['visa'],env['person']['id'],env['application']['id'],language)


def fields(page,action):
    data=Form(page.text,'specialist-'+action).data
    assert data.get('_sp_action'),page.text[-1600:]
    return data


def positive(env,data):
    data=data|dict(disposition='manual_internal_plan',reviewed_on=ON,meeting_nonprofit='yes',local_work='no',host_legal_entity_in_kg='yes')
    for row in env['findings']['evidence']:
        for key in ('reference','proof','on'):data[row['fact']+'_'+key]=row[key]
    return data


@pytest.mark.parametrize('language',['ru','en'])
def test_native_review_confirm_quote_withdraw_original_retry_and_authentication(env,tmp_path,monkeypatch,language):
    setup(env,tmp_path,language=language);configure(env,monkeypatch);path=url(env,language)
    def post(data):return env['client'].post(path,data=data,follow_redirects=False)
    page=env['client'].get(path);assert page.status_code==200 and page.headers['cache-control']=='no-store'
    assert read(env)['revision']==0
    data=positive(env,fields(page,'record'))
    for change in ({'_sp_revision':'1'},{'_sp_payload':'{}'},{'_sp_csrf':'f'*64},{'_sp_language':'en' if language=='ru' else 'ru'}):
        assert post(data|change).status_code==403
    for body in (urlencode(data)+'&local_work=yes',urlencode(data)+'&price=0',urlencode(data)+'&blob='+'x'*66000):
        assert env['client'].post(path,content=body,headers={'Content-Type':'application/x-www-form-urlencoded'}).status_code==422
    outsider=_login('medina')
    try:assert outsider.get(path).status_code==403 and outsider.post(path,data=data).status_code==403
    finally:outsider.close()
    prepared=post(data);assert prepared.status_code==200 and read(env)['revision']==0
    save=fields(prepared,'save');assert post(save).status_code==303 and post(save).status_code==303
    assert read(env)['revision']==1
    page=env['client'].get(path);q=fields(page,'preview');shown=post(q)
    assert shown.status_code==200 and '100.00 USD' in shown.text and read(env)['revision']==1
    quote_save=fields(shown,'save')
    original=ui.service.record_decision;original_read=ui.service.read_decisions
    async def lost(*a,**kw):await original(*a,**kw);raise EntryStorageUnavailable('synthetic lost response')
    async def unavailable(*a,**kw):raise EntryStorageUnavailable('synthetic reread unavailable')
    monkeypatch.setattr(ui.service,'record_decision',lost)
    healthy_reread=post(quote_save);assert healthy_reread.status_code==503
    assert fields(healthy_reread,'retry')==quote_save
    monkeypatch.setattr(ui.service,'read_decisions',unavailable)
    response=post(quote_save);assert response.status_code==503
    retry=fields(response,'retry');assert retry==quote_save
    monkeypatch.setattr(ui.service,'record_decision',original);monkeypatch.setattr(ui.service,'read_decisions',original_read)
    monkeypatch.setattr(ar.settings,'kg_specialist_policy',{})
    monkeypatch.setattr(ar.settings,'kg_knowledge_policy_ref','')
    monkeypatch.setattr(ar.settings,'kg_knowledge_policy_sha256','')
    monkeypatch.setattr(ar.settings,'kg_knowledge_publishers',[])
    assert post(retry).status_code==303 and read(env)['revision']==2
    page=env['client'].get(path);assert page.status_code==200
    wd=fields(page,'withdraw')|dict(reason_code='correction_required',reason_reference='SYN-WITHDRAW',reason_proof='a'*64,reason_on=ON)
    confirmed=post(wd);assert confirmed.status_code==200
    assert post(fields(confirmed,'save')).status_code==303
    assert read(env)['revision']==3 and not read(env)['current']['usable_for_internal_quote']
    assert post(save).status_code==303 and post(quote_save).status_code==303 and read(env)['revision']==3
    monkeypatch.setattr(ui.entry,'_write_on',lambda request:False)
    assert post(save).status_code==403
