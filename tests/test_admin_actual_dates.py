"""Signed native actual evidence and conditional tasks; no JavaScript required."""
from urllib.parse import urlencode

import app.admin.kg_actual_dates as ui
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests import test_conditional_deadlines as core
from tests.test_conditional_deadlines import env,clock,enforce_sqlite_foreign_keys
from tests.test_admin_kg_entry import Form
from tests.test_admin_workday import _login


def setup(env,tmp_path,monkeypatch):
    prepared=core.setup(env,tmp_path);rule='KG.DL.INTERNAL_EAEU_REG_REVIEW';authority=core.authority(env,rule)
    monkeypatch.setattr(ar.settings,'kg_actual_anchor_policy',authority.anchors.document)
    monkeypatch.setattr(ar.settings,'kg_conditional_deadline_authorities',[authority.document])
    env.update(prepared=prepared,authority=authority,rule=rule,ids=(prepared[1]['case_id'],prepared[0]['id'],prepared[1]['id']))


def url(env,language='ru'):return ui.url(env['ids'],language,env['rule'])


def form(env,name,language='ru'):
    response=env['client'].get(url(env,language));assert response.status_code==200,response.text[-1500:]
    data=Form(response.text,'actual-dates-'+name).data;assert data
    return data|{'confirmed':'yes'}


def post(env,data,language='ru'):return env['client'].post(url(env,language),data=data,follow_redirects=False)


def test_native_actual_correction_saved_review_reconcile_and_security(env,tmp_path,monkeypatch):
    setup(env,tmp_path,monkeypatch)
    data=form(env,'conditional_review')
    assert post(env,data|{'rule':'KG.DL.VISA_EXTENSION'}).status_code==422
    assert post(env,data|{'signature':'0'*64}).status_code==403
    assert post(env,data|{'confirmed':'no'}).status_code==422
    assert env['client'].post(url(env),content=urlencode(data)+'&confirmed=yes',headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422
    assert post(env,data).status_code==303 and post(env,data).status_code==303
    assert post(env,form(env,'reconcile')).status_code==303
    response=env['client'].get(url(env,'en'));assert '2026-10-19' in response.text and 'Planned' in response.text
    # Actual recording path, with a signed source revision and own profile/event.
    data=form(env,'record-1')
    assert data['kind']=='registration_period'
    data.update(record_key='CERTIFICATE',on='2026-10-13',reference='SYNTHETIC-CORRECTION',proof='c'*64,
        valid_from='2026-09-03',valid_until='2026-11-02',document_ref='a'*64,passport_ref='b'*64,
        basis_type='employment',tax_status='pending',basis_proof='e'*64)
    assert post(env,data).status_code==303
    assert post(env,form(env,'reconcile')).status_code==303
    assert 'Отменено' in env['client'].get(url(env)).text
    manager=_login('medina')
    try:assert manager.get(url(env)).status_code==403
    finally:manager.close()


def test_native_original_retry_after_unknown_commit_and_authority_loss(env,tmp_path,monkeypatch):
    setup(env,tmp_path,monkeypatch);data=form(env,'conditional_review','en')
    record=ui.deadlines.record;preview=ui.deadlines.preview
    async def lost(*args,**kwargs):
        await record(*args,**kwargs)
        raise EntryStorageUnavailable('synthetic-commit-ack-lost')
    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic-reader-lost')
    monkeypatch.setattr(ui.deadlines,'record',lost);monkeypatch.setattr(ui.deadlines,'preview',unavailable)
    response=post(env,data,'en');assert response.status_code==503
    retained=Form(response.text,'actual-dates-retry').data;assert retained==data
    assert response.headers['cache-control']=='no-store' and 'save outcome is unknown' in response.text
    monkeypatch.setattr(ui.deadlines,'record',record);monkeypatch.setattr(ui.deadlines,'preview',preview)
    monkeypatch.setattr(ar.settings,'kg_conditional_deadline_authorities',[])
    assert post(env,retained,'en').status_code==303
    assert post(env,form(env,'conditional_clear','en'),'en').status_code==303
