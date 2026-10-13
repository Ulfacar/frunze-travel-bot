import asyncio
from copy import deepcopy
from dataclasses import replace
from datetime import datetime,timezone

import pytest
from sqlalchemy import event,select,text

from app.config import settings,BotConfig
from app.channels.wappi import WappiAdapter
from app.core import kg_channel_guard as guard
from app.domain import entry_channel_stops as service,entry_channel_policy as rules
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,EntryStorageUnavailable,_hash
from app.domain.models import Dialog,EntryChannelStop,EntryInterviewEvent
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_entry_applications import enforce_sqlite_foreign_keys,person
from tests.test_entry_interviews import admins,start,read,action,counts

BASE='https://synthetic.invalid'
PROFILE='SYN-PROFILE'
CHAT='996700000001'
ROUTE=rules.route(BASE,PROFILE,CHAT)


def policy(**changes):
    return rules.policy_from_document(dict(format='kg-channel-stop-policy/1',reference='SYN-STOP',proof='a'*64,
        privacy_reference='SYN-PRIVACY',privacy_proof='b'*64,operators=['admin','reviewer'],scopes=[rules.route_scope(ROUTE)],
        valid_from='2026-01-01',review_due_on='2027-01-01')|changes)


def resolve(channel,bot_id,chat_id):
    if channel!='whatsapp' or bot_id not in ('syn','alias'):raise EntryStorageInvalid('unsupported_channel_dialog')
    return rules.route(BASE,PROFILE,chat_id)


@pytest.fixture(autouse=True)
def activation(env,monkeypatch):
    monkeypatch.setattr(settings,'kg_channel_guard_scopes',[rules.scope(BASE,PROFILE)])
    monkeypatch.setattr(settings,'kg_channel_stop_policy',policy().document())
    monkeypatch.setattr(guard,'_engine',lambda:env['engine'])


def dialog(env,**changes):
    async def run():
        async with env['sm']() as s:
            row=Dialog(**(dict(contact_id=env['contacts']['visa'],channel='whatsapp',bot_id='syn',channel_key=CHAT)|changes))
            s.add(row);await s.commit();return row.id
    return asyncio.run(run())


def targets(env,iv,did):return dict(actor=ADMIN,case_id=env['cases']['visa'],applicant_id=iv['applicant_id'],interview_id=iv['interview_id'],dialog_id=did)


def preview(env,iv,did,**changes):
    return asyncio.run(service.preview_stop(env['engine'],**(targets(env,iv,did)|dict(resolver=resolve,policy=policy())|changes)))


def args(env,iv,did,**changes):
    p=preview(env,iv,did)['preview']
    return targets(env,iv,did)|dict(resolver=resolve,policy=policy(),expected_revision=p['revision'],expected_policy_hash=p['policy_hash'],
        expected_preview_hash=_hash(p),request_key='SYN-STOP',confirmed=True)|changes


def bind(env,iv,did,**changes):return asyncio.run(service.bind_stop(env['engine'],**args(env,iv,did,**changes)))


def send(env,descriptor=ROUTE):
    calls=[]
    async def callback():calls.append(True);return None
    result=asyncio.run(service.guarded_send(env['engine'],descriptor,callback))
    return result,calls


def adapter(monkeypatch,profile=PROFILE):
    monkeypatch.setattr(settings,'wappi_base_url',BASE)
    monkeypatch.setattr(settings,'wappi_profile_id',profile)
    return WappiAdapter()


def test_atomic_handoff_stop_ack_policy_removal_and_exact_retry(env):
    iv=start(env);did=dialog(env);before=counts(env);parameters=args(env,iv,did)
    assert send(env)[0].invoked
    saved=asyncio.run(service.bind_stop(env['engine'],**parameters));after=counts(env)
    assert {k:after[k]-before[k] for k in before if after[k]!=before[k]}=={'entry_interview_events':1,'entry_channel_stops':1}
    assert saved['permanent'] and saved['card_hash']==read(env,iv)['state']['handoff']['hash']
    assert send(env)==(service.SendResult(False),[])
    action(env,iv,'ack');settings.kg_channel_stop_policy={}
    assert read(env,iv)['state']['phase']=='acked' and send(env)[1]==[]
    assert asyncio.run(service.bind_stop(env['engine'],**(parameters|{'policy':None})))==saved
    assert read(env,iv)['state']['channel_suppression']=='not_integrated'


