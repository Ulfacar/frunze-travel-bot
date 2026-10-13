"""Opt-in local PostgreSQL notification drafts, races and fresh-schema COPY recovery."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from types import SimpleNamespace
import uuid
import zipfile

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import event,text
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.pool import NullPool

from tests.test_entry_process_postgres import connection,db_url,database,template,env
from tests.test_entry_notifications import admins
from tests import test_entry_notifications as cases
from app.domain.entry_storage import EntryStorageConflict
from app.domain.models import DomainBase,EntryApplicationEvent


def test_deduplicated_concurrent_saves(env):cases.test_concurrent_identical_and_competing_confirmations(env)
def test_no_outgoing_or_other_domain_writes(env):cases.test_readonly_preview_one_saved_row_and_no_outgoing_side_effects(env)
def test_retry_after_policy_removed(env):cases.test_old_retry_survives_policy_removal_and_new_different_template_is_not_supersession(env)
def test_application_growth_and_stale_preview(env):cases.test_application_growth_preserves_old_receipt_but_rejects_stale_preview(env)
def test_old_renderer(env,monkeypatch):cases.test_old_renderer_replays_after_current_source_unavailable(env,monkeypatch)
def test_scope(env):cases.test_scope_and_person_substitution_cannot_reuse_confirmation(env)
def test_capacity_retry(env,monkeypatch):cases.test_capacity_preserves_read_and_exact_retry_but_refuses_new_save(env,monkeypatch)
def test_unicode_encoded_capacity(env,monkeypatch):cases.test_unicode_json_expansion_never_makes_a_successful_append_unreadable(env,monkeypatch)
def test_insert_rollback(env):cases.test_insert_failure_rolls_back_all_draft_data(env)

@pytest.mark.parametrize('status,template_id',[('approved','KG.TPL.A07'),('refused','KG.TPL.A09')])
def test_terminal_drafts(env,status,template_id):cases.test_terminal_outcome_allows_internal_draft_without_changing_outcome(env,status,template_id)

@pytest.mark.parametrize('kind',['text','send','source','unresolved','bool_pin','bool_revision','renderer'])
def test_semantic_tamper(env,kind):cases.test_fully_rehashed_corruption_is_rejected_by_semantic_replay(env,kind)

@pytest.mark.parametrize('at',['before_commit','after_commit'])
def test_commit_ambiguity(env,at):cases.test_commit_ambiguity_preserves_exact_retry(env,at)

@pytest.mark.parametrize('lock',['service_cases','entry_applications'])
@pytest.mark.parametrize('expiry',[True,False])
def test_post_lock_authority_day(env,monkeypatch,lock,expiry):cases.test_policy_day_is_checked_after_row_lock(env,monkeypatch,lock,expiry)

@pytest.mark.parametrize('limit',['MAX_EVENT_BYTES','MAX_HISTORY_BYTES'])
def test_byte_limits(env,monkeypatch,limit):cases.test_size_limit_rolls_back_and_refuses_oversize_stored_read(env,monkeypatch,limit)


def test_application_commit_during_real_lock_wait_invalidates_preview(env):
    app=cases.subject(env);args=cases.args(env,app)
    inserted=threading.Event();release=threading.Event()
    def pause(session,context):
        if any(isinstance(row,EntryApplicationEvent) for row in session.new):
            inserted.set();assert release.wait(10)
    async def waiting():
        async with env['engine'].connect() as conn:
            return bool(await conn.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock' AND pid<>pg_backend_pid())")))
    event.listen(Session,'after_flush',pause)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            advancing=pool.submit(cases.apps.record,env,app)
            assert inserted.wait(10)
            saving=pool.submit(lambda:asyncio.run(cases.service.save_draft(env['engine'],**args)))
            try:
                until=time.monotonic()+5
                observed=False
                while time.monotonic()<until:
                    if asyncio.run(waiting()):observed=True;break
                    time.sleep(.025)
                assert observed and not saving.done(),'draft save did not demonstrably wait on application transaction'
            finally:release.set()
            advancing.result(timeout=10)
            with pytest.raises(EntryStorageConflict,match='preview_changed'):saving.result(timeout=10)
    finally:release.set();event.remove(Session,'after_flush',pause)
    assert cases.read(env,app)['revision']==0
    assert cases.save(env,app)['receipt']['source_pin']['event_status']=='submitted'

def test_empty_cycle_constraints_and_model_parity(env):
    cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_channel_stops_0031');command.upgrade(cfg,'head')
    async def parity():
        async with env['engine'].connect() as conn:
            def compare(sync):
                ctx=MigrationContext.configure(sync,opts={'compare_type':True,'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name=='entry_notification_drafts'})
                return compare_metadata(ctx,DomainBase.metadata)
            assert await conn.run_sync(compare)==[]
    asyncio.run(parity());app=cases.subject(env);cases.save(env,app);cases.save(env,app)
    async def invalid():
        for column,value in [('case_id',env['cases']['other']),('applicant_id',99999),('procedure','registration'),
            ('revision',129),('previous_id',99999),('application_id',99999)]:
            async with env['engine'].begin() as conn:
                with pytest.raises(IntegrityError):await conn.execute(text(f'UPDATE entry_notification_drafts SET {column}=:value'),{'value':value})
    asyncio.run(invalid())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(cfg,'e6_channel_stops_0031')
    assert cases.read(env,app)['revision']==2


def test_binary_copy_recovery_old_draft_retry_native_read_and_new_revision(env,monkeypatch):
    import app.admin.router as ar
    from app.admin.kg_notifications import _url
    config=connection();runtime=Path(os.environ['FRUNZE_LOCAL_PG_CONNECTION']).parent
    output=runtime/'e616-recovery';output.mkdir(exist_ok=True)
    app=cases.subject(env);args=cases.args(env,app);first=asyncio.run(cases.service.save_draft(env['engine'],**args))
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
        retry=asyncio.run(cases.service.save_draft(engine,**(args|{'policy':None})))
        assert retry['receipt']==first['receipt'] and not retry['current']['context_current']
        monkeypatch.setattr(ar,'_domain_sessionmaker',lambda:recovered['sm']);monkeypatch.setattr(ar.settings,'kg_notification_storage_policy',cases.policy().document())
        response=env['client'].get(_url(env['cases']['visa'],app['id']))
        assert response.status_code==200 and 'notification-saved' in response.text
        new=cases.save(recovered,app);assert new['receipt']['revision']==3
        assert cases.read(recovered,app)['history'][-1]['receipt']==first['receipt']
        report={'server':'PostgreSQL16 isolated loopback55971','migration':'e6_notification_drafts_0032',
            'method':'binary COPY; fresh Alembic schema; FK on; sequences restored','native_pg_dump':'UNKNOWN: Windows App Control4551',
            'backup_bytes':dump.stat().st_size,'backup_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'table_counts':before_counts,
            'draft_history_equal':True,'exact_old_receipt_retry_equal':True,'retry_current_authority_blocked':True,
            'native_read_status':response.status_code,'new_draft_revision_after_recovery':True}
        artifact=Path('runs/notification-postgres-recovery.json');artifact.parent.mkdir(parents=True,exist_ok=True)
        artifact.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    finally:asyncio.run(engine.dispose());database(config,restored,drop=True)
