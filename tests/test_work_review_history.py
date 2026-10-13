"""Keep historical validation separate from mutable task projection validation."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.domain import work_review_tasks as service, knowledge_decisions, applicant_profiles
from app.domain.entry_storage import EntryStorageInvalid, _hash
from tests import test_work_review_tasks as baseline
from tests.test_work_review_tasks import (
    env, clock, review_clock, connected_clock, route_clock, admins, enforce_sqlite_foreign_keys,
)
from tests.test_work_review_regressions import rewrite
from tests.test_knowledge_decisions import write as source_review, data as source_data
from tests.test_applicant_profiles import save as profile_save


@pytest.mark.parametrize('field', ['nested_calendar', 'typed_person_scope'])
def test_exact_retry_verifies_nested_evidence_without_mutable_task_audit(env, tmp_path, field):
    baseline.setup(env, tmp_path)
    request = baseline.command(env)
    original = baseline.record(env, request)
    def change(payload):
        report = payload['snapshot']['report']
        current = report['current_stay']
        if field == 'nested_calendar':
            current['calendar']['hash'] = '1' * 64
        else:
            assert current['case_id'] == 1
            current['case_id'] = True
        current['evidence_hash'] = _hash({k:v for k,v in current.items() if k != 'evidence_hash'})
        report['evidence_hash'] = _hash({k:v for k,v in report.items() if k != 'evidence_hash'})
    rewrite(env, original['id'], change)
    with pytest.raises(EntryStorageInvalid):
        baseline.record(env, request | {'authority': None})


def test_later_profile_and_source_review_preserve_original_receipt(env, tmp_path, monkeypatch):
    baseline.setup(env, tmp_path)
    request = baseline.command(env)
    original = baseline.record(env, request)
    later = datetime(2026, 10, 12, 16, tzinfo=timezone.utc)
    monkeypatch.setattr(applicant_profiles, '_now', lambda: later)
    changed = deepcopy(env['profile_doc'])
    changed['profile']['purpose'] = 'tourism'
    profile_save(env, env['person'], doc=changed, revision=2, key='later-purpose')
    assert baseline.record(env, request | {'authority': None}) == original
    monkeypatch.setattr(knowledge_decisions, '_now', lambda: later)
    source_review(env, unit='KG.ESC.STOP_12', key='later-source-rejection',
        decision=source_data() | {'verdict': 'rejected', 'reason': 'source_conflict', 'review_due_on': None})
    assert baseline.record(env, request | {'authority': None}) == original
    assert baseline.read(env, authority=None)['history'][0] == original


def test_later_review_with_same_timestamp_preserves_original_receipt(env, tmp_path, monkeypatch):
    baseline.setup(env, tmp_path)
    at = datetime(2026, 10, 12, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(service, '_now', lambda: at)
    request = baseline.command(env)
    original = baseline.record(env, request)
    assert original['created_at'] == original['snapshot']['report']['current_stay']['checked_at']
    monkeypatch.setattr(knowledge_decisions, '_now', lambda: at)
    source_review(env, unit='KG.ESC.STOP_12', key='equal-time-later-review',
        decision=source_data() | {'verdict': 'rejected', 'reason': 'source_conflict', 'review_due_on': None})
    assert baseline.record(env, request | {'authority': None}) == original
    # Corrective follow-up: retained success does not bypass the latest review.
    assert baseline.read(env)['current']['eligible'] is False
    from app.domain import entry_interviews
    from tests.test_entry_interviews import start
    monkeypatch.setattr(entry_interviews, '_now', lambda: at)
    start(env, env['person'], request_key='equal-time-later-interview')
    assert baseline.record(env, request | {'authority': None}) == original
    cancelled = baseline.record(env, baseline.command(env, authority=None))
    assert cancelled['snapshot']['task']['status'] == 'cancelled'
    assert baseline.record(env, request | {'authority': None}) == original
