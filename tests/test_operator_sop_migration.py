"""Additive nullable time and composite own-process evidence; no mutable backfill."""
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine,inspect

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS='e6_actual_anchor_events_0042'
CURRENT='e6_sop_review_evidence_0043'


def test_empty_roundtrip_metadata_and_nullable_time(config):
    command.upgrade(config,PREVIOUS);engine=create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:
            assert 'expected_at' not in {r['name'] for r in inspect(conn).get_columns('entry_deadline_tasks')}
        command.upgrade(config,CURRENT)
        with engine.connect() as conn:
            assert compare_metadata(MigrationContext.configure(conn,opts={'compare_type':True}),DomainBase.metadata)==[]
            column=next(r for r in inspect(conn).get_columns('entry_deadline_tasks') if r['name']=='expected_at')
            assert column['nullable'] and column['default'] is None
        command.downgrade(config,PREVIOUS)
        with engine.connect() as conn:
            assert 'expected_at' not in {r['name'] for r in inspect(conn).get_columns('entry_deadline_tasks')}
            assert 'entry_sop_review_evidence' not in inspect(conn).get_table_names()
        command.upgrade(config,CURRENT)
    finally:engine.dispose()


def test_postgres_ddl_and_offline_downgrade_refused(config):
    config.set_main_option('sqlalchemy.url','postgresql+asyncpg://localhost/unused')
    config.output_buffer=io.StringIO();command.upgrade(config,f'{PREVIOUS}:{CURRENT}',sql=True)
    ddl=config.output_buffer.getvalue()
    assert 'expected_at TIMESTAMP WITH TIME ZONE' in ddl
    assert 'FOREIGN KEY(process_event_id, application_id, case_id, applicant_id)' in ddl
    assert 'FOREIGN KEY(application_event_id, active_application_id)' in ddl
    with pytest.raises(RuntimeError,match='offline downgrade'):command.downgrade(config,f'{CURRENT}:{PREVIOUS}',sql=True)
