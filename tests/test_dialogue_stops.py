import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import event, select, text

from app.domain import dialogue_stops as service
from app.domain.dialogue_policy import DialoguePolicy
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict, EntryStorageUnavailable
from app.domain.models import EntryDialogueStopCause, EntryChannelStop, EntryInterviewEvent
from app.domain.service_authz import PermissionDenied
from tests.test_entry_channel_stops import (env, admins, activation, start, dialog, resolve,
    policy as channel_policy, ROUTE, read, action, send, counts, adapter)
from tests.test_entry_interviews import policy as interview_policy


def policy(env, iv, did, **changes):
    current=read(env,iv)
    return DialoguePolicy(dict(format='kg-dialogue-policy/1',reference='SYN-DIALOGUE',proof='a'*64,
        privacy_reference='SYN-PRIVACY',privacy_proof='b'*64,valid_from='2026-01-01',review_due_on='2027-01-01',
        triage_version='kg-dialogue-interrupts/1',interview_policy_hash=interview_policy().digest,
        channel_policy_hash=channel_policy().digest,assignments=[dict(route=ROUTE,case_id=env['cases']['visa'],
            applicant_id=iv['applicant_id'],interview_id=iv['interview_id'],dialog_id=did,actor='admin',
            header_hash=current['interview']['snapshot_hash'],reference='SYN-ASSIGNMENT',proof='c'*64)])|changes)


def parameters(env,iv,did,**changes):
    return dict(route=ROUTE,provider_id='SYN-INCOMING-1',text='Хочу менеджера',resolver=resolve,
        policy=policy(env,iv,did),channel_policy=channel_policy())|changes


def run(env,parameters):
    return asyncio.run(service.record_interrupt(env['engine'],**parameters))


def test_atomic_cause_handoff_latch_and_exact_retry(env):
    iv=start(env);did=dialog(env);args=parameters(env,iv,did);before=counts(env)
    saved=run(env,args);after=counts(env)
    assert saved['reason']=='manager_requested' and saved['suppressed']
    assert read(env,iv)['state']['handoff']['card']['reasons']==['manager_requested']
    assert send(env)[1]==[]
    assert run(env,args)==saved
    assert counts(env)==after
    assert {k:after[k]-before[k] for k in before if after[k]!=before[k]}=={
        'entry_interview_events':1,'entry_channel_stops':1,'entry_dialogue_stop_causes':1}
    with pytest.raises(EntryStorageConflict,match='message_changed'):
        run(env,args|{'text':'Другой текст с тем же ID'})


@pytest.mark.parametrize('phase',['paused','pending','acked'])
def test_existing_handoff_and_later_privacy_stop_with_expired_policy(env,phase):
    iv=start(env);did=dialog(env)
    action(env,iv,'pause' if phase=='paused' else 'handoff')
    if phase=='acked':action(env,iv,'ack')
    old=read(env,iv);args=parameters(env,iv,did);first=run(env,args)
    if old['state']['handoff']:
        assert read(env,iv)['state']['handoff']==old['state']['handoff']
    else:action(env,iv,'ack')
    withdrawal=run(env,args|dict(provider_id='SYN-WITHDRAW',text='I no longer consent to storing my data',policy=None,channel_policy=None))
    assert withdrawal['revision']==2 and withdrawal['collection_blocked']
    assert read(env,iv)['state']['collection_blocked']
    assert send(env)[1]==[]
    assert run(env,args|{'policy':None,'channel_policy':None})==first
    assert run(env,args|dict(provider_id='SYN-WITHDRAW',text='I no longer consent to storing my data',policy=None,channel_policy=None))==withdrawal


@pytest.mark.parametrize('model',[EntryDialogueStopCause,EntryChannelStop,EntryInterviewEvent])
def test_failure_rolls_back_all_three_connected_writes(env,model):
    iv=start(env);did=dialog(env);args=parameters(env,iv,did);before=counts(env)
    def broken(*a):raise RuntimeError('synthetic insert failure')
    event.listen(model,'after_insert',broken)
    try:
        with pytest.raises(EntryStorageUnavailable):run(env,args)
    finally:event.remove(model,'after_insert',broken)
    assert counts(env)==before
    assert read(env,iv)['state']['phase']=='active'
    assert send(env)[0].invoked


