"""Opt-in local PostgreSQL typed profile integrity and unaffected retry/isolation."""
import pytest

from tests.test_entry_process_postgres import template,env
from tests import test_applicant_profiles as cases


@pytest.mark.parametrize('area,key,kind',cases.TYPE_COERCION_CASES)
def test_strict_typed_profile_integrity(env,area,key,kind):
    cases.test_rehashed_json_type_coercion_never_passes_integrity_checks(env,area,key,kind)


def test_old_receipt_retry_and_runtime_change(env,monkeypatch):
    cases.test_bounded_history_and_runtime_upgrade_preserve_read_but_refuse_replay(env,monkeypatch)


def test_payer_family_and_applicant_isolation(env):
    cases.test_people_never_inherit_payer_or_family_answers_and_applications_keep_identity(env)


def test_concurrent_successors(env):
    cases.test_concurrent_writers_create_only_one_successor(env)
