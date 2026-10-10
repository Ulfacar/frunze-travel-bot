"""Opt-in loopback-only PostgreSQL admission races, schema and recovery."""
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
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker,AsyncSession
from sqlalchemy.orm import Session
from sqlalchemy.pool import NullPool

from tests.test_entry_process_postgres import connection,db_url,database,template,env
from tests.test_entry_channel_stops import admins,activation
from tests import test_entry_channel_stops as cases
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageUnavailable
from app.domain.models import DomainBase,EntryChannelStop


def waiting_lock(env):
    async def run():
        until=time.monotonic()+1.5
        async with env['engine'].connect() as conn:
            while time.monotonic()<until:
                waiting=await conn.scalar(text("SELECT count(*) FROM pg_locks WHERE locktype='advisory' AND NOT granted AND database=(SELECT oid FROM pg_database WHERE datname=current_database())"))
                if waiting:return True
                await asyncio.sleep(.02)
        return False
    assert asyncio.run(run()),'competing connection never demonstrably waited on the advisory lock'


def test_atomic_ack_and_old_retry(env):cases.test_atomic_handoff_stop_ack_policy_removal_and_exact_retry(env)


@pytest.mark.parametrize('phase',['paused','pending','acked'])
def test_card_binding_permanence(env,phase):cases.test_existing_card_or_paused_and_no_resumption(env,phase)


@pytest.mark.parametrize('failure',['handoff','binding'])
def test_atomic_failure(env,failure):cases.test_injected_write_failure_rolls_back_handoff_and_stop(env,failure)


@pytest.mark.parametrize('column,value',[('transport_key','f'*64),('card_hash','f'*64),('snapshot_hash','f'*64)])
def test_negative_lookup_corruption(env,column,value):cases.test_corrupt_registry_blocks_negative_lookup_too(env,column,value)


@pytest.mark.parametrize('kind',['exception','timeout','cancel'])
def test_callback_once_on_failure(env,monkeypatch,kind):cases.test_provider_callback_at_most_once_on_failure(env,monkeypatch,kind)


def test_mutable_dialog_does_not_move_stop(env):cases.test_mutable_dialog_cannot_move_permanent_stop(env)


@pytest.mark.parametrize('kind',['boolean_pin','card_fact'])
def test_rehashed_card_semantics(env,kind):cases.test_rehashed_invalid_pin_or_card_semantics_fails_closed(env,kind)


def test_expired_authority_does_not_resume(env,monkeypatch):cases.test_expired_policy_cannot_resume_stop_or_prevent_exact_receipt_retry(env,monkeypatch)


@pytest.mark.parametrize('anchor',['case','dialog'])
@pytest.mark.parametrize('boundary',['expiry','day'])
def test_authority_clock_after_row_wait(env,monkeypatch,anchor,boundary):
    cases.test_policy_and_preview_clock_are_sampled_after_all_row_locks(env,monkeypatch,anchor,boundary)


def test_initially_absent_route_send_first_holds_admission_until_callback_ends(env):
    iv=cases.start(env);did=cases.dialog(env);parameters=cases.args(env,iv,did)
    admitted=threading.Event();release=threading.Event();binding_started=threading.Event();calls=[]
    async def callback():
        calls.append('provider');admitted.set()
        assert await asyncio.to_thread(release.wait,5)
        return 'SYN'
    def sending():return asyncio.run(cases.service.guarded_send(env['engine'],cases.ROUTE,callback))
    def binding():binding_started.set();return asyncio.run(cases.service.bind_stop(env['engine'],**parameters))
    with ThreadPoolExecutor(max_workers=2) as pool:
        sent=pool.submit(sending);assert admitted.wait(5)
        saved=pool.submit(binding);assert binding_started.wait(5)
        waiting_lock(env)
        assert not saved.done()
        release.set();assert sent.result(timeout=8).invoked;assert saved.result(timeout=8)['permanent']
    assert calls==['provider'] and cases.send(env)[1]==[]


