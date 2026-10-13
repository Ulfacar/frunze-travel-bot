"""Source-scoped operator-selected reviews through actual process/deadline/task APIs."""
import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import select

from app.domain import operator_sop_reviews as service, operator_sop_sources as sources, operator_sop_rules as rules
from app.domain import entry_deadline_tasks as tasks, entry_deadlines
from app.domain.operator_sop_policy import SopReviewAuthority, SopReviewPolicy
from app.domain.entry_storage import _hash, EntryStorageInvalid, EntryStorageConflict
from app.domain.knowledge_publication import _policy
from app.domain.models import CalendarTask, EntrySopReviewEvidence
from tests.test_admin_kg_entry import env, ADMIN
from tests.test_entry_applications import enforce_sqlite_foreign_keys, person
from tests.test_knowledge_publication import POLICY, preview as publication_preview
from tests import test_entry_processes as processes, test_applicant_profiles as profiles, test_connected_qualification as connected

ROOT=Path(__file__).resolve().parents[1]


def authority(env,rule,process=None,package=None):
    manifest=publication_preview(env,ids=env['published'])['manifest'];pp=process or processes.policy()
    p=SopReviewPolicy(dict(format=rules.FORMAT,reference='SYNTHETIC-SOP',proof='f'*64,operators=['admin'],
        valid_from='2026-01-01',review_due_on='2026-12-31',rule_id=rule,definition_hash=_hash(rules.definition(rule)),
        source_hash=rules.SOURCE_HASH,**{k:manifest[k] for k in ('bundle_hash','projection_hash','catalog_hash')},
        publication_policy_hash=_hash(_policy(POLICY)),process_policy_hash=pp.digest,process_catalog_hash=pp.catalog_digest,
        package_policy_hash=_hash(package.document() if package else None),source_mode='pinned_clause_internal_review_only'))
    return SopReviewAuthority(p,POLICY,pp,package)


def setup(env,tmp_path,key='LEAD_RESPONSE'):
    connected.source(env,tmp_path,source_file=ROOT/'runs/specialist-source.pdf')
    subject=person(env,'SOP-REVIEW');saved=profiles.save(env,subject)
    app=processes.setup(env,applicant=subject)
    rule=rules.PREFIX+key;allowed=authority(env,rule)
    return subject,app,saved,allowed


def args(env,prepared):
    subject,app,_,allowed=prepared
    return dict(actor=ADMIN,case_id=app['case_id'],applicant_id=subject['id'],application_id=app['id'],
        rule_unit_id=allowed.policy.document['rule_id'],authority=allowed)


def preview(env,arguments): return asyncio.run(service.preview(env['engine'],**arguments))


def write(env,arguments,*,key='sop-one',time='00:30'):
    current=preview(env,arguments)
    request=arguments|dict(expected_revision=current['revision'],request_key=key,
        operation=dict(action='operator_review',confirmed=True,evidence_hash=current['report']['evidence_hash'],
            schedule=dict(on='2026-11-02',time=time,reason='source_followup',reference='SYNTHETIC-REVIEW',proof='e'*64)))
    return asyncio.run(service.record(env['engine'],**request)),request


def task_args(arguments): return {k:v for k,v in arguments.items() if k not in ('applicant_id','authority')}


def test_source_stage_selected_time_task_stage_change_and_exact_retry(env,tmp_path,monkeypatch):
    prepared=setup(env,tmp_path);arguments=args(env,prepared)
    p=preview(env,arguments);assert p['report']['status']=='available',p
    saved,request=write(env,arguments)
    assert saved['summary']['operational_due_on'] is None
    assert saved['snapshot']['schedule']['at']=='2026-11-01T18:30:00+00:00'
    from app.config import settings
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[prepared[-1].document])
    ta=task_args(arguments)
    task=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta,enable=True))
    assert task['task']['at']=='2026-11-01T18:30:00+00:00' and task['task']['date']=='2026-11-02'
    first_id=task['task']['id']
    # A real process receipt invalidates the exact source head and cancels the
    # same eligible task atomically; the original command stays retryable.
    processes.attest(env,prepared[1],'conversation_started')
    processes.transition(env,prepared[1],'V02')
    current=asyncio.run(tasks.read_deadline_task(env['engine'],**ta))
    assert current['current']['task']['id']==first_id and current['current']['task']['status']=='cancelled'
    assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==saved
    replay=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**ta,replay=True))
    assert replay['selected']==saved and replay['operator_current']['status']=='unknown'
    cleared=asyncio.run(service.record(env['engine'],**(arguments|dict(authority=None,expected_revision=1,request_key='clear',
        operation=dict(action='operator_review_clear',confirmed=True,evidence_hash=saved['snapshot_hash'])))))
    assert cleared['summary']['review_due_on'] is None


def test_time_only_edit_conflict_clear_and_terminal_no_reopen(env,tmp_path,monkeypatch):
    prepared=setup(env,tmp_path);arguments=args(env,prepared);ta=task_args(arguments)
    from app.config import settings
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[prepared[-1].document])
    saved,request=write(env,arguments)
    first=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta,enable=True))
    async def edit():
        async with env['sm']() as session:
            task=await session.get(CalendarTask,first['task']['id'])
            task.scheduled_at=datetime(2026,11,1,19,30,tzinfo=timezone.utc);await session.commit()
    asyncio.run(edit())
    conflict=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta))
    assert conflict['attention']=='schedule_conflict'
    restored=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta,restore=True,expected_token=conflict['token']))
    assert restored['task']['at']=='2026-11-01T18:30:00+00:00'
    cancelled=asyncio.run(tasks.act_on_deadline_task(env['engine'],**ta,binding_id=restored['binding_id'],
        expected_token=restored['token'],request_key='cancel',action='cancel'))
    assert cancelled['task']['status']=='cancelled'
    assert asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta,enable=True))['task']['id']==first['task']['id']
    second,_=write(env,arguments,key='new-selected-time',time=None)
    fresh=asyncio.run(tasks.reconcile_deadline_task(env['engine'],**ta))
    assert fresh['generation']==2 and fresh['task']['at'] is None
    assert fresh['task']['id']!=first['task']['id']
