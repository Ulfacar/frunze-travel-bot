import asyncio
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import pytest
from sqlalchemy import event,select,text,update,func
from sqlalchemy.orm import Session

from app.domain import entry_interviews as service
from app.domain.entry_interview_policy import InterviewPolicy
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid,EntryStorageUnavailable,_hash
from app.domain.models import EntryInterview,EntryInterviewEvent,DomainError,DomainBase
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge import interview_catalog as catalog
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_entry_applications import person,enforce_sqlite_foreign_keys

OWNER=Actor(manager_id='reviewer',is_full_admin=True)


def policy(**changes):
    fields=dict(reference='SYN-INTERVIEW',proof='a'*64,source_reference='SYN-PDF',source_proof='b'*64,
        privacy_reference='SYN-PRIVACY',privacy_proof='c'*64,consent_version='SYN-CONSENT-V1',terms_version='SYN-OFFER-V1',
        catalog_hash=catalog.digest(),operators=('admin','reviewer'),pre_consent=tuple(f['path'] for f in catalog.FIELDS),
        valid_from='2026-01-01',review_due_on='2027-01-01')
    return InterviewPolicy(**(fields|changes))


@pytest.fixture(autouse=True)
def admins(env,monkeypatch):
    from app.config import settings,ManagerConfig
    monkeypatch.setattr(settings,'admin_user','admin')
    monkeypatch.setattr(settings,'managers',list(settings.managers)+[ManagerConfig(login='reviewer',name='Synthetic reviewer',admin=True,password='frunze')])


def start_args(env,applicant,**changes):
    return dict(actor=ADMIN,case_id=env['cases']['visa'],applicant_id=applicant['id'],owner_login='reviewer',
        language='ru',request_key='start',expected_policy_hash=policy().digest,policy=policy())|changes


def start(env,applicant=None,**changes):
    applicant=applicant or person(env)
    saved=asyncio.run(service.start_interview(env['engine'],**start_args(env,applicant,**changes)))
    return dict(applicant_id=applicant['id'],interview_id=saved['interview_id'],first=saved)


def read(env,interview,**changes):
    return asyncio.run(service.read_interview(env['engine'],**(dict(actor=ADMIN,case_id=env['cases']['visa'],
        applicant_id=interview['applicant_id'],interview_id=interview['interview_id'],policy=policy())|changes)))


def action_args(env,interview,name,**changes):
    current=read(env,interview);operation={'action':name}
    if name=='ack':operation.update(card_hash=current['state']['handoff']['hash'],confirmed=True)
    if name=='interrupt':operation['reason']='manager_requested'
    if name=='language':operation['language']='en' if current['state']['language']=='ru' else 'ru'
    return dict(actor=OWNER if name=='ack' else ADMIN,case_id=env['cases']['visa'],applicant_id=interview['applicant_id'],
        interview_id=interview['interview_id'],expected_revision=current['revision'],request_key=name+'-'+str(current['revision']),
        operation=operation,policy=policy(),expected_policy_hash=None if name in service.OPERATIONAL else policy().digest)|changes


def action(env,interview,name,**changes):
    return asyncio.run(service.record_action(env['engine'],**action_args(env,interview,name,**changes)))


def correct(env,interview,changes,**options):
    return action(env,interview,'correct',operation={'action':'correct','changes':changes,'displayed':list(changes)},**options)


def answer_unknown(env,interview,**options):
    current=read(env,interview);paths=[q['path'] for q in current['drafts']]
    return action(env,interview,'answer',operation={'action':'answer','displayed':paths,'changes':{p:'unknown' for p in paths}},**options)


def counts(env):
    async def run():
        async with env['sm']() as s:return {t.name:await s.scalar(select(func.count()).select_from(t)) for t in DomainBase.metadata.sorted_tables}
    return asyncio.run(run())


