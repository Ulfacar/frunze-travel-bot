"""Current reader clock guards with ordinary domain writes and unchanged history."""
from datetime import datetime,timedelta,timezone
import pytest
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_entry_applications import service as applications,record
from tests.test_process_aftercare_reader import (env,base_env,enforce_sqlite_foreign_keys,person,application,
    process,packages,approved,link,url)


def test_parent_future_head_hides_current_panel_and_equality_recovers(env,monkeypatch):
    subject=person(env,'parent-clock');root=process.setup(env,applicant=subject)
    initial=process.read(env,root)['selected']
    child=application(env,subject,'resident',procedure='resident_card');link(env,root,child,'resident')
    approved(env,child,'resident')
    future=datetime.now(timezone.utc)+timedelta(minutes=5)
    with monkeypatch.context() as shifted:
        shifted.setattr(process.service,'_now',lambda:future)
        receipt=process.attest(env,root,'resident_issued_and_collected',role='resident')
    view=process.read(env,root,revision=initial['revision'])
    assert view['dependencies']=={} and view['selected']==initial
    monkeypatch.setattr(ar.settings,'kg_process_execution_policy',process.policy().document())
    page=env['client'].get(url(env,root)+'?revision=1')
    assert page.status_code==200 and 'id="kg-pj-dependencies"' not in page.text
    with monkeypatch.context() as shifted:
        shifted.setattr(process.service,'_now',lambda:future)
        current=process.read(env,root)
        assert current['selected']=={k:v for k,v in receipt.items() if k not in ('current_revision','readiness')}
        assert current['dependencies']['resident']['facts']['resident_issued_and_collected']['value'] is True


@pytest.mark.parametrize('source',['application','package'])
def test_future_source_head_cannot_leak_current_positive(env,monkeypatch,source):
    subject=person(env,'source-clock');root=process.setup(env,applicant=subject)
    child=application(env,subject,'resident',procedure='resident_card');link(env,root,child,'resident')
    allowed=None
    if source=='package':
        packages.setup(env,app=child,product='RES');allowed=packages.complete(env,child)
    else:
        record(env,child,'submit',reference='TS'+str(child['id']).zfill(6))
    future=datetime.now(timezone.utc)+timedelta(minutes=5)
    with monkeypatch.context() as shifted:
        if source=='application':
            shifted.setattr(applications,'_now',lambda:future)
            record(env,child,'approve',status='approved',occurred_on='2026-09-04',reference='TS'+str(child['id']).zfill(6))
        else:
            shifted.setattr(packages.service,'_now',lambda:future)
            packages.approve(env,child,allowed)
    monkeypatch.setattr(ar.settings,'kg_process_execution_policy',process.policy().document())
    if allowed:monkeypatch.setattr(ar.settings,'kg_document_package_policy',allowed.document())
    with pytest.raises(EntryStorageInvalid,match='process_source_from_future'):
        process.read(env,root,package_policy=allowed)
    page=env['client'].get(url(env,root))
    assert page.status_code==503 and page.headers['cache-control']=='no-store'
    assert 'id="kg-pj-dependencies"' not in page.text
    with monkeypatch.context() as shifted:
        shifted.setattr(process.service,'_now',lambda:future)
        facts=process.read(env,root,package_policy=allowed)['dependencies']['resident']['facts']
        if source=='application':assert facts['decision']['value']=='approved'
        else:assert facts['documents_current']['value'] is True
        assert env['client'].get(url(env,root)).status_code==200
