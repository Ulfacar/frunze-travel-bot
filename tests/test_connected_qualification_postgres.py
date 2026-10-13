"""Opt-in disposable loopback PostgreSQL: coherent reader versus real writers."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from sqlalchemy import text

from tests.test_entry_process_postgres import connection, database, db_url, template, env
from tests import test_connected_qualification as cases
from tests.test_connected_qualification import clock, route_clock, admins
from app.domain import knowledge_publication


@pytest.mark.parametrize('writer', ['profile', 'history', 'interview', 'withdraw', 'review'])
def test_assessment_retains_all_locks_through_result(env, tmp_path, monkeypatch, writer):
    cases.setup(env, tmp_path)
    entered = threading.Event(); release = threading.Event()
    original = knowledge_publication._runtime_context
    async def hold(session):
        result = await original(session)
        entered.set()
        assert await asyncio.to_thread(release.wait, 20), 'read hold timed out'
        return result
    def change():
        if writer == 'profile':
            return cases.save_profile(env, env['person'], revision=1, key='writer-profile', doc=env['profile_doc'])
        if writer == 'history':
            return cases.save_history(env, env['person'], env['saved'], revision=1, key='writer-history',
                                      doc=cases.document(history_complete=None))
        if writer == 'interview':
            current = env['interview']; ip = env['interview_policy']
            return asyncio.run(cases.entry_interviews.record_action(env['engine'], actor=cases.OWNER,
                case_id=env['cases']['visa'], applicant_id=env['person']['id'], interview_id=current['interview_id'],
                expected_revision=current['revision'], request_key='writer-interview', policy=ip,
                expected_policy_hash=ip.digest, operation=dict(action='correct', displayed=['applicant.age'],
                                                             changes={'applicant.age': 31})))
        if writer == 'withdraw':
            return cases.publish(env, 'withdraw', ids=env['published'])
        return cases.review(env, decision=cases.review_data() | dict(verdict='rejected', reason='source_conflict', review_due_on=None),
                            unit='KG.VF.EAEU', key='writer-review')
    async def waiting():
        async with env['engine'].connect() as conn:
            return await conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
    with monkeypatch.context() as patch:
        patch.setattr(knowledge_publication, '_runtime_context', hold)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(cases.assess, env)
            try:
                assert entered.wait(15)
                mutation = pool.submit(change)
                until = time.monotonic() + 10; observed = False
                while time.monotonic() < until:
                    if asyncio.run(waiting()):
                        observed = True; break
                    time.sleep(.03)
                assert observed and not mutation.done(), 'writer did not wait on a PostgreSQL lock'
            finally:
                release.set()
            result = reader.result(timeout=40)
            assert result['selected_product'] == 'NO_VISA', result['reasons']
            mutation.result(timeout=40)
    after = cases.assess(env)
    expected = dict(profile='personal_history_review_required', history='personal_history_review_required',
                    interview='interview_changed_after_ack', withdraw='no_active_publication', review='assessment_source_unavailable')
    assert after['selected_product'] is None and after['reasons'] == [expected[writer]]