def test_start_reload_scope_catalog_and_no_old_domain_side_effects(env):
    applicant=person(env);before=counts(env);iv=start(env,applicant);current=read(env,iv)
    assert current['state']['phase']=='active' and len(current['drafts'])<=3
    assert current['state']['answers']['language']['value']=='ru'
    assert current['interview']['source_pin']['applicant_id']==applicant['id']
    assert current['interview']['source_pin']['profile'] is None
    after=counts(env)
    assert {k:v for k,v in after.items() if k not in ('entry_interviews','entry_interview_events')}=={k:v for k,v in before.items() if k not in ('entry_interviews','entry_interview_events')}
    assert current['state']['channel_suppression']=='not_integrated'


def test_language_pause_resume_unknown_and_old_start_retry(env):
    p=person(env);args=start_args(env,p);iv=start(env,p)
    first=answer_unknown(env,iv);assert first['state']['analysis']['gaps']
    saved_paths={q['path'] for q in iv['first']['state']['drafts']}
    assert not saved_paths & {q['path'] for q in read(env,iv)['drafts']}
    action(env,iv,'pause');assert not read(env,iv)['drafts']
    action(env,iv,'language');assert read(env,iv)['state']['language']=='en'
    action(env,iv,'resume');assert read(env,iv)['drafts']
    assert asyncio.run(service.start_interview(env['engine'],**(args|{'policy':None})))==iv['first']
    with pytest.raises(EntryStorageConflict):asyncio.run(service.start_interview(env['engine'],**(args|{'language':'en'})))


def test_displayed_questions_are_exact_and_corrections_are_explicit(env):
    iv=start(env);args=action_args(env,iv,'answer',operation={'action':'answer','displayed':['contact_name'],'changes':{'contact_name':'Synthetic'}})
    with pytest.raises(EntryStorageConflict,match='questions_changed'):asyncio.run(service.record_action(env['engine'],**args))
    saved=correct(env,iv,{'entry_on':'2026-12-01','exit_on':'2026-12-20'})
    assert saved['state']['answers']['entry_on']['value']=='2026-12-01'


def test_conflict_answer_and_handoff_are_one_event_and_card_stays_frozen(env):
    iv=start(env);saved=correct(env,iv,{'entry_on':'2026-12-20','exit_on':'2026-12-01'})
    assert saved['state']['phase']=='pending' and 'conflicting_answers' in saved['state']['handoff']['card']['reasons']
    frozen=deepcopy(saved['state']['handoff']);assert saved['state']['drafts']==saved['state']['analysis']['questions']==[]
    with pytest.raises(EntryStorageInvalid):correct(env,iv,{'exit_on':'2026-12-30'})
    with pytest.raises(PermissionDenied):action(env,iv,'ack',actor=ADMIN)
    ack=action(env,iv,'ack');assert ack['state']['phase']=='acked'
    with pytest.raises(PermissionDenied):correct(env,iv,{'exit_on':'2026-12-30'})
    later=correct(env,iv,{'exit_on':'2026-12-30'},actor=OWNER)
    assert later['state']['handoff']==frozen and later['state']['answers']['exit_on']['value']=='2026-12-30'
    assert not read(env,iv)['drafts'] and not read(env,iv)['current_analysis']['questions']
    for name in ('resume','language','refresh'):
        with pytest.raises(EntryStorageInvalid):action(env,iv,name,actor=OWNER)


@pytest.mark.parametrize('reason',sorted(service.rules.INTERRUPTS))
def test_all_explicit_interrupts_persist_while_paused_without_extra_narrative(env,reason):
    iv=start(env);action(env,iv,'pause')
    result=action(env,iv,'interrupt',operation={'action':'interrupt','reason':reason},policy=None)
    assert result['state']['phase']=='pending' and reason in result['state']['handoff']['card']['reasons']
    assert result['state']['drafts']==[]


