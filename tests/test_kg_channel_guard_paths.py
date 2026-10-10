import asyncio
from datetime import datetime,timedelta,timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock

import pytest

from app.channels.base import Message
from app.core import orchestrator as orch,followup,kg_channel_guard as guard
from app.core.state import DialogState
from tests.test_entry_channel_stops import env,admins,activation,start,dialog,bind,args,service,adapter,CHAT,ROUTE


def harness(monkeypatch,*,funnel='visa',intercepted=False):
    a=adapter(monkeypatch);a.send=AsyncMock(return_value='SYN-PROVIDER')
    state=DialogState(user_id='syn-user',funnel=funnel);state.intercepted=intercepted
    store=SimpleNamespace(load=AsyncMock(return_value=state),save=AsyncMock())
    panel=SimpleNamespace(add_message=AsyncMock(return_value=1),mark_message_status=AsyncMock(),get=AsyncMock(return_value=None))
    monkeypatch.setattr(orch,'get_state_store',lambda:store);monkeypatch.setattr(orch,'get_conversation_store',lambda:panel)
    o=orch.Orchestrator(channel=a);o._bots_on=AsyncMock(return_value=True);o._sync_card=AsyncMock();o._absorb_silent=AsyncMock();o._maybe_instant_handoff=AsyncMock()
    from app.integrations.crm import bitrix_mirror
    mirror=Mock();monkeypatch.setattr(bitrix_mirror,'fire',mirror)
    return o,state,store,panel,a,mirror


@pytest.mark.parametrize('branch',['greeting','persona','visa_faq','faq','normal','llm_error','wait_ack','file','voice_handoff','voice_fallback'])
def test_each_installed_reply_branch_hits_final_stop_without_success_side_effects(env,monkeypatch,branch):
    iv=start(env);did=dialog(env);bind(env,iv,did)
    o,state,store,panel,a,mirror=harness(monkeypatch,funnel=None if branch=='greeting' else 'visa')
    # Force work past the optimization: the real final guard must still stop it.
    monkeypatch.setattr(guard,'blocked',AsyncMock(return_value=False))
    msg=Message(channel='whatsapp',user_id='syn-user',chat_id=CHAT,text='synthetic request')
    async def normal(*a):state.stage='manager';return 'SYNTHETIC ANSWER'
    async def broken(*a):raise RuntimeError('synthetic LLM error')
    monkeypatch.setattr(orch,'get_funnel',lambda name:SimpleNamespace(handle=broken if branch=='llm_error' else normal))
    if branch=='greeting':monkeypatch.setattr(orch,'detect_funnel',lambda text:None)
    elif branch=='persona':msg.text='привет'
    elif branch=='visa_faq':
        from app.core import visa_pricing
        monkeypatch.setattr(visa_pricing,'visa_price_reply',lambda text:'SYNTHETIC FAQ')
    elif branch=='faq':
        from app.core import faq
        state.funnel='tours'
        monkeypatch.setattr(faq,'get_faq_store',lambda:SimpleNamespace(candidates=AsyncMock(return_value=[])))
        monkeypatch.setattr(faq,'match_faq',lambda *a,**k:SimpleNamespace(answer='SYNTHETIC FAQ',handoff_only=True,allow_during_qualification=False))
    elif branch=='wait_ack':state.intercepted=True;state.stage='manager'
    elif branch.startswith('voice') or branch=='file':
        msg.kind='non_text';msg.text='';msg.media_type='document' if branch=='file' else 'voice'
        state.consecutive_audio=1 if branch=='voice_handoff' else 0
    if msg.kind=='non_text':asyncio.run(o._handle_non_text(msg,log=False))
    else:asyncio.run(o._run_turn(msg))
    a.send.assert_not_awaited();panel.add_message.assert_not_awaited();panel.mark_message_status.assert_not_awaited()
    mirror.assert_not_called();o._maybe_instant_handoff.assert_not_awaited()
    if branch=='wait_ack':assert state.wait_ack_sent is False


def test_llm_started_before_atomic_handoff_is_suppressed_at_final_invocation(env,monkeypatch):
    iv=start(env);did=dialog(env);parameters=args(env,iv,did);calls=[]
    o,state,store,panel,a,mirror=harness(monkeypatch)
    o._maybe_persona_greeting=AsyncMock(return_value=False);o._maybe_faq_reply=AsyncMock(return_value=False)
    async def delayed(msg,state):
        calls.append('llm_started')
        await service.bind_stop(env['engine'],**parameters)
        state.stage='manager';return 'SYNTHETIC LATE REPLY'
    monkeypatch.setattr(orch,'get_funnel',lambda name:SimpleNamespace(handle=delayed))
    asyncio.run(o._run_turn(Message(channel='whatsapp',user_id='syn-user',chat_id=CHAT,text='synthetic request')))
    assert calls==['llm_started'];a.send.assert_not_awaited();panel.add_message.assert_not_awaited();o._maybe_instant_handoff.assert_not_awaited()


