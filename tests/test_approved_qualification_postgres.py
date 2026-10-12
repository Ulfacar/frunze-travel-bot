"""Actual loopback PostgreSQL: scope, replay and coherent source/profile locks."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time

import pytest
from sqlalchemy import text

from tests.test_entry_process_postgres import connection, database, db_url, template, env
from tests import test_approved_qualification as cases
from tests.test_approved_qualification import ready, clock


def test_positive_and_legacy_replay(ready):
    cases.test_candidate_has_current_exact_identity_but_no_eligibility_or_writes(ready)


def test_subject_latest_revision(ready):
    cases.test_latest_personal_scope_and_current_confirmation(ready)


@pytest.mark.parametrize('writer', ['profile', 'withdraw', 'review'])
def test_read_holds_coherent_snapshot_until_response(ready, monkeypatch, writer):
    entered = threading.Event()
    release = threading.Event()
    original = cases.knowledge_publication._runtime_context

    async def hold(session):
        result = await original(session)
        entered.set()
        assert await asyncio.to_thread(release.wait, 15), 'test read hold timed out'
        return result

    def change():
        if writer == 'profile':
            doc = cases.profile(); doc['profile']['purpose'] = 'work_hire'
            return cases.save(ready, ready['person'], revision=1, key='concurrent', doc=doc)
        if writer == 'withdraw':
            return cases.publish(ready, 'withdraw')
        from tests.test_knowledge_decisions import data
        return cases.review(ready, {**data(), 'verdict':'rejected', 'reason':'withdrawn', 'review_due_on':None},
            unit='KG.VF.TEST', version=ready['release'], key='concurrent-review')

    async def blocked():
        async with ready['engine'].connect() as conn:
            return await conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))

    with monkeypatch.context() as patch:
        patch.setattr(cases.knowledge_publication, '_runtime_context', hold)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reader = pool.submit(cases.propose, ready)
            try:
                assert entered.wait(10)
                mutation = pool.submit(change)
                until = time.monotonic()+8
                saw_lock = False
                while time.monotonic() < until:
                    if asyncio.run(blocked()):
                        saw_lock = True
                        break
                    time.sleep(.03)
                assert saw_lock and not mutation.done(), 'writer did not wait on an actual database lock'
            finally:
                release.set()
            assert reader.result(timeout=15)['candidate'] is not None
            mutation.result(timeout=15)
    after = cases.propose(ready)
    assert after['candidate'] is None
    expected = dict(profile='profile_stop_requires_specialist', withdraw='no_active_publication',
                    review='competing_regime_unavailable')
    assert after['reasons'] == [expected[writer]]