def test_default_policy_and_trusted_full_admin_owner_are_required(env):
    p=person(env)
    for changes in ({'policy':None},{'policy':policy(review_due_on='2026-01-02')},
                    {'owner_login':'medina'},{'owner_login':'invented'},{'actor':Actor(manager_id='admin',is_full_admin=False)}):
        with pytest.raises(PermissionDenied):start(env,p,**changes)
    assert counts(env)['entry_interviews']==0


def test_scope_and_unique_subject_cannot_bypass_a_handoff(env):
    iv=start(env);action(env,iv,'handoff');second=person(env,key='second')
    with pytest.raises(EntryStorageInvalid):read(env,iv,applicant_id=second['id'])
    with pytest.raises(EntryStorageInvalid):read(env,iv,case_id=env['cases']['other'])
    with pytest.raises(EntryStorageConflict):start(env,{'id':iv['applicant_id']},request_key='new-session')
    own=start(env,second,request_key='separate-person');assert read(env,own)['state']['phase']=='active'


def test_preconsent_refusal_withdrawal_and_offer_are_separate(env):
    limited=policy(pre_consent=('language','consent.given','consent.on','consent.evidence_ref','consent.evidence_sha256'))
    iv=start(env,policy=limited,expected_policy_hash=limited.digest)
    with pytest.raises(EntryStorageInvalid,match='consent_required'):
        correct(env,iv,{'contact_name':'Synthetic'},policy=limited,expected_policy_hash=limited.digest)
    saved=correct(env,iv,{'consent.given':False},policy=limited,expected_policy_hash=limited.digest)
    assert saved['state']['collection_blocked'] and saved['state']['phase']=='pending'
    action(env,iv,'ack',policy=None)
    with pytest.raises(EntryStorageInvalid,match='collection_blocked'):
        correct(env,iv,{'contact_name':'Synthetic'},actor=OWNER,policy=limited,expected_policy_hash=limited.digest)


def test_unknown_commit_exact_retry_after_expiry_and_later_revision(env):
    iv=start(env);args=action_args(env,iv,'interrupt')
    saved=asyncio.run(service.record_action(env['engine'],**args));action(env,iv,'ack')
    assert asyncio.run(service.record_action(env['engine'],**(args|{'policy':None})))==saved
    with pytest.raises(EntryStorageConflict):asyncio.run(service.record_action(env['engine'],**(args|{'operation':{'action':'interrupt','reason':'refund'}})))


@pytest.mark.parametrize('at',['before_commit','after_commit'])
def test_commit_fault_recovers_original_handoff_and_card(env,at):
    iv=start(env);args=action_args(env,iv,'interrupt')
    def fail(s):raise RuntimeError('synthetic commit uncertainty')
    event.listen(Session,at,fail)
    try:
        with pytest.raises(EntryStorageUnavailable):asyncio.run(service.record_action(env['engine'],**args))
    finally:event.remove(Session,at,fail)
    result=asyncio.run(service.record_action(env['engine'],**args))
    assert result['revision']==2 and read(env,iv)['state']['phase']=='pending'
    assert asyncio.run(service.record_action(env['engine'],**(args|{'policy':None})))==result


@pytest.mark.parametrize('model',[EntryInterview,EntryInterviewEvent])
def test_start_two_halves_rollback(model,env):
    p=person(env);before=counts(env)
    def fail(s,ctx):
        if any(isinstance(v,model) for v in s.new):raise RuntimeError('synthetic start fault')
    event.listen(Session,'after_flush',fail)
    try:
        with pytest.raises(EntryStorageUnavailable):start(env,p)
    finally:event.remove(Session,'after_flush',fail)
    assert counts(env)==before
    assert start(env,p)['first']['revision']==1


def test_concurrent_identical_ack_and_competing_answer_interrupt(env):
    iv=start(env);action(env,iv,'handoff');args=action_args(env,iv,'ack')
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(lambda:asyncio.run(service.record_action(env['engine'],**args))) for _ in range(2)]
        results=[f.result(timeout=60) for f in futures]
    assert results[0]==results[1] and results[0]['revision']==3


