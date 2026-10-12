"""Actual PostgreSQL at the isolated localhost opt-in boundary."""
import asyncio

import pytest
from alembic import command
from alembic.config import Config
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import text
from types import SimpleNamespace

from app.domain.models import DomainBase
from tests.test_entry_process_postgres import connection, database, db_url, template, env
from tests.test_knowledge_publication import release, activate, publish, runtime
from tests import test_publication_recovery as cases
from tests.test_admin_kg_knowledge_publication import publisher
from tests import test_admin_publication_recovery as native


@pytest.mark.parametrize('delta', [-1, 0])
def test_review_clock(release, monkeypatch, delta):
    cases.test_new_review_must_be_strictly_after_last_publication(release, monkeypatch, delta)


def test_review_retry(release, monkeypatch):
    cases.test_review_retry_survives_clock_rollback_and_new_clock_is_checked(release, monkeypatch)


def test_publication_clock(release, monkeypatch):
    cases.test_publication_review_must_not_pin_a_future_decision(release, monkeypatch)


def test_terminal_bytes(release, monkeypatch):
    cases.test_legacy_byte_full_history_can_withdraw_once(release, monkeypatch)


def test_terminal_251_and_metadata(release):
    cases.test_real_250_event_history_withdraws_at_251(release)
    async def check():
        async with release['engine'].connect() as conn:
            def compare(sync):
                assert compare_metadata(MigrationContext.configure(sync), DomainBase.metadata) == []
            await conn.run_sync(compare)
            assert await conn.scalar(text("SELECT version_num FROM alembic_version")) == 'e6_publication_withdraw_0034'
    asyncio.run(check())


@pytest.mark.parametrize('bound', ['count', 'bytes'])
def test_native_terminal(publisher, monkeypatch, bound):
    native.test_native_withdrawal_at_capacity_and_exact_retry(publisher, monkeypatch, bound)


def test_native_large_publication(publisher, tmp_path):
    native.test_native_withdraws_full_101_unit_manifest_using_bounded_selection(publisher, tmp_path)


def test_native_delayed_retry(publisher):
    native.test_original_native_withdrawal_retry_after_manifest_replacement(publisher)


def migration_config(env):
    cfg = Config('alembic.ini')
    cfg.cmd_opts = SimpleNamespace(x=['dburl='+env['engine'].url.render_as_string(hide_password=False)])
    return cfg


def test_migration_empty_cycle_and_populated_downgrade_refusal(env, tmp_path):
    cfg = migration_config(env)
    command.downgrade(cfg, 'e6_deadline_clear_0033')
    command.upgrade(cfg, 'head')
    from tests.test_knowledge_publication import load_source
    env['release'] = load_source(env, tmp_path)
    activate(env)
    before = runtime(env)
    with pytest.raises(RuntimeError, match='preserve populated'):
        command.downgrade(cfg, 'e6_deadline_clear_0033')
    after = runtime(env)
    assert after['version_id'] == before['version_id']
    assert [{k:v for k,v in u.items() if k != 'checked_at'} for u in after['available']] == [
        {k:v for k,v in u.items() if k != 'checked_at'} for u in before['available']]
    publish(env, 'withdraw')
    assert runtime(env)['version_id'] is None