@pytest.mark.parametrize('phase',['paused','pending','acked'])
def test_existing_card_or_paused_and_no_resumption(env,phase):
    iv=start(env);did=dialog(env)
    if phase=='paused':action(env,iv,'pause')
    else:
        action(env,iv,'handoff')
        if phase=='acked':action(env,iv,'ack')
    old=read(env,iv);bind(env,iv,did);new=read(env,iv)
    assert new['revision']==old['revision']+(phase=='paused')
    assert send(env)[1]==[]
    if old['state']['handoff']:assert old['state']['handoff']==new['state']['handoff']


@pytest.mark.parametrize('change',[{'contact_id':'other'},{'channel':'telegram'},{'channel':'bitrix_openlines'},{'channel_key':'12345@g.us'}, {'bot_id':'unknown'}])
def test_wrong_dialog_provenance_rejected(env,change):
    iv=start(env)
    if change.get('contact_id')=='other':change={'contact_id':env['contacts']['other']}
    did=dialog(env,**change)
    with pytest.raises(EntryStorageInvalid):preview(env,iv,did)
    assert read(env,iv)['state']['phase']=='active'


def test_stale_preview_conflict_and_current_actor_before_retry(env,monkeypatch):
    iv=start(env);did=dialog(env);parameters=args(env,iv,did)
    action(env,iv,'pause')
    with pytest.raises(EntryStorageConflict,match='preview_changed'):asyncio.run(service.bind_stop(env['engine'],**parameters))
    parameters=args(env,iv,did);asyncio.run(service.bind_stop(env['engine'],**parameters))
    with pytest.raises(EntryStorageConflict):asyncio.run(service.bind_stop(env['engine'],**(parameters|{'expected_preview_hash':'d'*64})))
    with pytest.raises(PermissionDenied):asyncio.run(service.bind_stop(env['engine'],**(parameters|{'actor':Actor('medina',False)})))
    monkeypatch.setattr(settings,'admin_user','newadmin')
    monkeypatch.setattr(settings,'managers',[m for m in settings.managers if m.login!='admin'])
    with pytest.raises(PermissionDenied):asyncio.run(service.bind_stop(env['engine'],**parameters))


@pytest.mark.parametrize('failure',['handoff','binding'])
def test_injected_write_failure_rolls_back_handoff_and_stop(env,failure):
    iv=start(env);did=dialog(env);parameters=args(env,iv,did);before=counts(env)
    model=EntryInterviewEvent if failure=='handoff' else EntryChannelStop
    def broken(*a):raise RuntimeError('synthetic insert failure')
    event.listen(model,'after_insert',broken)
    try:
        with pytest.raises(EntryStorageUnavailable):asyncio.run(service.bind_stop(env['engine'],**parameters))
    finally:event.remove(model,'after_insert',broken)
    assert counts(env)==before and read(env,iv)['state']['phase']=='active' and send(env)[0].invoked


def test_capacity_preserves_retry_and_block_and_unbound_read(env,monkeypatch):
    iv=start(env);did=dialog(env);parameters=args(env,iv,did);saved=asyncio.run(service.bind_stop(env['engine'],**parameters))
    monkeypatch.setattr(service,'MAX_STOPS',1)
    assert send(env)[1]==[]
    assert send(env,rules.route(BASE,PROFILE,'996700000002'))[0].invoked
    assert asyncio.run(service.bind_stop(env['engine'],**parameters))==saved
    other=start(env,person(env,key='SECOND'),request_key='SECOND');other_did=dialog(env,channel_key='996700000002')
    with pytest.raises(EntryStorageInvalid,match='registry_limit'):bind(env,other,other_did,request_key='SECOND-STOP')


@pytest.mark.parametrize('column,value',[('transport_key','f'*64),('card_hash','f'*64),('snapshot_hash','f'*64)])
def test_corrupt_registry_blocks_negative_lookup_too(env,column,value):
    iv=start(env);did=dialog(env);saved=bind(env,iv,did)
    async def corrupt():
        async with env['engine'].begin() as c:await c.execute(text(f'UPDATE entry_channel_stops SET {column}=:v WHERE id=:id'),{'v':value,'id':saved['id']})
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):send(env,rules.route(BASE,PROFILE,'996700000002'))


def test_mutable_dialog_cannot_move_permanent_stop(env):
    iv=start(env);did=dialog(env);bind(env,iv,did)
    async def move():
        async with env['sm']() as s:
            d=await s.get(Dialog,did);d.channel_key='996700000002';d.bot_id='alias';await s.commit()
    asyncio.run(move())
    assert send(env)[1]==[] and send(env,rules.route(BASE,PROFILE,'996700000002'))[0].invoked