def test_rehashed_handoff_card_tamper_fails_semantic_replay(env):
    iv=start(env);action(env,iv,'handoff')
    async def corrupt():
        async with env['sm']() as s:
            row=await s.scalar(select(EntryInterviewEvent).where(EntryInterviewEvent.revision==2))
            altered=service._plain(row.snapshot);altered['handoff']['card']['owner_login']='invented'
            altered['handoff']['hash']=_hash(altered['handoff']['card'])
            payload=service._event_payload(row);payload['snapshot']=altered
            async with env['engine'].begin() as c:
                await c.execute(text('UPDATE entry_interview_events SET snapshot=:snapshot,snapshot_hash=:hash WHERE id=:id'),
                    {'snapshot':__import__('json').dumps(altered),'hash':_hash(payload),'id':row.id})
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):read(env,iv)


def test_immutable_orm_and_bulk_guards(env):
    iv=start(env)
    async def run():
        for model in (EntryInterview,EntryInterviewEvent):
            async with env['sm']() as s:
                row=await s.scalar(select(model));row.created_by='forged'
                with pytest.raises(DomainError):await s.flush()
            async with env['sm']() as s:
                with pytest.raises(DomainError):await s.execute(update(model).values(created_by='forged'))
    asyncio.run(run())


def test_reserved_capacity_allows_handoff_ack_and_denies_terminal_noops(env,monkeypatch):
    iv=start(env)
    monkeypatch.setattr(service,'MAX_EVENTS',7)
    action(env,iv,'language');action(env,iv,'language');action(env,iv,'language')
    with pytest.raises(EntryStorageInvalid,match='history_limit'):action(env,iv,'language')
    assert action(env,iv,'handoff',policy=None)['revision']==5
    assert action(env,iv,'ack',policy=None)['revision']==6
    with pytest.raises(EntryStorageInvalid):action(env,iv,'handoff',policy=None)
    assert read(env,iv)['revision']==6
    withdrawn=action(env,iv,'interrupt',operation={'action':'interrupt','reason':'consent_withdrawn'},policy=None)
    assert withdrawn['revision']==7 and withdrawn['state']['collection_blocked']


def test_revoked_current_identity_cannot_read_retry_or_start_before_db_access(env,monkeypatch):
    from app.config import settings
    iv=start(env);args=action_args(env,iv,'language');saved=asyncio.run(service.record_action(env['engine'],**args))
    monkeypatch.setattr(settings,'admin_user','replacement')
    monkeypatch.setattr(settings,'managers',[m for m in settings.managers if m.login!='admin'])
    for call in (lambda:service.read_interview(None,actor=ADMIN,case_id=1,applicant_id=1),
                 lambda:service.record_action(None,**args),
                 lambda:service.start_interview(None,**start_args(env,{'id':iv['applicant_id']}))):
        with pytest.raises(PermissionDenied):asyncio.run(call())


def test_newly_granted_identity_cannot_append_unreplayable_event(env,monkeypatch):
    from app.config import settings,ManagerConfig
    expanded=policy(operators=('admin','reviewer','late_admin'))
    iv=start(env,policy=expanded,expected_policy_hash=expanded.digest)
    monkeypatch.setattr(settings,'managers',list(settings.managers)+[ManagerConfig(login='late_admin',name='Synthetic later',admin=True)])
    late=Actor('late_admin',True);before=counts(env)
    with pytest.raises(PermissionDenied):action(env,iv,'language',actor=late,policy=expanded,expected_policy_hash=expanded.digest)
    with pytest.raises(PermissionDenied):action(env,iv,'handoff',actor=late,policy=None)
    assert counts(env)==before and read(env,iv,actor=late,policy=expanded)['policy_enabled'] is False


