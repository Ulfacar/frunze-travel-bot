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

PREVIOUS='e6_deadline_tasks_0022'
CURRENT='e6_kb_decisions_0023'
TABLE='knowledge_decisions'


def schema(conn):
    return {n:s for n,s in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"))
            if n not in ('alembic_version',TABLE) and TABLE not in (s or '')}


def test_additive_empty_cycle_and_model_parity(config):
    command.upgrade(config,PREVIOUS);engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:before=schema(conn)
        for fn,target in ((command.upgrade,CURRENT),(command.downgrade,PREVIOUS),(command.upgrade,CURRENT)):
            fn(config,target)
            with engine.connect() as conn:assert schema(conn)==before
        with engine.connect() as conn:
            context=MigrationContext.configure(conn,opts={'compare_type':True,
                'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name==TABLE})
            assert compare_metadata(context,DomainBase.metadata)==[]
    finally:engine.dispose()


def test_migrated_decision_scope_and_populated_downgrade(config):
    from app.domain import knowledge_decisions as reviews
    from app.domain.knowledge_import import create_kg_entry_set,import_bundle
    from tests.test_admin_kg_entry import ADMIN,FIX
    from tests.test_knowledge_decisions import data
    command.upgrade(config,CURRENT)
    engine=create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:','sqlite+aiosqlite:',1),poolclass=NullPool)
    def enable(dbapi,record):
        cursor=dbapi.cursor();cursor.execute('PRAGMA foreign_keys=ON');cursor.close()
    event.listen(engine.sync_engine,'connect',enable)
    async def run():
        try:
            set_id=await create_kg_entry_set(engine,actor=ADMIN)
            imported=await import_bundle(engine,actor=ADMIN,set_id=set_id,directory=FIX/'synthetic_bundle',source=FIX/'synthetic_source.txt')
            assert imported.accepted
            args=dict(actor=ADMIN,version_id=imported.version_id,unit_id='KG.DL.TEST')
            row=await reviews.record_knowledge_decision(engine,**args,expected_revision=0,request_key='review',decision=data())
            assert (await reviews.read_knowledge_decisions(engine,**args))['selected']==row
            sql="INSERT INTO knowledge_decisions(version_id,unit_id,revision,previous_id,unit_hash,bundle_hash,request_key,request_hash,snapshot_hash,command,created_by,created_at) SELECT :version,:unit,:revision,:previous,unit_hash,bundle_hash,:key,request_hash,snapshot_hash,command,created_by,created_at FROM knowledge_decisions WHERE id=:id"
            defaults=dict(version=imported.version_id,unit='KG.DL.TEST',revision=2,previous=row['id'],key='second',id=row['id'])
            for override in ({'version':999},{'unit':'KG.DL.OTHER'},{'previous':999},{'revision':1,'previous':None},
                             {'revision':251},{'key':'review'}):
                async with engine.begin() as conn:
                    with pytest.raises(IntegrityError):await conn.execute(text(sql),{**defaults,**override})
        finally:await engine.dispose()
    asyncio.run(run())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
    engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:
            assert TABLE in inspect(conn).get_table_names()
            assert conn.scalar(text('SELECT count(*) FROM knowledge_decisions'))==1
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))==CURRENT
    finally:engine.dispose()


def test_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1
    assert 'FOREIGN KEY(version_id, unit_id)' in ddl and 'FOREIGN KEY(previous_id, version_id, unit_id)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
