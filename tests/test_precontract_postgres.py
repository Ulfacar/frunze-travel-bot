"""Actual independent sessions in the explicitly isolated local PG cluster."""
import asyncio
import uuid
from types import SimpleNamespace

import pytest
from alembic import command as migrations
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.domain import precontract_cases as service, service_cases as cases, service_money as money
from app.domain.models import DomainBase, DomainError, ServiceCase, ServiceEvent, ServiceCaseOpening, Contact
from tests.test_precontract_cases import prepare, signing, counts, ADMIN, OWNER, managers
from tests.test_entry_process_postgres import template, database, db_url


@pytest.fixture
def pg(template):
    config, original = template
    name = 'frunze_e610_' + uuid.uuid4().hex[:24]
    database(config, name, template=original)
    engine = create_async_engine(db_url(config, name), poolclass=NullPool)
    sm = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield SimpleNamespace(config=config, name=name, engine=engine, sm=sm)
    finally:
        asyncio.run(engine.dispose())
        database(config, name, drop=True)


async def blocked(pg, task):
    # Observe the contender actually waiting in this database before releasing
    # the first transaction; a timing-only sleep cannot prove serialization.
    for _ in range(100):
        async with pg.engine.connect() as c:
            waiting = await c.scalar(text("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=current_database() AND wait_event_type='Lock')"))
        if waiting:
            assert not task.done()
            return
        if task.done():
            task.result()
            raise AssertionError('contender did not wait for the original operation')
        await asyncio.sleep(.02)
    raise AssertionError('no database lock wait observed')


async def open_in(pg, values):
    async with pg.sm() as s:
        result = await service.open_preliminary(s, **values)
        await s.commit()
        return result


async def sign_in(pg, values):
    async with pg.sm() as s:
        result = await service.record_signed_contract(s, **values)
        await s.commit()
        return result


@pytest.mark.parametrize('different', [False, True])
def test_postgres_concurrent_open_preserves_distinct_command_keys(pg, different):
    async def run():
        async with pg.sm() as first:
            values = await prepare(first)
            original = await service.open_preliminary(first, **values)
            other = values | ({'request_key': 'OTHER-OPEN'} if different else {})
            contender = asyncio.create_task(open_in(pg, other))
            try:
                await blocked(pg, contender)
                await first.commit()
                result = await contender
            finally:
                if not contender.done(): contender.cancel()
            assert (result['case_id'] != original['case_id']) == different
            assert result['duplicate'] is (not different)
            state = await counts(first)
            assert state['service_cases'] == state['service_case_openings'] == state['service_events'] == (2 if different else 1)
            assert state['calendar_tasks'] == state['service_payments'] == 0
    asyncio.run(run())


@pytest.mark.parametrize('different', [False, True])
def test_postgres_concurrent_signature_one_contract_and_task(pg, different):
    async def run():
        async with pg.sm() as first:
            values = await prepare(first)
            opened = await service.open_preliminary(first, **values)
            await first.commit()
            original = await service.record_signed_contract(first, **signing(opened))
            other = signing(opened, **({'request_key': 'OTHER-SIGN'} if different else {}))
            contender = asyncio.create_task(sign_in(pg, other))
            try:
                await blocked(pg, contender)
                await first.commit()
                if different:
                    with pytest.raises(DomainError, match='conflict'): await contender
                else:
                    assert await contender == original | {'duplicate': True}
            finally:
                if not contender.done(): contender.cancel()
            assert await counts(first) == dict(service_cases=1,service_case_openings=1,service_events=2,calendar_tasks=1,service_payments=0)
    asyncio.run(run())


