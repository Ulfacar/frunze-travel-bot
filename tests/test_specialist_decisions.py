"""Connected original-source shape, with SYNTHETIC approval and no live policy."""
import asyncio
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from pathlib import Path
import json

import pytest
from sqlalchemy import select,event,func

from app.domain import specialist_decisions as service,specialist_facts as facts
from app.domain import entry_applications as apps,entry_interviews as interviews,entry_quotes
from app.domain import applicant_profiles,applicant_stay_history,knowledge_decisions,knowledge_publication
from app.domain.entry_storage import _hash,EntryStorageInvalid,EntryStorageConflict
from app.domain.models import SpecialistDecisionEvent,EntryQuoteRevision,DomainBase
from app.domain.specialist_policy import SpecialistPolicy
from app.domain.entry_quote_policy import policy_from_document
from app.domain.knowledge_import import create_kg_entry_set,import_bundle
from app.knowledge.bundle import validate_bundle
from app.knowledge import interview_rules
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_entry_interviews import admins,OWNER,policy as interview_policy
from tests.test_entry_applications import person,application,enforce_sqlite_foreign_keys
from tests.test_applicant_profiles import save as save_profile
from tests.test_applicant_stay_history import save as save_history,document as history_document
from tests.test_knowledge_decisions import write as review,data as review_data
from tests.test_knowledge_publication import POLICY,publish,preview
from tests.test_specialist_facts import source as source_shape,policy_document,example,ON,ROOT
from tests.test_entry_quotes import policy as quote_policy
from tests.test_quote_rules import recipe,na


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    at=datetime(2026,10,12,12,tzinfo=timezone.utc)
    def now():
        nonlocal at
        at+=timedelta(microseconds=1)
        return at
    for module in (service,apps,interviews,entry_quotes,applicant_profiles,applicant_stay_history,
                   knowledge_decisions,knowledge_publication):monkeypatch.setattr(module,'_now',now)
    return now


