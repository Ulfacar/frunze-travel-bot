"""Preserve populated chains and inbound task FKs while changing only the cap."""
import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_deadline_tasks import seed, sync, read as task_read
from tests.test_entry_deadlines import read, write
from tests.test_entry_deadline_clear_capacity import at_capacity
from tests.test_knowledge_migration import config

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = 'e6_notification_drafts_0032'
CURRENT = 'e6_deadline_clear_0033'


def migration():
    spec = importlib.util.spec_from_file_location('deadline_clear_migration',
        ROOT / 'alembic/versions/e6_deadline_clear_0033.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def captured(conn):
    return {table: [tuple(row) for row in conn.execute(text('SELECT * FROM ' + table + ' ORDER BY id'))]
            for table in ('entry_deadline_revisions', 'entry_deadline_tasks', 'calendar_tasks')}


def test_empty_migration_cycle(config):
    command.upgrade(config, PREVIOUS)
    command.upgrade(config, CURRENT)
    command.downgrade(config, PREVIOUS)
    command.upgrade(config, CURRENT)
    engine = create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []
            assert 'BETWEEN 1 AND 251' in conn.scalar(text(
                "SELECT sql FROM sqlite_master WHERE name='entry_deadline_revisions'"))
    finally:
        engine.dispose()


def test_populated_sqlite_upgrade_preserves_receipts_and_task_links(env, monkeypatch):
    app = seed(env)
    sync(env, app, enable=True)
    old = read(env, app)
    engine = create_engine(str(env['engine'].url).replace('sqlite+aiosqlite:', 'sqlite:', 1))
    module = migration()
    try:
        with engine.begin() as conn:
            before = captured(conn)
            conn.exec_driver_sql('BEGIN IMMEDIATE')
            # Construct the old schema for this fixture only. The production
            # downgrade intentionally refuses every populated journal.
            with Operations.context(MigrationContext.configure(conn)) as operations:
                with operations.batch_alter_table('entry_deadline_revisions', recreate='always') as batch:
                    batch.drop_constraint('ck_entry_deadline_revision', type_='check')
                    batch.create_check_constraint('ck_entry_deadline_revision', 'revision BETWEEN 1 AND 250')
            assert 'BETWEEN 1 AND 250' in conn.scalar(text(
                "SELECT sql FROM sqlite_master WHERE name='entry_deadline_revisions'"))
            assert captured(conn) == before
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
            assert captured(conn) == before
            assert conn.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []
        assert read(env, app) == old
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                with pytest.raises(RuntimeError, match='preserve populated'):
                    module.downgrade()
            assert captured(conn) == before
        at_capacity(env, app, monkeypatch, 'count')
        write(env, app, 'clear', {'reason': 'wrong_document'})
        assert task_read(env, app)['current']['task']['status'] == 'cancelled'
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                with pytest.raises(RuntimeError, match='preserve populated'):
                    module.downgrade()
    finally:
        engine.dispose()


def test_sqlite_fk_on_connection_refuses_without_changes(env):
    app = seed(env)
    sync(env, app, enable=True)
    engine = create_engine(str(env['engine'].url).replace('sqlite+aiosqlite:', 'sqlite:', 1))
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql('PRAGMA foreign_keys=ON')
            conn.commit()
            before = captured(conn)
            schema = conn.scalar(text("SELECT sql FROM sqlite_master WHERE name='entry_deadline_revisions'"))
            with Operations.context(MigrationContext.configure(conn)):
                with pytest.raises(RuntimeError, match='dedicated SQLite'):
                    migration().upgrade()
            assert captured(conn) == before
            assert conn.scalar(text("SELECT sql FROM sqlite_master WHERE name='entry_deadline_revisions'")) == schema
    finally:
        engine.dispose()
