import asyncio
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import NullPool

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_kb_publication_0024'
CURRENT='e6_document_packages_0025'
TABLE='entry_document_package_events'


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
            ctx=MigrationContext.configure(conn,opts={'compare_type':True,'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name==TABLE})
            assert compare_metadata(ctx,DomainBase.metadata)==[]
    finally:engine.dispose()


def test_migrated_operations_scoped_foreign_keys_and_populated_downgrade(config):
    from app.domain import entry_document_packages as packages, entry_applications as apps
    from app.domain.permissions import Actor
    from app.knowledge.complete_document_checklist import CATALOG_SHA256
    from tests.test_admin_workday import _seed_case
    command.upgrade(config,CURRENT)
    engine=create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:','sqlite+aiosqlite:',1),poolclass=NullPool)
    def enable(dbapi,record):
        cursor=dbapi.cursor();cursor.execute('PRAGMA foreign_keys=ON');cursor.close()
    event.listen(engine.sync_engine,'connect',enable)
    sm=async_sessionmaker(engine,expire_on_commit=False)
    case=_seed_case(sm,owner='admin',reference='synthetic-package',direction='visa')
    other=_seed_case(sm,owner='admin',reference='synthetic-other',direction='visa')
    async def run():
        try:
            args=dict(actor=Actor('admin',True),case_id=case['case_id'])
            person=await apps.add_applicant(engine,**args,role='primary',request_key='p')
            app=await apps.open_application(engine,**args,applicant_id=person['id'],procedure='visa',request_key='a')
            row=await packages.record_package_operation(engine,**args,application_id=app['id'],expected_revision=0,request_key='initialize',
                operation=dict(action='initialize',data=dict(product='TR',catalog_digest=CATALOG_SHA256,legacy_revision=0),confirmed=True))
            assert (await packages.read_document_package(engine,**args,application_id=app['id']))['current_revision']==1
            sql="INSERT INTO entry_document_package_events(case_id,application_id,revision,action,previous_id,legacy_inventory_id,legacy_inventory_hash,definition,request_key,request_hash,snapshot_hash,state_hash,command,created_by,created_at) SELECT :case,application_id,:rev,:action,:prev,:legacy,:legacy_hash,:definition,:key,request_hash,snapshot_hash,state_hash,command,created_by,created_at FROM entry_document_package_events WHERE id=:id"
            base=dict(case=case['case_id'],rev=2,action='facts',prev=row['id'],legacy=None,legacy_hash=None,definition=None,key='bad',id=row['id'])
            for changes in (dict(case=other['case_id']),dict(rev=1,action='initialize',prev=None,definition='{}'),
                            dict(prev=99999),dict(legacy=99999,legacy_hash='a'*64),dict(definition='{}'),dict(action='unknown')):
                async with engine.begin() as conn:
                    with pytest.raises(IntegrityError):await conn.execute(text(sql),base|changes)
        finally:await engine.dispose()
    asyncio.run(run())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
    sync=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with sync.connect() as conn:
            assert TABLE in inspect(conn).get_table_names()
            assert conn.scalar(text('SELECT count(*) FROM entry_document_package_events'))==1
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))==CURRENT
    finally:sync.dispose()


def test_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1
    assert 'FOREIGN KEY(application_id, case_id) REFERENCES entry_applications (id, case_id)' in ddl
    assert 'FOREIGN KEY(previous_id, application_id, case_id)' in ddl
    assert 'FOREIGN KEY(legacy_inventory_id, application_id, case_id)' in ddl
    assert 'UNIQUE (application_id, request_key)' in ddl
    assert all(word not in ddl for word in ('DROP TABLE','DELETE FROM','INSERT INTO','ALTER TABLE'))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
