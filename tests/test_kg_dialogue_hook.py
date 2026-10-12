import asyncio
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
import httpx
from fastapi.testclient import TestClient

from app.config import settings, BotConfig
from app.channels.wappi import WappiAdapter
from app.core import kg_dialogue as hook, kg_channel_guard as guard, orchestrator as orchestration
from app.domain.entry_channel_policy import route

BASE='https://synthetic.invalid'
PROFILE='SYN-PROFILE'
CHAT='996700000001'
ROUTE=route(BASE,PROFILE,CHAT)


@pytest.mark.parametrize('response,expected',[
    ({'message_id':'SYN-ACCEPTED'},'SYN-ACCEPTED'),
    ({'message':{'id':'SYN-NESTED'}},'SYN-NESTED'),
    ({'id':'SYN-SAME','message':{'message_id':'SYN-SAME'}},'SYN-SAME'),
    *[({'message_id':v},'') for v in (True,False,123,0,1.5,{},[],{'error':'NO'},'','   ','SYN\nID','SYN\x00ID','x'*257)],
    ({'message_id':True,'id':'SYN-VALID'},''),
    ({'message_id':'SYN-VALID','message':{'id':[]}},''),
    ({'message_id':'SYN-ONE','id':'SYN-TWO'},''),
])
def test_actual_adapter_strict_acceptance_uses_original_json_identity(monkeypatch,response,expected):
    monkeypatch.setattr(settings,'wappi_base_url',BASE)
    monkeypatch.setattr(settings,'wappi_token','SYN-ONLY')
    bot=BotConfig(id='syn',scenario='visa',wappi_profile_id=PROFILE)
    requests=[]
    def respond(request):
        requests.append(request)
        return httpx.Response(200,json=response)
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            return await WappiAdapter(bot,client=client).send(CHAT,'SYN-BODY',require_acceptance_id=True)
    assert asyncio.run(run())==expected
    assert len(requests)==1 and b'require_acceptance_id' not in requests[0].content


def packet(**kw):
    return dict(wh_type='incoming_message',profile_id=PROFILE,id='SYN-MSG',body='hello',
        type='chat',is_me=False,chat_type='dialog',chatId=CHAT+'@c.us',**{'from':CHAT+'@c.us'}) | kw


@pytest.fixture
def harness(monkeypatch):
    from app.channels import wappi
    from app.core import media_capture
    monkeypatch.setattr(settings,'wappi_base_url',BASE)
    monkeypatch.setattr(settings,'wappi_token','SYNTHETIC-NOT-REAL')
    monkeypatch.setattr(settings,'kg_dialogue_managed_routes',[ROUTE])
    monkeypatch.setattr(settings,'kg_typed_dialogue_authority',{})
    monkeypatch.setattr(settings,'kg_channel_guard_scopes',[])
    bot=BotConfig(id='syn',scenario='visa',wappi_profile_id=PROFILE)
    adapter=WappiAdapter(bot);adapter.send=AsyncMock(return_value='SYN-PROVIDER')
    orch=orchestration.Orchestrator(adapter,bot)
    spies=dict(stt=AsyncMock(side_effect=AssertionError('STT must not run')),
        capture=AsyncMock(side_effect=AssertionError('media capture must not run')),
        referral=Mock(side_effect=AssertionError('referral extraction must not run')),
        expiry=AsyncMock(side_effect=AssertionError('legacy intercept expiry must not run')))
    monkeypatch.setattr(wappi,'_stt_allowed',spies['stt'])
    monkeypatch.setattr(wappi,'extract_ad_referral',spies['referral'])
    monkeypatch.setattr(media_capture,'note_raw',spies['capture'])
    monkeypatch.setattr(orchestration,'expire_auto_intercept',spies['expiry'])
    received=AsyncMock(return_value=dict(duplicate=False,stopped=True,prompt_revision=None))
    monkeypatch.setattr(hook.sessions,'receive',received)
    monkeypatch.setattr(guard,'_engine',lambda:object())
    return orch,received,spies


@pytest.mark.parametrize('kind', ['chat','ptt','image','document'])
def test_actual_parser_and_handle_precede_stt_media_intercept_and_legacy(harness,kind):
    orch,received,spies=harness
    raw=packet(type=kind,body='Delete my data')
    async def run():
        msg=await orch.channel.parse(raw)
        assert msg.user_id==CHAT and msg.text=='Delete my data'
        assert msg.kind==('text' if kind=='chat' else 'non_text')
        await orch.handle(msg)
    asyncio.run(run())
    received.assert_awaited_once()
    assert received.call_args.kwargs['text']=='Delete my data'
    assert received.call_args.kwargs['route']==ROUTE
    assert not orch._buffers and not orch._timers
    orch.channel.send.assert_not_awaited()
    for spy in spies.values():spy.assert_not_called()