def test_initially_absent_route_bind_first_blocks_sender_until_commit_then_suppresses(env):
    iv=cases.start(env);did=cases.dialog(env);parameters=cases.args(env,iv,did)
    inserted=threading.Event();release=threading.Event();attempted=threading.Event();calls=[]
    def hold(*args):inserted.set();assert release.wait(5)
    async def callback():calls.append(True)
    def sending():attempted.set();return asyncio.run(cases.service.guarded_send(env['engine'],cases.ROUTE,callback))
    event.listen(EntryChannelStop,'after_insert',hold)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            saved=pool.submit(lambda:asyncio.run(cases.service.bind_stop(env['engine'],**parameters)))
            assert inserted.wait(5);sent=pool.submit(sending);assert attempted.wait(5);assert not sent.done()
            waiting_lock(env)
            release.set();assert saved.result(timeout=8)['permanent'];assert not sent.result(timeout=8).invoked
    finally:release.set();event.remove(EntryChannelStop,'after_insert',hold)
    assert calls==[]


def test_global_capacity_serializes_distinct_cases_and_routes(env,monkeypatch):
    first=cases.start(env);did=cases.dialog(env);one=cases.args(env,first,did)
    other=env|{'cases':env['cases']|{'visa':env['cases']['other']},'contacts':env['contacts']|{'visa':env['contacts']['other']}}
    second=cases.start(other);second_did=cases.dialog(other,channel_key='996700000002');two=cases.args(other,second,second_did)
    monkeypatch.setattr(cases.service,'MAX_STOPS',1)
    barrier=threading.Barrier(2)
    def save(params):
        barrier.wait(timeout=5)
        try:return asyncio.run(cases.service.bind_stop(env['engine'],**params))
        except EntryStorageInvalid as exc:return str(exc)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(save,[one,two]))
    assert sum(isinstance(r,dict) for r in results)==1 and 'channel_stop_registry_limit' in results
    assert cases.counts(env)['entry_channel_stops']==1


def test_provider_once_when_transaction_cleanup_ack_fails(env,monkeypatch):
    original=AsyncSession.rollback;calls=[];cleanup=[]
    async def rollback(session):
        await original(session);cleanup.append(True);raise RuntimeError('synthetic cleanup acknowledgement')
    async def callback():calls.append(True);return None
    monkeypatch.setattr(AsyncSession,'rollback',rollback)
    with pytest.raises(RuntimeError):asyncio.run(cases.service.guarded_send(env['engine'],cases.ROUTE,callback))
    assert calls==[True] and cleanup==[True]
    monkeypatch.setattr(AsyncSession,'rollback',original)
    assert cases.send(env)[0].invoked


def test_admission_lock_timeout_never_invokes_provider(env,monkeypatch):
    from sqlalchemy.exc import DBAPIError
    monkeypatch.setattr(cases.service,'LOCK_TIMEOUT_MS',100)
    held=threading.Event();release=threading.Event();calls=[]
    async def hold():
        async with env['sm']() as session:
            await cases.service._lock(session,cases.ROUTE,writer=True);held.set()
            await asyncio.to_thread(release.wait,5);await session.rollback()
    async def callback():calls.append(True)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(lambda:asyncio.run(hold()));assert held.wait(5)
        try:
            with pytest.raises(DBAPIError):asyncio.run(cases.service.guarded_send(env['engine'],cases.ROUTE,callback))
        finally:release.set();future.result(timeout=8)
    assert calls==[] and cases.send(env)[0].invoked


def test_lock_key_stable_in_fresh_process():
    import subprocess,sys
    result=subprocess.check_output([sys.executable,'-c',"from app.domain.entry_channel_stops import _lock_key; print(_lock_key('synthetic-route'))"],text=True)
    assert int(result.strip())==cases.service._lock_key('synthetic-route')


@pytest.mark.parametrize('when',['before_commit','after_commit'])
def test_commit_outcome_retry_exact_binding(env,when):
    iv=cases.start(env);did=cases.dialog(env);parameters=cases.args(env,iv,did);seen=[]
    def fail(session):
        if not seen:seen.append(True);raise RuntimeError('synthetic commit acknowledgement')
    event.listen(Session,when,fail)
    try:
        with pytest.raises(EntryStorageUnavailable):asyncio.run(cases.service.bind_stop(env['engine'],**parameters))
    finally:event.remove(Session,when,fail)
    saved=asyncio.run(cases.service.bind_stop(env['engine'],**parameters))
    assert saved['permanent'] and cases.counts(env)['entry_channel_stops']==1 and cases.send(env)[1]==[]


