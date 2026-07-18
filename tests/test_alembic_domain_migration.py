"""WP1M: Alembic foundation + domain schema migration tests.

Validates the additive ``wp1a_domain_0001`` revision end-to-end on a throwaway
SQLite database (the WP0 network guard stays active — nothing here touches the
external network; SQLite file access is local disk, not a socket).

A PostgreSQL tier runs the same structural checks plus DB-level enforcement of
the partial unique indexes, but ONLY when ``TEST_POSTGRES_DSN`` is set. Without
it the PG tier is honestly skipped:

    POSTGRESQL VALIDATION SKIPPED — REQUIRED BEFORE PRODUCTION ROLLOUT

The migration is NOT run against production, and no Docker image is pulled.
"""
from __future__ import annotations

import asyncio
import os
import pathlib

import pytest
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from alembic.config import Config

from app.domain.models import (
    Assignment, Contact, DomainBase, reassign_manager,
)
from app.integrations.crm.db import Base as LegacyBase

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]

DOMAIN_TABLES = {
    "contacts", "contact_identities", "requests", "dialogs",
    "assignments", "external_references",
}
LEGACY_TABLES = {
    "deals", "conversations", "messages", "audit_log", "app_flags", "faq_entries",
}
PARTIAL_UNIQUE_INDEXES = {
    "uq_active_request_per_contact_direction",
    "uq_active_assignment_per_contact_direction",
    "uq_active_external_reference",
}


