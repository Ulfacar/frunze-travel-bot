"""Actual journal count/withdrawal envelopes; constants are not reduced."""
import asyncio

import pytest

from app.config import settings,ManagerConfig
from app.domain import specialist_decisions as service,specialist_facts
from app.domain.specialist_policy import SpecialistPolicy
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_specialist_decisions import env,admins,clock,ADMIN,ON
from tests.test_specialist_facts import policy_document
from tests.test_entry_interviews import policy as interview_policy
from tests.test_entry_applications import person,enforce_sqlite_foreign_keys
from tests.test_knowledge_publication import POLICY


def prepare(env):
    subject=person(env)
    args=dict(actor=ADMIN,case_id=env['cases']['visa'],applicant_id=subject['id'],
        policy=SpecialistPolicy(policy_document()),interview_policy=interview_policy(),publication_policy=POLICY)
    view=asyncio.run(service.review_context(env['engine'],**args,application_id=None))
    assert view['context']['errors']
    operation=dict(action='record',application_id=None,capability_id=specialist_facts.CAPABILITY,
        disposition='needs_evidence',findings=None,
        reason=dict(code='evidence_missing',reference='SYN-BOUNDARY',proof='a'*64,on=ON),
        expected_policy_hash=args['policy'].digest,expected_context_hash=view['context']['context_hash'])
    return args,operation


def withdrawal(args,receipt,revision):
    return {k:v for k,v in args.items() if k in ('actor','case_id','applicant_id')}|dict(
        expected_revision=revision,request_key='SYN-RESERVED-WITHDRAW',
        operation=dict(action='withdraw',decision_id=receipt['id'],decision_hash=receipt['snapshot_hash'],
            confirmed=True,reason=dict(code='correction_required',reference='SYN-RESERVED',proof='a'*64,on=ON)))


def test_actual_63_ordinary_then_64th_withdrawal_and_replay(env):
    assert service.MAX_REVISIONS==64 and service.WITHDRAWAL_BYTES==8192
    args,operation=prepare(env)
    async def records():
        last=None
        for revision in range(63):
            last=await service.record_decision(env['engine'],**args,expected_revision=revision,
                request_key='SYN-COUNT-'+str(revision),operation=operation)
        with pytest.raises(EntryStorageInvalid,match='specialist_history_limit'):
            await service.record_decision(env['engine'],**args,expected_revision=63,request_key='SYN-OVERCOUNT',operation=operation)
        command=withdrawal(args,last['receipt'],63)
        terminal=await service.record_decision(env['engine'],**command)
        assert terminal['receipt']['revision']==64
        again=await service.record_decision(env['engine'],**command)
        assert again['duplicate'] and again['receipt']==terminal['receipt']
        old=await service.record_decision(env['engine'],**({k:v for k,v in args.items() if k in ('actor','case_id','applicant_id')}),
            expected_revision=62,request_key='SYN-COUNT-62',operation=operation)
        assert old['duplicate'] and old['receipt']==last['receipt']
        current=await service.read_decisions(env['engine'],**args)
        assert current['revision']==64 and not current['can_withdraw'] and not current['can_record']
    asyncio.run(records())


def test_legal_admin_registry_cannot_consume_reserved_withdrawal_envelope(env,monkeypatch):
    additions=[ManagerConfig(login='m'+str(i).zfill(3)+'x'*60,name='Synthetic admin',password='synthetic',admin=True)
        for i in range(140)]
    monkeypatch.setattr(settings,'managers',list(settings.managers)+additions)
    args,operation=prepare(env)
    saved=asyncio.run(service.record_decision(env['engine'],**args,expected_revision=0,
        request_key='SYN-LARGE-AUTHORITY',operation=operation))
    assert saved['receipt']['revision']==1
    result=asyncio.run(service.record_decision(env['engine'],**withdrawal(args,saved['receipt'],1)))
    assert result['receipt']['result']['disposition']=='withdrawn'
