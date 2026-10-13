"""Successor work observations with actual personal history and separate REG."""
import asyncio
from dataclasses import replace
import json
from pathlib import Path

import pytest

from app.domain import applicant_stay_history as stays
from app.domain import entry_processes as service
from app.domain.entry_process_policy import AUTHORITATIVE, edge_id
from app.domain.entry_process_rules import catalog
from app.domain.entry_storage import EntryStorageInvalid
from app.knowledge.process_preview import WORK_CATALOG_SHA256
from tests.test_admin_kg_entry import ADMIN, env as base_env
from tests.test_entry_applications import enforce_sqlite_foreign_keys, person, application, record
from tests.test_entry_processes import policy as legacy_policy, today, money
from tests.test_entry_process_dependencies import submit
from tests import test_applicant_profiles as profiles
from tests import test_entry_document_packages as packages
from tests import test_applicant_stay_history as histories


@pytest.fixture
def env(base_env,tmp_path):
    from app.domain.knowledge_import import create_kg_entry_set,import_bundle
    root=Path(__file__).resolve().parents[1]
    source=root/'runs/specialist-source.pdf'
    assert source.is_file(), 'env-free freezer must provide hash-verified original PDF'
    async def seed():
        sid=await create_kg_entry_set(base_env['engine'],actor=ADMIN)
        return await import_bundle(base_env['engine'],actor=ADMIN,set_id=sid,
            directory=root/'knowledge/kg_entry/draft-v1.1',source=source,
            catalog=root/'knowledge/kg_entry/conditions_v1_1/catalog.json')
    imported=asyncio.run(seed());assert imported.accepted,imported.report
    base_env['version']=imported.version_id
    return base_env


def policy():
    draft=catalog(WORK_CATALOG_SHA256)
    return replace(legacy_policy(),catalog_digest=WORK_CATALOG_SHA256,
        allowed_edges=tuple(edge_id(e) for e in draft['edges']),
        manual_sources=tuple((f,('operator_check','official_document','portal'))
            for f in sorted((set(draft['facts'])-AUTHORITATIVE)|{'profile_review_complete'})))


def read(env,app,**kwargs):
    return asyncio.run(service.read_process_history(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],
        application_id=app['id'],**({'policy':policy()}|kwargs)))


def write(env,app,action,data,**kwargs):
    revision=kwargs.pop('revision',None)
    if revision is None:revision=read(env,app)['current_revision']
    return asyncio.run(service.record_process_operation(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],
        application_id=app['id'],expected_revision=revision,request_key=f'{action}-{revision}',
        operation=dict(action=action,data=data,confirmed=True),**({'policy':policy()}|kwargs)))


def attest(env,app,fact,role='permit',value=True,**changes):
    return write(env,app,'attest',dict(role=role,fact=fact,value=value,on=today(),valid_through='2026-12-31',
        source='operator_check',reference='SYNTHETIC-EVIDENCE',proof='3'*64,profile_id=None)|changes)


def transition(env,app,target,**kwargs):
    edge=next(e for e in read(env,app,**kwargs)['readiness']['transitions'] if e['edge']['to']==target)
    return write(env,app,'transition',dict(edge_id=edge['edge_id'],evidence_digest=edge['evidence_digest'] or '0'*64,
        on=today()),**kwargs)


def link(env,root,child,role):return write(env,root,'link',dict(role=role,application_id=child['id'],on=today()))


def setup(env):
    subject=person(env,'work-v2')
    root=application(env,subject,'permit',procedure='unified_permit')
    write(env,root,'initialize',dict(catalog_digest=WORK_CATALOG_SHA256,on=today(),employer_reference='SYNTHETIC-EMPLOYER'),revision=0)
    doc=profiles.request();doc['as_of']=today()
    doc['profile'].update(citizenship=['UZB'],entry_passport_country='UZB',purpose='work_hire',
        current_location='in_kg',in_kg_since='2026-09-01',current_basis_in_kg='visa_free')
    profile=profiles.save(env,subject,doc=doc)
    attest(env,root,'profile_review_complete',profile_id=profile['qualification_id'])
    return subject,root,profile


def stay(env,subject,profile,**kwargs):
    doc=histories.document(as_of=today(),history_complete=True,
        intervals=[histories.interval(exit_date=None,passport_country='UZB')])
    return histories.save(env,subject,profile,doc=doc,**kwargs)


def at_permit(env,*,prepared=None):
    subject,root,profile=setup(env) if prepared is None else prepared
    resident=application(env,subject,'resident',procedure='resident_card')
    registration=application(env,subject,'permit-registration',procedure='registration')
    for role,child in [('resident',resident),('registration',registration)]:link(env,root,child,role)
    policies=[]
    for app,product in [(root,'EP'),(resident,'RES')]:
        packages.setup(env,app=app,product=product);policies.append(packages.complete(env,app))
    allowed=replace(policies[0],reviewed_source_items=tuple(sorted(set().union(*(set(p.reviewed_source_items) for p in policies)))))
    for app in (root,resident):packages.approve(env,app,allowed)
    for fact in ('employer_qualified','quote_sent','offer_accepted','employer_authorization_confirmed',
        'account_activated','quota_applied','quota_approved','checklist_sent','permit_issued'):attest(env,root,fact)
    money(env,amount='100000',currency='KGS',idempotency_key='full')
    for target in ('W02','W03','W04','W05','W06','W07','W08','W09','W10'):transition(env,root,target,package_policy=allowed)
    submit(env,root)
    for target in ('W11','W12'):transition(env,root,target,package_policy=allowed)
    record(env,root,'approve',status='approved',occurred_on='2026-09-02',reference=f"PS{root['id']:06}")
    transition(env,root,'W14',package_policy=allowed)
    submit(env,registration,approve=True);attest(env,root,'registration_confirmed',role='registration')
    return subject,root,profile,resident,registration,allowed


