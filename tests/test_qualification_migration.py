"""Qualification storage migration is additive and refuses destructive recovery."""
import asyncio
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

from app.domain.models import DomainBase
from app.domain.knowledge_import import create_kg_entry_set, import_bundle
from app.domain.qualification_storage import read_qualification, replay_qualification, save_qualification
from tests.test_entry_storage import ADMIN, FIX
from tests.test_knowledge_migration import config
from tests.test_qualification_storage import request

PREVIOUS='e5_calculation_0015'
CURRENT='e5_qualification_0016'


def schema(conn):
    return dict(conn.execute(text("SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL "
        "AND name NOT LIKE '%entry_qualification%'" )).all())


def test_additive_empty_cycle_schema_parity_preserves_contact(config):
    command.upgrade(config,PREVIOUS)
    engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO contacts(id) VALUES (12345)'))
            before=schema(conn)
            person=tuple(conn.execute(text('SELECT * FROM contacts')).one())
        for operation,revision in [(command.upgrade,CURRENT),(command.downgrade,PREVIOUS),(command.upgrade,CURRENT)]:
            operation(config,revision)
            with engine.connect() as conn:
                assert schema(conn)==before
                assert tuple(conn.execute(text('SELECT * FROM contacts')).one())==person
                if revision==CURRENT:assert conn.scalar(text('SELECT count(*) FROM entry_qualifications'))==0
        with engine.connect() as conn:
            context=MigrationContext.configure(conn,opts={'compare_type':True,'compare_server_default':True,
                'include_object':lambda obj,name,kind,reflected,other:kind!='table' or name=='entry_qualifications'})
            assert compare_metadata(context,DomainBase.metadata)==[]
    finally:engine.dispose()


def test_migrated_db_replay_and_populated_downgrade_refusal(config):
    command.upgrade(config,CURRENT)
    url=config.get_main_option('sqlalchemy.url')
    async def scenario():
        engine=create_async_engine(url.replace('sqlite:','sqlite+aiosqlite:',1))
        try:
            async with engine.begin() as conn:await conn.execute(text('INSERT INTO contacts(id) VALUES (12345)'))
            set_id=await create_kg_entry_set(engine,actor=ADMIN)
            imported=await import_bundle(engine,actor=ADMIN,set_id=set_id,directory=FIX/'synthetic_bundle',source=FIX/'synthetic_source.txt')
            saved=await save_qualification(engine,actor=ADMIN,contact_id=12345,expected_revision=0,
                request_key='migrated',knowledge_version_id=imported.version_id,request=request())
            assert await read_qualification(engine,actor=ADMIN,contact_id=12345)==saved
            assert (await replay_qualification(engine,actor=ADMIN,contact_id=12345,qualification_id=saved['qualification_id']))['replay_verified']
        finally:await engine.dispose()
    asyncio.run(scenario())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
    engine=create_engine(url)
    try:
        with engine.connect() as conn:
            assert 'entry_qualifications' in inspect(conn).get_table_names()
            assert conn.scalar(text('SELECT count(*) FROM entry_qualifications'))==1
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))==CURRENT
    finally:engine.dispose()


def test_postgresql_offline_ddl_scoped_constraints_and_no_backfill(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO()
    command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ')==1
    assert 'FOREIGN KEY(history_id, contact_id) REFERENCES stay_histories (id, contact_id)' in ddl
    assert 'FOREIGN KEY(previous_id, contact_id) REFERENCES entry_qualifications (id, contact_id)' in ddl
    assert 'UNIQUE (contact_id, revision)' in ddl and 'UNIQUE (contact_id, request_key)' in ddl
    assert all(word not in ddl for word in ('ALTER TABLE','DROP TABLE','DELETE FROM','INSERT INTO'))
    with pytest.raises(RuntimeError,match='offline downgrade'):
        command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
