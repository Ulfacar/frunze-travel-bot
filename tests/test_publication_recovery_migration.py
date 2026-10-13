import importlib.util
from pathlib import Path

import pytest
from alembic import command
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from tests.test_knowledge_migration import config
from tests.test_admin_kg_entry import env
from tests.test_knowledge_publication import release, activate, publish, runtime

PREVIOUS = 'e6_deadline_clear_0033'
CURRENT = 'e6_publication_withdraw_0034'


def migration():
    spec = importlib.util.spec_from_file_location('publication_withdraw_migration',
        Path(__file__).resolve().parents[1]/'alembic/versions/e6_publication_withdraw_0034.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def captured(conn):
    return {table: [tuple(r) for r in conn.execute(text('SELECT * FROM '+table+' ORDER BY '+key))]
            for table, key in (('knowledge_publication_events', 'id'), ('knowledge_publication_units', 'event_id,unit_id'))}


def test_empty_sqlite_cycle(config):
    command.upgrade(config, PREVIOUS)
    command.upgrade(config, CURRENT)
    command.downgrade(config, PREVIOUS)
    command.upgrade(config, CURRENT)
    engine = create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.connect() as conn:
            assert conn.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []
            assert 'BETWEEN 1 AND 251' in conn.scalar(text("SELECT sql FROM sqlite_master WHERE name='knowledge_publication_events'"))
    finally: engine.dispose()


def test_populated_upgrade_preserves_journal_links_and_refuses_downgrade(release):
    activate(release)
    engine = create_engine(str(release['engine'].url).replace('sqlite+aiosqlite:', 'sqlite:', 1))
    try:
        with engine.begin() as conn:
            before = captured(conn)
            conn.exec_driver_sql('BEGIN IMMEDIATE')
            with Operations.context(MigrationContext.configure(conn)) as operations:
                with operations.batch_alter_table('knowledge_publication_events', recreate='always') as batch:
                    batch.drop_constraint('ck_knowledge_publication_revision', type_='check')
                    batch.create_check_constraint('ck_knowledge_publication_revision', 'revision BETWEEN 1 AND 250')
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)): migration().upgrade()
            assert captured(conn) == before
            assert conn.exec_driver_sql('PRAGMA foreign_key_check').fetchall() == []
        assert len(runtime(release)['available']) == 2
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                with pytest.raises(RuntimeError, match='preserve populated'): migration().downgrade()
            assert captured(conn) == before
        publish(release, 'withdraw')
        assert runtime(release)['version_id'] is None
    finally: engine.dispose()


def test_sqlite_fk_on_refuses_without_mutation(release):
    activate(release)
    engine = create_engine(str(release['engine'].url).replace('sqlite+aiosqlite:', 'sqlite:', 1))
    try:
        with engine.connect() as conn:
            conn.exec_driver_sql('PRAGMA foreign_keys=ON'); conn.commit()
            before = captured(conn)
            with Operations.context(MigrationContext.configure(conn)):
                with pytest.raises(RuntimeError, match='dedicated SQLite'): migration().upgrade()
            assert captured(conn) == before
    finally: engine.dispose()
