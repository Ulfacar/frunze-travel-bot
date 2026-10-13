"""0040 empty cycle and refusal to erase even an unpopulated successor journal."""
import asyncio
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine,inspect,text
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.pool import NullPool

from app.domain.models import DomainBase
from app.knowledge.process_preview import WORK_CATALOG_SHA256
from tests.test_knowledge_migration import config

PREVIOUS='e6_specialist_decisions_0039'
CURRENT='e6_work_process_evidence_0040'


def test_work_pin_additive_empty_cycle_and_full_metadata(config):
    command.upgrade(config,PREVIOUS)
    engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:
            before={name:ddl for name,ddl in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%entry_process_pins%'"))}
            old_columns=[c['name'] for c in inspect(conn).get_columns('entry_process_pins')]
        command.upgrade(config,CURRENT)
        with engine.connect() as conn:
            assert [c['name'] for c in inspect(conn).get_columns('entry_process_pins')]==old_columns+['stay_history_id']
            assert compare_metadata(MigrationContext.configure(conn,opts={'compare_type':True}),DomainBase.metadata)==[]
        command.downgrade(config,PREVIOUS)
        with engine.connect() as conn:assert [c['name'] for c in inspect(conn).get_columns('entry_process_pins')]==old_columns
        command.upgrade(config,CURRENT)
        with engine.connect() as conn:
            after={name:ddl for name,ddl in conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%entry_process_pins%'"))}
            assert before==after
            assert compare_metadata(MigrationContext.configure(conn,opts={'compare_type':True}),DomainBase.metadata)==[]
    finally:engine.dispose()


def test_new_catalog_without_stay_pin_still_refuses_downgrade(config):
    from tests.test_admin_workday import _seed_case
    from tests.test_entry_applications import person,application
    from tests.test_work_process_v2 import write,today
    command.upgrade(config,CURRENT)
    engine=create_async_engine(config.get_main_option('sqlalchemy.url').replace('sqlite:','sqlite+aiosqlite:',1),poolclass=NullPool)
    sm=async_sessionmaker(engine,expire_on_commit=False)
    case=_seed_case(sm,owner='admin',reference='synthetic-work-migration',direction='visa')
    env=dict(engine=engine,sm=sm,cases={'visa':case['case_id']})
    try:
        app=application(env,person(env),'work',procedure='unified_permit')
        write(env,app,'initialize',dict(catalog_digest=WORK_CATALOG_SHA256,on=today(),employer_reference='SYNTHETIC'),revision=0)
    finally:asyncio.run(engine.dispose())
    with pytest.raises(RuntimeError,match='preserve populated'):command.downgrade(config,PREVIOUS)
    sync=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with sync.connect() as conn:
            assert conn.scalar(text('SELECT version_num FROM alembic_version'))==CURRENT
            assert conn.scalar(text('SELECT count(*) FROM entry_process_events'))==1
            assert conn.scalar(text('SELECT count(*) FROM entry_process_pins WHERE stay_history_id IS NOT NULL'))==0
    finally:sync.dispose()


def test_work_pin_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert 'ADD COLUMN stay_history_id INTEGER' in ddl
    assert 'FOREIGN KEY(stay_history_id, applicant_id, case_id)' in ddl
    assert not any(value in ddl for value in ('CREATE TABLE','DELETE FROM','INSERT INTO'))
    assert all(line.startswith('UPDATE alembic_version ') for line in ddl.splitlines() if line.startswith('UPDATE '))
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
