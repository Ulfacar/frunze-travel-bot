"""Independent connected UI controls; original PDF, synthetic policies, SQLite."""
import asyncio
import json

import pytest
from fastapi import HTTPException

import app.admin.kg_specialist as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable, _hash
from app.domain.specialist_policy import SpecialistPolicy
from tests.test_admin_kg_entry import Form
from tests.test_admin_kg_specialist import configure, url, fields, positive
from tests.test_specialist_decisions import (
    env, admins, clock, enforce_sqlite_foreign_keys, setup, read, record,
    quote_policy, quote_preview,
)
from tests.test_quote_rules import recipe


def prepare(env, tmp_path, monkeypatch, language='en'):
    setup(env,tmp_path,language=language);configure(env,monkeypatch)
    path=url(env,language)
    page=env['client'].get(path);assert page.status_code==200
    data=positive(env,fields(page,'record'))
    prepared=env['client'].post(path,data=data,follow_redirects=False)
    assert prepared.status_code==200
    assert read(env)['revision']==0
    return path,prepared,fields(prepared,'save')


def test_ru_confirmation_has_readable_material_fact_labels(env,tmp_path,monkeypatch):
    path,page,save=prepare(env,tmp_path,monkeypatch,'ru')
    section=page.text.split('id="specialist-confirmation"',1)[1].split('</section>',1)[0]
    assert '????' not in section, 'Russian confirmation contains literal question-mark labels'
    assert 'Дата проверки' in section or 'Дата рассмотрения' in section
    assert 'Принимающ' in section
    assert all(row['reference'] in section and row['proof'] in section for row in env['findings']['evidence'])
    assert json.loads(save['_sp_payload'])['findings']==env['findings']


def test_incomplete_quote_is_a_reviewable_internal_estimate(env,tmp_path,monkeypatch):
    setup(env,tmp_path,language='en')
    r=recipe(id='SYN-B')  # Approved synthetic recipe expressly leaves the bank fee unknown.
    env['quote_policy']=quote_policy(r)
    p=env['policy'].document();p['capabilities'][0]['quote_policy_hash']=env['quote_policy'].digest
    p['capabilities'][0]['recipes'][0]['hash']=_hash(r);env['policy']=SpecialistPolicy(p)
    configure(env,monkeypatch);saved=record(env)
    domain=quote_preview(env,saved)['preview']['quote']['result']
    assert domain['complete'] is False and domain['totals_by_currency'] is None
    path=url(env,'en');page=env['client'].get(path)
    response=env['client'].post(path,data=fields(page,'preview'),follow_redirects=False)
    assert response.status_code==200,response.text[-2500:]
    assert 'The complete price is not yet known.' in response.text
    assert response.text.count('50.00 USD')==2
    assert 'Unknown' in response.text
    assert read(env)['revision']==1
    assert env['client'].post(path,data=fields(response,'save'),follow_redirects=False).status_code==303
    assert read(env)['revision']==2


@pytest.mark.parametrize('method',['get','post'])
def test_case_registry_outage_is_controlled_and_keeps_original_post(env,tmp_path,monkeypatch,method):
    path,page,save=prepare(env,tmp_path,monkeypatch)
    calls=[]
    async def unavailable(*a,**kw):
        calls.append(1)
        raise EntryStorageUnavailable('synthetic case registry outage')
    monkeypatch.setattr(ui.entry,'_case',unavailable)
    env['client']._transport.raise_server_exceptions=False
    response=env['client'].get(path) if method=='get' else env['client'].post(path,data=save,follow_redirects=False)
    assert response.status_code==503, (response.status_code,response.text[-800:])
    assert response.headers['cache-control']=='no-store'
    assert not Form(response.text,'specialist-record').data
    if method=='post':
        assert fields(response,'retry')==save
        before=len(calls)
        assert env['client'].post(path,data=save|{'_sp_payload':'{}'},follow_redirects=False).status_code==403
        assert len(calls)==before
    for status in (403,404):
        async def denied(*a,status=status,**kw):raise HTTPException(status)
        monkeypatch.setattr(ui.entry,'_case',denied)
        response=env['client'].get(path) if method=='get' else env['client'].post(path,data=save,follow_redirects=False)
        assert response.status_code==status
    assert read(env)['revision']==0


def test_known_domain_error_classes_preserve_exact_confirmation_and_recover(env,tmp_path,monkeypatch):
    path,page,save=prepare(env,tmp_path,monkeypatch)
    original=ui.service.record_decision
    for changed in (path.replace('/case/1/','/case/2/'),path.replace('/applicants/1/','/applicants/2/'),
                    path.replace('/applications/1/','/applications/2/'),path.replace('language=en','language=ru')):
        assert changed!=path
        assert env['client'].post(changed,data=save,follow_redirects=False).status_code==403
    with monkeypatch.context() as m:
        m.setattr(ar.settings,'admin_user','removed-admin')
        m.setattr(ar.settings,'managers',[manager for manager in ar.settings.managers if manager.login!='admin'])
        assert env['client'].get(path).status_code==403
        assert env['client'].post(path,data=save,follow_redirects=False).status_code==403
    for status,error in [(409,EntryStorageConflict),(422,EntryStorageInvalid),(503,EntryStorageUnavailable)]:
        async def fail(*a,kind=error,**kw):
            if kind is EntryStorageUnavailable:await original(*a,**kw)
            raise kind('synthetic bounded failure')
        monkeypatch.setattr(ui.service,'record_decision',fail)
        response=env['client'].post(path,data=save,follow_redirects=False)
        assert response.status_code==status
        assert response.headers['cache-control']=='no-store'
        assert fields(response,'retry')==save
        assert not Form(response.text,'specialist-record').data
        assert read(env)['revision']==(1 if status==503 else 0)
    monkeypatch.setattr(ui.service,'record_decision',original)
    assert env['client'].post(path,data=save,follow_redirects=False).status_code==303
    assert read(env)['revision']==1