@pytest.mark.parametrize('writer', ['owner', 'stage', 'money'])
def test_postgres_signature_rechecks_committed_competing_writer(pg, writer):
    async def run():
        async with pg.sm() as first:
            values = await prepare(first)
            opened = await service.open_preliminary(first, **values)
            await first.commit()
            if writer == 'owner':
                await cases.reassign_case(first, opened['case_id'], target_login='peer', by=ADMIN)
            elif writer == 'stage':
                await cases.advance(first, opened['case_id'], to_stage='IN-02', by=OWNER)
            else:
                await money.correct_contract_amount(first, opened['case_id'], amount='200', currency='KGS', by=ADMIN, reason='Synthetic explicit correction')
            contender = asyncio.create_task(sign_in(pg, signing(opened)))
            try:
                await blocked(pg, contender)
                await first.commit()
                with pytest.raises(DomainError, match='revision'): await contender
            finally:
                if not contender.done(): contender.cancel()
            async with pg.sm() as s:
                current = await s.get(ServiceCase, opened['case_id'])
                assert current.signed_at is None
                assert not await s.scalar(select(ServiceEvent.id).where(ServiceEvent.event_type=='contract_signed'))
    asyncio.run(run())


def test_postgres_open_unique_collision_and_rollback_leave_original_case(pg):
    async def run():
        async with pg.sm() as s:
            values = await prepare(s)
            original = await service.open_preliminary(s, **values)
            await s.commit()
            extra = Contact(); s.add(extra); await s.flush(); await s.commit()
            with pytest.raises(DomainError, match='conflict'):
                await service.open_preliminary(s, **(values | {'contact_id': extra.id}))
            await s.rollback()
            assert (await counts(s))['service_cases'] == 1
            signed = await service.record_signed_contract(s, **signing(original))
            await s.rollback()
        async with pg.sm() as s:
            case = await s.get(ServiceCase, original['case_id'])
            assert case.signed_at is None and (await counts(s))['calendar_tasks'] == 0
            saved = await service.record_signed_contract(s, **signing(original))
            await s.commit()
        # A caller loses the response after commit, then uses the original key.
        replay = await sign_in(pg, signing(original))
        assert replay == saved | {'duplicate': True}
    asyncio.run(run())


def test_postgres_additive_migration_parity_and_populated_downgrade_guard(pg):
    cfg = Config('alembic.ini')
    cfg.cmd_opts = SimpleNamespace(x=['dburl='+db_url(pg.config, pg.name).render_as_string(hide_password=False)])
    migrations.downgrade(cfg, 'e6_dialogue_session_0037')
    migrations.upgrade(cfg, 'head')
    async def run():
        async with pg.engine.connect() as c:
            differences = await c.run_sync(lambda conn: compare_metadata(MigrationContext.configure(conn), DomainBase.metadata))
            assert not [d for d in differences if 'service_case_openings' in str(d)]
        async with pg.sm() as s:
            values = await prepare(s)
            result = await service.open_preliminary(s, **values)
            await s.commit()
            return values, result
    values, result = asyncio.run(run())
    with pytest.raises(RuntimeError, match='preserve populated'):
        migrations.downgrade(cfg, 'e6_dialogue_session_0037')
    assert asyncio.run(open_in(pg, values)) == result | {'duplicate': True}


