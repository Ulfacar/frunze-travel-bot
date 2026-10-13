"""Fresh-schema binary COPY recovery, exact retries and next real operation."""
import asyncio
import hashlib
import json
from pathlib import Path
import re
from types import SimpleNamespace
import uuid
import zipfile

import asyncpg
from alembic import command
from alembic.config import Config
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.pool import NullPool

from tests.test_entry_process_postgres import connection,db_url,database,template,env
from tests.test_conditional_deadline_postgres import setup,read,record,command as review_command
from tests.test_conditional_deadlines import clock


def test_conditional_binary_copy_recovery_preserves_evidence_retry_and_next_clear(env,tmp_path):
    setup(env,tmp_path);original=review_command(env);saved=record(env,original);before=read(env)
    config=connection();restored='frunze_e610_'+uuid.uuid4().hex[:24];dump=tmp_path/'conditional-deadline-recovery.zip'
    def ident(name):
        assert re.fullmatch('[a-z_][a-z0-9_]*',name);return '"'+name+'"'
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
                        assert ready,'nonempty cyclic dependencies';order.extend(ready);pending.difference_update(ready)
                    manifest['order']=order
                    for row in await conn.fetch("SELECT sequencename FROM pg_sequences WHERE schemaname='public'"):
                        name=row['sequencename'];manifest['sequences'][name]=dict(await conn.fetchrow('SELECT last_value,is_called FROM '+ident(name)))
                    archive.writestr('manifest.json',json.dumps(manifest,sort_keys=True))
                return manifest
        finally:await conn.close()
    manifest=asyncio.run(backup());database(config,restored)
    engine=create_async_engine(db_url(config,restored),poolclass=NullPool)
    try:
        cfg=Config('alembic.ini');cfg.cmd_opts=SimpleNamespace(x=['dburl='+db_url(config,restored).render_as_string(hide_password=False)])
        command.upgrade(cfg,'head')
        async def restore():
            conn=await asyncpg.connect(**(config|{'database':restored}))
            try:
                assert await conn.fetchval('SELECT version_num FROM alembic_version')==manifest['revision']
                with zipfile.ZipFile(dump) as archive:
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
        assert read(recovered)==before
        assert record(recovered,original|dict(authority=None))==saved
        cancelled=record(recovered,original|dict(authority=None,expected_revision=1,request_key='restored-clear',operation=dict(action='conditional_clear',confirmed=True,evidence_hash=saved['snapshot_hash'])))
        assert cancelled['revision']==2 and cancelled['snapshot']['cleared'] is True
        report=dict(environment='isolated PostgreSQL16 loopback55971',method='binary COPY; live foreign keys; fresh Alembic schema; restored sequences',
            revision=manifest['revision'],table_counts={t:v['count'] for t,v in manifest['tables'].items()},
            dump_sha256=hashlib.sha256(dump.read_bytes()).hexdigest(),history_equal=True,original_retry_equal=True,new_revision=2)
        Path('runs/conditional-deadline-recovery.json').write_text(json.dumps(report,indent=2)+'\n','utf8')
    finally:asyncio.run(engine.dispose());database(config,restored,drop=True)