def test_missing_policy_unbound_and_greeting_are_not_answer_admission(env):
    iv=start(env);did=dialog(env);args=parameters(env,iv,did);before=counts(env)
    assert run(env,args|{'policy':None}) is None
    assert run(env,args|{'text':'hello'}) is None
    assert counts(env)==before
    assert read(env,iv)['state']['phase']=='active'


def test_cause_corruption_fails_closed_and_restores(env):
    iv=start(env);did=dialog(env);args=parameters(env,iv,did);saved=run(env,args)
    async def change(value):
        async with env['engine'].begin() as c:
            await c.execute(text('UPDATE entry_dialogue_stop_causes SET snapshot_hash=:v WHERE id=:id'),dict(v=value,id=saved['id']))
    asyncio.run(change('f'*64))
    with pytest.raises(EntryStorageInvalid,match='integrity'):run(env,args)
    asyncio.run(change(saved['snapshot_hash']))
    assert run(env,args)==saved


def test_reserved_terminal_collection_stop_at_registry_capacity(env,monkeypatch):
    monkeypatch.setattr(service,'MAX_CAUSES',2)
    iv=start(env);did=dialog(env);args=parameters(env,iv,did)
    first=run(env,args)
    last=run(env,args|dict(provider_id='SECOND',text='не даю согласия',policy=None,channel_policy=None))
    assert last['revision']==2 and last['collection_blocked']
    assert run(env,args)==first
    assert run(env,args|dict(provider_id='THIRD',text='Отзываю согласие'))==last


@pytest.mark.parametrize('changes',[
    {'text':'I revoke consent to storing my data'+' x'*1100},
    {'text':'I revoke consent to storing my data','voice':True},
    {'text':'I revoke consent to storing my data\x00'},
    {'text':'I revoke con\u200bsent to storing my data'},
])
def test_unparseable_privacy_instruction_still_blocks_collection_after_ack(env,changes):
    iv=start(env);did=dialog(env);args=parameters(env,iv,did)
    run(env,args);action(env,iv,'ack')
    held=run(env,args|dict(provider_id='PRIVACY-HOLD',policy=None,channel_policy=None)|changes)
    assert held['reason']=='consent_withdrawn' and held['collection_blocked']
    assert held['interpretation']=='possible_privacy_stop'
    assert read(env,iv)['state']['collection_blocked']


@pytest.mark.parametrize('field,value', [('actor','missing'),('applicant_id',999999),
    ('header_hash','f'*64),('dialog_id',999999)])
def test_server_assignment_must_match_exact_existing_subject(env,field,value):
    iv=start(env);did=dialog(env);args=parameters(env,iv,did);doc=args['policy'].document
    doc['assignments'][0][field]=value;args['policy']=DialoguePolicy(doc)
    before=counts(env)
    with pytest.raises((EntryStorageInvalid,EntryStorageConflict,PermissionDenied)):run(env,args)
    assert counts(env)==before and read(env,iv)['state']['phase']=='active'


def test_native_cause_and_uncertain_privacy_hold_are_readable_and_fail_closed(env):
    from app.admin.kg_channel_stops import _url
    iv=start(env);did=dialog(env);args=parameters(env,iv,did)
    run(env,args)
    run(env,args|dict(provider_id='PRIVACY',text='Please explain your privacy policy'))
    path=_url(env['cases']['visa'],iv['applicant_id'],iv['interview_id'])
    page=env['client'].get(path)
    assert page.status_code==200 and page.headers['cache-control']=='no-store'
    assert 'Причины остановки' in page.text and 'Возможное ограничение обработки данных' in page.text
    assert 'Удаление данных не выполнялось' in page.text
    assert 'Please explain' not in page.text
    assert env['client'].get(path+'?actor=admin').status_code==422
    async def corrupt():
        async with env['engine'].begin() as c:
            await c.execute(text("UPDATE entry_dialogue_stop_causes SET snapshot_hash=:h"),{'h':'f'*64})
    asyncio.run(corrupt())
    failed=env['client'].get(path)
    assert failed.status_code==503 and failed.headers['cache-control']=='no-store'
    assert 'Причины остановки' not in failed.text


@pytest.mark.parametrize('value',[True,1.0,'1'])
def test_assignment_identity_is_not_coerced(env,value):
    iv=start(env);did=dialog(env);document=policy(env,iv,did).document
    document['assignments'][0]['case_id']=value
    with pytest.raises(EntryStorageInvalid):DialoguePolicy(document)