def test_postgres_binary_copy_recovery_preserves_open_sign_and_legacy_records(pg,tmp_path):
    import asyncpg
    import hashlib
    import json
    import re
    import zipfile
    from pathlib import Path
    def identifier(name):
        assert re.fullmatch('[a-z_][a-z0-9_]*',name)
        return '"'+name+'"'
    async def seed():
        async with pg.sm() as s:
            values=await prepare(s)
            opened=await service.open_preliminary(s,**values)
            signed=await service.record_signed_contract(s,**signing(opened))
            legacy=await cases.sign_contract(s,contact_id=values['contact_id'],product_id=values['product_id'],
                owner_login=values['owner_login'],by=ADMIN,reference='SYN-LEGACY',signed_at=signing(opened)['signed_at'],
                amount='50.00',currency='USD',idempotency_key='LEGACY-SIGN')
            await s.commit()
            return values,opened,signed,legacy.id,await counts(s)
    values,opened,signed,legacy_id,before=asyncio.run(seed())
    dump=tmp_path/'synthetic-recovery.zip'
    async def backup():
        conn=await asyncpg.connect(**(pg.config|{'database':pg.name}))
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
                        manifest['tables'][table]={'count':await conn.fetchval('SELECT count(*) FROM '+identifier(table)),
                            'sha256':hashlib.sha256(data).hexdigest()}
                    edges=await conn.fetch("SELECT c.relname AS child,p.relname AS parent FROM pg_constraint f JOIN pg_class c ON c.oid=f.conrelid JOIN pg_class p ON p.oid=f.confrelid JOIN pg_namespace n ON n.oid=c.relnamespace WHERE f.contype='f' AND n.nspname='public'")
                    pending={t for t,v in manifest['tables'].items() if v['count']};order=[]
                    while pending:
                        ready=sorted(t for t in pending if not any(e['child']==t and e['parent'] in pending and e['parent']!=t for e in edges))
                        assert ready,'recovery dependency cycle'
                        order.extend(ready);pending.difference_update(ready)
                    manifest['order']=order
                    for row in await conn.fetch("SELECT sequencename FROM pg_sequences WHERE schemaname='public'"):
                        name=row['sequencename']
                        manifest['sequences'][name]=dict(await conn.fetchrow('SELECT last_value,is_called FROM '+identifier(name)))
                    archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
        finally:await conn.close()
    asyncio.run(backup())
    restored='frunze_e610_'+uuid.uuid4().hex[:24]
    database(pg.config,restored)
    engine=create_async_engine(db_url(pg.config,restored),poolclass=NullPool)
    try:
        cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+db_url(pg.config,restored).render_as_string(hide_password=False)])
        migrations.upgrade(cfg,'head')
        async def recover():
            conn=await asyncpg.connect(**(pg.config|{'database':restored}))
            try:
                with zipfile.ZipFile(dump) as archive:
                    manifest=json.loads(archive.read('manifest.json'))
                    assert await conn.fetchval('SELECT version_num FROM alembic_version')==manifest['revision']
                    async with conn.transaction():
                        for table in manifest['tables']:assert await conn.fetchval('SELECT count(*) FROM '+identifier(table))==0
                        for table in manifest['order']:
                            data=archive.read(table+'.bin');assert hashlib.sha256(data).hexdigest()==manifest['tables'][table]['sha256']
                            await conn.copy_to_table(table,source=memoryview(data),format='binary',schema_name='public')
                        for table,entry in manifest['tables'].items():assert await conn.fetchval('SELECT count(*) FROM '+identifier(table))==entry['count']
                        for name,entry in manifest['sequences'].items():
                            identifier(name)
                            await conn.fetchval('SELECT setval($1::regclass,$2,$3)',name,entry['last_value'],entry['is_called'])
            finally:await conn.close()
            sm=async_sessionmaker(engine,expire_on_commit=False)
            async with sm() as s:
                assert await counts(s)==before
                assert await service.open_preliminary(s,**values)==opened|{'duplicate':True}
                assert await service.record_signed_contract(s,**signing(opened))==signed|{'duplicate':True}
                legacy=await s.get(ServiceCase,legacy_id)
                assert legacy.contract_reference=='SYN-LEGACY' and legacy.idempotency_key=='LEGACY-SIGN'
                later=await service.open_preliminary(s,**(values|{'request_key':'AFTER-RECOVERY'}))
                await s.commit();assert later['case_id']>legacy_id
        asyncio.run(recover())
        Path('runs').mkdir(exist_ok=True)
        Path('runs/e630-recovery.json').write_text(json.dumps(dict(method='all public data binary COPY; freshly migrated schema; FK enabled; restored sequences',
            revision='e6_precontract_case_0038',backup_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),
            previous_counts=before,original_open_and_sign_retried=True,legacy_preserved=True,new_write_after_restore=True),indent=2),encoding='utf-8')
    finally:
        asyncio.run(engine.dispose());database(pg.config,restored,drop=True)
