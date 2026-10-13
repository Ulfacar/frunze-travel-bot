"""Native exact-time reviews: signed source context, retries and private errors."""
from urllib.parse import urlencode

import app.admin.kg_sop_reviews as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests import test_operator_sop_reviews as core
from tests.test_operator_sop_reviews import env,enforce_sqlite_foreign_keys
from tests.test_admin_kg_entry import Form


def setup(env,tmp_path,monkeypatch):
    prepared=core.setup(env,tmp_path)
    monkeypatch.setattr(ar.settings,'kg_operator_sop_authorities',[prepared[-1].document])
    env.update(prepared=prepared,rule=prepared[-1].policy.document['rule_id'],ids=(prepared[1]['case_id'],prepared[0]['id'],prepared[1]['id']))


def url(env,language='ru'):return ui.url(env['ids'],language,env['rule'])


def form(env,name,language='ru'):
    response=env['client'].get(url(env,language));assert response.status_code==200,response.text[-1800:]
    data=Form(response.text,'sop-'+name).data;assert data
    return data|{'confirmed':'yes'}


def post(env,data,language='ru'):return env['client'].post(url(env,language),data=data,follow_redirects=False)


def schedule(env,language='ru'):
    return form(env,'operator_review',language)|dict(on='2026-11-02',time='00:30',reason='verify_missing_facts')


def test_native_manual_time_reconcile_clear_and_signed_security(env,tmp_path,monkeypatch):
    setup(env,tmp_path,monkeypatch);data=schedule(env)
    assert post(env,data|{'signature':'ю'*64}).status_code==403
    assert post(env,data|{'signature':'0'*64}).status_code==403
    assert post(env,data|{'revision':'99'}).status_code==403
    assert post(env,data|{'confirmed':'no'}).status_code==422
    assert post(env,data|{'time':'12:30:00'}).status_code==422
    assert env['client'].post(url(env),content=urlencode(data)+'&confirmed=yes',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422
    assert post(env,data).status_code==303
    assert post(env,data).status_code==303
    assert post(env,form(env,'reconcile')).status_code==303
    for language in ('ru','en'):
        response=env['client'].get(url(env,language))
        assert response.status_code==200 and '00:30' in response.text and '2026-11-02' in response.text
        assert 'Asia/Bishkek' in response.text and response.headers['cache-control']=='no-store'
    monkeypatch.setattr(ar.settings,'kg_operator_sop_authorities',[])
    assert post(env,form(env,'operator_review_clear')).status_code==303
    assert 'Cancelled' in env['client'].get(url(env,'en')).text


def test_lost_commit_retains_original_time_command_when_reader_unavailable(env,tmp_path,monkeypatch):
    setup(env,tmp_path,monkeypatch);data=schedule(env,'en')
    record=ui.service.record;preview=ui.service.preview
    async def lost(*args,**kwargs):
        await record(*args,**kwargs);raise EntryStorageUnavailable('synthetic-lost-ack')
    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic-read-lost')
    monkeypatch.setattr(ui.service,'record',lost);monkeypatch.setattr(ui.service,'preview',unavailable)
    response=post(env,data,'en');assert response.status_code==503
    original=Form(response.text,'sop-retry').data;assert original==data
    monkeypatch.setattr(ui.service,'record',record);monkeypatch.setattr(ui.service,'preview',preview)
    monkeypatch.setattr(ar.settings,'kg_operator_sop_authorities',[])
    assert post(env,original,'en').status_code==303
