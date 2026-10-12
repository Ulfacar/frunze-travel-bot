"""Independent final guards: no unknown re-enable, atomic rollback on clock drift."""
from datetime import datetime, timezone

import pytest

from app.domain.entry_storage import EntryStorageInvalid
from app.domain import work_review_tasks as service
from tests import test_work_review_tasks as baseline
from tests.test_work_review_tasks import (
    env, clock, review_clock, connected_clock, route_clock, admins,
    enforce_sqlite_foreign_keys,
)


def test_unknown_reenable_and_backward_clock_leave_original_task_intact(env, tmp_path, monkeypatch):
    baseline.setup(env, tmp_path)
    original = baseline.command(env)
    saved = baseline.record(env, original)
    before = baseline.counts(env)
    for action in ('restore', 'new_generation'):
        request = baseline.command(env, action, authority=None)
        with pytest.raises(EntryStorageInvalid, match='work_review_current_evidence_required'):
            baseline.record(env, request)
        assert baseline.counts(env) == before
    request = baseline.command(env, 'complete')
    monkeypatch.setattr(service, '_now', lambda: datetime(2026, 10, 12, 14, 59, tzinfo=timezone.utc))
    with pytest.raises(EntryStorageInvalid, match='work_review_clock_moved_back'):
        baseline.record(env, request)
    assert baseline.counts(env) == before
    current = baseline.read(env)
    assert current['current']['task']['status'] == 'planned'
    assert current['history'] == [saved]
    assert baseline.record(env, original | {'authority': None}) == saved
