"""Connected synthetic evidence only; no real authority, provider or activation."""
import asyncio
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select

from app.domain import dialogue_sessions as service, dialogue_journal as journal
from app.domain import entry_interviews, current_stay_stops, entry_channel_stops
from app.domain.dialogue_authority import DialogueAuthority
from app.domain.dialogue_policy import DialoguePolicy
from app.domain.dialogue_session_policy import SessionPolicy, VERSION
from app.domain.current_stay_policy import CurrentStayFact
from app.domain.entry_storage import _hash, EntryStorageConflict
from app.domain.models import EntryDialogueSession
from app.knowledge import dialogue_questions, dialogue_reconciliation
from tests import test_current_stay_stops as current_test
from tests.test_current_stay_stops import env, clock as current_clock, connected_clock, route_clock, admins
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_channel_stops import activation, dialog, resolve, ROUTE, policy as channel_policy
from tests.test_entry_interviews import start, correct, read, action, counts
from tests.test_admin_kg_entry import ADMIN
from tests.test_knowledge_publication import POLICY
from app.domain.knowledge_publication import _policy as publication_document


@pytest.fixture(autouse=True)
def persistent_panel(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings,'panel_backend','postgres')


@pytest.fixture(autouse=True)
def clock(current_clock, monkeypatch):
    at = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)
    def now():
        nonlocal at
        at += timedelta(microseconds=1)
        return at
    for mod in (service, current_stay_stops, entry_interviews): monkeypatch.setattr(mod, '_now', now)


def setup(env, tmp_path, *, language='ru', **kw):
    from app.integrations.crm.db import Conversation, ConvMessage
    async def inbox_schema():
        async with env['engine'].begin() as conn:
            await conn.run_sync(lambda sync: Conversation.metadata.create_all(sync,
                tables=[Conversation.__table__, ConvMessage.__table__]))
    asyncio.run(inbox_schema())
    current_test.setup(env, tmp_path, **kw)
    ip = env['interview_policy']; p = env['profile_doc']['profile']
    iv = start(env, env['person'], profile_id=env['saved']['qualification_id'], policy=ip,
               expected_policy_hash=ip.digest, language=language)
    correct(env, iv, {'consent.given': True}, policy=ip, expected_policy_hash=ip.digest)
    correct(env, iv, {'consent.on': '2026-10-12', 'consent.evidence_ref': 'SYN-CONSENT', 'consent.evidence_sha256': 'a'*64},
            policy=ip, expected_policy_hash=ip.digest)
    values = {'citizenships': ['RUS'], 'location': 'in_kg', 'actual_entry.on': p['in_kg_since'], 'actual_entry.point': 'Synthetic crossing',
        'purpose': p['purpose'], 'entry_on': p['entry_date'], 'exit_on': p['exit_date'], 'party_type': 'individual', 'applicants_count': 1,
        'planned_entry_point': 'Synthetic airport', 'accommodation_address': 'Synthetic hotel',
        'contact_name': 'Synthetic', 'contact_phone': 'Synthetic', 'contact_messenger': 'Synthetic', 'contact_role': 'applicant',
        'contact_email': 'synthetic@example.invalid', 'terms.accepted': False, 'residence_country': 'RUS',
        'foreign_residence.exists': False, 'organized_group.exists': False, 'previous_visits': False,
        'current_basis': p['current_basis_in_kg'], 'current_until': p['current_basis_until']}
    for key, value in values.items(): correct(env, iv, {key: value}, policy=ip, expected_policy_hash=ip.digest)
    current = read(env, iv, policy=ip); did = dialog(env)
    env['iv'] = iv
    env['fact_doc']['interview'] = dict(id=iv['interview_id'], header_hash=current['interview']['snapshot_hash'], head_hash=current['history'][-1]['snapshot_hash'])
    cp = channel_policy()
    dp = DialoguePolicy(dict(format='kg-dialogue-policy/1', reference='SYN-DIALOGUE', proof='a'*64,
        privacy_reference='SYN-PRIVACY', privacy_proof='b'*64, valid_from='2026-01-01', review_due_on='2027-01-01',
        triage_version='kg-dialogue-interrupts/1', interview_policy_hash=ip.digest, channel_policy_hash=cp.digest,
        assignments=[dict(route=ROUTE, case_id=env['cases']['visa'], applicant_id=env['person']['id'], interview_id=iv['interview_id'],
            dialog_id=did, actor='admin', header_hash=current['interview']['snapshot_hash'], reference='SYN-ASSIGNMENT', proof='c'*64)]))
    sp = SessionPolicy(dict(format='kg-dialogue-session-policy/1', reference='SYN-TYPED', proof='d'*64,
        valid_from='2026-01-01', review_due_on='2027-01-01', algorithm=VERSION,
        question_map_hash=dialogue_questions.MAP_HASH, reconciliation_map_hash=dialogue_reconciliation.MAP_HASH,
        dialogue_policy_hash=dp.digest, current_stay_policy_hash=env['current_policy'].digest,
        qualification_policy_hash=env['qualification_policy'].digest, publication_policy_hash=_hash(publication_document(POLICY)),
        calendar_hash=env['calendars'].content_hash,
        retained_privacy_processing='original_operator_if_currently_authorized_no_new_collection',
        delivery='durable_claim_single_attempt_provider_acceptance_required'))
    env['authority'] = DialogueAuthority(sp, dp, cp, ip, env['current_policy'], CurrentStayFact(env['fact_doc']),
                                       env['qualification_policy'], POLICY, env['calendars'])
    return env


