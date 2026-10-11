"""Actual isolated PostgreSQL parity for typed corruption and valid receipts."""
import pytest

from tests.test_entry_process_postgres import template,env
from tests.test_entry_interviews import admins
from tests import test_entry_typed_integrity as cases


@pytest.mark.parametrize('kind',cases.CANDIDATES)
@pytest.mark.parametrize('substitution',['coercible_bool_number','coercible_float'])
def test_typed_integrity(env,kind,substitution):
    cases.test_rehashed_json_coercion_is_rejected(env,kind,substitution)


def test_qualification_float_and_old_receipt(env,monkeypatch):
    cases.test_writer_accepted_integral_float_keeps_qualification_receipt_and_retry(env,monkeypatch)


@pytest.mark.parametrize('column',['knowledge_version_id','anchor_event_id','anchor_issued_id'])
def test_deadline_float_and_old_receipt(env,monkeypatch,column):
    cases.test_writer_accepted_integral_float_keeps_deadline_receipt_and_retry(env,monkeypatch,column)


@pytest.mark.parametrize('scenario',[
    cases.documents.test_retry_payload_conflict_stale_and_terminal_application,
    cases.issued.test_approval_scope_authorization_and_exact_retry,
    cases.processes.test_explicit_edges_manual_evidence_exact_retry_and_history,
    cases.interviews.test_language_pause_resume_unknown_and_old_start_retry,
    cases.deadlines.test_duplicate_requests_cas_and_person_scope,
])
def test_healthy_journal_operations(env,scenario):
    scenario(env)


def test_healthy_portal_operations(env):
    cases.portal.test_five_receipts_do_not_change_fact_until_separate_verified_confirmation(env,'correction')
