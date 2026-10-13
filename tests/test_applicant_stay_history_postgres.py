"""Only explicit disposable loopback PostgreSQL; real locks and migrated schema."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace

import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.domain.models import DomainBase
from tests.test_entry_process_postgres import connection,database,db_url,template,env
from tests import test_applicant_stay_history as cases
from tests.test_applicant_stay_history import clock
from tests import test_admin_kg_applicant_history as native


def test_people_scope_and_payer(env):cases.test_people_do_not_inherit_payer_or_each_other_history(env)
def test_concurrent_cas_and_duplicate(env):cases.test_concurrent_duplicate_and_competing_writes(env)
def test_actual_count_limit_and_withdrawal(env):cases.test_real_249_revision_history_reserves_terminal_withdrawal(env)
def test_bytes_and_predecode_bound(env,monkeypatch):cases.test_byte_capacity_reserves_withdrawal_and_oversized_raw_data_fails_closed(env,monkeypatch)


@pytest.mark.parametrize('when',['before_insert','before_commit','after_commit'])
def test_atomicity_and_uncertain_commit(env,when):cases.test_failed_transaction_and_uncertain_commit_recover_without_duplicate(env,when)


def test_native_retry_original_pin(env,monkeypatch):
    subject,profile=cases.setup(env)
    native.test_lost_commit_ack_original_base_retry_after_new_profile_and_day(env,
        (subject,profile,f'{env["url"]}/applicants/{subject["id"]}/history'),monkeypatch)


@pytest.mark.parametrize('writer',['history','profile'])
def test_read_holds_person_lock_until_complete(env,monkeypatch,writer):
    subject,profile=cases.setup(env);first=cases.save(env,subject,profile)
    entered=threading.Event();release=threading.Event();original=cases.service._history
    async def hold(session,case,person):
        result=await original(session,case,person)
        entered.set();assert await asyncio.to_thread(release.wait,15),'history read timed out'
        return result
    def change():
        if writer=='history':return cases.save(env,subject,profile,revision=1,key='concurrent')
        return cases.profiles.save(env,subject,revision=1,key='concurrent-profile')
    async def blocked():
        async with env['engine'].connect() as conn:
            return await conn.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
    with monkeypatch.context() as patch:
        patch.setattr(cases.service,'_history',hold)
        with ThreadPoolExecutor(max_workers=2) as pool:
            reader=pool.submit(cases.read,env,subject)
            try:
                assert entered.wait(10);mutation=pool.submit(change);until=time.monotonic()+8;saw_lock=False
                while time.monotonic()<until:
                    if asyncio.run(blocked()):saw_lock=True;break
                    time.sleep(.03)
                assert saw_lock and not mutation.done()
            finally:release.set()
            before=reader.result(timeout=15);mutation.result(timeout=15)
    assert before['selected']==first and 'profile_changed' not in before['current']['findings']
    after=cases.read(env,subject)
    assert after['current_revision']==(2 if writer=='history' else 1)
    assert ('profile_changed' in after['current']['findings'])==(writer=='profile')


def test_migration_cycle_real_constraints_profile_preservation_and_populated_refusal(env):
    cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    subject,profile=cases.setup(env);second,profile2=cases.setup(env,'second')
    command.downgrade(cfg,'e6_publication_withdraw_0034');command.upgrade(cfg,'head')
    assert cases.profiles.read(env,subject)['saved']==profile
    first=cases.save(env,subject,profile)
    async def inspect():
        async with env['engine'].connect() as conn:
            def compare(sync):return compare_metadata(MigrationContext.configure(sync),DomainBase.metadata)
            assert await conn.run_sync(compare)==[]
            assert await conn.scalar(text('SELECT count(*) FROM service_cases'))==3
        sql='INSERT INTO entry_applicant_stay_history(case_id,applicant_id,profile_id,revision,previous_id,action,request_key,request_hash,snapshot_hash,command,provenance,created_by,created_at) SELECT :case,:person,:profile,:rev,:prev,action,:key,request_hash,snapshot_hash,command,provenance,created_by,created_at FROM entry_applicant_stay_history WHERE id=:id'
        for overrides in ({'case':env['cases']['other']},{'person':second['id']},{'profile':profile2['qualification_id']},
            {'prev':999},{'rev':251}):
            params=dict(case=env['cases']['visa'],person=subject['id'],profile=profile['qualification_id'],rev=2,
                prev=first['id'],key='invalid',id=first['id'])|overrides
            async with env['engine'].begin() as conn:
                with pytest.raises(IntegrityError):await conn.execute(text(sql),params)
    asyncio.run(inspect())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(cfg,'e6_publication_withdraw_0034')
    assert cases.read(env,subject)['selected']==first and cases.profiles.read(env,subject)['saved']==profile