def test_competing_answer_and_interrupt_have_one_compare_and_swap_winner(env):
    iv=start(env);paths=[q['path'] for q in read(env,iv)['drafts']]
    answer=action_args(env,iv,'answer',request_key='RACE-ANSWER',operation={'action':'answer','displayed':paths,'changes':{p:'unknown' for p in paths}})
    stop=action_args(env,iv,'interrupt',request_key='RACE-STOP')
    def execute(args):
        try:return asyncio.run(service.record_action(env['engine'],**args))
        except EntryStorageConflict:return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(execute,[answer,stop]))
    assert results.count('conflict')==1 and read(env,iv)['revision']==2
    current=read(env,iv)
    if current['state']['phase']=='active':action(env,iv,'interrupt',request_key='RACE-STOP-REFRESHED')
    assert read(env,iv)['state']['phase']=='pending' and not read(env,iv)['drafts']


def test_profile_pin_is_exact_applicant_and_survives_later_profile_growth(env):
    from tests import test_applicant_profiles as profiles
    p=person(env);other=person(env,key='OTHER');first=profiles.save(env,p)
    with pytest.raises(EntryStorageInvalid):start(env,other,profile_id=first['qualification_id'])
    iv=start(env,p,profile_id=first['qualification_id']);before=read(env,iv)
    next_profile=profiles.request();next_profile['language']='en'
    profiles.save(env,p,revision=1,key='LATER',doc=next_profile)
    after=read(env,iv)
    assert before==after and after['interview']['source_pin']['profile']['id']==first['qualification_id']


def test_consent_withdrawal_after_completed_consent_cannot_be_resumed(env):
    iv=start(env);correct(env,iv,{'consent.given':True})
    correct(env,iv,{'consent.on':'2026-10-01','consent.evidence_ref':'SYN-OWN-CONSENT','consent.evidence_sha256':'d'*64})
    assert read(env,iv)['state']['analysis']['consent_complete']
    result=action(env,iv,'remove',operation={'action':'remove','paths':['consent.evidence_ref']})
    assert result['state']['collection_blocked'] and 'consent_withdrawn' in result['state']['handoff']['card']['reasons']
    action(env,iv,'ack')
    with pytest.raises(EntryStorageInvalid,match='collection_blocked'):correct(env,iv,{'consent.evidence_ref':'SYN-NEW'},actor=OWNER)


def test_expired_policy_allows_minimal_handoff_and_ack_but_not_collection(env,monkeypatch):
    from datetime import date
    iv=start(env)
    monkeypatch.setattr(service.applications,'_today',lambda:date(2028,1,1))
    assert not read(env,iv)['drafts']
    with pytest.raises(PermissionDenied):action(env,iv,'language')
    assert action(env,iv,'handoff',policy=None)['state']['phase']=='pending'
    assert action(env,iv,'ack',policy=None)['state']['phase']=='acked'


def test_fresh_consent_reaffirmation_preserves_evidence_and_explicit_false_still_withdraws(env):
    iv=start(env);correct(env,iv,{'consent.given':True})
    correct(env,iv,{'consent.on':'2026-10-01','consent.evidence_ref':'SYN-OWN-CONSENT','consent.evidence_sha256':'d'*64})
    before=read(env,iv);assert before['state']['analysis']['consent_complete']
    args=action_args(env,iv,'correct',operation={'action':'correct','displayed':['consent.given'],'changes':{'consent.given':True}})
    after=asyncio.run(service.record_action(env['engine'],**args))
    assert after['state']['answers']==before['state']['answers']
    assert after['state']['analysis']['consent_complete'] and not after['state']['collection_blocked']
    assert after['state']['consent_withdrawal'] is None and after['state']['phase']=='active'
    assert asyncio.run(service.record_action(env['engine'],**args))==after
    assert read(env,iv)['state']==after['state']
    withdrawn=correct(env,iv,{'consent.given':False})
    assert withdrawn['state']['collection_blocked'] and withdrawn['state']['consent_withdrawal']
    assert withdrawn['state']['phase']=='pending' and not read(env,iv)['drafts']
    assert action(env,iv,'ack',policy=None)['state']['phase']=='acked'


