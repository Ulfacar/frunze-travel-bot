"""Actual authenticated webhook -> Wappi parser -> handle -> durable typed flow."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.config import settings, BotConfig
from app.channels.wappi import WappiAdapter
from app.core.orchestrator import Orchestrator
from app.core import kg_channel_guard, channel_heartbeat, state
from app.domain import knowledge_publication
from tests.test_dialogue_sessions import (env, clock, current_clock, connected_clock, route_clock, admins,
    enforce_sqlite_foreign_keys, activation, persistent_panel, setup, journal_state, read, inbox_messages)
from tests.test_entry_channel_stops import ROUTE, resolve
from tests.test_kg_dialogue_hook import packet


def test_malformed_provider_identity_persists_unknown_and_cannot_authorize_answer(env,tmp_path,monkeypatch):
    from app.core import kg_dialogue
    from tests.test_dialogue_sessions import receive
    setup(env,tmp_path)
    monkeypatch.setattr(settings,'kg_dialogue_managed_routes',[ROUTE])
    monkeypatch.setattr(settings,'wappi_base_url',ROUTE['base_url'])
    monkeypatch.setattr(settings,'wappi_token','SYN-ONLY')
    monkeypatch.setattr(kg_dialogue,'authority_for',lambda route:env['authority'])
    monkeypatch.setattr(kg_channel_guard,'resolve_dialog',resolve)
    monkeypatch.setattr(state,'get_state_store',lambda:SimpleNamespace(load=AsyncMock(return_value=SimpleNamespace(intercepted=False))))
    bot=BotConfig(id='syn',scenario='visa',wappi_profile_id=ROUTE['profile_id'])
    calls=[]
    def malformed(request):
        calls.append(request)
        return httpx.Response(200,json={'message_id':{'error':'NOT-ACCEPTED'}})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(malformed)) as client:
            adapter=WappiAdapter(bot,client=client)
            orch=Orchestrator(adapter,bot);orch._bots_on=AsyncMock(return_value=True)
            raw=packet(id='SYN-MALFORMED')
            await orch.handle(await adapter.parse(raw))
            await orch.handle(await adapter.parse(raw))
    asyncio.run(run())
    assert len(calls)==1
    _,rows,flow=journal_state(env)
    assert flow['outcome']=='unknown'
    label=flow['prompt']['prompt']['displayed'][0]['label']
    assert receive(env,label+': 1','SYN-UNSEEN')['stopped']
    assert 'document_type' not in read(env,env['iv'])['state']['answers']


@pytest.mark.parametrize('failure',['timeout','cancel'])
def test_actual_managed_attempt_timeout_or_cancellation_is_unknown_and_not_retried(env,tmp_path,monkeypatch,failure):
    from app.core import kg_dialogue
    from app.domain import entry_channel_stops, dialogue_sessions
    setup(env,tmp_path)
    monkeypatch.setattr(settings,'kg_dialogue_managed_routes',[ROUTE])
    monkeypatch.setattr(settings,'wappi_base_url',ROUTE['base_url'])
    monkeypatch.setattr(kg_dialogue,'authority_for',lambda route:env['authority'])
    monkeypatch.setattr(kg_channel_guard,'resolve_dialog',resolve)
    monkeypatch.setattr(entry_channel_stops,'PROVIDER_TIMEOUT',.02 if failure=='timeout' else 25)
    monkeypatch.setattr(state,'get_state_store',lambda:SimpleNamespace(load=AsyncMock(return_value=SimpleNamespace(intercepted=False))))
    bot=BotConfig(id='syn',scenario='visa',wappi_profile_id=ROUTE['profile_id'])
    adapter=WappiAdapter(bot)
    orch=Orchestrator(adapter,bot);orch._bots_on=AsyncMock(return_value=True)
    calls=[]
    async def run():
        entered=asyncio.Event()
        async def uncertain(*args,**kwargs):
            calls.append(True);entered.set()
            await asyncio.Event().wait()
        adapter.send=uncertain
        raw=packet(id='SYN-UNCERTAIN')
        msg=await adapter.parse(raw)
        task=asyncio.create_task(orch.handle(msg))
        await asyncio.wait_for(entered.wait(),180)
        if failure=='cancel':
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
        else:await task
        # Provider redelivery uses the original durable message identity.
        await orch.handle(await adapter.parse(raw))
        assert calls==[True]
    asyncio.run(run())
    _,rows,flow=journal_state(env)
    assert flow['outcome']=='unknown'
    assert len([r for r in rows if r.kind=='claim'])==1
    assert len([r for r in rows if r.kind=='outcome'])==1
    # The normal claim API cannot grant a second provider attempt.
    header=journal_state(env)[0]
    async def denied_claim():
        return await dialogue_sessions.claim(env['engine'],route=ROUTE,session_id=header.id,
            prompt_revision=flow['prompt']['revision'],authority=env['authority'],resolver=resolve)
    assert asyncio.run(denied_claim()) is None
    assert not orch._buffers and not orch._timers


@pytest.mark.parametrize('language',['ru','en'])
def test_actual_webhook_provider_acceptance_and_normal_saved_progress(env,tmp_path,monkeypatch,language):
    import app.main as main
    setup(env,tmp_path,language=language)
    authority=env['authority']
    monkeypatch.setattr(settings,'kg_dialogue_managed_routes',[ROUTE])
    monkeypatch.setattr(settings,'kg_typed_dialogue_authority',dict(policy=authority.policy.document,
        dialogue_policy=authority.dialogue.document,current_stay_policy=authority.current.document,
        facts=[authority.fact.document],calendars=authority.calendars.export()))
    monkeypatch.setattr(settings,'kg_interview_policy',authority.interview.document())
    monkeypatch.setattr(settings,'kg_channel_stop_policy',authority.channel.document())
    monkeypatch.setattr(settings,'kg_qualification_policy',authority.qualification.document)
    monkeypatch.setattr(settings,'kg_knowledge_policy_ref',authority.publication.reference)
    monkeypatch.setattr(settings,'kg_knowledge_policy_sha256',authority.publication.fingerprint)
    monkeypatch.setattr(settings,'kg_knowledge_publishers',list(authority.publication.publishers))
    monkeypatch.setattr(settings,'wappi_base_url',ROUTE['base_url'])
    monkeypatch.setattr(settings,'wappi_token','SYNTHETIC-ONLY')
    monkeypatch.setattr(kg_channel_guard,'resolve_dialog',resolve)
    from app.integrations.panel import store as panel_store
    monkeypatch.setattr(panel_store,'_pg_store',panel_store.PostgresConversationStore(env['sm']))
    sent=[]
    def accepted(request):
        sent.append(request)
        return httpx.Response(200,json={'message_id':'SYN-PROVIDER-'+str(len(sent))})
    provider=httpx.AsyncClient(transport=httpx.MockTransport(accepted))
    bot=BotConfig(id='syn',scenario='visa',wappi_profile_id=ROUTE['profile_id'])
    orch=Orchestrator(WappiAdapter(bot,client=provider),bot)
    orch._bots_on=AsyncMock(return_value=True)
    monkeypatch.setattr(state,'get_state_store',lambda:SimpleNamespace(load=AsyncMock(return_value=SimpleNamespace(intercepted=False))))
    monkeypatch.setattr(main,'_wappi_orchestrators',{ROUTE['profile_id']:orch})
    monkeypatch.setattr(main,'_verify_webhook',lambda request:True)
    monkeypatch.setattr(main,'_seen_before',Mock(side_effect=AssertionError('legacy dedupe must not hide changed content')))
    monkeypatch.setattr(channel_heartbeat,'note_inbound',AsyncMock())
    client=TestClient(main.app)
    def send(body,identifier):
        response=client.post('/webhook/wappi',json={'messages':[packet(body=body,id=identifier)]})
        assert response.status_code==200 and response.json()['handled']==1
    try:
        send('Здравствуйте' if language=='ru' else 'hello','SYN-WEB-0')
        assert len(sent)==1, journal_state(env)[2]
        for i,path,literal in [(1,'document_type','1'),(2,'passport_two_blank_pages','да' if language=='ru' else 'yes'),
                                (3,'passport_expiry',env['profile_doc']['profile']['passport_expiry'])]:
            _,_,flow=journal_state(env)
            assert flow['outcome']=='provider_accepted'
            label=next(p['label'] for p in flow['prompt']['prompt']['displayed'] if p['path']==path)
            body=label+': '+literal;send(body,'SYN-WEB-'+str(i))
            assert len(sent)==i+1, journal_state(env)[2]
            original_count=len(journal_state(env)[1]);send(body,'SYN-WEB-'+str(i))
            assert len(sent)==i+1 and len(journal_state(env)[1])==original_count
        assert read(env,env['iv'])['state']['answers']['passport_expiry']['value']==env['profile_doc']['profile']['passport_expiry']
        assert len(inbox_messages(env))==4
        transcript=asyncio.run(panel_store.get_conversation_store().get('syn:'+ROUTE['recipient']))
        assert transcript is not None and len(transcript.messages)==4
        assert all(m.sender=='client' for m in transcript.messages)
        assert not orch._buffers and not orch._timers
        _,_,flow=journal_state(env)
        assert len(flow['prompt']['check']['reconciliation']['tail'])==3
        # Bot-off still processes privacy; no further provider call.
        orch._bots_on=AsyncMock(return_value=False)
        send('Удалите мои данные' if language=='ru' else 'Delete my data','SYN-WEB-PRIVACY')
        assert journal_state(env)[2]['collection_blocked'] and len(sent)==4
        assert len(inbox_messages(env))==4
    finally:
        client.close();asyncio.run(provider.aclose())