def receive(env, text='hello', provider_id='SYN-FIRST', **kw):
    return asyncio.run(service.receive(env['engine'], route=ROUTE, text=text, provider_id=provider_id,
                                      resolver=resolve, **(dict(authority=env['authority']) | kw)))


def journal_state(env):
    async def run():
        async with env['sm']() as session:
            header = await session.scalar(select(EntryDialogueSession))
            rows, flow, total = await journal.history(session, header)
            return header, rows, flow
    return asyncio.run(run())


def deliver(env, receipt):
    async def run():
        cap = await service.claim(env['engine'], route=ROUTE, session_id=receipt['session_id'],
            prompt_revision=receipt['prompt_revision'], authority=env['authority'], resolver=resolve)
        assert cap is not None
        calls = []
        async def provider(): calls.append(cap.body); return 'synthetic-provider-accepted'
        result = await entry_channel_stops.guarded_send(env['engine'], ROUTE, provider,
            typed_capability=cap, dialogue_authority=env['authority'], dialogue_resolver=resolve)
        assert result.invoked and len(calls) == 1
        # The actual capability and a reconstruction both fail a second send.
        for candidate in (cap, service.TypedSend(cap.session_id, cap.claim_revision, cap.claim_hash, cap.body, cap.route_hash)):
            denied = await entry_channel_stops.guarded_send(env['engine'], ROUTE, provider,
                typed_capability=candidate, dialogue_authority=env['authority'], dialogue_resolver=resolve)
            assert not denied.invoked and len(calls) == 1
        await service.record_outcome(env['engine'], route=ROUTE, capability=cap, outcome='provider_accepted')
        assert await service.claim(env['engine'], route=ROUTE, session_id=receipt['session_id'],
            prompt_revision=receipt['prompt_revision'], authority=env['authority'], resolver=resolve) is None
        return calls[0]
    return asyncio.run(run())


@pytest.mark.parametrize('language', ['ru', 'en'])
def test_persistent_enum_boolean_date_preserves_original_attestation(env, tmp_path, language):
    setup(env, tmp_path, language=language)
    original = env['authority'].fact.digest
    receipt = receive(env)
    assert not receipt['stopped'], journal_state(env)[1][-1].document
    deliver(env, receipt)
    for i, path, literal in [(1, 'document_type', '1'), (2, 'passport_two_blank_pages', 'да' if language == 'ru' else 'yes'),
                              (3, 'passport_expiry', env['profile_doc']['profile']['passport_expiry'])]:
        header, _, flow = journal_state(env)
        p = flow['prompt']['prompt']; item = next(x for x in p['displayed'] if x['path'] == path)
        receipt = receive(env, f'{item["label"]}: {literal}', provider_id='SYN-ANSWER-'+str(i))
        assert not receipt['stopped'], journal_state(env)[1][-1].document
        assert env['authority'].fact.digest == original and _hash(header.document['fact']) == original
        deliver(env, receipt)
    _, rows, flow = journal_state(env)
    assert len([r for r in rows if r.kind == 'turn' and r.document['payload']['parsed']['action'] == 'answer']) == 3
    check = flow['prompt']['check']
    assert check['reconciliation']['original_fact_hash'] == original
    assert len(check['reconciliation']['tail']) == 3 and check['permission_to_remain'] is None
    # Default E629B still requires the original exact head.
    assert current_test.check(env)['checks']['expired_stay']['reason'] == 'current_stay_interview_changed'


def inbox_messages(env):
    from app.integrations.crm.db import ConvMessage
    async def run():
        async with env['sm']() as s:
            return list((await s.scalars(select(ConvMessage).order_by(ConvMessage.id))).all())
    return asyncio.run(run())


