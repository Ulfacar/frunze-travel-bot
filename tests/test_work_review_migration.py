"""0041 is additive and never downgrades a populated review history."""
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine,inspect,text

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_work_process_evidence_0040'
CURRENT='e6_work_review_events_0041'


def test_review_additive_empty_cycle_and_full_metadata(config):
    command.upgrade(config,PREVIOUS);engine=create_engine(config.get_main_option('sqlalchemy.url'))
    def old_schema(conn):
        return dict(conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%work_review%'" )).all())
    try:
        with engine.connect() as conn:before=old_schema(conn)
        command.upgrade(config,CURRENT)
        with engine.connect() as conn:
            assert old_schema(conn)==before
            assert compare_metadata(MigrationContext.configure(conn,opts={'compare_type':True}),DomainBase.metadata)==[]
            assert conn.scalar(text('SELECT count(*) FROM entry_work_review_events'))==0
        command.downgrade(config,PREVIOUS)
        with engine.connect() as conn:assert 'entry_work_review_events' not in inspect(conn).get_table_names() and old_schema(conn)==before
        command.upgrade(config,CURRENT)
        with engine.connect() as conn:assert compare_metadata(MigrationContext.configure(conn,opts={'compare_type':True}),DomainBase.metadata)==[]
    finally:engine.dispose()


def test_review_postgres_ddl_and_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert 'CREATE TABLE entry_work_review_events' in ddl and 'FOREIGN KEY(application_id, case_id, applicant_id, procedure)' in ddl
    assert 'FOREIGN KEY(task_id) REFERENCES calendar_tasks (id)' in ddl and 'DROP TABLE' not in ddl
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
