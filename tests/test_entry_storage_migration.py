"""E5-03C additive/recovery checks and complete synthetic rehearsal; no live DSN."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.domain.models import DomainBase, ENTRY_STORAGE_MODELS
from tests.test_knowledge_migration import config

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = 'e5_projection_0014'
CURRENT = 'e5_calculation_0015'
NEW = {m.__tablename__ for m in ENTRY_STORAGE_MODELS}


def snapshot(conn):
    return [(name, sql) for name, sql in conn.execute(text(
        'SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name'))
        if name not in NEW and name != 'uq_stay_history_open']


def test_additive_cycle_schema_parity_and_no_seed(config):
    command.upgrade(config, PREVIOUS)
    engine = create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.begin() as conn:
            conn.execute(text('INSERT INTO contacts (id, created_at, updated_at) VALUES (1,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)'))
            before = snapshot(conn)
            contact = tuple(conn.execute(text('SELECT * FROM contacts')).one())
        for operation, revision in [(command.upgrade, CURRENT), (command.downgrade, PREVIOUS), (command.upgrade, CURRENT)]:
            operation(config, revision)
            with engine.connect() as conn:
                assert snapshot(conn) == before
                assert tuple(conn.execute(text('SELECT * FROM contacts')).one()) == contact
                if revision == CURRENT:
                    assert all(conn.scalar(text(f'SELECT count(*) FROM {table}')) == 0 for table in NEW)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={'compare_type': True, 'compare_server_default': True,
                'include_object': lambda obj, name, kind, reflected, other: kind != 'table' or name in NEW})
            assert compare_metadata(context, DomainBase.metadata) == []
    finally:
        engine.dispose()


def test_populated_downgrade_refuses_before_any_table_drop(config):
    command.upgrade(config, CURRENT)
    engine = create_engine(config.get_main_option('sqlalchemy.url'))
    try:
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO work_calendars (jurisdiction,year,version,status,content_hash,document,created_by,created_at) "
                "VALUES ('KG',2026,1,'draft',:hash,'{}','synthetic',CURRENT_TIMESTAMP)"), {'hash': '0'*64})
        with pytest.raises(RuntimeError, match='preserve populated'):
            command.downgrade(config, PREVIOUS)
        with engine.connect() as conn:
            assert NEW.issubset(inspect(conn).get_table_names())
            assert conn.scalar(text('SELECT count(*) FROM work_calendars')) == 1
            assert conn.scalar(text('SELECT version_num FROM alembic_version')) == CURRENT
    finally:
        engine.dispose()


def test_postgresql_ddl_scoped_fks_and_partial_index(config):
    config.set_main_option('sqlalchemy.url', 'postgresql+asyncpg://localhost/unused')
    config.output_buffer = io.StringIO()
    command.upgrade(config, f'{PREVIOUS}:{CURRENT}', sql=True)
    ddl = config.output_buffer.getvalue()
    assert ddl.count('CREATE TABLE ') == 7
    assert 'FOREIGN KEY(history_id, contact_id) REFERENCES stay_histories (id, contact_id)' in ddl
    assert 'FOREIGN KEY(interval_id, history_id) REFERENCES stay_intervals (id, history_id)' in ddl
    assert 'FOREIGN KEY(calculation_id, history_id) REFERENCES entry_calculations (id, history_id)' in ddl
    assert 'CREATE UNIQUE INDEX uq_stay_history_open ON stay_intervals (history_id) WHERE exit_date IS NULL' in ddl
    assert all(word not in ddl for word in ('ALTER TABLE', 'DROP TABLE', 'DELETE FROM', 'INSERT INTO'))
    with pytest.raises(RuntimeError, match='offline downgrade'):
        command.downgrade(config, f'{CURRENT}:{PREVIOUS}', sql=True)


def test_cli_synthetic_replay_ignores_ambient_dsn_and_refuses_existing(tmp_path):
    path = tmp_path / 'rehearsal.sqlite3'
    args = [sys.executable, '-X', 'utf8', str(ROOT/'scripts/rehearse_kg_calculations.py'), '--db', str(path)]
    env = {**os.environ, 'ALEMBIC_DATABASE_URL': 'invalid://must-not-be-used', 'DATABASE_URL': 'invalid://must-not-be-used'}
    first = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, encoding='utf-8', timeout=60)
    assert first.returncode == 0, first.stdout + first.stderr
    result = json.loads(first.stdout)
    assert result['replay_verified'] and result['may_quote'] is False
    assert result['exact_deadline'] is None and result['exact_remaining_days'] is None
    assert result['stay_scenario_presence_days'] == 6 and result['deadline_scenario_due'] == '2026-10-08'
    assert result['counts'] == dict(zip([m.__tablename__ for m in ENTRY_STORAGE_MODELS], [1,1,2,6,2,1,2]))
    original = path.read_bytes()
    again = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, encoding='utf-8', timeout=30)
    assert again.returncode == 1 and json.loads(again.stdout)['ok'] is False
    assert path.read_bytes() == original
