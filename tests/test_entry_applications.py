"""Synthetic real SQLite transactions, not mocked persistence."""
import asyncio

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.domain import entry_applications as service
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.models import (DomainError, EntryApplicant, EntryApplication, EntryApplicationEvent,
                              EntryApplicationReference, EntryQualification, ServiceCase)
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, env


@pytest.fixture(autouse=True)
def enforce_sqlite_foreign_keys(request):
    if 'env' not in request.fixturenames:
        yield
        return
    engine = request.getfixturevalue('env')['engine'].sync_engine
    def enable(dbapi, record):
        cursor = dbapi.cursor(); cursor.execute('PRAGMA foreign_keys=ON'); cursor.close()
    event.listen(engine, 'connect', enable)
    try: yield
    finally: event.remove(engine, 'connect', enable)


def person(env, key='person', case='visa', role='primary'):
    return asyncio.run(service.add_applicant(env['engine'], actor=ADMIN, case_id=env['cases'][case], role=role, request_key=key))


def application(env, applicant, key='application', case='visa', procedure='visa', previous=None):
    return asyncio.run(service.open_application(env['engine'], actor=ADMIN, case_id=env['cases'][case],
        applicant_id=applicant['id'], procedure=procedure, previous_id=previous, request_key=key))


def read(env, app, case='visa'):
    return asyncio.run(service.read_application(env['engine'], actor=ADMIN, case_id=env['cases'][case], application_id=app['id']))


def record(env, app, key='event', revision=None, case='visa', **changes):
    current = read(env, app, case=case)['current']
    args = dict(status='submitted', occurred_on='2026-09-01', source='portal', reference='AB12CD34', confirmed=True)
    args.update(changes)
    return asyncio.run(service.record_application_event(env['engine'], actor=ADMIN, case_id=env['cases'][case],
        application_id=app['id'], expected_revision=current['revision'] if revision is None else revision, request_key=key, **args))


def counts(env):
    async def run():
        async with env['sm']() as session:
            return tuple([await session.scalar(select(func.count()).select_from(model)) for model in
                          (EntryApplicant, EntryApplication, EntryApplicationEvent, EntryApplicationReference, EntryQualification)])
    return asyncio.run(run())


def test_separate_people_six_documents_four_families_and_unchanged_case(env):
    async def case_state():
        async with env['sm']() as session:
            row = await session.get(ServiceCase, env['cases']['visa'])
            return row.stage, row.revision, row.owner_login
    before = asyncio.run(case_state())
    first, second = person(env), person(env, 'child', role='child')
    assert first['id'] != second['id'] and second['ordinal'] == 2
    apps = [application(env, first if i % 2 else second, kind, procedure=kind)
            for i, kind in enumerate(service.PROCEDURES)]
    assert {app['process'] for app in apps} == {'visa', 'work', 'stay', 'regularization'}
    record(env, apps[0]); record(env, apps[0], 'approved', status='approved', occurred_on='2026-09-05')
    assert read(env, apps[0])['current']['status'] == 'approved'
    assert all(read(env, app)['current']['status'] == 'draft' for app in apps[1:])
    assert asyncio.run(case_state()) == before and counts(env) == (2, 6, 8, 1, 0)


def test_revision_loop_same_attempt_refusal_linked_retry_and_independent_new_root(env):
    p = person(env); app = application(env, p)
    record(env, app)
    record(env, app, 'return', status='revision_requested', occurred_on='2026-09-02')
    record(env, app, 'resubmit', status='submitted', occurred_on='2026-09-03')
    record(env, app, 'refusal', status='refused', occurred_on='2026-09-04')
    old = read(env, app)
    assert old['attempt'] == 1 and old['current']['revision'] == 5
    again = application(env, p, 'retry', previous=app['id'])
    assert again['attempt'] == 2 and again['previous_id'] == app['id']
    assert read(env, app)['events'] == old['events'] and read(env, app)['successor_id'] == again['id']
    assert read(env, again)['current']['reference'] is None
    assert application(env, p, 'independent')['attempt'] == 1
    with pytest.raises(EntryStorageConflict): application(env, p, 'fork', previous=app['id'])
    with pytest.raises(EntryStorageInvalid): application(env, p, 'wrong-kind', previous=app['id'], procedure='registration')
    other_person = person(env, 'other')
    with pytest.raises(EntryStorageInvalid): application(env, other_person, 'wrong-person', previous=app['id'])


def test_retry_checks_key_contents_before_reuse_and_returns_original_revision(env):
    p = person(env)
    assert person(env) == p
    with pytest.raises(EntryStorageConflict): person(env, role='child')
    app = application(env, p)
    assert application(env, p) == app
    with pytest.raises(EntryStorageConflict): application(env, p, procedure='registration')
    first = record(env, app)
    record(env, app, 'return', status='revision_requested', occurred_on='2026-09-02')
    assert record(env, app, revision=1) == first
    with pytest.raises(EntryStorageConflict): record(env, app, revision=1, occurred_on='2026-09-03')
    with pytest.raises(EntryStorageConflict): record(env, app, 'stale', revision=1)
    assert counts(env) == (1, 1, 3, 1, 0)


