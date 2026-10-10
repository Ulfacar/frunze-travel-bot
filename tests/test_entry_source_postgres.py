"""Opt-in exact connected source scenarios on isolated migrated local PG."""
import pytest

from tests.test_entry_process_postgres import template,env
from tests.test_entry_interviews import admins
from tests.test_entry_channel_stops import activation
from tests.test_entry_source_scenarios import source_review
from tests import test_entry_source_scenarios as cases


def test_connected_visa_to_aftercare(env):
    cases.test_source_19_visa_same_subject_through_handoff_quote_rework_portal_and_aftercare(env)


def test_connected_registration(env):
    cases.test_source_registration_same_subject_certificate_requires_separate_decision(env)


@pytest.mark.parametrize('name',cases.B8)
def test_source_b8_uncertainty(env,source_review,name):
    cases.test_exact_b8_facts_survive_handoff_and_unapproved_source_never_becomes_advice(env,source_review,name)