def _alembic_cfg(db_url: str) -> Config:
    cfg = Config(str(REPO_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


@pytest.fixture()
def sqlite_url(tmp_path, monkeypatch):
    """A clean, throwaway file-backed SQLite DB (sync driver → env.py sync path)."""
    # Do not let an ambient env var override the per-test URL.
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    db_file = tmp_path / "wp1m.db"
    return f"sqlite:///{db_file.as_posix()}"


def _table_names(url: str) -> set[str]:
    eng = create_engine(url)
    try:
        return set(inspect(eng).get_table_names())
    finally:
        eng.dispose()


# --- structural: target_metadata scope ----------------------------------------

def test_target_metadata_is_limited_to_domain_base():
    # DomainBase carries exactly the six new tables and NONE of the legacy ones.
    assert set(DomainBase.metadata.tables) == DOMAIN_TABLES
    assert set(DomainBase.metadata.tables).isdisjoint(LEGACY_TABLES)
    # Legacy tables live on a separate metadata (never seen by Alembic).
    assert LEGACY_TABLES.issubset(set(LegacyBase.metadata.tables))
    # env.py binds target_metadata to DomainBase.metadata (and nothing else).
    env_src = (REPO_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "target_metadata = DomainBase.metadata" in env_src


# --- upgrade / tables ----------------------------------------------------------

def test_upgrade_head_creates_all_six_domain_tables(sqlite_url):
    command.upgrade(_alembic_cfg(sqlite_url), "head")
    tables = _table_names(sqlite_url)
    assert DOMAIN_TABLES.issubset(tables)
    assert "alembic_version" in tables


def test_upgrade_does_not_create_any_legacy_table(sqlite_url):
    command.upgrade(_alembic_cfg(sqlite_url), "head")
    tables = _table_names(sqlite_url)
    # Only the six domain tables (+ alembic bookkeeping). No legacy table.
    assert tables.isdisjoint(LEGACY_TABLES)
    assert tables == DOMAIN_TABLES | {"alembic_version"}


def test_key_indexes_and_constraints_present(sqlite_url):
    command.upgrade(_alembic_cfg(sqlite_url), "head")
    eng = create_engine(sqlite_url)
    try:
        insp = inspect(eng)

        # Partial unique indexes exist on their tables.
        req_idx = {i["name"] for i in insp.get_indexes("requests")}
        asg_idx = {i["name"] for i in insp.get_indexes("assignments")}
        ext_idx = {i["name"] for i in insp.get_indexes("external_references")}
        assert "uq_active_request_per_contact_direction" in req_idx
        assert "uq_active_assignment_per_contact_direction" in asg_idx
        assert "uq_active_external_reference" in ext_idx

        # Simple secondary indexes from index=True.
        assert "ix_requests_contact_id" in req_idx
        assert "ix_assignments_contact_id" in asg_idx
        ci_idx = {i["name"] for i in insp.get_indexes("contact_identities")}
        assert "ix_contact_identities_contact_id" in ci_idx
        assert "ix_contact_identities_normalized_value" in ci_idx

        # Named composite unique constraint on identities.
        ci_uq = {u["name"] for u in insp.get_unique_constraints("contact_identities")}
        assert "uq_contact_identity_normalized" in ci_uq

        # Foreign keys wire the graph together.
        assert any(fk["referred_table"] == "contacts"
                   for fk in insp.get_foreign_keys("requests"))
        assert any(fk["referred_table"] == "requests"
                   for fk in insp.get_foreign_keys("external_references"))

        # The partial predicate is actually present in the DDL (SQLite exposes it).
        rows = eng.connect().execute(text(
            "select name, sql from sqlite_master where type='index' "
            "and name in ('uq_active_request_per_contact_direction',"
            "'uq_active_assignment_per_contact_direction',"
            "'uq_active_external_reference')")).all()
        ddl = {name: sql for name, sql in rows}
        assert "WHERE closed_at IS NULL" in ddl["uq_active_request_per_contact_direction"]
        assert "WHERE active = 1" in ddl["uq_active_assignment_per_contact_direction"]
        assert "WHERE active = 1" in ddl["uq_active_external_reference"]
    finally:
        eng.dispose()


# --- downgrade / re-upgrade ----------------------------------------------------

def test_downgrade_base_removes_only_domain_tables(sqlite_url):
    cfg = _alembic_cfg(sqlite_url)
    command.upgrade(cfg, "head")
    assert DOMAIN_TABLES.issubset(_table_names(sqlite_url))
    command.downgrade(cfg, "base")
    remaining = _table_names(sqlite_url)
    # All six domain tables gone; only alembic bookkeeping remains.
    assert remaining.isdisjoint(DOMAIN_TABLES)
    assert remaining <= {"alembic_version"}


def test_repeat_upgrade_after_downgrade_works(sqlite_url):
    cfg = _alembic_cfg(sqlite_url)
    command.upgrade(cfg, "head")
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")  # must not raise (deterministic, idempotent path)
    assert DOMAIN_TABLES.issubset(_table_names(sqlite_url))


# --- reassignment flush ordering (section 3 proof) ----------------------------

def test_reassignment_flushes_deactivation_before_insert(sqlite_url):
    """Against the migration-created schema (real partial unique index), a peer
    reassignment must (a) not violate the one-active-assignment index and (b) emit
    the deactivation UPDATE strictly before the new-row INSERT — proving the
    explicit ``await session.flush()`` in reassign_manager orders the writes."""
    command.upgrade(_alembic_cfg(sqlite_url), "head")
    async_url = sqlite_url.replace("sqlite://", "sqlite+aiosqlite://")

    emitted: list[str] = []

    async def scenario():
        engine = create_async_engine(async_url)

        @event.listens_for(engine.sync_engine, "before_cursor_execute")
        def _record(conn, cursor, statement, params, ctx, executemany):
            s = statement.lstrip().upper()
            if "ASSIGNMENTS" in s and (s.startswith("UPDATE") or s.startswith("INSERT")):
                emitted.append(s.split(None, 1)[0])

        sm = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with sm() as s:
                c = Contact()
                s.add(c)
                await s.flush()
                await reassign_manager(s, c.id, "visa", "medina", assigned_by="system")
                emitted.clear()  # ignore the first INSERT; watch the reassignment only
                a2 = await reassign_manager(
                    s, c.id, "visa", "eliza", assigned_by="admin",
                    reason="vacation", allow_emergency=True)
                await s.commit()
                assert a2.revision == 2 and a2.active is True
            # Re-open to assert exactly one active row survived the DB index.
            async with sm() as s:
                from sqlalchemy import select
                active = (await s.scalars(select(Assignment).where(
                    Assignment.contact_id == c.id, Assignment.active.is_(True)))).all()
                assert len(active) == 1 and active[0].manager_id == "eliza"
        finally:
            await engine.dispose()

    asyncio.run(scenario())

    # The deactivation UPDATE was emitted before the new active INSERT.
    assert emitted == ["UPDATE", "INSERT"], emitted


def test_dialog_unique_index_present_after_upgrade(sqlite_url):
    """WP1B revision wp1b_dialog_uidx_0002 adds the DB-level Dialog idempotency index
    on (channel, bot_id, channel_key)."""
    command.upgrade(_alembic_cfg(sqlite_url), "head")
    eng = create_engine(sqlite_url)
    try:
        idx = {i["name"]: i for i in inspect(eng).get_indexes("dialogs")}
        assert "uq_dialog_channel_bot_key" in idx
        assert idx["uq_dialog_channel_bot_key"]["unique"]
        assert idx["uq_dialog_channel_bot_key"]["column_names"] == [
            "channel", "bot_id", "channel_key"]
    finally:
        eng.dispose()


# =====================================================================
# PostgreSQL tier — only with TEST_POSTGRES_DSN; otherwise honestly skipped.
# =====================================================================

_PG_DSN = os.environ.get("TEST_POSTGRES_DSN")
_pg_reason = ("POSTGRESQL VALIDATION SKIPPED — REQUIRED BEFORE PRODUCTION ROLLOUT "
              "(set TEST_POSTGRES_DSN to a dedicated, non-production test database)")


def _normalize_async_pg(dsn: str) -> str:
    if dsn.startswith("postgresql+asyncpg://"):
        return dsn
    if dsn.startswith("postgresql://"):
        return "postgresql+asyncpg://" + dsn[len("postgresql://"):]
    if dsn.startswith("postgres://"):
        return "postgresql+asyncpg://" + dsn[len("postgres://"):]
    return dsn


@pytest.mark.skipif(not _PG_DSN, reason=_pg_reason)
class TestPostgresTier:
    """Runs only when a dedicated Postgres test DSN is provided (loopback stays
    allowed by the WP0 guard; a remote DSN would be blocked — as intended)."""

    def _cfg(self):
        return _alembic_cfg(_normalize_async_pg(_PG_DSN))

    def test_upgrade_downgrade_reupgrade(self):
        cfg = self._cfg()
        command.upgrade(cfg, "head")
        try:
            command.downgrade(cfg, "base")
            command.upgrade(cfg, "head")
        finally:
            command.downgrade(cfg, "base")

    def test_db_level_partial_unique_and_types(self):
        cfg = self._cfg()
        command.upgrade(cfg, "head")
        async_url = _normalize_async_pg(_PG_DSN)

        async def scenario():
            from sqlalchemy import select
            from app.domain.models import (
                Request, ExternalReference, open_request,
            )
            engine = create_async_engine(async_url)
            sm = async_sessionmaker(engine, expire_on_commit=False)
            try:
                async with sm() as s:
                    c = Contact()
                    s.add(c)
                    await s.flush()

                    # UUID/timestamp compatibility: request_id is a uuid hex str,
                    # timestamps come back tz-aware from now().
                    r = await open_request(s, c.id, "tours")
                    await s.flush()
                    assert len(r.request_id) == 32
                    assert r.created_at is not None

                    # DB-level: a second ACTIVE request for the same direction fails.
                    s.add(Request(contact_id=c.id, direction="tours"))
                    with pytest.raises(IntegrityError):
                        await s.flush()
                    await s.rollback()

                async with sm() as s:
                    c2 = Contact()
                    s.add(c2)
                    await s.flush()
                    s.add(Assignment(contact_id=c2.id, direction="tours",
                                     manager_id="ademi", active=True))
                    s.add(Assignment(contact_id=c2.id, direction="tours",
                                     manager_id="sezim", active=True))
                    with pytest.raises(IntegrityError):
                        await s.flush()
                    await s.rollback()

                async with sm() as s:
                    c3 = Contact()
                    s.add(c3)
                    await s.flush()
                    r3 = await open_request(s, c3.id, "visa")
                    await s.flush()
                    s.add(ExternalReference(provider="bitrix", external_type="deal",
                                            external_id="D-1", request_ref=r3.id,
                                            direction="visa", active=True))
                    s.add(ExternalReference(provider="bitrix", external_type="deal",
                                            external_id="D-1", request_ref=r3.id,
                                            direction="visa", active=True))
                    with pytest.raises(IntegrityError):
                        await s.flush()
                    await s.rollback()
            finally:
                await engine.dispose()

        try:
            asyncio.run(scenario())
        finally:
            command.downgrade(cfg, "base")
