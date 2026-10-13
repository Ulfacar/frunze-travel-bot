"""Opt-in isolated PostgreSQL rehearsal; never discovers or accepts a live DSN.

FRUNZE_LOCAL_PG_CONNECTION names a private local JSON connection file for the
temporary localhost:55971 cluster. Each test clones an empty migrated template.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import threading
import time
import hashlib
import zipfile
from types import SimpleNamespace
import uuid

import pytest
from alembic import command
from alembic.config import Config
import asyncpg
from sqlalchemy import event, text
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from tests import test_admin_kg_entry as base
from tests import test_entry_processes as scenarios
from tests import test_entry_process_dependencies as dependencies
from app.domain.entry_storage import EntryStorageConflict
from app.domain.models import DomainBase, EntryProcessEvent, EntryQuarantinedFile


class _LocalConnection(dict):
    def __repr__(self): return repr({k:('***' if k=='password' else v) for k,v in self.items()})


def connection():
    filename=os.getenv('FRUNZE_LOCAL_PG_CONNECTION')
    if not filename: pytest.skip('isolated localhost PostgreSQL runtime not configured')
    config=_LocalConnection(json.loads(Path(filename).read_text(encoding='utf-8')))
    if config.keys()!={'host','port','user','password','database'} or config['host']!='127.0.0.1' or config['port']!=55971 or config['user']!='local_rehearsal' or config['database']!='postgres':
        raise RuntimeError('only the explicitly isolated localhost rehearsal cluster is permitted')
    return config


def db_url(config,name):
    return URL.create('postgresql+asyncpg',username=config['user'],password=config['password'],
        host=config['host'],port=config['port'],database=name)


def database(config,name,*,template=None,drop=False):
    if not re.fullmatch(r'frunze_e610_[a-f0-9]{24}',name): raise RuntimeError('unsafe rehearsal database name')
    if template is not None and not re.fullmatch(r'frunze_e610_[a-f0-9]{24}',template): raise RuntimeError('unsafe template name')
    async def run():
        conn=await asyncpg.connect(**config)
        try:
            assert await conn.fetchval('SELECT inet_server_addr()::text')=='127.0.0.1/32'
            if drop: await conn.execute('DROP DATABASE '+name+' WITH (FORCE)')
            else: await conn.execute('CREATE DATABASE '+name+(' TEMPLATE '+template if template else ''))
        finally: await conn.close()
    asyncio.run(run())


@pytest.fixture(scope='module')
def template():
    config=connection(); name='frunze_e610_'+uuid.uuid4().hex[:24]
    database(config,name)
    try:
        cfg=Config('alembic.ini')
        # Explicit -x has priority over any inherited ALEMBIC_DATABASE_URL.
        cfg.cmd_opts=SimpleNamespace(x=['dburl='+db_url(config,name).render_as_string(hide_password=False)])
        command.upgrade(cfg,'head')
        yield config,name
    finally: database(config,name,drop=True)


@pytest.fixture
def env(template,monkeypatch,tmp_path):
    config,original=template; name='frunze_e610_'+uuid.uuid4().hex[:24]
    database(config,name,template=original)
    engine=create_async_engine(db_url(config,name),poolclass=NullPool)
    sm=async_sessionmaker(engine,expire_on_commit=False)
    monkeypatch.setattr(base,'_make_domain_sm',lambda _:sm)
    fixture=base.env.__wrapped__(monkeypatch,tmp_path)
    try: yield next(fixture)
    finally:
        try: next(fixture,None)
        finally:
            asyncio.run(engine.dispose())
            database(config,name,drop=True)


def test_postgres_distinct_work_dependencies(env):
    dependencies.test_work_permit_resident_registration_have_distinct_scoped_decisions(env)


@pytest.mark.parametrize('route,procedure,product',[('registration','registration','REG'),('exit_visa','exit_visa','L')])
def test_postgres_regularization_branches(env,route,procedure,product):
    dependencies.test_regularization_uses_distinct_branch_application_and_never_turns_registration_into_l(env,route,procedure,product)


@pytest.mark.parametrize('invalidate',['quarantine','passport'])
def test_postgres_exit_visa_retained_verification(env,invalidate):
    dependencies.test_exit_visa_verification_remains_required_after_u07(env,invalidate)


@pytest.mark.parametrize('stream',['payments','contracts'])
def test_postgres_later_ledger_growth_recovery(env,stream):
    scenarios.test_later_money_stream_growth_preserves_history_retry_and_stop(env,stream)


@pytest.mark.parametrize('skip_middle',[False,True])
def test_postgres_rehashed_package_pin_rejected(env,skip_middle):
    scenarios.test_rehashed_package_observation_cannot_use_wrong_revision_consent(env,skip_middle)


@pytest.mark.parametrize('stream',['payments','contracts'])
def test_postgres_corrective_ledger_overflow_replay(env,stream):
    scenarios.test_corrective_transition_with_ledger_overflow_remains_replayable(env,stream)


@pytest.mark.parametrize('change',['withdraw','false','expired','source_scope'])
def test_postgres_consumed_manual_evidence_invalidation(env,change,monkeypatch):
    dependencies.test_consumed_official_manual_evidence_keeps_dependent_stages_blocked(env,change,monkeypatch)


def test_postgres_retry_and_competing_cas(env):
    scenarios.test_concurrent_same_request_and_competing_compare_and_swap(env)


@pytest.mark.parametrize('when',['before_commit','after_commit','before_insert'])
def test_postgres_commit_uncertainty(env,when):
    scenarios.test_atomic_pins_lost_ack_exact_retry(env,when)


def test_postgres_late_quarantine(env,monkeypatch):
    scenarios.test_late_old_timestamp_quarantine_preserves_history_but_blocks_current(env,monkeypatch)


def test_postgres_late_payment(env):
    scenarios.test_late_old_timestamp_money_preserves_old_balance_and_blocks_current(env)


def test_postgres_rework_and_post_issue(env):
    scenarios.test_visa_rework_requires_new_approval_and_new_submission_then_post_issue(env)


def test_postgres_profile_change_invalidates_rendered_evidence(env):
    scenarios.test_signed_evidence_does_not_survive_source_change(env)


@pytest.mark.parametrize('first',['stage','quarantine'])
def test_postgres_cross_case_quarantine_stage_lock_order(env,first):
    import hashlib
    from tests.test_quarantine_multipart import PDF
    from tests.test_entry_quarantine import arguments as upload_arguments
    from app.domain.entry_quarantine import record_upload
    other_env=env|{'cases':env['cases']|{'visa':env['cases']['other']}}
    other=scenarios.packages.setup(other_env,key='cross-case-upload')
    app,allowed=scenarios.visa_ready(env,fingerprint=hashlib.sha256(PDF).hexdigest())
    scenarios.money(env,amount='100000',currency='KGS',idempotency_key='full')
    for target in ('V09','V10','V12'): scenarios.transition(env,app,target,package_policy=allowed)
    edge=next(e for e in scenarios.read(env,app,package_policy=allowed)['readiness']['transitions'] if e['edge']['to']=='V14')
    args=scenarios.arguments(env,app,'transition',dict(edge_id=edge['edge_id'],evidence_digest=edge['evidence_digest'],on=scenarios.today()),
        request_key='race-stage',package_policy=allowed)
    uploads=upload_arguments(other_env,other)
    paused=threading.Event();resume=threading.Event()
    def pause_after_flush(session,context):
        if session.info.get('race_paused'): return
        matches=any((first=='stage' and isinstance(row,EntryProcessEvent) and row.request_key=='race-stage') or
            (first=='quarantine' and isinstance(row,EntryQuarantinedFile) and row.application_id==other['id']) for row in session.new)
        if matches:
            session.info['race_paused']=True;paused.set()
            if not resume.wait(20): raise RuntimeError('synthetic synchronization timeout')
    def stage(): return asyncio.run(scenarios.service.record_process_operation(env['engine'],**args))
    def quarantine(): return asyncio.run(record_upload(env['engine'],**uploads))
    async def waiting_lock():
        conn=await asyncpg.connect(**connection())
        try: return await conn.fetchval("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE locktype='advisory' AND NOT granted)")
        finally: await conn.close()
    event.listen(Session,'after_flush',pause_after_flush)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a=pool.submit(stage if first=='stage' else quarantine)
            try:
                assert paused.wait(20)
                b=pool.submit(quarantine if first=='stage' else stage)
                deadline=time.monotonic()+5
                while not asyncio.run(waiting_lock()) and time.monotonic()<deadline: time.sleep(.03)
                assert asyncio.run(waiting_lock()) and not b.done()
            finally: resume.set()
            a.result(timeout=30)
            if first=='quarantine':
                with pytest.raises(EntryStorageConflict,match='evidence_changed'): b.result(timeout=30)
            else: b.result(timeout=30)
    finally: resume.set();event.remove(Session,'after_flush',pause_after_flush)
    current=scenarios.read(env,app,package_policy=allowed)
    assert current['selected']['snapshot']['stage']==('V14' if first=='stage' else 'V12')
    assert not current['readiness']['ready'] if first=='stage' else not next(
        e for e in current['readiness']['transitions'] if e['edge']['to']=='V14')['ready']


def test_postgres_empty_cycle_schema_parity_and_populated_refusal(env):
    cfg=Config('alembic.ini')
    cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_document_quarantine_0026'); command.upgrade(cfg,'head')
    async def parity():
        async with env['engine'].connect() as conn:
            def compare(sync):
                ctx=MigrationContext.configure(sync,opts={'compare_type':True,
                    'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name in ('entry_process_events','entry_process_pins')})
                return compare_metadata(ctx,DomainBase.metadata)
            assert await conn.run_sync(compare)==[]
            assert await conn.scalar(text('SELECT count(*) FROM service_cases'))==3
    asyncio.run(parity())
    app=scenarios.setup(env)
    with pytest.raises(RuntimeError,match='preserve populated'): command.downgrade(cfg,'e6_document_quarantine_0026')
    assert scenarios.read(env,app)['current_revision']==1


def test_postgres_copy_backup_restore_preserves_journals_binary_and_native_read(env,monkeypatch):
    from tests.test_entry_quarantine import upload
    from app.domain.entry_quarantine import verify_file
    from tests.test_admin_kg_entry import ADMIN
    import app.admin.router as ar
    config=connection(); runtime=Path(os.environ['FRUNZE_LOCAL_PG_CONNECTION']).parent
    output=runtime/'e610-recovery';output.mkdir(exist_ok=True)
    original=env['engine'].url.database
    app=scenarios.setup(env);scenarios.attest(env,app,'conversation_started');scenarios.transition(env,app,'V02')
    other=scenarios.packages.setup(env,key='upload'); uploaded=upload(env,other)
    scenarios.money(env,amount='10000',currency='KGS',idempotency_key='synthetic-payment')
    before=scenarios.read(env,app)
    async def counts(engine):
        async with engine.connect() as conn:
            return {table:await conn.scalar(text('SELECT count(*) FROM '+table)) for table in sorted(DomainBase.metadata.tables)}
    before_counts=asyncio.run(counts(env['engine']))
    restored='frunze_e610_'+uuid.uuid4().hex[:24]; dump=output/(restored+'.zip')
    # Windows App Control blocks the downloaded pg_dump executable. This is an
    # explicit synthetic data-recovery rehearsal via the PostgreSQL COPY API,
    # with schema reconstructed from the same migrations, not a pg_dump claim.
    def identifier(value):
        assert re.fullmatch('[a-z_][a-z0-9_]*',value)
        return '"'+value+'"'
    async def backup():
        conn=await asyncpg.connect(**(config|{'database':original}))
        try:
            async with conn.transaction(isolation='repeatable_read',readonly=True):
                tables=[r['tablename'] for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version' ORDER BY tablename")]
                manifest={'revision':await conn.fetchval('SELECT version_num FROM alembic_version'),'tables':{},'sequences':{}}
                with zipfile.ZipFile(dump,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                    for table in tables:
                        chunks=[]
                        async def sink(data): chunks.append(data)
                        await conn.copy_from_table(table,output=sink,format='binary',schema_name='public')
                        data=b''.join(chunks);archive.writestr(table+'.bin',data)
                        manifest['tables'][table]={'count':await conn.fetchval('SELECT count(*) FROM '+identifier(table)),
                            'sha256':hashlib.sha256(data).hexdigest()}
                    edges=await conn.fetch("SELECT c.relname AS child,p.relname AS parent FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid JOIN pg_class p ON p.oid=f.confrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE f.contype='f' AND n.nspname='public'")
                    pending={t for t,v in manifest['tables'].items() if v['count']}; order=[]
                    while pending:
                        ready=sorted(t for t in pending if not any(e['child']==t and e['parent'] in pending and e['parent']!=t for e in edges))
                        assert ready,'nonempty cyclic recovery dependencies require a separate adapter'
                        order.extend(ready);pending.difference_update(ready)
                    manifest['order']=order
                    for row in await conn.fetch("SELECT sequencename FROM pg_sequences WHERE schemaname='public'"):
                        name=row['sequencename']
                        value=await conn.fetchrow('SELECT last_value,is_called FROM '+identifier(name))
                        manifest['sequences'][name]=dict(value)
                    archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
        finally: await conn.close()
    asyncio.run(backup())
    database(config,restored)
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
                        for table in manifest['tables']:
                            assert await conn.fetchval('SELECT count(*) FROM '+identifier(table))==0
                        for table in manifest['order']:
                            data=archive.read(table+'.bin');assert hashlib.sha256(data).hexdigest()==manifest['tables'][table]['sha256']
                            await conn.copy_to_table(table,source=memoryview(data),format='binary',schema_name='public')
                        for table,value in manifest['tables'].items():
                            assert await conn.fetchval('SELECT count(*) FROM '+identifier(table))==value['count']
                        for name,value in manifest['sequences'].items():
                            identifier(name)
                            await conn.fetchval('SELECT setval($1::regclass,$2,$3)',name,value['last_value'],value['is_called'])
            finally: await conn.close()
        asyncio.run(restore())
        recovered=env|{'engine':engine,'sm':async_sessionmaker(engine,expire_on_commit=False)}
        assert asyncio.run(counts(engine))==before_counts
        assert scenarios.read(recovered,app)==before
        checked=asyncio.run(verify_file(engine,actor=ADMIN,case_id=env['cases']['visa'],application_id=other['id'],file_id=uploaded['id']))
        assert checked==uploaded
        monkeypatch.setattr(ar,'_domain_sessionmaker',lambda:recovered['sm'])
        monkeypatch.setattr(ar.settings,'kg_process_execution_policy',scenarios.policy().document())
        url=f"/admin/case/{env['cases']['visa']}/kg-entry/applications/{app['id']}/process-journal"
        response=env['client'].get(url)
        assert response.status_code==200 and 'V02' in response.text
        resumed=scenarios.attest(recovered,app,'conversation_started',False)
        assert resumed['revision']==before['current_revision']+1 and resumed['id']>before['selected']['id']
        report={'server':'PostgreSQL16 local loopback55971','migration':'e6_process_journal_0027',
            'method':'all public table data via binary COPY; schema rebuilt by Alembic; FK checks enabled; sequences restored',
            'native_pg_dump':'UNKNOWN: Windows App Control 4551; no security setting changed',
            'backup_bytes':dump.stat().st_size,'backup_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),
            'table_counts':before_counts,'process_revision':before['current_revision'],
            'quarantine_sha256_verified':True,'native_read_status':response.status_code,'restored_into_fresh_database':True,
            'write_after_recovery':True}
        Path('runs/process-postgres-recovery.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    finally:
        asyncio.run(engine.dispose());database(config,restored,drop=True)
