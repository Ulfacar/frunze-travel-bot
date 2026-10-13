"""Independent real HTTP oracles, scoped to native actual-date commands."""
import json,re
from pathlib import Path
import pytest
from tests import test_admin_actual_dates as native
from tests.test_admin_actual_dates import env,clock,enforce_sqlite_foreign_keys
from tests.test_admin_kg_entry import Form
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_workday import _login


def record_form(env,kind,language='en'):
    response=env['client'].get(native.url(env,language));assert response.status_code==200
    for form_id in re.findall(r'id="(actual-dates-record-\d+)"',response.text):
        data=Form(response.text,form_id).data
        if data['kind']==kind:return data|{'confirmed':'yes'}
    raise AssertionError(kind)


def registration(data):
    return data|dict(record_key='CERTIFICATE',on='2026-10-13',reference='SYNTHETIC-CORRECTION',proof='c'*64,
        valid_from='2026-09-03',valid_until='2026-11-02',document_ref='a'*64,passport_ref='b'*64,
        basis_type='employment',tax_status='pending',basis_proof='e'*64)


@pytest.mark.parametrize('action',['conditional_review','record'])
def test_lost_commit_healthy_reader_keeps_exact_original_retry(env,tmp_path,monkeypatch,action):
    native.setup(env,tmp_path,monkeypatch)
    data=native.form(env,'conditional_review','en') if action=='conditional_review' else registration(record_form(env,'registration_period'))
    service=native.ui.deadlines if action=='conditional_review' else native.ui.anchors
    original=service.record
    async def committed_but_ack_lost(*args,**kwargs):
        await original(*args,**kwargs)
        raise EntryStorageUnavailable('synthetic-response-lost-after-commit')
    monkeypatch.setattr(service,'record',committed_but_ack_lost)
    response=native.post(env,data,'en')
    output=Path('runs/reviewer-http');output.mkdir(parents=True,exist_ok=True)
    (output/(action+'.html')).write_text(response.text,'utf8')
    assert response.status_code==503,(response.status_code,response.text[-1000:])
    assert response.headers['cache-control']=='no-store'
    retry=Form(response.text,'actual-dates-retry').data
    assert retry==data
    assert not re.search(r'id="actual-dates-(?:record-\d+|conditional_review|reconcile)"',response.text)
    monkeypatch.setattr(service,'record',original)
    assert native.post(env,retry,'en').status_code==303
    assert native.post(env,retry,'en').status_code==303


def test_current_signed_visa_context_save_and_cross_scope_refusals(env,tmp_path,monkeypatch):
    native.setup(env,tmp_path,monkeypatch)
    prepared=native.core.actual.setup(env,'visa_period',key='REVIEW-VISA')
    prepared,context=native.core.renewal(env,prepared)
    rule='KG.DL.VISA_EXTENSION';authority=native.core.authority(env,rule)
    monkeypatch.setattr(native.ar.settings,'kg_conditional_deadline_authorities',[authority.document])
    env.update(prepared=prepared,authority=authority,rule=rule,ids=(prepared[1]['case_id'],prepared[0]['id'],prepared[1]['id']))
    for language in ('ru','en'):
        page=env['client'].get(native.url(env,language));assert page.status_code==200
        assert '????' not in page.text
        assert 'actual-dates-conditional_review' not in page.text
    data=record_form(env,'visa_renewal_context')
    values=context['operation']['data'];data.update({k:str(v) for k,v in values['value'].items()})
    data.update(record_key='RENEWAL',on=values['on'],reference=values['reference'],proof=values['proof'])
    # A valid envelope cannot be reassigned to another applicant/route/query/session.
    alternate=native.ui.url((env['ids'][0],env['ids'][1]+1,env['ids'][2]),'en',rule)
    assert env['client'].post(alternate,data=data,follow_redirects=False).status_code==403
    assert native.post(env,data|{'profile_id':str(int(data['profile_id'])+1)},'en').status_code==403
    assert native.post(env,data|{'csrf':'0'*64},'en').status_code==403
    assert env['client'].post(native.url(env,'ru'),data=data,follow_redirects=False).status_code==422
    other=_login('admin')
    try:assert other.post(native.url(env,'en'),data=data,follow_redirects=False).status_code==403
    finally:other.close()
    assert env['client'].get(native.url(env,'en')+'&language=en').status_code==422
    assert env['client'].post(native.url(env,'en'),content='x'*16385,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert native.post(env,data,'en').status_code==303
    assert native.post(env,data,'en').status_code==303
    page=env['client'].get(native.url(env,'en'));assert page.status_code==200
    assert '2026-10-26' in page.text and 'actual-dates-conditional_review' in page.text
    old_review=native.form(env,'conditional_review','en')
    corrected=record_form(env,'visa_renewal_context')
    corrected.update({k:str(v) for k,v in values['value'].items()})
    corrected.update(record_key='RENEWAL',on=values['on'],reference='CHANGED-RENEWAL-PROOF',proof=values['proof'])
    assert native.post(env,corrected,'en').status_code==303
    assert native.post(env,old_review,'en').status_code==409
    assert native.post(env,native.form(env,'conditional_review','en'),'en').status_code==303
