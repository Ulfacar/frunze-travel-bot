"""Verified, whole-service aggregates over synthetic stored application chains."""
import asyncio

import pytest
from sqlalchemy import event, text

from app.domain import entry_applications as journal
from app.domain import entry_group_overview as service
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import application, counts, enforce_sqlite_foreign_keys, person, record


def overview(env, **options):
    return asyncio.run(service.read_group_overview(env['engine'], actor=ADMIN, case_id=env['cases']['visa'], **options))


def approve(env, app, key='submit'):
    record(env, app, key, source='official_document', reference=None)
    record(env, app, key + '-approve', source='official_document', reference=None, status='approved')


def group(env):
    first, second, missing = person(env), person(env, 'second', role='child'), person(env, 'missing')
    approved = application(env, first); approve(env, approved)
    old = application(env, second, 'refused')
    record(env, old); record(env, old, 'refusal', status='refused')
    retry = application(env, second, 'retry', previous=old['id'])
    registration = application(env, second, 'registration', procedure='registration')
    record(env, registration, 'registration-submitted', source='official_document', reference=None)
    independent = application(env, second, 'independent'); approve(env, independent, 'independent-submit')
    return first, second, missing, approved, old, retry, registration, independent


def test_whole_group_latest_attempts_independent_roots_and_missing_person(env):
    first, second, missing, approved, old, retry, registration, independent = group(env)
    before = counts(env)
    result = overview(env)
    assert result['state'] == 'incomplete'
    assert (result['total_people'], result['total_applications'], result['current_applications'], result['historical_applications']) == (3, 5, 4, 1)
    assert result['without_applications'] == 1
    assert result['counts'] == dict(draft=1, submitted=1, revision_requested=0, approved=2, refused=0, closed=0)
    child = result['people'][1]
    assert {row['id'] for row in child['applications']} == {retry['id'], registration['id'], independent['id']}
    assert child['historical_count'] == 1 and result['people'][2]['applications'] == []
    assert result['processes']['visa']['approved'] == 2 and result['processes']['stay']['submitted'] == 1
    assert counts(env) == before


@pytest.mark.parametrize('selection,expected', [('all', 3), ('without_applications', 1), ('attention', 0),
    ('draft', 1), ('submitted', 1), ('approved', 2)])
def test_filters_do_not_reduce_totals_or_hide_other_procedures_of_matching_person(env, selection, expected):
    group(env)
    result = overview(env, selection=selection)
    assert result['total_people'] == 3 and result['current_applications'] == 4 and result['matching_people'] == expected
    if selection in ('draft', 'submitted'):
        assert len(result['people'][0]['applications']) == 3


def test_all_approvals_are_only_journal_progress_and_empty_group_is_not_approved(env):
    assert overview(env)['state'] == 'empty'
    p = person(env); assert overview(env)['state'] == 'incomplete'
    app = application(env, p); assert overview(env)['state'] == 'draft'
    record(env, app); assert overview(env)['state'] == 'submitted'
    record(env, app, 'approved', status='approved'); assert overview(env)['state'] == 'approved'
    assert 'готов' not in service.STATES['approved'].lower() and 'заверш' not in service.STATES['approved'].lower()


@pytest.mark.parametrize('status', ['revision_requested', 'refused', 'closed'])
def test_each_exception_remains_visible_until_a_valid_linked_retry(env, status):
    p = person(env); app = application(env, p); record(env, app)
    record(env, app, 'exception', status=status)
    result = overview(env, selection='attention')
    assert result['state'] == 'attention' and result['counts'][status] == 1 and result['matching_people'] == 1
    if status != 'revision_requested':
        application(env, p, 'retry', previous=app['id'])
        result = overview(env)
        assert result['state'] == 'draft' and result['counts'][status] == 0 and result['historical_applications'] == 1