def test_empty_migration_cycle_metadata_and_populated_refusal(env):
    cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_quote_revisions_0030');command.upgrade(cfg,'head')
    async def compare():
        async with env['engine'].connect() as conn:
            def check(sync):return compare_metadata(MigrationContext.configure(sync,opts={'compare_type':True,
                'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name=='entry_channel_stops'}),DomainBase.metadata)
            assert await conn.run_sync(check)==[]
    asyncio.run(compare());iv=cases.start(env);did=cases.dialog(env);cases.bind(env,iv,did)
    async def invalid():
        for col,value in [('case_id',env['cases']['other']),('applicant_id',99999),('handoff_event_id',99999),('contact_id',99999),('dialog_id',99999)]:
            async with env['engine'].begin() as conn:
                with pytest.raises(IntegrityError):await conn.execute(text(f'UPDATE entry_channel_stops SET {col}=:v'),{'v':value})
    asyncio.run(invalid())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(cfg,'e6_quote_revisions_0030')
    assert cases.send(env)[1]==[]


def test_copy_recovery_preserves_permanent_stop_old_retry_and_new_binding(env,monkeypatch):
    import app.admin.router as ar
    from app.admin.kg_channel_stops import _url
    config=connection();output=Path(os.environ['FRUNZE_LOCAL_PG_CONNECTION']).parent/'e614-recovery';output.mkdir(exist_ok=True)
    iv=cases.start(env);did=cases.dialog(env);parameters=cases.args(env,iv,did)
    first=asyncio.run(cases.service.bind_stop(env['engine'],**parameters));cases.action(env,iv,'ack');before=cases.counts(env)
    restored='frunze_e610_'+uuid.uuid4().hex[:24];dump=output/(restored+'.zip')
    def ident(value):
        assert re.fullmatch('[a-z_][a-z0-9_]*',value);return '"'+value+'"'
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
                        manifest['tables'][table]={'count':await conn.fetchval('SELECT count(*) FROM '+ident(table)),'sha256':hashlib.sha256(data).hexdigest()}
                    edges=await conn.fetch("SELECT c.relname child,p.relname parent FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid JOIN pg_class p ON p.oid=f.confrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE f.contype='f' AND n.nspname='public'")
                    pending={t for t,v in manifest['tables'].items() if v['count']};order=[]
                    while pending:
                        ready=sorted(t for t in pending if not any(e['child']==t and e['parent'] in pending and e['parent']!=t for e in edges))
                        assert ready;order.extend(ready);pending.difference_update(ready)
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
        assert cases.counts(recovered)==before and cases.send(recovered)[1]==[]
        assert asyncio.run(cases.service.bind_stop(engine,**(parameters|{'policy':None})))==first
        monkeypatch.setattr(ar,'_domain_sessionmaker',lambda:recovered['sm'])
        response=env['client'].get(_url(env['cases']['visa'],iv['applicant_id'],iv['interview_id']))
        assert response.status_code==200 and 'stop-current' in response.text
        other=cases.start(recovered,cases.person(recovered,key='SECOND'),request_key='SECOND')
        other_did=cases.dialog(recovered,channel_key='996700000002');second=cases.bind(recovered,other,other_did,request_key='SECOND')
        assert second['id']>first['id'] and cases.send(recovered,cases.rules.route(cases.BASE,cases.PROFILE,'996700000002'))[1]==[]
        report={'server':'PostgreSQL16 isolated loopback55971','migration':'e6_channel_stops_0031',
            'method':'binary COPY; fresh Alembic schema; FK on; sequences restored','native_pg_dump':'UNKNOWN: Windows App Control4551',
            'backup_bytes':dump.stat().st_size,'backup_sha256':hashlib.sha256(dump.read_bytes()).hexdigest(),'table_counts':before,
            'old_stop_survives_ack_and_recovery':True,'exact_retry_after_policy_removal':True,'new_binding_after_recovery':True,'native_read_status':response.status_code}
        artifact=Path('runs/channel-postgres-recovery.json');artifact.parent.mkdir(parents=True,exist_ok=True)
        artifact.write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    finally:asyncio.run(engine.dispose());database(config,restored,drop=True)
