"""Actual signed forms with isolated domain storage and no external calls."""
import asyncio

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

import app.admin.router as ar
import app.admin.kg_process_journal as ui
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import Form, env
from tests.test_entry_applications import person, application, enforce_sqlite_foreign_keys
from tests.test_entry_processes import policy, read, setup, today
from tests.test_admin_workday import _login, _on


def url(env, app): return f"/admin/case/{env['cases']['visa']}/kg-entry/applications/{app['id']}/process-journal"


def enabled(monkeypatch): monkeypatch.setattr(ar.settings, 'kg_process_execution_policy', policy().document())


def form(env, app, name):
    response = env['client'].get(url(env, app))
    assert response.status_code == 200, response.text[-1200:]
    values = Form(response.text, 'kg-pj-'+name).data
    assert '_pj_signature' in values, response.text[-1200:]
    return values


def post(env, app, values): return env['client'].post(url(env, app), data=values, follow_redirects=False)


def test_large_application_list_keeps_history_scoped_link_and_native_stop(env,monkeypatch):
    from tests.test_entry_processes import write
    enabled(monkeypatch)
    subject=person(env,'many-apps');app=setup(env,procedure='violation_protocol',applicant=subject)
    for index in range(100): child=application(env,subject,f'app-{index}',procedure='registration')
    current=read(env,app)
    assert current['link_candidates_truncated'] and len(current['link_candidates'])==100
    page=env['client'].get(url(env,app)+'?revision=1')
    assert page.status_code==200
    values=form(env,app,'link-registration');values.update(application_id=str(child['id']),confirmed='yes')
    assert post(env,app,values).status_code==303
    assert read(env,app)['selected']['snapshot']['links']['registration']==child['id']
    values=form(env,app,'stop');values.update(reference='SYNTHETIC-STOP',proof='4'*64,confirmed='yes')
    assert post(env,app,values).status_code==303
    assert read(env,app)['selected']['snapshot']['stopped']
    assert env['client'].get(url(env,app)).status_code==200


def test_withdrawn_consumed_milestone_has_native_renewal_form(env,monkeypatch):
    from tests.test_entry_processes import attest,transition,profiles
    from tests.test_entry_process_dependencies import submit
    enabled(monkeypatch)
    subject=person(env,'protocol');app=setup(env,procedure='violation_protocol',applicant=subject)
    profile=profiles.save(env,subject)
    attest(env,app,'profile_review_complete',role='protocol',profile_id=profile['qualification_id'])
    submit(env,app,approve=True)
    for fact in ('overstay_assessed','protocol_received','fine_payment_confirmed'):attest(env,app,fact,role='protocol')
    transition(env,app,'U02');transition(env,app,'U03')
    values=form(env,app,'withdraw-protocol.protocol_received')
    values.update(reference='SYNTHETIC-WITHDRAW',proof='4'*64,confirmed='yes')
    assert post(env,app,values).status_code==303
    assert not read(env,app)['readiness']['ready']
    values=form(env,app,'attest-protocol.protocol_received')
    values.update(value='true',valid_through='2026-12-31',source='operator_check',reference='SYNTHETIC-RENEWAL',proof='5'*64,confirmed='yes')
    assert post(env,app,values).status_code==303
    values=form(env,app,'transition-U04');values['confirmed']='yes'
    assert post(env,app,values).status_code==303
    assert read(env,app)['selected']['snapshot']['stage']=='U04'


def test_disabled_policy_then_native_initialize_attest_transition_history(env, monkeypatch):
    app = application(env, person(env))
    page = env['client'].get(url(env, app))
    assert page.status_code == 200 and 'kg-pj-disabled' in page.text
    assert 'id="kg-pj-initialize"' not in page.text
    enabled(monkeypatch)
    initial = form(env, app, 'initialize'); initial['confirmed']='yes'
    assert post(env, app, initial).status_code == 303
    values = form(env, app, 'attest-visa.conversation_started')
    values.update(value='true', valid_through='2026-12-31', reference='SYNTHETIC', proof='3'*64, confirmed='yes')
    assert post(env, app, values).status_code == 303
    transition = form(env, app, 'transition-V02'); transition['confirmed']='yes'
    assert post(env, app, transition).status_code == 303
    assert post(env, app, transition).status_code == 303
    assert read(env, app)['current_revision'] == 3
    page = env['client'].get(url(env, app)+'?revision=1')
    assert page.status_code == 200 and 'kg-pj-historical' in page.text
    assert '<form' not in page.text.split('<main class="kg-process">', 1)[1]


@pytest.mark.parametrize('key', ['_pj_revision','_pj_role','_pj_fact','_pj_edge','_pj_evidence','_pj_active','_pj_profile','_pj_policy','_pj_csrf','_pj_signature'])
def test_signed_scope_is_not_editable(env, monkeypatch, key):
    enabled(monkeypatch); app=setup(env)
    values=form(env,app,'attest-visa.conversation_started'); values[key]='changed'; values['confirmed']='yes'
    assert post(env,app,values).status_code == 403
    assert read(env,app)['current_revision'] == 1


def test_gates_and_forbidden_extra_fields(env, monkeypatch):
    enabled(monkeypatch); app=setup(env)
    values=form(env,app,'attest-visa.conversation_started')
    assert post(env,app,values|{'all_facts_true':'true'}).status_code == 422
    for login in ('ademi','medina'):
        client=_login(login)
        try:
            assert client.get(url(env,app)).status_code == 403
            assert client.post(url(env,app),data=values).status_code == 403
        finally: client.close()
    _on(monkeypatch,write=False)
    assert post(env,app,values).status_code == 403
    _on(monkeypatch,write=True)
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(url(env,app)).status_code == 404


@pytest.mark.parametrize('read_fails',[False,True])
def test_lost_ack_retry_and_policy_change_preserve_request(env, monkeypatch, read_fails):
    enabled(monkeypatch); app=setup(env)
    values=form(env,app,'attest-visa.conversation_started')
    values.update(value='true', valid_through='2026-12-31', reference='SYNTHETIC', proof='3'*64, confirmed='yes')
    actual=ui.service.record_process_operation; actual_read=ui.service.read_process_history
    async def uncertain(*args,**kwargs):
        await actual(*args,**kwargs)
        raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
    async def unavailable(*args,**kwargs): raise EntryStorageUnavailable('synthetic read unavailable')
    monkeypatch.setattr(ui.service,'record_process_operation',uncertain)
    if read_fails: monkeypatch.setattr(ui.service,'read_process_history',unavailable)
    response=post(env,app,values)
    monkeypatch.setattr(ui.service,'record_process_operation',actual)
    monkeypatch.setattr(ui.service,'read_process_history',actual_read)
    assert response.status_code == 503
    retry=Form(response.text,'kg-pj-retry').data
    assert retry == values
    monkeypatch.setattr(ar.settings,'kg_process_execution_policy',{})
    assert post(env,app,retry).status_code == 303
    assert read(env,app)['current_revision'] == 2


def test_changed_server_policy_rejects_old_form_without_append(env,monkeypatch):
    enabled(monkeypatch); app=setup(env)
    values=form(env,app,'attest-visa.conversation_started')
    values.update(value='true',valid_through='2026-12-31',reference='SYNTHETIC',proof='3'*64,confirmed='yes')
    monkeypatch.setattr(ar.settings,'kg_process_execution_policy',policy(proof='9'*64).document())
    assert post(env,app,values).status_code == 409
    assert read(env,app)['current_revision'] == 1
