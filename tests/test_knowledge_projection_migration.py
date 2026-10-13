"""Additive migration and guarded recovery of projection tables; isolated DB only."""
import io
import sqlite3

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, inspect, text

from app.domain.models import DomainBase
from scripts.import_kg_entry_local import prepare_database
from tests.test_knowledge_migration import config

PREVIOUS = "e5_knowledge_0013"
CURRENT = "e5_projection_0014"
NEW = {"knowledge_projections", "knowledge_country_links", "knowledge_condition_links"}


def snapshot(connection):
    return [(name, sql) for name, sql in connection.execute(text(
        "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY name")) if name not in NEW]


def insert_old_version(connection):
    connection.execute(text("INSERT INTO knowledge_versions (id,set_id,version,status,source_document,source_hash,"
        "bundle_hash,source_prepared_by,created_by,created_at,bundle_meta,country_aliases,import_report) "
        "VALUES (1,1,1,'draft','Synthetic',:hash,:hash,'test','test',CURRENT_TIMESTAMP,'{}','{}','{}')"),
        {"hash": "1" * 64})


def test_additive_cycle_keeps_historical_versions_without_backfill(config):
    command.upgrade(config, PREVIOUS)
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as conn:
            insert_old_version(conn)
            before = snapshot(conn)
            before_version = tuple(conn.execute(text("SELECT * FROM knowledge_versions")).one())
        for operation, revision in [(command.upgrade, CURRENT), (command.downgrade, PREVIOUS), (command.upgrade, CURRENT)]:
            operation(config, revision)
            with engine.connect() as conn:
                assert snapshot(conn) == before
                assert tuple(conn.execute(text("SELECT * FROM knowledge_versions")).one()) == before_version
                if revision == CURRENT:
                    assert all(conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0 for table in NEW)
        with engine.connect() as conn:
            context = MigrationContext.configure(conn, opts={"compare_type": True, "compare_server_default": True,
                "include_object": lambda obj, name, kind, reflected, other: kind != "table" or name in NEW})
            assert compare_metadata(context, DomainBase.metadata) == []
    finally:
        engine.dispose()


def test_populated_downgrade_checks_before_first_drop(config):
    command.upgrade(config, CURRENT)
    engine = create_engine(config.get_main_option("sqlalchemy.url"))
    try:
        with engine.begin() as conn:
            insert_old_version(conn)
            conn.execute(text("INSERT INTO knowledge_projections VALUES (1,1,:hash,NULL,'{}',NULL)"), {"hash": "1" * 64})
        with pytest.raises(RuntimeError, match="preserve populated"):
            command.downgrade(config, PREVIOUS)
        with engine.connect() as conn:
            assert NEW.issubset(inspect(conn).get_table_names())
            assert conn.scalar(text("SELECT count(*) FROM knowledge_projections")) == 1
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == CURRENT
    finally:
        engine.dispose()


def test_postgresql_compilation_has_scoped_foreign_keys_and_no_data_mutation(config):
    config.set_main_option("sqlalchemy.url", "postgresql+asyncpg://localhost/unused")
    config.output_buffer = io.StringIO()
    command.upgrade(config, f"{PREVIOUS}:{CURRENT}", sql=True)
    ddl = config.output_buffer.getvalue()
    assert ddl.count("CREATE TABLE knowledge_") == 3
    assert ddl.count("FOREIGN KEY(version_id, unit_id) REFERENCES knowledge_units (version_id, unit_id)") == 2
    assert all(word not in ddl for word in ("ALTER TABLE", "DROP TABLE", "DELETE FROM", "INSERT INTO knowledge_"))
    assert "condition_catalog JSON" in ddl
    # Compilation is not PostgreSQL runtime or concurrency evidence.
    with pytest.raises(RuntimeError, match="offline downgrade"):
        command.downgrade(config, f"{CURRENT}:{PREVIOUS}", sql=True)


def test_local_cli_refuses_to_upgrade_existing_old_database(config):
    command.upgrade(config, PREVIOUS)
    database = config.get_main_option("sqlalchemy.url").removeprefix("sqlite:///")
    with sqlite3.connect(database) as conn:
        before = conn.iterdump()
        old_dump = list(before)
    from pathlib import Path
    with pytest.raises(ValueError, match="different migration revision"):
        prepare_database(Path(database))
    with sqlite3.connect(database) as conn:
        assert list(conn.iterdump()) == old_dump