@pytest.mark.parametrize('kind',['exception','timeout','cancel'])
def test_provider_callback_at_most_once_on_failure(env,monkeypatch,kind):
    calls=[]
    async def callback():
        calls.append(True)
        if kind=='exception':raise RuntimeError('synthetic provider')
        if kind=='cancel':raise asyncio.CancelledError()
        await asyncio.sleep(1)
    monkeypatch.setattr(service,'PROVIDER_TIMEOUT',.01)
    with pytest.raises({'exception':RuntimeError,'timeout':TimeoutError,'cancel':asyncio.CancelledError}[kind]):
        asyncio.run(service.guarded_send(env['engine'],ROUTE,callback))
    assert calls==[True] and send(env)[0].invoked


def test_actual_adapter_alias_suffix_and_account_isolation(env,monkeypatch):
    iv=start(env);did=dialog(env);bind(env,iv,did);a=adapter(monkeypatch);calls=[]
    async def callback():calls.append(True);return 'synthetic'
    assert not asyncio.run(guard.send(a,CHAT+'@c.us',callback)).invoked
    assert not asyncio.run(guard.send(a,CHAT,callback)).invoked
    assert calls==[]
    b=adapter(monkeypatch,'SYN-OTHER')
    assert asyncio.run(guard.send(b,CHAT,callback)).invoked and calls==[True]


@pytest.mark.parametrize('failure',['config','recipient','schema'])
def test_installed_guard_failure_closed(env,monkeypatch,failure):
    a=adapter(monkeypatch);chat=CHAT;calls=[]
    async def callback():calls.append(True)
    if failure=='config':monkeypatch.setattr(settings,'kg_channel_guard_scopes',[{}])
    elif failure=='recipient':chat='123@g.us'
    else:
        async def drop():
            async with env['engine'].begin() as c:await c.execute(text('DROP TABLE entry_channel_stops'))
        asyncio.run(drop())
    assert not asyncio.run(guard.send(a,chat,callback)).invoked and calls==[]


@pytest.mark.parametrize('value',['+996700000001','0996700000001','996700000001@s.whatsapp.net','123@g.us',' 996700000001','123','0',True])
def test_route_rejects_guessed_or_unsupported_recipients(value):
    with pytest.raises(EntryStorageInvalid):rules.route(BASE,PROFILE,value)


@pytest.mark.parametrize('value',['http://synthetic.invalid','https://secret@synthetic.invalid','https://synthetic.invalid?token=x','https://synthetic.invalid/path','https://synthetic.invalid:444'])
def test_account_metadata_cannot_contain_secrets(value):
    with pytest.raises(EntryStorageInvalid):rules.scope(value,PROFILE)


@pytest.mark.parametrize('kind',['boolean_pin','card_fact'])
def test_rehashed_invalid_pin_or_card_semantics_fails_closed(env,kind):
    import json
    iv=start(env);did=dialog(env);saved=bind(env,iv,did)
    async def corrupt():
        async with env['sm']() as session:
            row=await session.get(EntryChannelStop,saved['id'])
            pin=service._plain(row.source_pin)
            if kind=='boolean_pin':pin['observed_revision']=True
            else:
                e=await session.get(EntryInterviewEvent,row.handoff_event_id)
                state=service._plain(e.snapshot);state['handoff']['card']['legal_qualification']='approved'
                state['handoff']['hash']=_hash(state['handoff']['card'])
                payload=service.interviews._event_payload(e)|{'snapshot':state};digest=_hash(payload)
                await session.execute(text('UPDATE entry_interview_events SET snapshot=:s,snapshot_hash=:h WHERE id=:id'),
                    {'s':json.dumps(state),'h':digest,'id':e.id})
                pin['handoff_hash']=digest
                await session.execute(text('UPDATE entry_channel_stops SET card_hash=:h WHERE id=:id'),{'h':state['handoff']['hash'],'id':row.id})
            await session.execute(text('UPDATE entry_channel_stops SET source_pin=:s WHERE id=:id'),{'s':json.dumps(pin),'id':row.id})
            await session.commit()
        async with env['sm']() as session:
            row=await session.get(EntryChannelStop,saved['id']);digest=_hash(service._payload(row))
            await session.execute(text('UPDATE entry_channel_stops SET snapshot_hash=:h WHERE id=:id'),{'h':digest,'id':row.id});await session.commit()
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):send(env)


def test_current_actor_denied_before_database_access(env):
    async def run():
        await service.bind_stop(None,actor=Actor('unknown',True),case_id=1,applicant_id=1,interview_id=1,dialog_id=1,
            resolver=resolve,policy=policy(),expected_revision=1,expected_policy_hash='a'*64,expected_preview_hash='b'*64,
            request_key='SYN',confirmed=True)
    with pytest.raises(PermissionDenied):asyncio.run(run())