def complete_work_flow(env,monkeypatch,*,native_basis=None,prepared=None):
    subject,root,profile,resident,registration,allowed=at_permit(env,prepared=prepared)
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):transition(env,root,'W15',package_policy=allowed)
    saved=stay(env,subject,profile)
    entered=transition(env,root,'W15',package_policy=allowed)
    presence=entered['evidence']['facts']['permit.actual_presence_confirmed']
    assert presence['value'] is True and presence['reason']=='recorded_personal_presence_only'
    assert any(p.get('stay_history_id')==saved['id'] for p in presence['pins'])
    assert 'visa' not in entered['snapshot']['links']
    transition(env,root,'W16',package_policy=allowed);submit(env,resident)
    for target in ('W17','W18'):transition(env,root,target,package_policy=allowed)
    approval=record(env,resident,'approve',status='approved',occurred_on='2026-09-04',reference=f"PS{resident['id']:06}")
    attest(env,root,'resident_issued_and_collected',role='resident')
    transition(env,root,'W19',package_policy=allowed)
    with pytest.raises(EntryStorageInvalid,match='dependency_missing'):transition(env,root,'W20',package_policy=allowed)
    with pytest.raises(EntryStorageInvalid,match='dependency_in_use'):link(env,root,registration,'resident_registration')
    fresh=application(env,subject,'resident-registration',procedure='registration')
    link(env,root,fresh,'resident_registration')
    submit(env,fresh)
    record(env,fresh,'approve',status='approved',occurred_on='2026-09-05',reference=f"PS{fresh['id']:06}")
    attest(env,root,'registration_confirmed',role='resident_registration')
    with pytest.raises(EntryStorageInvalid,match='prerequisites'):transition(env,root,'W20',package_policy=allowed)
    # The official basis is explicitly reviewed, with its own period and receipt.
    basis=dict(application_id=resident['id'],approval_id=approval['id'],valid_from='2026-09-04',
        valid_until='2027-09-03',registration_from='2026-09-05',registration_until='2027-09-03')
    from tests.test_admin_kg_process_journal import ar,form,post
    monkeypatch.setattr(ar.settings,'kg_process_execution_policy',policy().document())
    monkeypatch.setattr(ar.settings,'kg_document_package_policy',allowed.document())
    values=form(env,root,'attest-resident_registration.resident_registration_basis_reviewed')
    assert values['_pj_basis_app']==str(resident['id']) and values['_pj_basis_approval']==str(approval['id'])
    values.update(value='true',valid_through='2026-12-31',source='official_document',
        reference=f"PS{resident['id']:06}",proof='3'*64,confirmed='yes')
    values.update({'basis_'+key:value for key,value in basis.items() if key not in ('application_id','approval_id')})
    assert post(env,root,values|{'_pj_basis_app':str(registration['id'])}).status_code==403
    if native_basis is None:
        assert post(env,root,values).status_code==303
        assert post(env,root,values).status_code==303
    else:
        native_basis(env,root,values)
    moved=transition(env,root,'W20',package_policy=allowed)
    assert moved['snapshot']['active_application_id']==fresh['id']
    transition(env,root,'W21',package_policy=allowed)
    # Presence is a phase observation consumed at W15, not ongoing lawful-stay
    # permission. Later withdrawal cannot rewrite that original receipt.
    histories.withdraw(env,subject,revision=1)
    assert read(env,root,revision=entered['revision'])['selected']['evidence']==entered['evidence']
    assert read(env,root)['selected']['snapshot']['stage']=='W21'
    return root,entered,moved,allowed


def test_visa_free_worker_uses_own_stay_and_fresh_resident_registration(env,monkeypatch):
    complete_work_flow(env,monkeypatch)


def test_successor_policy_does_not_reinterpret_old_work_or_allow_client_presence(env):
    from tests.test_entry_processes import setup as old_setup,read as old_read
    app=old_setup(env,procedure='unified_permit')
    original=old_read(env,app)['selected']
    assert read(env,app)['readiness']['reason']=='process_policy_changed'
    with pytest.raises(EntryStorageInvalid,match='catalog_changed'):
        attest(env,app,'employer_qualified')
    with pytest.raises(EntryStorageInvalid,match='authoritative'):
        attest(env,app,'actual_presence_confirmed')
    assert old_read(env,app)['selected']==original


def test_dismissal_is_manager_recorded_handoff_not_automatic_annulment(env,monkeypatch):
    subject,root,profile,resident,registration,allowed=at_permit(env)
    attest(env,root,'termination_observed',source='official_document')
    result=transition(env,root,'WX1',package_policy=allowed)
    assert result['snapshot']['stage']=='WX1'
    assert result['snapshot']['active_application_id']==root['id']
    from tests.test_admin_kg_process_journal import ar,form,post
    monkeypatch.setattr(ar.settings,'kg_process_execution_policy',policy().document())
    for fact in ('termination_notice_recorded','cancellation_request_recorded','departure_plan_recorded'):
        values=form(env,root,'attest-permit.'+fact)
        values.update(value='true',valid_through='2026-12-31',source='official_document',
            reference='SYNTHETIC',proof='3'*64,confirmed='yes')
        assert post(env,root,values).status_code==303
    assert read(env,root)['readiness']['transitions']==[]
