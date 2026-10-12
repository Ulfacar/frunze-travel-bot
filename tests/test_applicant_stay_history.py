"""Personal journal acceptance on real FK-enforced SQLite transactions."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone

import pytest
from sqlalchemy import select,text,update,event
from sqlalchemy.orm import Session

from app.domain import applicant_stay_history as service
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,EntryStorageUnavailable,save_stay_history,_hash
from app.domain.models import EntryApplicantStayHistory,DomainError
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_entry_applications import person,enforce_sqlite_foreign_keys
from tests import test_applicant_profiles as profiles


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    monkeypatch.setattr(service,'_now',lambda:datetime(2026,10,12,12,tzinfo=timezone.utc))
    monkeypatch.setattr(profiles.service,'_now',lambda:datetime(2026,10,12,11,tzinfo=timezone.utc))


def document(**changes):
    return dict(format='kg-stay-history/1',as_of='2026-10-12',history_complete=None,intervals=[])|changes


def interval(**changes):
    return dict(ref='trip-1',entry_date='2026-09-01',exit_date='2026-09-10',basis='visa_free',
        passport_country='RUS',passport_ref='a'*32,evidence='passport_stamp',confirmed=True)|changes


def setup(env,key='person'):
    subject=person(env,key)
    saved=profiles.save(env,subject,key=key+'profile')
    return subject,saved


def read(env,subject,**kwargs):
    return asyncio.run(service.read_history(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],applicant_id=subject['id'],**kwargs))


def save(env,subject,profile,*,revision=0,key='history',doc=None,passport='a'*32,actor=ADMIN,case='visa'):
    return asyncio.run(service.record_history(env['engine'],actor=actor,case_id=env['cases'][case],applicant_id=subject['id'],
        expected_revision=revision,request_key=key,operation=dict(action='save',confirmed=True,
            profile_id=profile['qualification_id'],passport_ref=passport,document=document() if doc is None else doc)))


def withdraw(env,subject,*,revision,key='withdraw'):
    return asyncio.run(service.record_history(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],applicant_id=subject['id'],
        expected_revision=revision,request_key=key,operation=dict(action='withdraw',confirmed=True,reason='correction_required')))


def test_people_do_not_inherit_payer_or_each_other_history(env):
    one,p1=setup(env,'one');two,p2=setup(env,'two')
    doc=document(history_complete=True,intervals=[interval()])
    asyncio.run(save_stay_history(env['engine'],actor=ADMIN,contact_id=env['contacts']['visa'],expected_revision=0,
        request_key='payer',document=doc))
    assert read(env,one)['current']['status']==read(env,two)['current']['status']=='missing'
    saved=save(env,one,p1,doc=doc)
    assert read(env,two)['current']['status']=='missing'
    assert read(env,one)['selected']==saved
    assert read(env,one)['current']['status']=='recorded_inputs'
    assert read(env,one)['current']['eligibility_evaluated'] is False
    with pytest.raises(EntryStorageConflict,match='profile_changed'):save(env,two,p1)
    with pytest.raises(EntryStorageInvalid):save(env,one,p1,case='other')
    with pytest.raises(EntryStorageInvalid):read(env,two,revision=saved['revision'])
    # Equal-looking opaque labels across people still do not attach evidence.
    other=save(env,two,p2,passport='a'*32)
    assert other['applicant_id']!=saved['applicant_id'] and other['operation']['document']['intervals']==[]


def test_unknowns_stale_profile_and_current_confirmation_remain_explicit(env):
    subject,profile=setup(env)
    original=save(env,subject,profile,passport=None,doc=document(intervals=[interval(confirmed=False,
        passport_ref=None,passport_country=None,basis='unknown')]))
    assert set(read(env,subject)['current']['findings'])=={'history_incomplete','current_passport_unknown',
        'history_unconfirmed','stay_basis_unknown','passport_continuity_requires_review','passport_country_unknown'}
    newer=profiles.save(env,subject,revision=1,key='profile2')
    assert 'profile_changed' in read(env,subject)['current']['findings']
    assert save(env,subject,profile,passport=None,doc=original['operation']['document'])==original
    with pytest.raises(EntryStorageConflict,match='profile_changed'):
        save(env,subject,profile,revision=1,key='stale-profile')
    save(env,subject,newer,revision=1,key='current',doc=document(history_complete=True,as_of='2026-10-11'))
    assert read(env,subject)['current']['findings']==['history_needs_current_confirmation']
    assert read(env,subject,revision=1)['selected']==original


def test_exact_retry_actor_body_conflict_and_clock_reversal(env,monkeypatch):
    subject,profile=setup(env);old=save(env,subject,profile)
    save(env,subject,profile,revision=1,key='next',doc=document(history_complete=True))
    assert save(env,subject,profile)==old
    with pytest.raises(EntryStorageConflict,match='request_key_reused'):
        save(env,subject,profile,doc=document(history_complete=True))
    with pytest.raises(EntryStorageConflict,match='revision_changed'):save(env,subject,profile,key='stale')
    monkeypatch.setattr(service,'_now',lambda:datetime(2026,10,11,12,tzinfo=timezone.utc))
    assert save(env,subject,profile)==old
    with pytest.raises(EntryStorageInvalid,match='clock_reversed'):
        save(env,subject,profile,revision=2,key='clock')
    assert 'clock_uncertain' in read(env,subject)['current']['findings']


@pytest.mark.parametrize('doc',[document(as_of='2026-10-13'),document(intervals=[interval(evidence='client_statement')]),
    document(intervals=[interval(),interval()]),document(intervals=[interval(exit_date=None),interval(ref='second',exit_date=None)]),
    document(intervals=[interval(entry_date='2026-10-13')])])
def test_invalid_dates_evidence_duplicates_and_open_intervals_do_not_write(env,doc):
    subject,profile=setup(env)
    with pytest.raises(EntryStorageInvalid):save(env,subject,profile,doc=doc)
    assert read(env,subject)['current_revision']==0


def test_capacity_reserves_withdrawal_and_old_receipts(env,monkeypatch):
    subject,profile=setup(env);monkeypatch.setattr(service,'MAX_REVISIONS',3)
    first=save(env,subject,profile,doc=document(history_complete=True))
    save(env,subject,profile,revision=1,key='second')
    with pytest.raises(EntryStorageInvalid,match='history_limit'):save(env,subject,profile,revision=2,key='overflow')
    stopped=withdraw(env,subject,revision=2)
    assert stopped['revision']==3 and read(env,subject)['current']['status']=='withdrawn'
    assert save(env,subject,profile,doc=document(history_complete=True))==first
    assert withdraw(env,subject,revision=2)==stopped
    assert read(env,subject,revision=1)['selected']==first


def test_concurrent_duplicate_and_competing_writes(env):
    subject,profile=setup(env)
    async def run():
        args=dict(actor=ADMIN,case_id=env['cases']['visa'],applicant_id=subject['id'],expected_revision=0,
            operation=dict(action='save',confirmed=True,profile_id=profile['qualification_id'],passport_ref=None,document=document()))
        same=await asyncio.gather(*(service.record_history(env['engine'],request_key='same',**args) for _ in range(2)))
        assert same[0]==same[1]
        args['expected_revision']=1
        other=deepcopy(args);other['operation']['document']['history_complete']=False
        results=await asyncio.gather(service.record_history(env['engine'],request_key='a',**args),
            service.record_history(env['engine'],request_key='b',**other),return_exceptions=True)
        assert sum(isinstance(value,dict) for value in results)==1
        assert sum(isinstance(value,EntryStorageConflict) for value in results)==1
    asyncio.run(run());assert read(env,subject)['current_revision']==2


def test_immutable_guards_and_raw_chain_corruption(env):
    subject,profile=setup(env);save(env,subject,profile)
    save(env,subject,profile,revision=1,key='second')
    async def corrupt():
        async with env['sm']() as session:
            row=await session.scalar(select(EntryApplicantStayHistory))
            row.snapshot_hash='0'*64
            with pytest.raises(DomainError):await session.commit()
        async with env['sm']() as session:
            with pytest.raises(DomainError):await session.execute(update(EntryApplicantStayHistory).values(snapshot_hash='0'*64))
        async with env['engine'].begin() as connection:
            await connection.execute(text('UPDATE entry_applicant_stay_history SET snapshot_hash=:h WHERE revision=1'),{'h':'0'*64})
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):read(env,subject)
    with pytest.raises(EntryStorageInvalid):save(env,subject,profile,revision=2,key='next')


@pytest.mark.parametrize('actor',[None,{},Actor('medina'),Actor('bot',True)])
def test_access_before_any_database(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(service.read_history(None,actor=actor,case_id=1,applicant_id=1))


@pytest.mark.parametrize('when',['before_insert','before_commit','after_commit'])
def test_failed_transaction_and_uncertain_commit_recover_without_duplicate(env,when):
    subject,profile=setup(env)
    def fail(*args):raise RuntimeError('synthetic history failure')
    target=EntryApplicantStayHistory if when=='before_insert' else Session
    event.listen(target,when,fail)
    try:
        with pytest.raises(EntryStorageUnavailable):save(env,subject,profile)
    finally:event.remove(target,when,fail)
    assert read(env,subject)['current_revision']==(1 if when=='after_commit' else 0)
    receipt=save(env,subject,profile)
    assert save(env,subject,profile)==receipt and read(env,subject)['current_revision']==1


def test_real_249_revision_history_reserves_terminal_withdrawal(env):
    subject,profile=setup(env);first=save(env,subject,profile,doc=document(history_complete=True))
    async def fill():
        async with env['sm']() as session:
            previous=await session.get(EntryApplicantStayHistory,first['id'])
            for revision in range(2,250):
                command=service._command('admin',env['cases']['visa'],subject['id'],revision-1,dict(
                    action='save',confirmed=True,profile_id=profile['qualification_id'],passport_ref='a'*32,
                    document=document(history_complete=True)))
                provenance=dict(first['provenance']);provenance['previous']=dict(id=previous.id,hash=previous.snapshot_hash)
                row=EntryApplicantStayHistory(case_id=env['cases']['visa'],applicant_id=subject['id'],profile_id=profile['qualification_id'],
                    revision=revision,previous_id=previous.id,action='save',request_key=f'fill-{revision}',
                    request_hash=_hash(command),command=command,provenance=provenance,created_by='admin',created_at=service._now())
                row.snapshot_hash=_hash(service._payload(row));session.add(row);await session.flush();previous=row
            await session.commit()
    asyncio.run(fill())
    assert read(env,subject)['current_revision']==249
    with pytest.raises(EntryStorageInvalid,match='history_limit'):save(env,subject,profile,revision=249,key='overflow')
    stopped=withdraw(env,subject,revision=249)
    assert stopped['revision']==250 and read(env,subject)['current']['status']=='withdrawn'
    assert read(env,subject,revision=1)['selected']==first
    assert save(env,subject,profile,doc=document(history_complete=True))==first
    assert withdraw(env,subject,revision=249)==stopped


def test_byte_capacity_reserves_withdrawal_and_oversized_raw_data_fails_closed(env,monkeypatch):
    subject,profile=setup(env);first=save(env,subject,profile)
    async def size():
        async with env['sm']() as session:return service._size(await session.get(EntryApplicantStayHistory,first['id']))
    amount=asyncio.run(size());monkeypatch.setattr(service,'MAX_BYTES',amount+service.WITHDRAWAL_BYTES)
    with pytest.raises(EntryStorageInvalid,match='history_limit'):save(env,subject,profile,revision=1,key='full')
    assert withdraw(env,subject,revision=1)['revision']==2
    assert read(env,subject)['current']['status']=='withdrawn'
    async def corrupt():
        async with env['engine'].begin() as conn:
            await conn.execute(text('UPDATE entry_applicant_stay_history SET command=:value WHERE id=:id'),
                {'id':first['id'],'value':'"'+'x'*(2*service.MAX_EVENT_BYTES+1)+'"'})
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid,match='history_limit'):read(env,subject)