@pytest.mark.parametrize('change', [{'is_me':True},{'wh_type':'message_ack'},{'chat_type':'group'},
    {'type':'reaction'},{'from':'996700000002@c.us'},{'profile_id':'OTHER'}])
def test_direct_entrypoint_does_not_treat_echo_group_or_wrong_identity_as_answer(harness,change):
    orch,received,_=harness
    async def run():await orch.handle(await orch.channel.parse(packet(**change)))
    asyncio.run(run())
    received.assert_not_awaited();orch.channel.send.assert_not_awaited()


def test_managed_legacy_send_denied_even_without_companion_account_activation(harness):
    orch,_,_=harness;called=[]
    async def callback():called.append(True)
    result=asyncio.run(guard.send(orch.channel,CHAT,callback))
    assert not result.invoked and not called


@pytest.mark.parametrize('privacy',[False,True])
def test_oversized_packet_only_privacy_reaches_stored_operational_hold(harness,privacy):
    orch,received,_=harness
    raw=packet(body='x'*140000+(' Delete my data' if privacy else ''))
    async def run():await orch.handle(await orch.channel.parse(raw))
    asyncio.run(run())
    assert received.await_count==int(privacy)
    orch.channel.send.assert_not_awaited()


@pytest.mark.parametrize('broken', [[ROUTE,ROUTE],[{'recipient':CHAT}],None])
def test_invalid_deployment_config_is_consumed_and_never_empty(harness,monkeypatch,broken):
    orch,received,spies=harness
    monkeypatch.setattr(settings,'kg_dialogue_managed_routes',broken)
    received.side_effect=RuntimeError('synthetic invalid authority')
    async def run():
        await orch.handle(await orch.channel.parse(packet(type='ptt')))
        async def callback():raise AssertionError('must not send')
        assert not (await guard.send(orch.channel,CHAT,callback)).invoked
    asyncio.run(run())
    spies['stt'].assert_not_awaited();spies['expiry'].assert_not_awaited()


def test_unrelated_route_keeps_ordinary_send(harness):
    orch,_,_=harness;called=[]
    async def callback():called.append(True);return 'SYN-OK'
    result=asyncio.run(guard.send(orch.channel,'996700000002',callback))
    assert result.invoked and called==[True]


def test_managed_storage_failure_returns_retryable_webhook_status_without_legacy_send(harness,monkeypatch):
    import app.main as main
    from app.core import channel_heartbeat
    from app.domain.entry_storage import EntryStorageUnavailable
    orch,received,_=harness
    received.side_effect=EntryStorageUnavailable('synthetic_write_unavailable')
    monkeypatch.setattr(main,'_verify_webhook',lambda request:True)
    monkeypatch.setattr(main,'_wappi_orchestrators',{PROFILE:orch})
    monkeypatch.setattr(channel_heartbeat,'note_inbound',AsyncMock())
    client=TestClient(main.app)
    try:
        assert client.post('/webhook/wappi',json={'messages':[packet()]}).status_code==503
    finally:client.close()
    orch.channel.send.assert_not_awaited()


def test_actual_webhook_keeps_auth_filters_and_passes_retries_to_durable_identity(harness,monkeypatch):
    import app.main as main
    from app.core import channel_heartbeat
    orch,received,_=harness
    monkeypatch.setattr(main,'_verify_webhook',lambda request:True)
    monkeypatch.setattr(main,'_wappi_orchestrators',{PROFILE:orch})
    seen=Mock(return_value=True);monkeypatch.setattr(main,'_seen_before',seen)
    monkeypatch.setattr(channel_heartbeat,'note_inbound',AsyncMock())
    monkeypatch.setattr(channel_heartbeat,'note_service_event',AsyncMock())
    monkeypatch.setattr(settings,'capture_manager_echo',False)
    client=TestClient(main.app)
    try:
        raw=packet()
        for body in ('hello','different content same provider ID'):
            raw['body']=body
            response=client.post('/webhook/wappi',json={'messages':[deepcopy(raw)]})
            assert response.status_code==200 and response.json()['handled']==1
        for change in ({'is_me':True},{'chat_type':'group'},{'type':'reaction'}):
            client.post('/webhook/wappi',json={'messages':[packet(**change)]})
        monkeypatch.setattr(main,'_verify_webhook',lambda request:False)
        assert client.post('/webhook/wappi',json={'messages':[packet()]}).status_code==403
    finally:client.close()
    assert received.await_count==2
    assert received.call_args_list[0].kwargs['attachment_identity']!=received.call_args_list[1].kwargs['attachment_identity']
    seen.assert_not_called()
