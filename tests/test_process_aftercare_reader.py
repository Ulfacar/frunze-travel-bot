"""Independent source-aftercare reader probes, isolated actual journals."""
from dataclasses import replace
import pytest
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_work_process_v2 import env,base_env,policy as successor_policy
from tests.test_entry_applications import person,application,record,enforce_sqlite_foreign_keys
from tests import test_entry_processes as process
from tests import test_entry_document_packages as packages
from tests.test_admin_kg_process_journal import url


def link(env,root,child,role):
    return process.write(env,root,'link',dict(role=role,application_id=child['id'],on=process.today()))


def approved(env,app,key):
    record(env,app,key+'-submit',reference='TS'+str(app['id']).zfill(6))
    record(env,app,key+'-approve',status='approved',occurred_on='2026-09-04',reference='TS'+str(app['id']).zfill(6))


def withdraw_receipt(env,app,role,fact):
    process.write(env,app,'withdraw',dict(role=role,fact=fact,on=process.today(),reference='SYNTHETIC-WITHDRAW',proof='4'*64))


def test_own_res_decision_current_policy_package_and_historical_display(env,monkeypatch):
    subject=person(env,'aftercare-person');root=process.setup(env,applicant=subject)
    initial=process.read(env,root)['selected']
    other=person(env,'other-person');foreign=application(env,other,'foreign-res',procedure='resident_card')
    with pytest.raises(EntryStorageInvalid,match='subject_mismatch|dependency_scope'):
        link(env,root,foreign,'resident')
    assert process.read(env,root)['selected']==initial
    child=application(env,subject,'resident',procedure='resident_card');link(env,root,child,'resident')
    approved(env,root,'visa')
    process.attest(env,root,'resident_issued_and_collected',role='resident')
    before=process.read(env,root)['dependencies']['resident']['facts']
    assert before['decision']['value']=='draft' and before['resident_issued_and_collected']['value'] is False
    packages.setup(env,app=child,product='RES');allowed=packages.complete(env,child);packages.approve(env,child,allowed)
    approved(env,child,'resident')
    current=process.read(env,root,package_policy=allowed)
    facts=current['dependencies']['resident']['facts']
    assert facts['decision']['value']=='approved' and facts['documents_current']['value'] is True
    assert facts['resident_issued_and_collected']['value'] is True
    assert current['selected']['snapshot']['stage']=='V01'
    historical=process.read(env,root,revision=initial['revision'],package_policy=allowed)
    assert historical['selected']==initial and historical['dependencies']==current['dependencies']
    monkeypatch.setattr(ar.settings,'kg_process_execution_policy',process.policy().document())
    monkeypatch.setattr(ar.settings,'kg_document_package_policy',allowed.document())
    page=env['client'].get(url(env,root)+'?revision=1')
    assert page.status_code==200 and 'id="kg-pj-historical"' in page.text
    assert 'id="kg-pj-dependencies"' in page.text and 'Текущие подтверждения' in page.text
    assert f'applications?application_id={child["id"]}' in page.text
    for policy in (None,process.policy(review_due_on='2026-01-02'),successor_policy()):
        view=process.read(env,root,policy=policy,package_policy=allowed)
        assert view['dependencies']=={} and view['selected']==current['selected']
    revoked=process.policy(manual_sources=tuple(p for p in process.policy().manual_sources if p[0]!='resident_issued_and_collected'))
    assert process.read(env,root,policy=revoked,package_policy=allowed)['dependencies']['resident']['facts']['resident_issued_and_collected']['value'] is None
    packages.write(env,child,'consent',dict(status='withdrawn',on=process.today(),reference='SYNTHETIC-WITHDRAW',proof='6'*64))
    assert process.read(env,root,package_policy=allowed)['dependencies']['resident']['facts']['documents_current']['value'] is False
    withdraw_receipt(env,root,'resident','resident_issued_and_collected')
    assert process.read(env,root,package_policy=allowed)['dependencies']['resident']['facts']['resident_issued_and_collected']['value'] is None
    assert process.read(env,root,revision=initial['revision'])['selected']==initial


@pytest.mark.parametrize('duplicate_parent',[False,True])
def test_initialized_reg_child_owns_receipt_and_withdrawal(env,duplicate_parent):
    subject=person(env,'reg-person');root=process.setup(env,applicant=subject)
    child=process.setup(env,key='reg-child',applicant=subject,procedure='registration')
    link(env,root,child,'registration');approved(env,child,'registration')
    process.attest(env,child,'registration_certificate_received',role='registration')
    if duplicate_parent:
        process.attest(env,root,'registration_certificate_received',role='registration')
        assert process.read(env,root)['dependencies']['registration']['facts']['registration_certificate_received']['value'] is True
        withdraw_receipt(env,child,'registration','registration_certificate_received')
        expected=None
    else:expected=True
    fact=process.read(env,root)['dependencies']['registration']['facts']['registration_certificate_received']
    assert fact['value'] is expected,fact
