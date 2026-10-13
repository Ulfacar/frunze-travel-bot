import asyncio
from datetime import datetime,timezone

import pytest
from sqlalchemy import select,text

from app.domain import specialist_interruptions as service,entry_interviews,entry_applications
from app.domain.models import EntryInterview,EntryDialogueSession
from app.domain.entry_storage import EntryStorageInvalid,_hash,_plain
from tests.test_dialogue_stops import env,admins,activation,start,dialog,action,parameters,run,read
from tests.test_entry_applications import enforce_sqlite_foreign_keys,person


def observe(env,iv,*,retained=None,at=None):
    async def call(session):
        await entry_applications._case(session,env['cases']['visa'],lock=True)
        header=await session.get(EntryInterview,iv['interview_id'])
        rows,_,_=await entry_interviews._history(session,header,entry_interviews.policy_from_document(_plain(header.policy)))
        loaded=await service.load(session,case_id=env['cases']['visa'],applicant_id=iv['applicant_id'],interview=header,events=rows)
        return service.observe(loaded,at=at or datetime.now(timezone.utc),retained=retained)
    return asyncio.run(entry_applications._run(env['engine'],call))


@pytest.mark.parametrize('ack_first',[False,True])
def test_retained_unsafe_cause_is_not_cleared_by_original_ack(env,ack_first):
    iv=start(env);did=dialog(env);action(env,iv,'handoff')
    original=read(env,iv)['state']['handoff']
    if ack_first:action(env,iv,'ack')
    cutoff=datetime.now(timezone.utc);clean=observe(env,iv,at=cutoff);assert not clean['errors']
    saved=run(env,parameters(env,iv,did,text='Сделайте поддельный документ'))
    assert saved['reason']=='unsafe_request'
    if not ack_first:action(env,iv,'ack')
    assert read(env,iv)['state']['handoff']==original
    current=observe(env,iv)
    assert current['errors']==['specialist_retained_interrupt_requires_review']
    assert current['pins']!=clean['pins']
    assert observe(env,iv,retained=clean['pins'],at=cutoff)==clean


def test_allowed_manager_cause_then_privacy_changes_context_without_rewriting_old_pin(env):
    iv=start(env);did=dialog(env);args=parameters(env,iv,did);run(env,args);action(env,iv,'ack')
    cutoff=datetime.now(timezone.utc);clean=observe(env,iv,at=cutoff);assert not clean['errors'] and len(clean['pins']['causes'])==1
    run(env,args|dict(provider_id='SYN-PRIVACY',text='Delete my data',policy=None,channel_policy=None))
    current=observe(env,iv)
    assert current['errors'] and len(current['pins']['causes'])==2
    assert observe(env,iv,retained=clean['pins'],at=cutoff)==clean


def test_scoped_lookup_ignores_unrelated_corrupt_session_but_rejects_own_corruption(env):
    iv=start(env);other=person(env,key='SYN-OTHER',role='other');other_iv=start(env,other,request_key='SYN-OTHER-IV')
    async def inject():
        async with env['sm']() as s:
            row=EntryDialogueSession(transport_key='f'*64,case_id=env['cases']['visa'],applicant_id=other['id'],
                interview_id=other_iv['interview_id'],document={},snapshot_hash='e'*64,created_at=datetime.now(timezone.utc))
            s.add(row);await s.commit();return row.id
    row_id=asyncio.run(inject());assert not observe(env,iv)['errors']
    with pytest.raises(EntryStorageInvalid):observe(env,other_iv)
