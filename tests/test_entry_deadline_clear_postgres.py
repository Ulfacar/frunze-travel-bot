"""Actual isolated PostgreSQL withdrawal parity."""
import pytest
from tests.test_entry_process_postgres import template, env
from tests import test_entry_deadline_clear_capacity as cases


@pytest.mark.parametrize('bound', ['count', 'bytes'])
def test_terminal_clear(env, monkeypatch, bound):
    cases.test_terminal_clear_preserves_receipts_and_cancels_task(env, monkeypatch, bound)


@pytest.mark.parametrize('bound', ['count', 'bytes'])
def test_native_clear(env, monkeypatch, bound):
    cases.test_native_capacity_clear_and_terminal_history(env, monkeypatch, bound)


def test_atomic_rollback(env, monkeypatch):
    cases.test_clear_and_task_cancellation_roll_back_together(env, monkeypatch)
