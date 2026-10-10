"""Opt-in local PostgreSQL quote persistence, races and fresh-schema COPY recovery."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
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
from tests.test_entry_quotes import admins
from tests import test_entry_quotes as cases
from app.domain.entry_storage import EntryStorageConflict
from app.domain.models import DomainBase


def test_concurrent_identical_and_distinct_saves(env):cases.test_concurrent_identical_and_competing_saves_preserve_one_revision(env)
def test_unknown_total_and_no_ledger_side_effects(env):cases.test_preview_is_readonly_saved_unknown_blocks_total_and_other_domain_is_unchanged(env)
def test_old_retry_after_new_policy_and_revision(env):cases.test_old_exact_retry_survives_policy_removal_replacement_and_later_revision(env)
def test_application_growth_keeps_history_but_marks_current_stale(env):cases.test_observed_application_head_survives_growth_but_current_quote_becomes_stale(env)
def test_preview_binding(env):cases.test_policy_and_preview_parameters_cannot_change_between_preview_and_save(env)
def test_current_identity_before_db(env,monkeypatch):cases.test_current_identity_revoked_before_any_database_access(env,monkeypatch,'save')
def test_midnight_and_backwards_clock(env,monkeypatch):cases.test_midnight_expiry_and_backwards_clock_cannot_persist_invalid_history(env,monkeypatch)
def test_retained_calculator(env,monkeypatch):cases.test_retained_calculator_history_retry_and_new_active_version(env,monkeypatch)


@pytest.mark.parametrize('kind',['source_rewinds','untyped_revision','untyped_pin','untyped_result','null_version'])
def test_impossible_rehashed_history(env,kind):cases.test_impossible_fully_rehashed_history_fails_closed(env,kind)


@pytest.mark.parametrize('at',['before_commit','after_commit'])
def test_commit_fault_exact_retry(env,at):cases.test_commit_uncertainty_preserves_original_receipt(env,at)


@pytest.mark.parametrize('kind',['total','omitted_line','source','reducer'])
def test_semantic_tamper(env,kind):cases.test_fully_rehashed_semantic_tamper_is_rejected(env,kind)


@pytest.mark.parametrize('quote_first',[True,False])
def test_application_writer_race_with_quote_preview(env,quote_first):
    app=cases.subject(env);args=cases.args(env,app)
    def quote():
        try:return asyncio.run(cases.service.save_quote(env['engine'],**args))
        except EntryStorageConflict:return 'conflict'
    def advance():return cases.apps.record(env,app)
    with ThreadPoolExecutor(max_workers=2) as pool:
        calls=[quote,advance] if quote_first else [advance,quote]
        futures=[pool.submit(fn) for fn in calls];results=[future.result() for future in futures]
    current=cases.read(env,app)
    if current['revision']:
        assert current['revision']==1 and current['history'][0]['receipt']['source_pin']['event_revision']==1
        assert 'quote_application_changed' in current['history'][0]['current']['reasons']
    else:assert 'conflict' in results
    assert cases.apps.read(env,app)['current']['revision']==2


def test_empty_cycle_constraints_and_model_parity(env):
    cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_interview_handoff_0029');command.upgrade(cfg,'head')
    async def parity():
        async with env['engine'].connect() as conn:
            def compare(sync):
                ctx=MigrationContext.configure(sync,opts={'compare_type':True,'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name=='entry_quote_revisions'})
                return compare_metadata(ctx,DomainBase.metadata)
            assert await conn.run_sync(compare)==[]
    asyncio.run(parity());app=cases.subject(env);cases.save(env,app);cases.save(env,app)
    async def invalid():
        for column,value in [('case_id',env['cases']['other']),('applicant_id',99999),('procedure','registration'),
            ('revision',129),('previous_id',99999),('application_id',99999)]:
            async with env['engine'].begin() as conn:
                with pytest.raises(IntegrityError):await conn.execute(text(f'UPDATE entry_quote_revisions SET {column}=:value'),{'value':value})
    asyncio.run(invalid())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(cfg,'e6_interview_handoff_0029')
    assert cases.read(env,app)['revision']==2


def test_binary_copy_recovery_old_quote_retry_native_read_and_new_revision(env,monkeypatch):
    import app.admin.router as ar
    from app.admin.kg_quotes import _url
    config=connection();runtime=Path(os.environ['FRUNZE_LOCAL_PG_CONNECTION']).parent
    output=runtime/'e613-recovery';output.mkdir(exist_ok=True)
    app=cases.subject(env);args=cases.args(env,app);first=asyncio.run(cases.service.save_quote(env['engine'],**args))
    cases.save(env,app);before=cases.read(env,app);before_counts=cases.counts(env)
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
        assert cases.counts(recovered)==before_counts and cases.read(recovered,app)==before
        retry=asyncio.run(cases.service.save_quote(engine,**(args|{'policy':None})))
        assert retry['receipt']==first['receipt'] and not retry['current']['usable']
        monkeypatch.setattr(ar,'_domain_sessionmaker',lambda:recovered['sm']);monkeypatch.setattr(ar.settings,'kg_quote_policy',cases.policy().document())
        response=env['client'].get(_url(env['cases']['visa'],app['id']))
        assert response.status_code==200 and 'quote-saved' in response.text
        new=cases.save(recovered,app);assert new['receipt']['revision']==3
        assert cases.read(recovered,app)['history'][-1]['receipt']==first['receipt']
        report={'server':'PostgreSQL16 isolated loopback55971','migration':'e6_quote_revisions_0030',
            'method':'binary COPY; fresh Alembic schema; FK on; sequences restored','native_pg_dump':'UNKNOWN: Windows App Control4551',
            'backup_bytes':dump.stat().st_size,'backup_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'table_counts':before_counts,
            'quote_history_equal':True,'exact_old_receipt_retry_equal':True,'retry_current_authority_blocked':True,
            'native_read_status':response.status_code,'new_quote_revision_after_recovery':True}
        artifact=Path('runs/quote-postgres-recovery.json');artifact.parent.mkdir(parents=True,exist_ok=True)
        artifact.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    finally:asyncio.run(engine.dispose());database(config,restored,drop=True)
