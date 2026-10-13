"""Opt-in actual PostgreSQL locks; synthetic databases only."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import threading
import time

import pytest
from sqlalchemy import text

from app.domain import applicant_profiles, knowledge_publication
from tests import test_current_stay_stops as cases
from tests.test_current_stay_stops import clock, connected_clock, route_clock, admins
from tests.test_entry_process_postgres import connection, database, db_url, template, env


def wait_for_db_lock(env):
    async def waiting():
        async with env['engine'].connect() as conn:
            return await conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
    until = time.monotonic() + 10
    while time.monotonic() < until:
        if asyncio.run(waiting()): return True
        time.sleep(.03)
    return False


@pytest.mark.parametrize('writer', ['profile', 'history', 'withdraw'])
def test_reader_holds_person_history_and_publication_locks(env, tmp_path, monkeypatch, writer):
    cases.setup(env, tmp_path)
    entered = threading.Event(); release = threading.Event()
    original = knowledge_publication._runtime_context
    async def hold(session):
        value = await original(session); entered.set()
        assert await asyncio.to_thread(release.wait, 25)
        return value
    def change():
        if writer == 'profile':
            return cases.save_profile(env, env['person'], revision=1, key='profile-after-read', doc=env['profile_doc'])
        if writer == 'history':
            return cases.withdraw(env, env['person'], revision=1)
        return cases.connected.publish(env, 'withdraw', ids=env['published'])
    with monkeypatch.context() as patch:
        patch.setattr(knowledge_publication, '_runtime_context', hold)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(cases.check, env)
            try:
                assert entered.wait(15)
                mutation = pool.submit(change)
                assert wait_for_db_lock(env) and not mutation.done()
            finally: release.set()
            result = reader.result(timeout=40)
            assert result['checks']['visa_free_headroom']['current_window_headroom'] == 4, result
            mutation.result(timeout=40)
    after = cases.check(env)
    expected = dict(profile='current_stay_attestation_scope_changed', history='current_stay_history_changed', withdraw='no_active_publication')
    assert all(v.get('reason') == expected[writer] for v in after['checks'].values()), after


def test_profile_correction_committed_during_real_lock_wait(env, tmp_path, monkeypatch):
    cases.setup(env, tmp_path)
    entered = threading.Event(); release = threading.Event()
    original = applicant_profiles._subject
    async def hold(session, case_id, applicant_id, *, write=False):
        value = await original(session, case_id, applicant_id, write=write)
        if write:
            entered.set(); assert await asyncio.to_thread(release.wait, 25)
        return value
    with monkeypatch.context() as patch:
        patch.setattr(applicant_profiles, '_subject', hold)
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(cases.save_profile, env, env['person'], revision=1, key='first-writer', doc=env['profile_doc'])
            try:
                assert entered.wait(15)
                reader = pool.submit(cases.check, env)
                assert wait_for_db_lock(env) and not reader.done()
            finally: release.set()
            writer.result(timeout=40); result = reader.result(timeout=40)
    assert all(v.get('reason') == 'current_stay_attestation_scope_changed' for v in result['checks'].values()), result


def test_clock_sample_after_actual_case_lock_wait(env, tmp_path, monkeypatch):
    cases.setup(env, tmp_path)
    entered = threading.Event(); release = threading.Event()
    at = datetime(2026,10,12,17,59,tzinfo=timezone.utc)
    monkeypatch.setattr(cases.service, '_now', lambda: at)
    async def lock():
        from app.domain import entry_applications
        async with env['engine'].begin() as conn:
            await conn.execute(text('SELECT id FROM service_cases WHERE id=:id FOR UPDATE'), {'id':env['cases']['visa']})
            entered.set(); assert await asyncio.to_thread(release.wait, 25)
    with ThreadPoolExecutor(max_workers=2) as pool:
        blocker = pool.submit(asyncio.run, lock())
        try:
            assert entered.wait(15)
            reader = pool.submit(cases.check, env)
            assert wait_for_db_lock(env) and not reader.done()
            at = datetime(2026,10,12,18,1,tzinfo=timezone.utc)
        finally: release.set()
        blocker.result(timeout=40); result = reader.result(timeout=40)
    assert result['as_of'] == '2026-10-13'
    assert all(v.get('reason') == 'individual_profile_needs_current_confirmation' for v in result['checks'].values())