def test_actual_registry_aliases_and_global_profile_fallback_share_route(env,monkeypatch):
    from app.core import bots
    from app.channels import outbound
    one=BotConfig(id='syn',scenario='visa',wappi_profile_id=PROFILE)
    two=BotConfig(id='alias',scenario='visa')
    registry=bots.BotRegistry([one,two]);monkeypatch.setattr(bots,'registry',registry);monkeypatch.setattr(outbound,'registry',registry)
    adapter(monkeypatch)
    assert guard.resolve_dialog('whatsapp','syn',CHAT)==guard.resolve_dialog('whatsapp','alias',CHAT+'@c.us')==ROUTE
    iv=start(env);did=dialog(env);p=preview(env,iv,did,resolver=guard.resolve_dialog)
    parameters=args(env,iv,did,resolver=guard.resolve_dialog)
    asyncio.run(service.bind_stop(env['engine'],**parameters))
    calls=[]
    async def callback():calls.append(True)
    assert not asyncio.run(guard.send(WappiAdapter(bot=two),CHAT,callback)).invoked and calls==[]


def test_adapter_identity_changed_while_waiting_is_not_sent(env,monkeypatch):
    a=adapter(monkeypatch);original=service._registry;calls=[]
    async def registry(session):
        result=await original(session);a._profile_id='CHANGED';return result
    monkeypatch.setattr(service,'_registry',registry)
    async def callback():calls.append(True)
    assert not asyncio.run(guard.send(a,CHAT,callback)).invoked and calls==[]


def test_expired_policy_cannot_resume_stop_or_prevent_exact_receipt_retry(env,monkeypatch):
    iv=start(env);did=dialog(env);parameters=args(env,iv,did)
    saved=asyncio.run(service.bind_stop(env['engine'],**parameters))
    monkeypatch.setattr(service,'_now',lambda:datetime(2028,1,1,tzinfo=timezone.utc))
    assert send(env)[1]==[] and asyncio.run(service.bind_stop(env['engine'],**parameters))==saved
    with pytest.raises(PermissionDenied,match='expired'):preview(env,iv,did)


def test_new_day_requires_fresh_preview_even_when_policy_remains_valid(env,monkeypatch):
    iv=start(env);did=dialog(env);parameters=args(env,iv,did)
    monkeypatch.setattr(service,'_now',lambda:datetime(2026,12,20,tzinfo=timezone.utc))
    with pytest.raises(EntryStorageConflict,match='preview_changed'):asyncio.run(service.bind_stop(env['engine'],**parameters))
    assert read(env,iv)['state']['phase']=='active' and send(env)[0].invoked


@pytest.mark.parametrize('kind',['update','delete','bulk'])
def test_permanent_binding_rejects_orm_mutation(env,kind):
    from sqlalchemy import update
    from app.domain.models import DomainError
    iv=start(env);did=dialog(env);saved=bind(env,iv,did)
    async def mutate():
        async with env['sm']() as session:
            row=await session.get(EntryChannelStop,saved['id'])
            if kind=='update':row.transport_key='f'*64
            elif kind=='delete':await session.delete(row)
            else:await session.execute(update(EntryChannelStop).values(transport_key='f'*64))
            await session.commit()
    with pytest.raises(DomainError):asyncio.run(mutate())
    assert send(env)[1]==[]


@pytest.mark.parametrize('anchor',['case','dialog'])
@pytest.mark.parametrize('boundary',['expiry','day'])
def test_policy_and_preview_clock_are_sampled_after_all_row_locks(env,monkeypatch,anchor,boundary):
    from datetime import timedelta
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.domain.models import ServiceCase
    iv=start(env);did=dialog(env)
    before=datetime(2027,1,1,17,59,59,tzinfo=timezone.utc) if boundary=='expiry' else datetime(2026,12,1,17,59,59,tzinfo=timezone.utc)
    clock=[before];monkeypatch.setattr(service,'_now',lambda:clock[0]);parameters=args(env,iv,did)
    original=AsyncSession.scalar;target=ServiceCase if anchor=='case' else Dialog
    async def delayed(session,statement,*a,**kw):
        result=await original(session,statement,*a,**kw)
        descriptions=getattr(statement,'column_descriptions',[])
        if (getattr(statement,'_for_update_arg',None) is not None and descriptions and descriptions[0].get('entity') is target):
            clock[0]=before+timedelta(seconds=2)
        return result
    monkeypatch.setattr(AsyncSession,'scalar',delayed)
    with pytest.raises(PermissionDenied if boundary=='expiry' else EntryStorageConflict):
        asyncio.run(service.bind_stop(env['engine'],**parameters))
    assert read(env,iv)['state']['phase']=='active' and send(env)[0].invoked
