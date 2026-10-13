"""Real isolated PostgreSQL: claim/stop concurrency and immutable recovery."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from tests.test_entry_process_postgres import connection, db_url, database, template, env
from tests.test_dialogue_sessions import clock, current_clock, connected_clock, route_clock, admins, activation, persistent_panel
from tests import test_dialogue_sessions as cases
from tests.test_entry_channel_postgres import waiting_lock
from app.domain import dialogue_sessions as service, dialogue_journal as journal, entry_channel_stops as stops
from app.domain.entry_storage import EntryStorageUnavailable, EntryStorageInvalid
from app.domain.models import EntryDialogueEvent


def claim(env, receipt):
    return asyncio.run(service.claim(env['engine'], route=cases.ROUTE, session_id=receipt['session_id'],
        prompt_revision=receipt['prompt_revision'], authority=env['authority'], resolver=cases.resolve))


def send(env, capability, callback):
    return asyncio.run(stops.guarded_send(env['engine'], cases.ROUTE, callback, typed_capability=capability,
        dialogue_authority=env['authority'], dialogue_resolver=cases.resolve))


def bounded_result(operation):
    """Only the verified PG bounded-lock failure permits an exact later retry."""
    try:return operation()
    except EntryStorageUnavailable as exc:
        nested=exc;states=[]
        while nested is not None:
            states.append(getattr(nested,'sqlstate',None));nested=nested.__context__
        if '55P03' not in states:raise
        return exc


def test_normal_exact_profile_progression(env,tmp_path):
    cases.test_persistent_enum_boolean_date_preserves_original_attestation(env,tmp_path,'ru')


def test_two_incoming_retries_and_two_claimants_create_one_inbox_turn_and_attempt(env,tmp_path):
    cases.setup(env,tmp_path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(bounded_result,lambda:cases.receive(env)) for _ in range(2)]
        receipts=[f.result(timeout=60) for f in futures]
    assert any(isinstance(r,dict) for r in receipts)
    receipts=[cases.receive(env) if isinstance(r,EntryStorageUnavailable) else r for r in receipts]
    assert sorted(r['duplicate'] for r in receipts)==[False,True]
    assert len(cases.inbox_messages(env))==1
    receipt=next(r for r in receipts if not r['duplicate'])
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(bounded_result,lambda:claim(env,receipt)) for _ in range(2)]
        caps=[f.result(timeout=60) for f in futures]
    caps=[claim(env,receipt) if isinstance(c,EntryStorageUnavailable) else c for c in caps]
    assert len([c for c in caps if c is not None])==1
    assert len([e for e in cases.journal_state(env)[1] if e.kind=='claim'])==1
    held=cases.receive(env,'Delete my data','SYN-PRIVACY')
    calls=[]
    async def callback():calls.append(True)
    assert not send(env,next(c for c in caps if c is not None),callback).invoked
    assert held['collection_blocked'] and not calls


def test_send_holds_admission_locks_until_callback_then_privacy_commits(env,tmp_path):
    cases.setup(env,tmp_path);receipt=cases.receive(env);cap=claim(env,receipt)
    entered=threading.Event();release=threading.Event();calls=[]
    async def callback():
        calls.append(True);entered.set();assert await asyncio.to_thread(release.wait,20)
        return 'SYN-PROVIDER'
    with ThreadPoolExecutor(max_workers=2) as pool:
        sending=pool.submit(send,env,cap,callback)
        try:
            assert entered.wait(20)
            privacy=pool.submit(cases.receive,env,'Delete my data','SYN-PRIVACY')
            waiting_lock(env);assert not privacy.done()
        finally:release.set()
        assert sending.result(timeout=30).invoked
        assert privacy.result(timeout=30)['collection_blocked']
    asyncio.run(service.record_outcome(env['engine'],route=cases.ROUTE,capability=cap,outcome='provider_accepted'))
    assert not send(env,cap,callback).invoked and calls==[True]


def test_privacy_commit_first_waiting_send_cannot_invoke_provider(env,tmp_path):
    cases.setup(env,tmp_path);receipt=cases.receive(env);cap=claim(env,receipt)
    entered=threading.Event();release=threading.Event();calls=[]
    def held(mapper,connection,target):
        if target.kind=='stop':entered.set();assert release.wait(20)
    async def callback():calls.append(True)
    event.listen(EntryDialogueEvent,'after_insert',held)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            privacy=pool.submit(cases.receive,env,'Delete my data','SYN-PRIVACY')
            try:
                assert entered.wait(20)
                sending=pool.submit(send,env,cap,callback)
                waiting_lock(env);assert not sending.done()
            finally:release.set()
            assert privacy.result(timeout=30)['collection_blocked']
            assert not sending.result(timeout=30).invoked
    finally:event.remove(EntryDialogueEvent,'after_insert',held)
    assert not calls


def test_held_provider_callback_blocks_actual_profile_history_and_publication_writers(env,tmp_path):
    import time
    cases.setup(env,tmp_path);receipt=cases.receive(env);cap=claim(env,receipt)
    entered=threading.Event();release=threading.Event();calls=[]
    async def callback():
        calls.append(True);entered.set();assert await asyncio.to_thread(release.wait,20)
        return 'SYN-PROVIDER'
    def profile():
        return cases.current_test.save_profile(env,env['person'],revision=1,key='SYN-PROFILE-AFTER-SEND',doc=env['profile_doc'])
    def history():return cases.current_test.withdraw(env,env['person'],revision=1)
    def publication():return cases.current_test.connected.publish(env,'withdraw',ids=env['published'])
    async def waiters():
        async with env['engine'].connect() as c:
            return await c.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock'"))
    with ThreadPoolExecutor(max_workers=4) as pool:
        sending=pool.submit(send,env,cap,callback)
        try:
            assert entered.wait(20)
            writers=[pool.submit(fn) for fn in (profile,history,publication)]
            deadline=time.monotonic()+10
            while time.monotonic()<deadline:
                if asyncio.run(waiters())>=3:break
                time.sleep(.03)
            assert asyncio.run(waiters())>=3 and all(not w.done() for w in writers)
        finally:release.set()
        assert sending.result(timeout=30).invoked
        for writer in writers:writer.result(timeout=60)
    asyncio.run(service.record_outcome(env['engine'],route=cases.ROUTE,capability=cap,outcome='provider_accepted'))
    assert not send(env,cap,callback).invoked and calls==[True]
    assert cases.receive(env,'hello','SYN-AFTER-CONTEXT-CHANGE')['stopped']


@pytest.mark.parametrize('when',['before_commit','after_commit'])
def test_claim_commit_uncertainty_never_reissues_committed_attempt(env,tmp_path,when):
    cases.setup(env,tmp_path);receipt=cases.receive(env);seen=[]
    def fail(session):
        if not seen:seen.append(True);raise RuntimeError('synthetic claim commit acknowledgement')
    event.listen(Session,when,fail)
    try:
        with pytest.raises(EntryStorageUnavailable):claim(env,receipt)
    finally:event.remove(Session,when,fail)
    retry=claim(env,receipt)
    if when=='after_commit':assert retry is None
    else:assert retry is not None
    assert len([e for e in cases.journal_state(env)[1] if e.kind=='claim'])==1


def test_reserved_count_and_bytes_allow_first_stop_later_privacy_and_late_outcome(env,tmp_path,monkeypatch):
    cases.setup(env,tmp_path);receipt=cases.receive(env);cap=claim(env,receipt)
    # Three actual records already exist. Reserve space for first stop, later
    # privacy, and the interrupted send's final (possibly unknown) outcome.
    header,rows,_=cases.journal_state(env)
    from app.knowledge.review import canonical
    total=sum(len(canonical(journal.event_payload(r)).encode()) for r in rows)
    monkeypatch.setattr(journal,'MAX_EVENTS',8)
    monkeypatch.setattr(journal,'MAX_JOURNAL_BYTES',total+6*journal.MAX_EVENT_BYTES)
    assert cases.receive(env,'Хочу менеджера','SYN-HUMAN')['stopped']
    cases.action(env,env['iv'],'ack',policy=env['interview_policy'])
    assert cases.receive(env,'Delete my data','SYN-PRIVACY',authority=None)['collection_blocked']
    asyncio.run(service.record_outcome(env['engine'],route=cases.ROUTE,capability=cap,outcome='unknown'))
    assert len(cases.journal_state(env)[1])==8
    assert cases.receive(env,'Delete my data','SYN-PRIVACY',authority=None)['duplicate']


def test_actual_migration_parity_empty_roundtrip_and_populated_downgrade_refusal(env,tmp_path):
    from alembic import command
    from alembic.config import Config
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from types import SimpleNamespace
    from app.domain.models import DomainBase
    cfg=Config('alembic.ini')
    cfg.cmd_opts=SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    command.downgrade(cfg,'e6_dialogue_cause_0036');command.upgrade(cfg,'head')
    async def compare():
        async with env['engine'].connect() as conn:
            def check(sync):
                return compare_metadata(MigrationContext.configure(sync,opts={'compare_type':True,
                    'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name in
                    ('entry_dialogue_sessions','entry_dialogue_events')}),DomainBase.metadata)
            assert await conn.run_sync(check)==[]
    asyncio.run(compare())
    cases.setup(env,tmp_path);receipt=cases.receive(env)
    with pytest.raises(RuntimeError,match='preserve populated'):
        command.downgrade(cfg,'e6_dialogue_cause_0036')
    assert cases.receive(env)==receipt|{'duplicate':True}


def test_binary_copy_restores_inbox_prompt_retry_and_privacy_without_reissuing_send(env,tmp_path):
    import hashlib
    import json
    import re
    import uuid
    import zipfile
    from types import SimpleNamespace
    import asyncpg
    from alembic import command
    from alembic.config import Config
    from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.integrations.crm.db import Conversation,ConvMessage

    cases.setup(env,tmp_path);original=cases.receive(env);cap=claim(env,original)
    # A committed attempt has no result. Recovery must not create a new attempt.
    before=cases.journal_state(env);before_inbox=[(m.id,m.text) for m in cases.inbox_messages(env)]
    config=connection();restored='frunze_e610_'+uuid.uuid4().hex[:24];archive_path=tmp_path/'synthetic-recovery.zip'
    def ident(value):
        assert re.fullmatch('[a-z_][a-z0-9_]*',value)
        return '"'+value+'"'
    async def backup():
        conn=await asyncpg.connect(**(config|{'database':env['engine'].url.database}))
        try:
            async with conn.transaction(isolation='repeatable_read',readonly=True):
                tables=[r['tablename'] for r in await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname='public' AND tablename <> 'alembic_version' ORDER BY tablename")]
                manifest=dict(revision=await conn.fetchval('SELECT version_num FROM alembic_version'),tables={},sequences={})
                with zipfile.ZipFile(archive_path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
                    for table in tables:
                        chunks=[]
                        async def sink(chunk):chunks.append(chunk)
                        await conn.copy_from_table(table,output=sink,format='binary',schema_name='public')
                        data=b''.join(chunks);archive.writestr(table+'.bin',data)
                        manifest['tables'][table]=dict(count=await conn.fetchval('SELECT count(*) FROM '+ident(table)),sha256=hashlib.sha256(data).hexdigest())
                    edges=await conn.fetch("SELECT c.relname child,p.relname parent FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid JOIN pg_class p ON p.oid=f.confrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE f.contype='f' AND n.nspname='public'")
                    pending={t for t,v in manifest['tables'].items() if v['count']};order=[]
                    while pending:
                        ready=sorted(t for t in pending if not any(e['child']==t and e['parent'] in pending and e['parent']!=t for e in edges))
                        assert ready
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
            async with engine.begin() as c:
                await c.run_sync(lambda s:Conversation.metadata.create_all(s,tables=[Conversation.__table__,ConvMessage.__table__]))
            conn=await asyncpg.connect(**(config|{'database':restored}))
            try:
                with zipfile.ZipFile(archive_path) as archive:
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
        asyncio.run(restore());recovered=env|dict(engine=engine,sm=async_sessionmaker(engine,expire_on_commit=False))
        after=cases.journal_state(recovered)
        assert after[0].snapshot_hash==before[0].snapshot_hash
        assert [e.snapshot_hash for e in after[1]]==[e.snapshot_hash for e in before[1]]
        assert [(m.id,m.text) for m in cases.inbox_messages(recovered)]==before_inbox
        assert cases.receive(recovered)==original|{'duplicate':True}
        assert claim(recovered,original) is None
        assert cases.receive(recovered,'Delete my data','SYN-RECOVERY-PRIVACY',authority=None)['collection_blocked']
        calls=[]
        async def callback():calls.append(True)
        assert not send(recovered,cap,callback).invoked and not calls
    finally:
        asyncio.run(engine.dispose());database(config,restored,drop=True)