def test_privacy_after_native_ack_and_removed_authority(env, tmp_path):
    setup(env, tmp_path); receive(env)
    stopped = receive(env, 'Хочу менеджера', 'SYN-HUMAN')
    assert stopped['stopped'] and not stopped['collection_blocked']
    action(env, env['iv'], 'ack', policy=env['interview_policy'])
    held = receive(env, 'Delete my data', 'SYN-PRIVACY', authority=None)
    assert held['collection_blocked'] and read(env, env['iv'])['state']['collection_blocked']
    before = counts(env)
    assert receive(env, 'Delete my data', 'SYN-PRIVACY', authority=None)['duplicate']
    assert counts(env) == before
    with pytest.raises(EntryStorageConflict, match='message_changed'):
        receive(env, 'Delete my data', 'SYN-PRIVACY', authority=None, voice=True)


def test_oversized_privacy_after_ack_and_unknown_attempt_never_retains_raw(env,tmp_path):
    setup(env,tmp_path); first=receive(env)
    async def attempted():
        cap=await service.claim(env['engine'],route=ROUTE,session_id=first['session_id'],
            prompt_revision=first['prompt_revision'],authority=env['authority'],resolver=resolve)
        await service.record_outcome(env['engine'],route=ROUTE,capability=cap,outcome='unknown')
    asyncio.run(attempted())
    receive(env,'Хочу менеджера','SYN-HUMAN')
    action(env,env['iv'],'ack',policy=env['interview_policy'])
    before=[(m.id,m.text) for m in inbox_messages(env)]
    raw='x'*140000+' Delete my data'
    held=receive(env,raw,'SYN-LARGE-PRIVACY',authority=None)
    assert held['stopped'] and held['collection_blocked']
    assert [(m.id,m.text) for m in inbox_messages(env)]==before
    assert receive(env,raw,'SYN-LARGE-PRIVACY',authority=None)==held|{'duplicate':True}
    assert read(env,env['iv'])['state']['collection_blocked']


