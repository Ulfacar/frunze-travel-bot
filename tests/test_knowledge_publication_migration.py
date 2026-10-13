import asyncio
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_kb_decisions_0023'
CURRENT='e6_kb_publication_0024'
TABLES=('knowledge_publication_events','knowledge_publication_units')


def schema(conn):
    return {n:s for n,s in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
            if n not in ('alembic_version',*TABLES) and not any(t in (s or '') for t in TABLES)}


def test_additive_empty_cycle_and_model_parity(config):
    command.upgrade(config,PREVIOUS);engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:before=schema(conn)
        for fn,target in ((command.upgrade,CURRENT),(command.downgrade,PREVIOUS),(command.upgrade,CURRENT)):
            fn(config,target)
            with engine.connect() as conn:assert schema(conn)==before
        with engine.connect() as conn:
            context=MigrationContext.configure(conn,opts={'compare_type':True,
                'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name in TABLES})
            assert compare_metadata(context,DomainBase.metadata)==[]
    finally:engine.dispose()


def test_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==2
    assert 'FOREIGN KEY(decision_id, version_id, unit_id)' in ddl and 'FOREIGN KEY(previous_id, set_id)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)


def test_migrated_publication_scope_and_populated_downgrade(config, tmp_path):
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from tests.test_knowledge_publication import load_source, activate, runtime
    command.upgrade(config, CURRENT)
    engine = create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:', 'sqlite+aiosqlite:', 1), poolclass=NullPool)
    def enable(dbapi, record):
        cursor=dbapi.cursor(); cursor.execute('PRAGMA foreign_keys=ON'); cursor.close()
    event.listen(engine.sync_engine, 'connect', enable)
    env = {'engine':engine, 'sm':async_sessionmaker(engine, expire_on_commit=False)}
    try:
        env['release'] = load_source(env, tmp_path)
        activate(env); assert len(runtime(env)['available']) == 2
        async def check():
            stmt = "INSERT INTO knowledge_publication_units(event_id,unit_id,version_id,decision_id,unit_hash,decision_hash) SELECT :event,:unit,:version,:decision,unit_hash,decision_hash FROM knowledge_publication_units LIMIT 1"
            for params in (dict(event=999,unit='KG.DL.TEST',version=env['release'],decision=1),
                           dict(event=1,unit='KG.VF.TEST',version=999,decision=1),
                           dict(event=1,unit='KG.REG.DEFAULT',version=env['release'],decision=1)):
                async with engine.begin() as conn:
                    with pytest.raises(IntegrityError): await conn.execute(text(stmt), params)
        asyncio.run(check())
        with pytest.raises(RuntimeError, match='preserve populated'): command.downgrade(config, PREVIOUS)
        assert len(runtime(env)['available']) == 2
    finally: asyncio.run(engine.dispose())
