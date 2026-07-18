"""Alembic migration environment for the WP1A domain schema (WP1M).

Design constraints (WP1M):

* ``target_metadata`` is **only** ``DomainBase.metadata`` — the six new domain
  tables. The legacy runtime schema (deals / conversations / messages / … under
  ``app.integrations.crm.db.Base``) is intentionally excluded, so Alembic never
  creates, drops, or reports drift on legacy tables and never treats the legacy
  schema as "already migrated".
* The database URL is provided **explicitly** and never guessed. Resolution order:
    1. ``alembic -x dburl=<url>``
    2. ``ALEMBIC_DATABASE_URL`` environment variable
    3. ``sqlalchemy.url`` in alembic.ini (blank by default)
  If none is set, we raise instead of silently touching a default/production DB.
* The production ``.env`` is NOT auto-loaded. We import only
  ``app.domain.models.DomainBase`` (pure SQLAlchemy models, no app.config /
  pydantic settings), so importing this env never reads secrets.
* Both async (``+asyncpg`` / ``+aiosqlite``) and sync (``sqlite://`` /
  ``postgresql://``) SQLAlchemy URLs are supported.
"""
from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection, make_url

from alembic import context

# Domain metadata ONLY. Importing app.domain.models does not import app.config,
# so no .env / secrets are read here.
from app.domain.models import DomainBase

config = context.config

# Standard alembic logging setup (guarded — the config file is always present here).
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The one and only metadata Alembic manages. Legacy tables live elsewhere and are
# NOT included, by design.
target_metadata = DomainBase.metadata


def _resolve_url() -> str:
    """Resolve the database URL explicitly; refuse to guess production."""
    x_args = context.get_x_argument(as_dictionary=True)
    if x_args.get("dburl"):
        return x_args["dburl"]
    env_url = os.environ.get("ALEMBIC_DATABASE_URL")
    if env_url:
        return env_url
    ini_url = config.get_main_option("sqlalchemy.url")
    if ini_url:
        return ini_url
    raise RuntimeError(
        "No database URL configured. Set ALEMBIC_DATABASE_URL or pass "
        "`-x dburl=<url>`; env.py refuses to guess a default/production DSN."
    )


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        # Detect column type changes and server-default changes if we ever
        # autogenerate against this schema in the future.
        compare_type=True,
        compare_server_default=True,
        # Render batch ops so SQLite (no ALTER for constraints) stays supported
        # for any future ALTER-style migration; harmless for the additive create.
        render_as_batch=True,
        **kwargs,
    )


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a DBAPI connection (``alembic upgrade --sql``)."""
    url = _resolve_url()
    _configure(url=url, literal_binds=True, dialect_opts={"paramstyle": "named"})
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection=connection)
    with context.begin_transaction():
        context.run_migrations()


async def _run_async_migrations(url: str) -> None:
    from sqlalchemy.ext.asyncio import create_async_engine

    connectable = create_async_engine(url, poolclass=pool.NullPool)
    try:
        async with connectable.connect() as connection:
            await connection.run_sync(_do_run_migrations)
    finally:
        await connectable.dispose()


def _run_sync_migrations(url: str) -> None:
    from sqlalchemy import create_engine

    connectable = create_engine(url, poolclass=pool.NullPool)
    try:
        with connectable.connect() as connection:
            _do_run_migrations(connection)
    finally:
        connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations against a live connection (sync or async driver)."""
    url = _resolve_url()
    if make_url(url).get_dialect().is_async:
        asyncio.run(_run_async_migrations(url))
    else:
        _run_sync_migrations(url)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
