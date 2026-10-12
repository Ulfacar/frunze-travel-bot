"""Current dependency controls beyond the unchanged original REG probes."""
import asyncio
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import text
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageInvalid
from app.knowledge.process_preview import WORK_CATALOG_SHA256
from tests.test_process_aftercare_reader import (env,base_env,enforce_sqlite_foreign_keys,person,application,
    process,approved,link,successor_policy,url)


@pytest.mark.parametrize('condition',['stopped','catalog','corrupt'])
def test_child_stop_catalog_and_integrity_never_fall_back_to_parent(env,monkeypatch,condition):
    subject=person(env,'boundary-person');root=process.setup(env,applicant=subject)
    if condition=='catalog':
        child=application(env,subject,'successor-registration',procedure='registration')
        process.write(env,child,'initialize',dict(catalog_digest=WORK_CATALOG_SHA256,on=process.today(),
            employer_reference=None),revision=0,policy=successor_policy())
    else:child=process.setup(env,key='child',applicant=subject,procedure='registration')
    link(env,root,child,'registration');approved(env,child,'registration')
    child_policy=successor_policy() if condition=='catalog' else process.policy()
    receipt=process.attest(env,child,'registration_certificate_received',role='registration',policy=child_policy)
    process.attest(env,root,'registration_certificate_received',role='registration')
    monkeypatch.setattr(ar.settings,'kg_process_execution_policy',process.policy().document())
    if condition=='stopped':
        process.write(env,child,'stop',dict(on=process.today(),reference='SYNTHETIC-STOP',proof='7'*64))
    if condition=='corrupt':
        async def set_hash(value):
            async with env['sm']() as session:
                await session.execute(text('UPDATE entry_process_events SET snapshot_hash=:hash WHERE id=:id'),
                    {'hash':value,'id':receipt['id']});await session.commit()
        asyncio.run(set_hash('0'*64))
        with pytest.raises(EntryStorageInvalid):process.read(env,root)
        assert env['client'].get(url(env,root)).status_code==503
        asyncio.run(set_hash(receipt['snapshot_hash']))
        assert process.read(env,root)['dependencies']['registration']['facts']['registration_certificate_received']['value'] is True
        assert env['client'].get(url(env,root)).status_code==200
    else:
        packet=process.read(env,root)['dependencies']['registration']['facts']['registration_certificate_received']
        assert packet['value'] is None and packet['reason']=='dependent_process_unavailable'
        page=env['client'].get(url(env,root))
        assert page.status_code==200 and 'id="kg-pj-dependencies"' in page.text and 'Неизвестно' in page.text


def test_res_collection_actual_date_before_official_approval_cannot_be_current(env):
    subject=person(env,'dated-person');root=process.setup(env,applicant=subject)
    child=application(env,subject,'resident',procedure='resident_card');link(env,root,child,'resident')
    process.attest(env,root,'resident_issued_and_collected',role='resident',on='2026-09-01')
    approved(env,child,'resident') # Actual approval on 2026-09-04.
    packet=process.read(env,root)['dependencies']['resident']['facts']['resident_issued_and_collected']
    assert packet['value'] is not True,packet


def test_future_child_receipt_is_not_current_after_clock_returns(env,monkeypatch):
    subject=person(env,'clock-person');root=process.setup(env,applicant=subject)
    child=process.setup(env,key='clock-child',applicant=subject,procedure='registration')
    link(env,root,child,'registration');approved(env,child,'registration')
    with monkeypatch.context() as shifted:
        shifted.setattr(process.service,'_now',lambda:datetime.now(timezone.utc)+timedelta(days=1))
        process.attest(env,child,'registration_certificate_received',role='registration')
    packet=process.read(env,root)['dependencies']['registration']['facts']['registration_certificate_received']
    assert packet['value'] is not True,packet