@pytest.mark.parametrize('actor', [None, Actor('admin', False), Actor('medina', False, ('visa',)), Actor('system', True), Actor('', True)])
def test_named_full_admin_precedes_engine_access(actor):
    for coro in (service.add_applicant(None, actor=actor, case_id=1, role='primary', request_key='k'),
                 service.open_application(None, actor=actor, case_id=1, applicant_id=1, procedure='visa', request_key='k'),
                 service.read_application_register(None, actor=actor, case_id=1),
                 service.read_application(None, actor=actor, case_id=1, application_id=1),
                 service.record_application_event(None, actor=actor, case_id=1, application_id=1, expected_revision=1,
                     request_key='k', status='submitted', occurred_on='2026-09-01', source='portal')):
        with pytest.raises(PermissionDenied): asyncio.run(coro)


def test_case_applicant_previous_and_reference_scope(env):
    p = person(env); app = application(env, p)
    with pytest.raises(EntryStorageInvalid): read(env, app, case='other')
    with pytest.raises(EntryStorageInvalid): application(env, p, 'foreign', case='other')
    with pytest.raises(EntryStorageInvalid): person(env, case='tours')
    other = person(env, 'other', case='other'); foreign_app = application(env, other, 'other', case='other')
    record(env, app)
    with pytest.raises(EntryStorageConflict, match='portal_reference_already_recorded'):
        record(env, foreign_app, case='other')
    assert read(env, foreign_app, case='other')['current']['revision'] == 1
    with pytest.raises(EntryStorageInvalid): application(env, other, 'foreign-previous', case='other', previous=app['id'])


@pytest.mark.parametrize('changes', [
    {'status': 'approved'}, {'status': 'unknown'}, {'source': 'client_request'}, {'source': 'unknown'},
    {'confirmed': False}, {'confirmed': 1}, {'occurred_on': 'unknown'}, {'occurred_on': '2099-01-01'},
    {'occurred_on': '20260901'}, {'reference': None}, {'reference': 'TOO-LONG-REF'}, {'reference': '<script>'},
    {'reference': 'ab12cd34'}, {'source': 'official_document', 'reference': 'AB12CD34'},
])
def test_invalid_fact_does_not_create_any_event_or_claim(env, changes):
    app = application(env, person(env)); before = counts(env)
    with pytest.raises(EntryStorageInvalid): record(env, app, **changes)
    assert counts(env) == before


def test_actual_date_order_and_reference_immutability(env):
    app = application(env, person(env)); record(env, app, occurred_on='2026-09-05')
    for changes in ({'occurred_on': '2026-09-04'}, {'reference': 'XY98PQ76'}, {'reference': None}):
        with pytest.raises(EntryStorageInvalid): record(env, app, 'bad', status='approved', **changes)
    record(env, app, 'result', status='approved', occurred_on='2026-09-05')
    with pytest.raises(EntryStorageInvalid): record(env, app, 'terminal', status='submitted', occurred_on='2026-09-06')
    with pytest.raises(EntryStorageInvalid): application(env, {'id': app['applicant_id']}, 'bad-retry', previous=app['id'])


def test_paper_submission_and_crm_closure_do_not_claim_portal_operation(env):
    p = person(env); app = application(env, p, procedure='registration')
    record(env, app, source='official_document', reference=None)
    record(env, app, 'close', status='closed', source='client_request', reference=None, occurred_on='2026-09-02')
    assert counts(env)[3] == 0
    assert application(env, p, 'retry', procedure='registration', previous=app['id'])['attempt'] == 2


def test_parallel_duplicate_and_conflicting_events(env):
    p = person(env); app = application(env, p)
    async def run():
        args = dict(actor=ADMIN, case_id=env['cases']['visa'], application_id=app['id'], expected_revision=1,
            status='submitted', occurred_on='2026-09-01', source='portal', reference='AB12CD34', confirmed=True)
        same = await asyncio.gather(*(service.record_application_event(env['engine'], request_key='same', **args) for _ in range(2)))
        assert same[0] == same[1]
        args.update(expected_revision=2, occurred_on='2026-09-02')
        attempts = await asyncio.gather(service.record_application_event(env['engine'], request_key='a', **{**args, 'status': 'approved'}),
                                       service.record_application_event(env['engine'], request_key='b', **{**args, 'status': 'refused'}), return_exceptions=True)
        assert sum(isinstance(result, dict) for result in attempts) == 1
        assert sum(isinstance(result, EntryStorageConflict) for result in attempts) == 1
    asyncio.run(run())
    assert counts(env) == (1, 1, 3, 1, 0)


