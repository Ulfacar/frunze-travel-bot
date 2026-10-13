"""Actual isolated PostgreSQL parity for deadline task review regressions."""
import pytest
from tests.test_entry_process_postgres import template, env
from tests import test_entry_deadline_task_integrity as cases


@pytest.mark.parametrize('scenario', [
    cases.test_restore_form_rejects_unseen_new_source,
    cases.test_binding_audit_rejects_boolean_identity,
    cases.test_existing_action_retry_rejects_typed_receipt_corruption,
    cases.test_generic_calendar_refuses_claimed_deadline_cancellation,
    cases.test_missing_bound_task_pointer_fails_closed_without_duplicate,
    cases.test_active_binding_cannot_be_replaced_by_null_waiting_pair,
    cases.test_stale_restore_owner_change_requires_fresh_consent,
])
def test_review_regression(env, scenario): scenario(env)


def test_actual_calendar_source_cancel_race(env,monkeypatch):
    cases.calendar_cancellation_race(env,monkeypatch)


@pytest.mark.parametrize('action',['complete','cancel'])
def test_terminal_capacity(env,monkeypatch,action):
    cases.test_escalation_capacity_preserves_terminal_action(env,monkeypatch,action)


@pytest.mark.parametrize('mode',['unknown_date','missing_owner'])
def test_legitimate_waiting(env,mode):
    cases.test_legitimate_no_task_waiting_remains_readable_and_idempotent(env,mode)


@pytest.mark.parametrize('field',['binding','deadline','task'])
def test_integral_float_audit(env,field):
    cases.test_binding_audit_rejects_integral_float_identity(env,field)


@pytest.mark.parametrize('writer',['calendar','conversation'])
@pytest.mark.parametrize('action',['complete','cancel','reschedule'])
def test_claimed_writers(env,writer,action):
    cases.test_both_calendar_writers_refuse_claimed_bound_task(env,writer,action)