@pytest.mark.parametrize('scenario,language',[('tourism','ru'),('current_stay','en'),('family','ru'),('employer','en'),('company_investor','ru')])
def test_connected_golden_journal_collection_handoff_ack_and_specialist_completion(env,scenario,language):
    from tests.test_kg_interview_rules import GOLDENS,golden_value
    iv=start(env,language=language);frozen=None
    for step in range(100):
        current=read(env,iv);state=current['state']
        if state['phase']=='pending':
            frozen=deepcopy(state['handoff']);action(env,iv,'ack');continue
        questions=current['drafts'] if state['phase']=='active' else current['current_analysis']['manual_questions']
        if not questions:break
        fields=service.rules.Answers(state['answers']).fields
        changes={q['path']:golden_value(fields[q['path']],GOLDENS[scenario]) for q in questions}
        name='answer' if state['phase']=='active' else 'correct'
        action(env,iv,name,actor=ADMIN if name=='answer' else OWNER,
            operation={'action':name,'changes':changes,'displayed':list(changes)},request_key='GOLDEN-'+str(step))
    else:pytest.fail('journal intake failed to converge')
    final=read(env,iv)
    assert final['state']['phase']=='acked' and final['state']['handoff']==frozen
    assert not final['drafts'] and not final['current_analysis']['gaps'] and not final['current_analysis']['conflicts']
    assert final['current_analysis']['legal_qualification']==final['current_analysis']['quote']=='unknown'
    if scenario in ('employer','company_investor'):
        assert frozen['card']['gaps'] and final['revision']>frozen['card']['revision']
    assert read(env,iv)==final


def test_byte_budget_reserves_handoff_and_ack_even_when_normal_append_is_full(env,monkeypatch):
    iv=start(env)
    async def size():
        async with env['sm']() as session:
            rows=list((await session.scalars(select(EntryInterviewEvent))).all())
            return sum(service._bytes(service._event_payload(row)) for row in rows)
    monkeypatch.setattr(service,'MAX_JOURNAL_BYTES',asyncio.run(size())+3*service.MAX_EVENT_BYTES)
    with pytest.raises(EntryStorageInvalid,match='history_limit'):action(env,iv,'language')
    assert action(env,iv,'handoff',policy=None)['state']['phase']=='pending'
    assert action(env,iv,'ack',policy=None)['state']['phase']=='acked'
    assert action(env,iv,'interrupt',operation={'action':'interrupt','reason':'consent_withdrawn'},policy=None)['state']['collection_blocked']


def test_policy_midnight_change_before_persist_does_not_create_unreadable_event(env,monkeypatch):
    from datetime import date,datetime,timezone
    iv=start(env);before=counts(env)
    monkeypatch.setattr(service.applications,'_today',lambda:date(2027,1,1))
    monkeypatch.setattr(service,'_now',lambda:datetime(2027,1,2,0,0,tzinfo=timezone.utc))
    with pytest.raises(PermissionDenied):action(env,iv,'language')
    p=person(env,key='MIDNIGHT')
    with pytest.raises(PermissionDenied):start(env,p,request_key='MIDNIGHT')
    assert counts(env)['entry_interview_events']==before['entry_interview_events']
    assert counts(env)['entry_interviews']==before['entry_interviews']


def test_backwards_clock_cannot_commit_an_unreplayable_event(env,monkeypatch):
    from datetime import datetime,timezone
    iv=start(env);before=counts(env)
    monkeypatch.setattr(service,'_now',lambda:datetime(2026,1,2,tzinfo=timezone.utc))
    with pytest.raises(EntryStorageInvalid,match='clock_moved_back'):action(env,iv,'handoff')
    assert counts(env)==before


