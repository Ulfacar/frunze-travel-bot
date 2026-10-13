"""Independent original failures on the frozen R27 review-task adapter."""
import asyncio
from copy import deepcopy
from datetime import date
import json

import pytest
from sqlalchemy import text

from app.domain import work_review_tasks as service
from app.domain.calendar_tasks import CalendarTaskService
from app.domain.entry_storage import EntryStorageInvalid, _hash
from app.domain.models import EntryWorkReviewEvent, ServiceCase
from app.domain.permissions import Actor
from tests import test_work_review_tasks as baseline
from tests.test_work_review_tasks import (
    env, clock, review_clock, connected_clock, route_clock, admins, enforce_sqlite_foreign_keys,
)


def rewrite(env, row_id, change):
    async def run():
        async with env['sm']() as session:
            row = await session.get(EntryWorkReviewEvent, row_id)
            payload = deepcopy(service._payload(row))
        change(payload)
        async with env['engine'].begin() as conn:
            await conn.execute(text('UPDATE entry_work_review_events SET task_id=:task_id, snapshot=:snapshot, '
                'command=:command, request_hash=:request_hash, snapshot_hash=:snapshot_hash WHERE id=:id'),
                dict(id=row_id, task_id=payload['task_id'], snapshot=json.dumps(payload['snapshot']),
                     command=json.dumps(payload['command']), request_hash=_hash(payload['command']),
                     snapshot_hash=_hash(payload)))
    asyncio.run(run())


def test_same_meaning_does_not_reopen_after_authority_loss(env, tmp_path):
    baseline.setup(env, tmp_path)
    original = baseline.record(env, baseline.command(env))
    withdrawn = baseline.record(env, baseline.command(env, authority=None))
    assert withdrawn['snapshot']['task']['status'] == 'cancelled'
    assert baseline.read(env)['current']['report']['due_on'] == original['snapshot']['report']['due_on']
    with pytest.raises(EntryStorageInvalid, match='terminal_task'):
        baseline.record(env, baseline.command(env, 'new_generation'))


def test_rehashed_pointer_cannot_capture_unrelated_same_case_task(env, tmp_path):
    baseline.setup(env, tmp_path)
    original = baseline.record(env, baseline.command(env))
    async def other_task():
        async with env['sm']() as session:
            case = await session.get(ServiceCase, env['cases']['visa'])
            task = await CalendarTaskService.create(session, manager_id=case.owner_login, direction='visa',
                kind='followup', contact_id=case.contact_id, scheduled_date=date(2026, 10, 16),
                comment='Unrelated same-case internal task', created_by='admin')
            task.service_case_id = case.id
            await session.commit()
            return task.id
    other = asyncio.run(other_task())
    assert other != original['task_id']
    def change(payload):
        payload['task_id'] = other
        payload['snapshot']['task']['id'] = other
    rewrite(env, original['id'], change)
    with pytest.raises(EntryStorageInvalid):
        baseline.read(env)


def test_rehashed_historical_source_provenance_is_verified(env, tmp_path):
    baseline.setup(env, tmp_path)
    original = baseline.record(env, baseline.command(env))
    def change(payload):
        report = payload['snapshot']['report']
        report['source']['rule_hash'] = '1' * 64
        report['evidence_hash'] = _hash({k:v for k,v in report.items() if k != 'evidence_hash'})
    rewrite(env, original['id'], change)
    with pytest.raises(EntryStorageInvalid):
        baseline.read(env)


def test_retained_operator_list_is_not_a_new_authority(env, tmp_path):
    baseline.setup(env, tmp_path)
    original = baseline.record(env, baseline.command(env))
    def change(payload):
        payload['snapshot']['operators'].append('unapproved')
    rewrite(env, original['id'], change)
    intruder = Actor(manager_id='unapproved', is_full_admin=True)
    with pytest.raises(EntryStorageInvalid):
        baseline.record(env, baseline.command(env, 'cancel', authority=None, actor=intruder))
