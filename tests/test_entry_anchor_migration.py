"""Additive actual-anchor schema, own-source composite keys and recovery guard."""
import io

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.domain.models import DomainBase
from tests.test_knowledge_migration import config

PREVIOUS = 'e6_work_review_events_0041'
CURRENT = 'e6_actual_anchor_events_0042'


def metadata_options():
    # 0043 additions are excluded only while comparing the exact 0042 boundary.
    return dict(compare_type=True,include_object=lambda obj,name,kind,reflected,compare_to:
        not (kind=='table' and name=='entry_sop_review_evidence' or
             kind=='column' and obj.table.name=='entry_deadline_tasks' and name=='expected_at'))


def test_actual_anchor_empty_round_trip_preserves_old_schema_and_matches_metadata(config):
    command.upgrade(config, PREVIOUS); engine = create_engine(config.get_main_option('sqlalchemy.url'))
    def old_schema(conn):
        return dict(conn.execute(text("SELECT name,sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%actual_anchor%' AND name NOT LIKE '%entry_anchor%' AND name NOT LIKE '%conditional%'" )).all())
    try:
        with engine.connect() as conn: before = old_schema(conn)
        command.upgrade(config, CURRENT)
        with engine.connect() as conn:
            assert old_schema(conn) == before
            assert compare_metadata(MigrationContext.configure(conn, opts=metadata_options()), DomainBase.metadata) == []
            assert conn.scalar(text('SELECT count(*) FROM entry_anchor_events')) == 0
            assert conn.scalar(text('SELECT count(*) FROM entry_anchor_pins')) == 0
        command.downgrade(config, PREVIOUS)
        with engine.connect() as conn:
            assert 'entry_anchor_events' not in inspect(conn).get_table_names()
            assert 'entry_anchor_pins' not in inspect(conn).get_table_names()
            assert old_schema(conn) == before
        command.upgrade(config, CURRENT)
        with engine.connect() as conn:
            assert compare_metadata(MigrationContext.configure(conn, opts=metadata_options()), DomainBase.metadata) == []
    finally: engine.dispose()


def test_actual_anchor_postgres_ddl_and_no_unchecked_offline_downgrade(config):
    config.set_main_option('sqlalchemy.url', 'postgresql+asyncpg://localhost/unused')
    config.output_buffer = io.StringIO(); command.upgrade(config, f'{PREVIOUS}:{CURRENT}', sql=True)
    ddl = config.output_buffer.getvalue()
    assert 'CREATE TABLE entry_anchor_events' in ddl and 'CREATE TABLE entry_anchor_pins' in ddl
    for columns in ('anchor_id, application_id, case_id, applicant_id', 'profile_id, applicant_id, case_id', 'application_event_id, application_id', 'issued_id, application_id, case_id'):
        assert 'FOREIGN KEY('+columns+')' in ddl
    assert 'DROP TABLE' not in ddl
    with pytest.raises(RuntimeError, match='offline downgrade'):
        command.downgrade(config, f'{CURRENT}:{PREVIOUS}', sql=True)
