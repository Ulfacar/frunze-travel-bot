"""Opt-in fresh guarded local PostgreSQL DBs; no live credentials or data."""
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
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from tests.test_entry_process_postgres import connection,db_url,database,template,env
from tests import test_entry_portal as cases
from app.domain.models import DomainBase


def test_postgres_concurrent_identical_confirmation(env):cases.test_concurrent_identical_confirmation_keeps_one_fact(env)


@pytest.mark.parametrize('at',['before_commit','after_commit'])
def test_postgres_commit_fault(env,at):cases.test_commit_fault_exact_retry_recovers_one_fact(env,at)


@pytest.mark.parametrize('at',['application','action'])
def test_postgres_two_halves_atomic(env,at):cases.test_fault_after_either_half_flush_rolls_back_entire_confirmation(env,at)


def test_postgres_enabled_task_hook_atomic(env,monkeypatch):cases.test_enabled_deadline_task_hook_and_action_are_one_transaction(env,monkeypatch)


def test_postgres_out_of_order_cycle(env):cases.test_old_cycle_late_correction_and_same_day_resubmit_need_new_verified_binding(env)


def test_postgres_manual_evidence_and_rename_dedup(env):cases.test_distinct_manual_source_evidence_can_confirm_new_same_day_cycle(env)


def test_postgres_same_content_dedup(env):cases.test_exact_content_new_transport_cannot_apply_twice_after_a_new_cycle(env)


def test_postgres_scope_transport_and_old_retry(env):cases.test_transport_dedup_conflict_and_exact_retry_after_policy_loss(env)


def test_postgres_empty_cycle_schema_constraints_and_populated_refusal(env):
    cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_process_journal_0027');command.upgrade(cfg,'head')
    async def parity():
        async with env['engine'].connect() as conn:
            def compare(sync):
                ctx=MigrationContext.configure(sync,opts={'compare_type':True,
                    'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name in ('entry_portal_receipts','entry_portal_actions')})
                return compare_metadata(ctx,DomainBase.metadata)
            assert await conn.run_sync(compare)==[]
    asyncio.run(parity())
    cases.setup(env);receipt=cases.receive(env);cases.action(env,receipt,'correlate');cases.action(env,receipt,'confirm')
    async def invalid():
        for table,column,value in [('entry_portal_actions','case_id',env['cases']['other']),('entry_portal_actions','head_id',99999),
            ('entry_portal_actions','cycle_id',99999),('entry_portal_actions','applied_event_id',99999),
            ('entry_portal_actions','revision',65),('entry_portal_receipts','raw_bytes',16385)]:
            async with env['engine'].begin() as conn:
                with pytest.raises(IntegrityError):await conn.execute(text(f'UPDATE {table} SET {column}=:value'),{'value':value})
    asyncio.run(invalid())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(cfg,'e6_process_journal_0027')
    assert cases.read(env,receipt)['state']['disposition']=='applied'


def test_postgres_portal_task_copy_recovery_retry_and_new_write(env,monkeypatch):
    """Restore populated receipts/actions/application/task history with FK on."""
    import app.admin.router as ar
    from tests import test_entry_deadlines as deadlines
    from tests.test_entry_deadline_sources import selection
    from tests.test_entry_deadline_tasks import sync,read as task_read
    config=connection();runtime=Path(os.environ['FRUNZE_LOCAL_PG_CONNECTION']).parent
    output=runtime/'e611-recovery';output.mkdir(exist_ok=True)
    app=cases.setup(env);deadlines.write(env,app,'recalculate',selection(env))
    deadlines.write(env,app,'manual',deadlines.manual()|{'evidence_on':'2026-10-10'});sync(env,app,enable=True)
    receipt=cases.receive(env,text=cases.message('correction'));cases.action(env,receipt,'correlate')
    args=cases.action_args(env,receipt,'confirm')
    applied=asyncio.run(cases.service.record_action(env['engine'],**args))
    before=cases.read(env,receipt);before_tasks=task_read(env,app);before_counts=cases.counts(env)
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
    asyncio.run(backup());database(config,restored)
    engine=create_async_engine(db_url(config,restored),poolclass=NullPool)
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
        assert cases.counts(recovered)==before_counts and cases.read(recovered,receipt)==before
        assert task_read(recovered,app)==before_tasks
        assert asyncio.run(cases.service.record_action(engine,**(args|{'policy':None})))==applied
        monkeypatch.setattr(ar,'_domain_sessionmaker',lambda:recovered['sm'])
        monkeypatch.setattr(ar.settings,'kg_portal_observation_policy',cases.policy().document())
        response=env['client'].get(env['url']+'/portal?receipt_id='+str(receipt['id']))
        assert response.status_code==200 and 'Подтверждение записано в заявку' in response.text
        fresh=cases.receive(recovered,transport_id='after-recovery',request_key='after-recovery',text=cases.message('payment'))
        assert fresh['id']>receipt['id'];cases.action(recovered,fresh,'correlate')
        checked=cases.action(recovered,fresh,'confirm');assert checked['state']['disposition']=='checked'
        report={'server':'PostgreSQL16 isolated loopback55971','migration':'e6_portal_observations_0028',
            'method':'binary COPY; fresh Alembic schema; FK on; sequences restored',
            'native_pg_dump':'UNKNOWN: Windows App Control4551', 'backup_bytes':dump.stat().st_size,
            'backup_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'table_counts':before_counts,
            'receipt_action_history_equal':True,'deadline_task_history_equal':True,'exact_retry_equal':True,
            'native_read_status':response.status_code,'new_receipt_and_action_after_recovery':True}
        Path('runs/portal-postgres-recovery.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    finally:asyncio.run(engine.dispose());database(config,restored,drop=True)
