"""Source-derived date to a separate internal review reminder, never filing."""
import asyncio
from dataclasses import replace

import pytest
from sqlalchemy import select,func

from app.domain import work_review_tasks as service
from app.domain.work_review_policy import ReviewPolicy,WorkReviewAuthority,FORMAT
from app.domain.current_stay_policy import CurrentStayFact
from app.domain.knowledge_publication import _policy as publication_document
from app.domain.entry_storage import _hash,EntryStorageConflict,EntryStorageInvalid
from app.domain.models import CalendarTask,EntryWorkReviewEvent
from app.domain.service_authz import PermissionDenied
from tests import test_work_deadlines as deadline
from tests.test_work_deadlines import env,clock,connected_clock,route_clock,admins,ADMIN,POLICY
from tests.test_entry_applications import application,person,enforce_sqlite_foreign_keys


@pytest.fixture(autouse=True)
def review_clock(clock,monkeypatch):
    from datetime import datetime,timezone
    monkeypatch.setattr(service,'_now',lambda:datetime(2026,10,12,15,0,1,tzinfo=timezone.utc))


def setup(env,tmp_path):
    deadline.setup(env,tmp_path)
    review=ReviewPolicy(dict(format=FORMAT,scope='conditional_ep_filing_date_review',reference='SYNTHETIC-REVIEW-TASK',proof='9'*64,
        operators=['admin'],valid_from='2026-01-01',review_due_on='2026-12-31',work_policy_hash=env['work_policy'].digest,
        qualification_policy_hash=env['qualification_policy'].digest,publication_policy_hash=_hash(publication_document(POLICY))))
    env['review_authority']=WorkReviewAuthority(review,env['work_policy'],env['current_policy'],CurrentStayFact(env['fact_doc']),
        env['qualification_policy'],POLICY,env['calendars'])
    env['permit']=application(env,env['person'],'REVIEW-PERMIT',procedure='unified_permit')
    return env


def arguments(env,**changes):
    return dict(actor=ADMIN,case_id=env['cases']['visa'],applicant_id=env['person']['id'],
        application_id=env['permit']['id'],authority=env['review_authority'])|changes


def read(env,**changes):return asyncio.run(service.read(env['engine'],**arguments(env,**changes)))


def command(env,action='refresh',**changes):
    current=read(env,**changes)['current']
    return arguments(env,**changes)|dict(expected_revision=current['revision'],request_key=action+'-'+str(current['revision']),
        operation=dict(action=action,token=current['token'],confirmed=True))


def record(env,args):return asyncio.run(service.record(env['engine'],**args))


def counts(env):
    async def run():
        async with env['sm']() as session:
            return [await session.scalar(select(func.count()).select_from(m)) for m in (CalendarTask,EntryWorkReviewEvent)]
    return asyncio.run(run())


def test_conditional_date_actual_task_atomic_receipt_retry_and_withdrawal(env,tmp_path):
    setup(env,tmp_path);before=counts(env)
    request=command(env);saved=record(env,request)
    assert saved['snapshot']['report']['due_on']=='2026-10-16'
    task=saved['snapshot']['task'];assert task['date']=='2026-10-16' and task['at'] is None
    assert counts(env)==[before[0]+1,before[1]+1]
    assert record(env,request|{'authority':None})==saved
    assert saved['snapshot']['report']['permission_to_work'] is None
    assert saved['snapshot']['report']['operational_action_allowed'] is False
    with pytest.raises(EntryStorageConflict):record(env,request|{'operation':dict(action='cancel',token=request['operation']['token'],confirmed=True)})
    # Loss of authority is visible; an explicit reconcile cancels the projection.
    assert read(env,authority=None)['current']['attention']=='unknown_date'
    cancelled=record(env,command(env,authority=None))
    assert cancelled['snapshot']['task']['status']=='cancelled'
    assert record(env,request|{'authority':None})==saved
    assert read(env,authority=None)['history'][-1]['snapshot']==saved['snapshot']
    assert counts(env)==[before[0]+1,before[1]+2]


def test_current_subject_policy_and_claimed_or_external_calendar_changes(env,tmp_path):
    setup(env,tmp_path)
    assert not read(env,authority=None)['current']['eligible']
    with pytest.raises(PermissionDenied):
        record(env,command(env,authority=None))
    wrong=application(env,person(env,'OTHER'),'OTHER-PERMIT',procedure='unified_permit')
    with pytest.raises(EntryStorageInvalid,match='scope'):read(env,application_id=wrong['id'])
    saved=record(env,command(env));task_id=saved['task_id']
    async def alter(**values):
        async with env['sm']() as session:
            task=await session.get(CalendarTask,task_id)
            for key,value in values.items():setattr(task,key,value)
            await session.commit()
    asyncio.run(alter(claimed_by='synthetic-worker'))
    with pytest.raises(EntryStorageConflict,match='claimed'):record(env,command(env,'cancel'))
    asyncio.run(alter(claimed_by=None))
    from datetime import date
    asyncio.run(alter(scheduled_date=date(2026,10,15)))
    with pytest.raises(EntryStorageConflict,match='schedule_conflict'):record(env,command(env))
    restored=record(env,command(env,'restore'));assert restored['snapshot']['task']['date']=='2026-10-16'
    closed=record(env,command(env,'complete'));assert closed['snapshot']['task']['status']=='completed'
    with pytest.raises(EntryStorageInvalid,match='terminal_task'):record(env,command(env))
    with pytest.raises(EntryStorageInvalid,match='terminal_task'):record(env,command(env,'new_generation'))
