"""Opt-in fresh local PostgreSQL databases; synthetic interview evidence only."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import uuid
import zipfile

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.pool import NullPool

from tests.test_entry_process_postgres import connection,db_url,database,template,env
from tests.test_entry_interviews import admins
from tests import test_entry_interviews as cases
from app.domain.models import DomainBase,EntryInterview,EntryInterviewEvent


def test_concurrent_identical_ack(env):cases.test_concurrent_identical_ack_and_competing_answer_interrupt(env)


def test_concurrent_answer_interrupt(env):cases.test_competing_answer_and_interrupt_have_one_compare_and_swap_winner(env)


def test_exact_profile_growth(env):cases.test_profile_pin_is_exact_applicant_and_survives_later_profile_growth(env)


@pytest.mark.parametrize('at',['before_commit','after_commit'])
def test_commit_uncertainty_and_exact_retry(env,at):cases.test_commit_fault_recovers_original_handoff_and_card(env,at)


@pytest.mark.parametrize('model',[EntryInterview,EntryInterviewEvent])
def test_start_two_halves_rollback(env,model):cases.test_start_two_halves_rollback(model,env)


def test_conflict_facts_handoff_ack_frozen_card(env):cases.test_conflict_answer_and_handoff_are_one_event_and_card_stays_frozen(env)


def test_exact_scope_and_single_enrollment(env):cases.test_scope_and_unique_subject_cannot_bypass_a_handoff(env)


def test_rehashed_semantic_tamper(env):cases.test_rehashed_handoff_card_tamper_fails_semantic_replay(env)


def test_terminal_capacity_and_noops(env,monkeypatch):cases.test_reserved_capacity_allows_handoff_ack_and_denies_terminal_noops(env,monkeypatch)


def test_withdrawal_before_ack_at_capacity(env,monkeypatch):cases.test_last_reserved_events_allow_withdrawal_before_owner_ack(env,monkeypatch)


@pytest.mark.parametrize('phase',['pending','acked'])
def test_withdrawal_after_handoff(env,monkeypatch,phase):cases.test_withdrawal_is_durable_in_every_phase_and_never_rewrites_frozen_card(env,monkeypatch,phase)


def test_historical_catalog_and_retry_survive_new_active_version(env,monkeypatch):cases.test_new_active_catalog_keeps_old_card_readable_and_old_retry_and_ack_exact(env,monkeypatch)


def test_midnight_policy_boundary(env,monkeypatch):cases.test_policy_midnight_change_before_persist_does_not_create_unreadable_event(env,monkeypatch)


def test_consent_reaffirmation_and_explicit_withdrawal(env):cases.test_fresh_consent_reaffirmation_preserves_evidence_and_explicit_false_still_withdraws(env)


def test_empty_cycle_schema_constraints_and_populated_refusal(env):
    cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_portal_observations_0028');command.upgrade(cfg,'head')
    async def parity():
        async with env['engine'].connect() as conn:
            def compare(sync):
                ctx=MigrationContext.configure(sync,opts={'compare_type':True,
                    'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name in ('entry_interviews','entry_interview_events')})
                return compare_metadata(ctx,DomainBase.metadata)
            assert await conn.run_sync(compare)==[]
    asyncio.run(parity());iv=cases.start(env);cases.action(env,iv,'handoff');cases.action(env,iv,'ack')
    async def invalid():
        for table,column,value in [('entry_interview_events','case_id',env['cases']['other']),('entry_interview_events','applicant_id',99999),
            ('entry_interview_events','revision',257),('entry_interview_events','previous_id',99999),('entry_interviews','profile_id',99999)]:
            async with env['engine'].begin() as conn:
                with pytest.raises(IntegrityError):await conn.execute(text(f'UPDATE {table} SET {column}=:value'),{'value':value})
    asyncio.run(invalid())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(cfg,'e6_portal_observations_0028')
    assert cases.read(env,iv)['state']['phase']=='acked'


def test_binary_copy_recovery_frozen_card_ack_old_retry_native_read_and_new_write(env,monkeypatch):
    import app.admin.router as ar
    from app.admin.kg_interviews import _url
    config=connection();runtime=Path(os.environ['FRUNZE_LOCAL_PG_CONNECTION']).parent
    output=runtime/'e612-recovery';output.mkdir(exist_ok=True)
    iv=cases.start(env);cases.correct(env,iv,{'entry_on':'2026-12-20','exit_on':'2026-12-01'})
    args=cases.action_args(env,iv,'ack');ack=asyncio.run(cases.service.record_action(env['engine'],**args))
    cases.correct(env,iv,{'exit_on':'2026-12-30'},actor=cases.OWNER)
    before=cases.read(env,iv);before_counts=cases.counts(env)
    restored='frunze_e610_'+uuid.uuid4().hex[:24];dump=output/(restored+'.zip')
    def ident(value):
        assert re.fullmatch('[a-z_][a-z0-9_]*',value)
        return '"'+value+'"'
    async def backup():
        conn=await asyncpg.connect(**(config|{'database':env['engine'].url.database}))
        try:
            async with conn.transaction(isolation='repeatable_read',readonly=True):
                tables=[r['tablename'] for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version' ORDER BY tablename")]
                manifest={'revision':await conn.fetchval('SELECT version_num FROM alembic_version'),'tables':{},'sequences':{}}
                with zipfile.ZipFile(dump,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                    for table in tables:
                        chunks=[]
                        async def sink(data):chunks.append(data)
                        await conn.copy_from_table(table,output=sink,format='binary',schema_name='public')
                        data=b''.join(chunks);archive.writestr(table+'.bin',data)
                        manifest['tables'][table]={'count':await conn.fetchval('SELECT count(*) FROM '+ident(table)),
                            'sha256':hashlib.sha256(data).hexdigest()}
                    edges=await conn.fetch("SELECT c.relname child,p.relname parent FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid JOIN pg_class p ON p.oid=f.confrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE f.contype='f' AND n.nspname='public'")
                    pending={t for t,v in manifest['tables'].items() if v['count']};order=[]
                    while pending:
                        ready=sorted(t for t in pending if not any(e['child']==t and e['parent'] in pending and e['parent']!=t for e in edges))
                        assert ready,'nonempty cyclic dependencies require separate recovery adapter'
                        order.extend(ready);pending.difference_update(ready)
                    manifest['order']=order
                    for row in await conn.fetch("SELECT sequencename FROM pg_sequences WHERE schemaname='public'"):
                        name=row['sequencename'];manifest['sequences'][name]=dict(await conn.fetchrow('SELECT last_value,is_called FROM '+ident(name)))
                    archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
        finally:await conn.close()
    asyncio.run(backup());database(config,restored);engine=create_async_engine(db_url(config,restored),poolclass=NullPool)
    try:
        cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+db_url(config,restored).render_as_string(hide_password=False)])
        command.upgrade(cfg,'head')
        async def restore():
            conn=await asyncpg.connect(**(config|{'database':restored}))
            try:
                with zipfile.ZipFile(dump) as archive:
                    manifest=json.loads(archive.read('manifest.json'))
                    assert await conn.fetchval('SELECT version_num FROM alembic_version')==manifest['revision']
                    async with conn.transaction():
                        for table in manifest['tables']:assert await conn.fetchval('SELECT count(*) FROM '+ident(table))==0
                        for table in manifest['order']:
                            data=archive.read(table+'.bin');assert hashlib.sha256(data).hexdigest()==manifest['tables'][table]['sha256']
                            await conn.copy_to_table(table,source=memoryview(data),format='binary',schema_name='public')
                        for table,value in manifest['tables'].items():assert await conn.fetchval('SELECT count(*) FROM '+ident(table))==value['count']
                        for name,value in manifest['sequences'].items():
                            ident(name);await conn.fetchval('SELECT setval($1::regclass,$2,$3)',name,value['last_value'],value['is_called'])
            finally:await conn.close()
        asyncio.run(restore());recovered=env|{'engine':engine,'sm':async_sessionmaker(engine,expire_on_commit=False)}
        assert cases.counts(recovered)==before_counts and cases.read(recovered,iv)==before
        assert asyncio.run(cases.service.record_action(engine,**(args|{'policy':None})))==ack
        monkeypatch.setattr(ar,'_domain_sessionmaker',lambda:recovered['sm'])
        monkeypatch.setattr(ar.settings,'kg_interview_policy',cases.policy().document())
        response=env['client'].get(_url(env['cases']['visa'],iv['applicant_id']))
        assert response.status_code==200 and 'interview-card' in response.text
        new=cases.correct(recovered,iv,{'contact_name':'Synthetic after recovery'},actor=cases.OWNER)
        assert new['revision']==before['revision']+1 and new['state']['handoff']==before['state']['handoff']
        report={'server':'PostgreSQL16 isolated loopback55971','migration':'e6_interview_handoff_0029',
            'method':'binary COPY; fresh Alembic schema; FK on; sequences restored',
            'native_pg_dump':'UNKNOWN: Windows App Control4551','backup_bytes':dump.stat().st_size,
            'backup_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'table_counts':before_counts,
            'interview_card_ack_history_equal':True,'exact_old_ack_retry_equal':True,
            'native_read_status':response.status_code,'new_manual_answer_after_recovery':True}
        artifact=Path('runs/interview-postgres-recovery.json');artifact.parent.mkdir(parents=True,exist_ok=True)
        artifact.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    finally:asyncio.run(engine.dispose());database(config,restored,drop=True)
