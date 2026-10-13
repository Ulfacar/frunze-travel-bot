"""Additive migration, recovery, schema parity, local CLI (no production DSN)."""
from __future__ import annotations

import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.domain.models import DomainBase

ROOT = Path(__file__).resolve().parents[1]
PREVIOUS = "e2_taskclaim_0012"
CURRENT = "e5_knowledge_0013"
NEW = {"knowledge_sets", "knowledge_versions", "knowledge_units", "knowledge_imports"}


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{(tmp_path / 'migration.sqlite3').as_posix()}")
    return cfg


def schema(connection):
    return dict(connection.execute(text(
        "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL "
        "AND name NOT LIKE 'knowledge_%' AND name NOT LIKE 'uq_knowledge_%'"
    )).all())


def test_migration_cycle_preserves_existing_schema_and_data(config):
    command.upgrade(config, PREVIOUS)
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO contacts(id) VALUES (12345)"))
            before = schema(connection)
        for operation, revision in ((command.upgrade, CURRENT), (command.downgrade, PREVIOUS), (command.upgrade, CURRENT)):
            operation(config, revision)
            with engine.connect() as connection:
                assert schema(connection) == before
                assert connection.scalar(text("SELECT id FROM contacts WHERE id=12345")) == 12345
                actual = set(inspect(connection).get_table_names())
                assert NEW.issubset(actual) if operation == command.upgrade else NEW.isdisjoint(actual)
        with engine.connect() as connection:
            context = MigrationContext.configure(connection, opts={
                "compare_type": True, "compare_server_default": True,
                "include_object": lambda obj, name, kind, reflected, compare_to: kind != "table" or name in NEW,
            })
            assert compare_metadata(context, DomainBase.metadata) == []
            assert connection.scalar(text("SELECT count(*) FROM knowledge_sets")) == 0
    finally:
        engine.dispose()


def test_populated_downgrade_refuses_before_any_drop(config):
    command.upgrade(config, CURRENT)
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as connection:
            connection.execute(text("INSERT INTO knowledge_sets (code,jurisdiction,domain,name,created_at,updated_at) "
                                    "VALUES ('test','KG','entry','Test',CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"))
        with pytest.raises(RuntimeError, match="preserve populated"):
            command.downgrade(config, PREVIOUS)
        with engine.connect() as connection:
            assert NEW.issubset(inspect(connection).get_table_names())
            assert connection.scalar(text("SELECT count(*) FROM knowledge_sets")) == 1
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == CURRENT
    finally:
        engine.dispose()


def test_postgresql_ddl_is_additive_and_has_required_constraints(config):
    # DDL compilation is NOT evidence of PostgreSQL runtime/concurrency behavior.
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://localhost/unused")
    config.output_buffer = io.StringIO()
    command.upgrade(config, f"{PREVIOUS}:{CURRENT}", sql=True)
    ddl = config.output_buffer.getvalue()
    assert "JSONB" not in ddl and "value JSON" in ddl
    assert ddl.count("CREATE TABLE knowledge_") == 4
    assert all(word not in ddl for word in ("ALTER TABLE", "DROP TABLE", "DELETE FROM"))
    assert "FOREIGN KEY(active_version_id, id) REFERENCES knowledge_versions (id, set_id)" in ddl
    assert "value IS NULL AND blocked_value IS NOT NULL" in ddl
    assert "WHERE status = 'active'" in ddl
    assert "UNIQUE (set_id, bundle_hash)" in ddl


def test_local_cli_ignores_ambient_dsn_and_repeats_without_duplicate(tmp_path):
    env = {**os.environ, "ALEMBIC_DATABASE_URL": "postgresql+asyncpg://invalid.invalid/must_not_connect", "PYTHONIOENCODING": "utf-8"}
    args = [sys.executable, "scripts/import_kg_entry_local.py", "--db", str(tmp_path / "demo.sqlite3"),
            "--bundle", "tests/fixtures/kg_entry/synthetic_bundle", "--source", "tests/fixtures/kg_entry/synthetic_source.txt"]
    outputs = []
    for _ in range(2):
        result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=40)
        assert result.returncode == 0, result.stdout + result.stderr
        outputs.append(json.loads(result.stdout))
    assert outputs[0]["version_id"] == outputs[1]["version_id"]
    assert not outputs[0]["reused"] and outputs[1]["reused"]
    assert outputs[0]["report"]["activated"] is False


def test_local_cli_does_not_migrate_existing_unknown_file(tmp_path):
    database = tmp_path / "unrelated.sqlite3"
    database.write_bytes(b"this is not a knowledge database")
    result = subprocess.run([sys.executable, "scripts/import_kg_entry_local.py", "--db", str(database),
                             "--bundle", "missing", "--source", "missing"], cwd=ROOT,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 2
    assert database.read_bytes() == b"this is not a knowledge database"