def test_bound_early_path_avoids_llm_and_legacy_reset_cannot_resume(env,monkeypatch):
    iv=start(env);did=dialog(env);bind(env,iv,did)
    o,state,store,panel,a,mirror=harness(monkeypatch);state.intercepted=False
    handler=AsyncMock();monkeypatch.setattr(orch,'get_funnel',lambda name:SimpleNamespace(handle=handler))
    asyncio.run(o._run_turn(Message(channel='whatsapp',user_id='syn-user',chat_id=CHAT,text='synthetic request')))
    handler.assert_not_awaited();a.send.assert_not_awaited();store.load.assert_not_awaited()


@pytest.mark.parametrize('manual',[False,True])
def test_followup_selected_before_handoff_stops_without_count_touch_or_outbound(env,monkeypatch,manual):
    from app.channels import outbound
    iv=start(env);did=dialog(env);parameters=args(env,iv,did)
    a=adapter(monkeypatch);a.send=AsyncMock(return_value='SYN')
    monkeypatch.setattr(outbound,'_adapter_for',lambda *args:a)
    conv=SimpleNamespace(user_id='syn-user',chat_id=CHAT,channel='whatsapp',bot_id='syn',funnel='visa',stage='qualification',followup_count=0)
    store=SimpleNamespace(all_conversations=AsyncMock(return_value=[conv]),add_message=AsyncMock(),update_meta=AsyncMock())
    monkeypatch.setattr(followup,'get_conversation_store',lambda:store)
    monkeypatch.setattr(followup,'select_followup_targets',lambda *args:[conv])
    touch=Mock();monkeypatch.setattr(followup,'_mark_touch',touch)
    original=outbound.send_automated_to_client
    async def selected(*a,**kw):
        await service.bind_stop(env['engine'],**parameters)
        return await original(*a,**kw)
    monkeypatch.setattr(outbound,'send_automated_to_client',selected)
    monkeypatch.setattr(followup,'is_quiet_hour',lambda *a:False)
    result=asyncio.run(followup.run_manual() if manual else followup._send_followups(datetime.now(timezone.utc),followup.settings))
    assert result==({'sent':0,'quiet':False} if manual else 0)
    a.send.assert_not_awaited();store.add_message.assert_not_awaited();store.update_meta.assert_not_awaited();touch.assert_not_called()


def test_manual_human_outbound_is_separate_and_unbound_provider_none_is_success(env,monkeypatch):
    from app.channels import outbound
    iv=start(env);did=dialog(env);bind(env,iv,did)
    a=adapter(monkeypatch);a.send=AsyncMock(return_value=None);monkeypatch.setattr(outbound,'_adapter_for',lambda *args:a)
    assert asyncio.run(outbound.send_to_client('whatsapp','syn',CHAT,'SYNTHETIC HUMAN')) is None
    assert a.send.await_count==1
    result=asyncio.run(outbound.send_automated_to_client('whatsapp','syn','996700000002','SYNTHETIC AUTO'))
    assert result==service.SendResult(True,None) and a.send.await_count==2


@pytest.mark.parametrize('changed',['recipient','profile','origin'])
def test_actual_wappi_request_uses_captured_route_across_pending_log_await(env,monkeypatch,changed):
    import httpx
    from app.config import settings
    from app.domain import entry_channel_policy as policy,messaging_shadow
    from app.integrations.crm import bitrix_mirror
    iv=start(env);did=dialog(env);bind(env,iv,did)
    a=adapter(monkeypatch);a._token='synthetic-provider-token';calls=[]
    initial_chat='996700000002' if changed=='recipient' else CHAT
    if changed=='profile':a._profile_id='SYN-OTHER'
    if changed=='origin':a._base='https://other-synthetic.invalid'
    initial=policy.route(a._base,a._profile_id,initial_chat)
    monkeypatch.setattr(settings,'kg_channel_guard_scopes',[policy.scope(ROUTE['base_url'],ROUTE['profile_id'])]+(
        [policy.scope(a._base,a._profile_id)] if changed!='recipient' else []))
    class Client:
        async def post(self,url,**kwargs):
            calls.append((url,kwargs['params']['profile_id'],kwargs['json']['recipient']))
            return httpx.Response(200,json={'message_id':'SYNTHETIC'},request=httpx.Request('POST',url))
    a._client=Client();msg=Message(channel='whatsapp',user_id='syn-user',chat_id=initial_chat,text='synthetic')
    async def pending(*args,**kwargs):
        a._base=ROUTE['base_url'];a._profile_id=ROUTE['profile_id'];msg.chat_id=CHAT
        await asyncio.sleep(0)
        return 1
    panel=SimpleNamespace(add_message=AsyncMock(side_effect=pending),mark_message_status=AsyncMock())
    monkeypatch.setattr(orch,'get_conversation_store',lambda:panel)
    monkeypatch.setattr(bitrix_mirror,'fire',Mock());monkeypatch.setattr(messaging_shadow,'mirror_outbound_message',AsyncMock())
    assert asyncio.run(orch.Orchestrator(channel=a)._reply(msg,'SYNTHETIC RESPONSE')) is True
    assert calls==[(initial['base_url']+'/api/sync/message/send',initial['profile_id'],initial['recipient'])]