def setup(env,tmp_path,*,language='ru'):
    pdf=ROOT/'runs/specialist-source.pdf'
    if not pdf.exists():pytest.skip('explicit original PDF needed; env-free freezer supplies its verified copy')
    bundle,conditions,_=source_shape();folder=tmp_path/'source';folder.mkdir()
    bundle['meta']['source_document']='SYNTHETIC specialist review of supplied PDF; NOT legal approval'
    unit=next(u for u in bundle['units'] if u['unit_id']=='KG.VR.GENERAL')
    unit.update(effective_from='2026-01-01',verified_at='2026-09-01T00:00:00Z',verified_by='synthetic-reviewer',
        review_due_at='2027-01-01T00:00:00Z',owner='synthetic-owner',source_ref='SYNTHETIC general procedure',
        label='none',confirmation_status='confirmed',blocked_value=None,conflict_ref=None)
    validation=validate_bundle(**bundle,source_hash=bundle['meta']['source_hash']);assert validation.ok,validation.errors
    bundle=validation.normalized_bundle;conditions['bundle_hash']=validation.bundle_hash
    for key,value in bundle.items():(folder/f'{key}.yaml').write_text(json.dumps(value,ensure_ascii=False),'utf8')
    cp=tmp_path/'conditions.json';cp.write_text(json.dumps(conditions),'utf8')
    async def load():
        sid=await create_kg_entry_set(env['engine'],actor=ADMIN)
        return await import_bundle(env['engine'],actor=ADMIN,set_id=sid,directory=folder,source=pdf,catalog=cp)
    imported=asyncio.run(load());assert imported.accepted,imported.report
    env.update(version=imported.version_id,release=imported.version_id,bundle=bundle)
    review(env,unit='KG.VR.GENERAL',key='SYN-GENERAL',decision=review_data()|{'review_due_on':'2026-12-31'})
    for action in ('review','approve','activate'):publish(env,action,ids=['KG.VR.GENERAL'])
    sample=example(language);env['person']=person(env)
    env['profile_doc']=sample['request'];env['saved']=save_profile(env,env['person'],doc=sample['request'])
    env['history']=save_history(env,env['person'],env['saved'],doc=history_document(history_complete=True,intervals=[]))
    env['application']=application(env,env['person'])
    ip=interview_policy();env['interview_policy']=ip
    values={k:v['value'] for k,v in sample['state']['answers'].items()}
    async def interview():
        current=await interviews.start_interview(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],applicant_id=env['person']['id'],
            owner_login='reviewer',language=language,request_key='SYN-START',expected_policy_hash=ip.digest,policy=ip,
            profile_id=env['saved']['qualification_id'])
        async def act(operation,actor=OWNER):
            return await interviews.record_action(env['engine'],actor=actor,case_id=env['cases']['visa'],applicant_id=env['person']['id'],
                interview_id=current['interview_id'],expected_revision=current['revision'],request_key='SYN-ACT-'+str(current['revision']),
                operation=operation,expected_policy_hash=ip.digest,policy=ip)
        if current['state']['phase']=='active':current=await act(dict(action='handoff'))
        current=await act(dict(action='ack',confirmed=True,card_hash=current['state']['handoff']['hash']))
        for _ in range(100):
            analysis=interview_rules.analyze(current['state']['answers'],on=ON,language=language,pre_consent=ip.pre_consent,
                catalog_document=sample['catalog'])
            questions=analysis['manual_questions']
            if not questions:break
            changes={q['path']:values[q['path']] for q in questions}
            current=await act(dict(action='correct',displayed=list(changes),changes=changes))
        assert not analysis['gaps'] and not analysis['stops'],analysis
        return current
    env['interview']=asyncio.run(interview());env['findings']=sample['findings']
    r=recipe(id='SYN-B');r['lines'][2]=na('bank');env['quote_policy']=quote_policy(r)
    doc=policy_document();manifest=preview(env,ids=['KG.VR.GENERAL'])['manifest']
    doc.update(bundle_hash=manifest['bundle_hash'],projection_hash=manifest['projection_hash'],condition_catalog_hash=manifest['catalog_hash'])
    cap=doc['capabilities'][0];cap['quote_policy_hash']=env['quote_policy'].digest
    cap['recipes'][0]['hash']=_hash(r)
    ids={p['unit_id'] for p in cap['unit_pins']}
    cap['unit_pins']=[dict(unit_id=u['unit_id'],unit_hash=_hash(u)) for u in bundle['units'] if u['unit_id'] in ids]
    env['policy']=SpecialistPolicy(doc)
    return env


def options(env):return dict(actor=ADMIN,case_id=env['cases']['visa'],applicant_id=env['person']['id'],
    policy=env['policy'],interview_policy=env['interview_policy'],publication_policy=POLICY)


def context(env):return asyncio.run(service.review_context(env['engine'],**options(env),application_id=env['application']['id']))


def record_args(env,**changes):
    view=context(env)
    op=dict(action='record',application_id=env['application']['id'],capability_id=facts.CAPABILITY,
        disposition='manual_internal_plan',findings=env['findings'],reason=None,
        expected_policy_hash=env['policy'].digest,expected_context_hash=view['context']['context_hash'])
    return options(env)|dict(expected_revision=view['revision'],request_key='SYN-DECISION-'+str(view['revision']),operation=op)|changes


def record(env,**changes):return asyncio.run(service.record_decision(env['engine'],**record_args(env,**changes)))


def read(env,**changes):return asyncio.run(service.read_decisions(env['engine'],**(options(env)|changes)))


def quote_preview(env,recorded,**changes):
    r=recorded['receipt']
    return asyncio.run(service.preview_decision_quote(env['engine'],**(options(env)|dict(decision_id=r['id'],
        decision_hash=r['snapshot_hash'],parameters=dict(recipe_id='SYN-B',additional_blocks=0,urgent=False),quote_policy=env['quote_policy'])|changes)))