@pytest.mark.parametrize('phase',['active','paused','pending','acked'])
def test_withdrawal_is_durable_in_every_phase_and_never_rewrites_frozen_card(env,monkeypatch,phase):
    iv=start(env)
    if phase=='paused':action(env,iv,'pause')
    if phase in ('pending','acked'):action(env,iv,'handoff')
    if phase=='acked':action(env,iv,'ack')
    before=read(env,iv);args=action_args(env,iv,'interrupt',operation={'action':'interrupt','reason':'consent_withdrawn'},policy=None)
    withdrawn=asyncio.run(service.record_action(env['engine'],**args))
    assert withdrawn['state']['collection_blocked'] and withdrawn['state']['consent_withdrawal']['actor']=='admin'
    if before['state']['handoff']:assert withdrawn['state']['handoff']==before['state']['handoff']
    assert asyncio.run(service.record_action(env['engine'],**args))==withdrawn
    if read(env,iv)['state']['phase']=='pending':action(env,iv,'ack',policy=None)
    assert not read(env,iv)['can_collect'] and not read(env,iv)['can_withdraw']
    with pytest.raises(EntryStorageInvalid):correct(env,iv,{'contact_name':'Forbidden'},actor=OWNER)
    with pytest.raises(EntryStorageInvalid):action(env,iv,'interrupt',operation={'action':'interrupt','reason':'consent_withdrawn'},policy=None)


def switch_catalog(monkeypatch):
    """A separately registered future catalog uses different text and one new field."""
    later=catalog.document();later['version']='kg-interview-catalog/3.2-synthetic'
    later['fields'][0]['en']='Synthetic future prompt'
    added=deepcopy(later['fields'][0]);added.update(path='synthetic_future_field',ru='Synthetic future field',en='Synthetic future field')
    later['fields'].append(added)
    monkeypatch.setitem(catalog._REGISTRY,catalog.digest(later),deepcopy(later))
    monkeypatch.setattr(catalog,'document',lambda:deepcopy(later))
    return later


def test_new_active_catalog_keeps_old_card_readable_and_old_retry_and_ack_exact(env,monkeypatch):
    p=person(env);start_command=start_args(env,p);iv=start(env,p)
    args=action_args(env,iv,'handoff');saved=asyncio.run(service.record_action(env['engine'],**args));before=read(env,iv)
    later=switch_catalog(monkeypatch)
    after=read(env,iv)
    assert after['state']==before['state'] and after['history']==before['history'] and not after['policy_enabled']
    assert 'synthetic_future_field' not in after['current_analysis']['field_states']
    assert asyncio.run(service.start_interview(env['engine'],**(start_command|{'policy':None})))==iv['first']
    assert asyncio.run(service.record_action(env['engine'],**(args|{'policy':None})))==saved
    accepted=action(env,iv,'ack',policy=None)
    assert accepted['state']['handoff']==before['state']['handoff']
    fresh=start(env,person(env,key='FUTURE'),request_key='FUTURE')
    current=read(env,fresh)
    assert current['interview']['catalog_version']==later['version'] and 'synthetic_future_field' in current['current_analysis']['field_states']


def test_unknown_reducer_cannot_commit_a_new_interview(env,monkeypatch):
    future=switch_catalog(monkeypatch);future['reducer_version']='unsupported-engine'
    monkeypatch.setitem(catalog._REGISTRY,catalog.digest(future),deepcopy(future))
    monkeypatch.setattr(catalog,'document',lambda:deepcopy(future))
    p=person(env);before=counts(env)
    with pytest.raises(EntryStorageInvalid,match='unsupported_interview_reducer'):start(env,p)
    assert counts(env)==before


def test_last_reserved_events_allow_withdrawal_before_owner_ack(env,monkeypatch):
    iv=start(env);monkeypatch.setattr(service,'MAX_EVENTS',7)
    for _ in range(3):action(env,iv,'language')
    action(env,iv,'handoff',policy=None)
    assert action(env,iv,'interrupt',operation={'action':'interrupt','reason':'consent_withdrawn'},policy=None)['revision']==6
    accepted=action(env,iv,'ack',policy=None)
    assert accepted['revision']==7 and accepted['state']['collection_blocked'] and not read(env,iv)['drafts']