def test_lost_commit_acknowledgement_recovers_by_same_key(env):
    app = application(env, person(env))
    def lost(session): raise OperationalError('synthetic lost ack', {}, RuntimeError('synthetic'))
    event.listen(Session, 'after_commit', lost)
    try:
        # Avoid the read helper while the commit fault is active.
        with pytest.raises(EntryStorageUnavailable):
            asyncio.run(service.record_application_event(env['engine'], actor=ADMIN, case_id=env['cases']['visa'],
                application_id=app['id'], expected_revision=1, request_key='event', status='submitted',
                occurred_on='2026-09-01', source='portal', reference='AB12CD34', confirmed=True))
    finally: event.remove(Session, 'after_commit', lost)
    assert record(env, app, revision=1)['revision'] == 2
    assert counts(env) == (1, 1, 2, 1, 0)


def test_concurrent_read_and_write_never_mix_event_and_reference_snapshots(env):
    app = application(env, person(env))
    async def run():
        args = dict(actor=ADMIN, case_id=env['cases']['visa'], application_id=app['id'])
        writer = service.record_application_event(env['engine'], **args, expected_revision=1, request_key='write',
            status='submitted', occurred_on='2026-09-01', source='portal', reference='AB12CD34', confirmed=True)
        results = await asyncio.gather(writer, *(service.read_application(env['engine'], **args) for _ in range(5)))
        for result in results[1:]:
            current = result['current']
            assert (current['revision'], current['reference']) in ((1, None), (2, 'AB12CD34'))
    asyncio.run(run())


def test_parallel_applicant_and_attempt_creation_reuses_identical_requests(env):
    async def run():
        args = dict(actor=ADMIN, case_id=env['cases']['visa'], request_key='person', role='child')
        people = await asyncio.gather(*(service.add_applicant(env['engine'], **args) for _ in range(2)))
        assert people[0] == people[1]
        args = dict(actor=ADMIN, case_id=env['cases']['visa'], request_key='app', applicant_id=people[0]['id'], procedure='visa')
        apps = await asyncio.gather(*(service.open_application(env['engine'], **args) for _ in range(2)))
        assert apps[0] == apps[1]
    asyncio.run(run())
    assert counts(env) == (1, 1, 1, 0, 0)


@pytest.mark.parametrize('mutation', [
    "UPDATE entry_applicants SET role='child'", "UPDATE entry_applications SET procedure='registration'",
    "UPDATE entry_application_events SET source='client_request' WHERE revision=2",
    "UPDATE entry_application_references SET reference='XY98PQ76'",
    "DELETE FROM entry_application_events WHERE revision=2",
])
def test_corruption_cannot_be_read_or_extended(env, mutation):
    app = application(env, person(env)); record(env, app)
    async def mutate():
        async with env['engine'].begin() as conn: await conn.execute(text(mutation))
    asyncio.run(mutate())
    with pytest.raises(EntryStorageInvalid): read(env, app)
    before = counts(env)
    with pytest.raises(EntryStorageInvalid):
        asyncio.run(service.record_application_event(env['engine'], actor=ADMIN, case_id=env['cases']['visa'],
            application_id=app['id'], expected_revision=2, request_key='new', status='approved', occurred_on='2026-09-02',
            source='portal', reference='AB12CD34', confirmed=True))
    assert counts(env) == before


def test_orm_update_delete_bulk_are_rejected(env):
    p = person(env); app = application(env, p); record(env, app)
    async def scenario():
        for model in (EntryApplicant, EntryApplication, EntryApplicationEvent, EntryApplicationReference):
            async with env['sm']() as session:
                row = await session.scalar(select(model))
                await session.delete(row)
                with pytest.raises(DomainError): await session.flush()
                await session.rollback()
            async with env['sm']() as session:
                with pytest.raises(DomainError): await session.execute(update(model).values(case_id=env['cases']['other']))
        async with env['sm']() as session:
            row = await session.get(EntryApplicant, p['id']); row.role = 'child'
            with pytest.raises(DomainError): await session.flush()
    asyncio.run(scenario())


def test_pagination_no_silent_drop_and_get_no_writes(env):
    p = person(env)
    for i in range(21): application(env, p, f'a-{i}')
    statements = []
    def capture(conn, cursor, statement, params, context, executemany): statements.append(statement)
    event.listen(env['engine'].sync_engine, 'before_cursor_execute', capture)
    try:
        first = asyncio.run(service.read_application_register(env['engine'], actor=ADMIN, case_id=env['cases']['visa']))
        second = asyncio.run(service.read_application_register(env['engine'], actor=ADMIN, case_id=env['cases']['visa'], page=2))
    finally: event.remove(env['engine'].sync_engine, 'before_cursor_execute', capture)
    assert first['total'] == 21 and len(first['applications']) == 20 and first['has_next']
    assert len(second['applications']) == 1 and not second['has_next']
    assert not any(statement.lstrip().upper().startswith(('INSERT', 'UPDATE', 'DELETE')) for statement in statements)