def quote_args(env,recorded):
    p=quote_preview(env,recorded);r=recorded['receipt']
    return options(env)|dict(expected_revision=p['revision'],request_key='SYN-QUOTE',quote_policy=env['quote_policy'],
        operation=dict(action='quote',decision_id=r['id'],decision_hash=r['snapshot_hash'],preview=p['preview'],preview_hash=p['preview_hash']))


def withdraw_args(env,recorded,revision):
    r=recorded['receipt']
    return dict(actor=ADMIN,case_id=env['cases']['visa'],applicant_id=env['person']['id'],expected_revision=revision,
        request_key='SYN-WITHDRAW',operation=dict(action='withdraw',decision_id=r['id'],decision_hash=r['snapshot_hash'],confirmed=True,
            reason=dict(code='correction_required',reference='SYN-CORRECTION',proof='a'*64,on=ON)))


@pytest.mark.parametrize('language',['ru','en'])
def test_original_source_india_ten_day_decision_quote_reload_and_withdraw(env,tmp_path,language):
    setup(env,tmp_path,language=language)
    old=record_args(env);recorded=asyncio.run(service.record_decision(env['engine'],**old))
    assert recorded['receipt']['result']['assessment']['planned_days']==10
    assert read(env)['current']['usable_for_internal_quote']
    quoted_args=quote_args(env,recorded);quoted=asyncio.run(service.record_decision(env['engine'],**quoted_args))
    assert quoted['receipt']['result']['arithmetic_complete']
    assert read(env)['revision']==2
    saved_quote=asyncio.run(entry_quotes.read_quotes(env['engine'],actor=ADMIN,case_id=env['cases']['visa'],
        application_id=env['application']['id'],policy=env['quote_policy']))
    assert saved_quote['history'][0]['receipt']['result']['totals_by_currency']=={'USD':'100.00'}
    assert quoted['receipt']['quote_id']==saved_quote['history'][0]['receipt']['id']
    withdrawal=asyncio.run(service.record_decision(env['engine'],**withdraw_args(env,recorded,2)))
    assert withdrawal['receipt']['result']['disposition']=='withdrawn'
    assert not read(env)['current']['usable_for_internal_quote']
    for command,receipt in ((old,recorded['receipt']),(quoted_args,quoted['receipt'])):
        replay=asyncio.run(service.record_decision(env['engine'],**(command|dict(policy=None,interview_policy=None,publication_policy=None))))
        assert replay['duplicate'] and replay['receipt']==receipt
    with pytest.raises(EntryStorageConflict):quote_preview(env,recorded)


def test_changed_profile_blocks_quote_but_keeps_original_and_withdrawal(env,tmp_path):
    setup(env,tmp_path);recorded=record(env);quoted_args=quote_args(env,recorded)
    changed=deepcopy(env['profile_doc']);changed['profile']['purpose_details']='Changed meeting scope'
    save_profile(env,env['person'],doc=changed,key='SYN-CHANGED',revision=1)
    with pytest.raises(EntryStorageConflict):asyncio.run(service.record_decision(env['engine'],**quoted_args))
    assert not read(env)['current']['usable_for_internal_quote']
    assert read(env)['history'][0]==recorded['receipt']
    asyncio.run(service.record_decision(env['engine'],**withdraw_args(env,recorded,1)))


def test_wrong_recipe_and_cross_person_are_rejected(env,tmp_path):
    setup(env,tmp_path);recorded=record(env)
    with pytest.raises(EntryStorageInvalid):
        quote_preview(env,recorded,parameters=dict(recipe_id='SYN-TS',additional_blocks=0,urgent=False))
    other=person(env,role='other',key='SYN-OTHER')
    with pytest.raises(EntryStorageInvalid):quote_preview(env,recorded,applicant_id=other['id'])