def test_whole_service_beyond_both_paginations_and_bounded_select_count(env):
    for i in range(22):
        p = person(env, f'p-{i}'); application(env, p, f'app-{i}')
    queries = []
    def capture(conn, cursor, sql, params, ctx, many): queries.append(sql)
    event.listen(env['engine'].sync_engine, 'before_cursor_execute', capture)
    try: result = overview(env, page=2)
    finally: event.remove(env['engine'].sync_engine, 'before_cursor_execute', capture)
    assert result['total_people'] == 22 and result['counts']['draft'] == 22
    assert len(result['people']) == 2 and (result['first'], result['last'], result['page']) == (21, 22, 2)
    assert not result['has_next'] and overview(env, page=100000)['page'] == 2
    assert sum(sql.lstrip().upper().startswith('SELECT') for sql in queries) <= 7
    assert not any(sql.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE', 'CREATE', 'DROP')) for sql in queries)


@pytest.mark.parametrize('actor', [None, Actor('admin', False), Actor('medina', False, ('visa',)), Actor('system', True), Actor('', True)])
def test_access_denied_before_engine(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(service.read_group_overview(None, actor=actor, case_id=1))


@pytest.mark.parametrize('kwargs', [{'page': 0}, {'page': True}, {'page': 100001}, {'selection': 'refused'}, {'selection': []}])
def test_invalid_filters_before_engine(kwargs):
    with pytest.raises(EntryStorageInvalid, match='invalid_group_filter'):
        asyncio.run(service.read_group_overview(None, actor=ADMIN, case_id=1, **kwargs))


def test_foreign_case_is_excluded_and_other_direction_rejected(env):
    p = person(env, case='other'); app = application(env, p, case='other')
    record(env, app, case='other')
    result = overview(env)
    assert result['total_people'] == 0 and result['total_applications'] == 0
    assert 'AB12CD34' not in str(result)
    for case_id in (env['cases']['tours'], 2147483647):
        with pytest.raises(EntryStorageInvalid, match='application_case_unavailable'):
            asyncio.run(service.read_group_overview(env['engine'], actor=ADMIN, case_id=case_id))


@pytest.mark.parametrize('limit', ['MAX_OVERVIEW_APPLICATIONS', 'MAX_OVERVIEW_EVENTS', 'MAX_APPLICANTS'])
def test_oversized_snapshot_refuses_partial_summary(env, monkeypatch, limit):
    group(env); monkeypatch.setattr(service, limit, 1)
    with pytest.raises(EntryStorageInvalid, match='group_overview_too_large'): overview(env)


@pytest.mark.parametrize('target', ['old_event', 'applicant', 'application', 'reference'])
def test_tampered_history_and_subjects_cannot_produce_clean_overview(env, target):
    first, second, missing, approved, old, retry, registration, independent = group(env)
    commands = {
        'old_event': ('UPDATE entry_application_events SET snapshot_hash = :value WHERE application_id = :id AND revision = 1', old['id'], '0' * 64),
        'applicant': ('UPDATE entry_applicants SET snapshot_hash = :value WHERE id = :id', first['id'], '0' * 64),
        'application': ('UPDATE entry_applications SET snapshot_hash = :value WHERE id = :id', old['id'], '0' * 64),
        'reference': ('UPDATE entry_application_references SET reference = :value WHERE application_id = :id', old['id'], 'ZZZZZZZZ')}
    sql, row_id, value = commands[target]
    async def corrupt():
        async with env['engine'].begin() as conn: await conn.execute(text(sql), {'id': row_id, 'value': value})
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid, match='application_integrity_failed'): overview(env)


def test_concurrent_readers_observe_valid_snapshots_during_submission_and_approval(env):
    p = person(env); app = application(env, p)
    async def scenario():
        async def writer():
            args = dict(actor=ADMIN, case_id=env['cases']['visa'], application_id=app['id'],
                        occurred_on='2026-09-01', source='portal', reference='AB12CD34', confirmed=True)
            await journal.record_application_event(env['engine'], expected_revision=1, request_key='submit', status='submitted', **args)
            await journal.record_application_event(env['engine'], expected_revision=2, request_key='approve', status='approved', **args)
        values = await asyncio.gather(writer(), *(service.read_group_overview(env['engine'], actor=ADMIN, case_id=env['cases']['visa']) for _ in range(8)))
        for result in values[1:]:
            assert result['state'] in ('draft', 'submitted', 'approved') and sum(result['counts'].values()) == 1
            row = result['people'][0]['applications'][0]
            assert (row['current']['reference'] is None) == (row['current']['status'] == 'draft')
    asyncio.run(scenario())
    assert overview(env)['state'] == 'approved'