def test_inbox_and_turn_commit_together_no_retry_backfill_and_no_orphan_on_failure(env,tmp_path,monkeypatch):
    from app.domain.entry_storage import EntryStorageInvalid
    setup(env,tmp_path)
    original=journal.append
    async def broken(*args,**kwargs):
        if kwargs['kind']=='turn':raise EntryStorageInvalid('synthetic_failure_after_inbox_write')
        return await original(*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(journal,'append',broken)
        with pytest.raises(EntryStorageInvalid,match='synthetic_failure'):
            receive(env)
    assert not inbox_messages(env)
    receipt=receive(env,provider_id='SYN-'+'x'*200)
    messages=inbox_messages(env)
    assert len(messages)==1 and messages[0].text=='hello' and messages[0].provider_msg_id==''
    assert receive(env,provider_id='SYN-'+'x'*200)==receipt|{'duplicate':True}
    assert len(inbox_messages(env))==1
    stopped=receive(env,'Delete my data','SYN-PRIVACY')
    assert stopped['collection_blocked'] and len(inbox_messages(env))==1


def test_mutable_inbox_removal_cannot_block_privacy_or_repopulate_old_raw(env,tmp_path,monkeypatch):
    from app.integrations.crm.db import ConvMessage
    from app.config import settings
    from sqlalchemy import delete
    setup(env,tmp_path);first=receive(env)
    async def remove():
        async with env['sm']() as s:
            await s.execute(delete(ConvMessage));await s.commit()
    asyncio.run(remove())
    url=f"{env['url']}/applicants/{env['person']['id']}/interview/{env['iv']['interview_id']}/channel-stop"
    page=env['client'].get(url)
    assert page.status_code==200 and 'Исходный текст недоступен' in page.text
    for scopes,expected in [([], 'отключена в настройках'),(None,'Настройки защиты некорректны')]:
        with monkeypatch.context() as patch:
            patch.setattr(settings,'kg_channel_guard_scopes',scopes)
            assert expected in env['client'].get(url).text
    assert receive(env)==first|{'duplicate':True} and not inbox_messages(env)
    held=receive(env,'Delete my data','SYN-AFTER-INBOX-REMOVAL',authority=None)
    assert held['collection_blocked'] and not inbox_messages(env)
    page=env['client'].get(url)
    assert page.status_code==200 and 'отдельная запись остановки канала не создавалась' in page.text
    assert 'Сбор данных остановлен' in page.text


def test_persistent_panel_required_for_collection_but_not_retained_privacy(env,tmp_path,monkeypatch):
    from app.config import settings
    from app.domain.service_authz import PermissionDenied
    setup(env,tmp_path)
    with monkeypatch.context() as patch:
        patch.setattr(settings,'panel_backend','memory')
        with pytest.raises(PermissionDenied,match='persistent_inbox_required'):receive(env)
    first=receive(env)
    with monkeypatch.context() as patch:
        patch.setattr(settings,'panel_backend','memory')
        assert receive(env,'Delete my data','SYN-PRIVACY',authority=None)['collection_blocked']
    assert len(inbox_messages(env))==1


def test_reconstructed_or_unconsumed_claim_cannot_fabricate_provider_acceptance(env,tmp_path):
    from app.domain.entry_storage import EntryStorageInvalid
    setup(env,tmp_path);first=receive(env)
    async def attempt():
        cap=await service.claim(env['engine'],route=ROUTE,session_id=first['session_id'],
            prompt_revision=first['prompt_revision'],authority=env['authority'],resolver=resolve)
        copied=service.TypedSend(cap.session_id,cap.claim_revision,cap.claim_hash,cap.body,cap.route_hash)
        for forged in (cap,copied):
            with pytest.raises(EntryStorageInvalid,match='unissued_or_unconsumed'):
                await service.record_outcome(env['engine'],route=ROUTE,capability=forged,outcome='provider_accepted')
        await service.record_outcome(env['engine'],route=ROUTE,capability=cap,outcome='unknown')
    asyncio.run(attempt())
    _,_,flow=journal_state(env)
    label=flow['prompt']['prompt']['displayed'][0]['label']
    assert receive(env,label+': 1','SYN-UNSEEN')['stopped']


@pytest.mark.parametrize('text,kw', [('https://synthetic.invalid/private-media',{'kind':'non_text','voice':True}),
                                  ('hello\x00',{}),('hello',{'voice_failed':True})])
def test_unsupported_payload_retains_only_cause_without_raw_inbox(env,tmp_path,text,kw):
    setup(env,tmp_path)
    receipt=receive(env,text,**kw)
    assert receipt['stopped'] and not inbox_messages(env)
    _,rows,_=journal_state(env)
    assert rows[0].document['payload']['inbox']['status']=='not_retained'
    assert receive(env,text,**kw)==receipt|{'duplicate':True}


@pytest.mark.parametrize('kw,stopped,check_name', [
    ({'headroom':2},True,'visa_free_headroom'),
    ({'headroom':3,'exit_count':False},True,'visa_free_headroom'),
    ({'headroom':4,'exit_count':False},False,'visa_free_headroom'),
    ({'basis':'visa','until':'2026-10-19'},True,'working_day_margin'),
    ({'basis':'visa','until':'2026-10-20'},False,'working_day_margin'),
    ({'basis':'visa','until':'2026-10-21'},False,'working_day_margin'),
])
def test_current_thresholds_selectively_stop_or_permit_actual_prompt_and_turn(env,tmp_path,kw,stopped,check_name):
    setup(env,tmp_path,**kw)
    receipt=receive(env)
    assert receipt['stopped'] is stopped, journal_state(env)[1][-1].document
    if stopped:
        _,rows,_=journal_state(env)
        packet=rows[-1].document['payload']['evidence']['current_check']
        assert packet['checks'][check_name]['status']=='triggered'
        async def denied():
            calls=[]
            async def callback():calls.append(True)
            result=await entry_channel_stops.guarded_send(env['engine'],ROUTE,callback)
            assert not result.invoked and not calls
        asyncio.run(denied())
        retry=receive(env)
        assert retry==receipt|{'duplicate':True}
        with pytest.raises(EntryStorageConflict,match='message_changed'):receive(env,voice=True)
    else:
        deliver(env,receipt)
        _,_,flow=journal_state(env)
        label=next(v['label'] for v in flow['prompt']['prompt']['displayed'] if v['path']=='document_type')
        progressed=receive(env,label+': 1','SYN-POSITIVE-ANSWER')
        assert not progressed['stopped'] and read(env,env['iv'])['state']['answers']['document_type']['value']=='ordinary'


def test_native_correction_then_privacy_preserves_real_observed_head(env,tmp_path):
    setup(env,tmp_path);receive(env)
    corrected=correct(env,env['iv'],{'contact_name':'Synthetic correction'},policy=env['interview_policy'])
    held=receive(env,'Не даю согласия','SYN-NATIVE-PRIVACY',authority=None)
    assert held['collection_blocked']
    _,rows,_=journal_state(env)
    assert rows[-1].document['payload']['observed']['hash']==corrected['snapshot_hash']
    assert rows[-1].document['payload']['stop_id'] is None


def test_native_change_terminal_retains_input_identity_and_original_retry(env,tmp_path):
    setup(env,tmp_path);first=receive(env)
    corrected=correct(env,env['iv'],{'contact_name':'Synthetic correction'},policy=env['interview_policy'])
    stopped=receive(env,'hello','SYN-AFTER-NATIVE')
    assert stopped['stopped']
    assert receive(env,'hello','SYN-AFTER-NATIVE')==stopped|{'duplicate':True}
    with pytest.raises(EntryStorageConflict,match='message_changed'):receive(env,'hello','SYN-AFTER-NATIVE',voice=True)
    assert receive(env)==first|{'duplicate':True}
