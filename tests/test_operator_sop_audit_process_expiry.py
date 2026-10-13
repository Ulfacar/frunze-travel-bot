"""Expired nested process authority is uncertainty, not broken retained history."""
import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from tests.test_operator_sop_reviews import env, enforce_sqlite_foreign_keys
from tests import test_operator_sop_reviews as core


def test_nested_process_expiry_keeps_historical_view_and_clear(env, tmp_path, monkeypatch):
    today = core.processes.service.applications._today()
    original_policy = core.processes.policy
    monkeypatch.setattr(core.processes, 'policy', lambda **kw: original_policy(
        **({'review_due_on': today.isoformat()} | kw)))
    prepared = core.setup(env, tmp_path)
    arguments = core.args(env, prepared)
    from app.config import settings
    monkeypatch.setattr(settings, 'kg_operator_sop_authorities', [prepared[-1].document])
    saved, request = core.write(env, arguments)
    ta = core.task_args(arguments)
    task = asyncio.run(core.tasks.reconcile_deadline_task(env['engine'], **ta, enable=True))
    later = datetime.now(timezone.utc) + timedelta(days=2)
    monkeypatch.setattr(core.service, '_now', lambda: later)
    monkeypatch.setattr(core.sources, '_now', lambda: later)
    outcomes = {}
    def capture(name, action):
        try:
            outcomes[name] = {'ok': True, 'value': action()}
        except Exception as exc:
            outcomes[name] = {'ok': False, 'type': type(exc).__name__, 'reason': str(exc)}
    capture('retry', lambda: asyncio.run(core.service.record(env['engine'], **request)))
    capture('preview', lambda: core.preview(env, arguments))
    capture('history', lambda: asyncio.run(core.entry_deadlines.read_deadline_history(env['engine'], **ta)))
    capture('task', lambda: asyncio.run(core.tasks.read_deadline_task(env['engine'], **ta)))
    capture('clear', lambda: asyncio.run(core.service.record(env['engine'], **(arguments | dict(
        authority=None, expected_revision=1, request_key='after-process-expiry-clear', operation=dict(
            action='operator_review_clear', confirmed=True, evidence_hash=saved['snapshot_hash']))))))
    Path('runs').mkdir(exist_ok=True)
    Path('runs/audit-sop-process-expiry.json').write_text(json.dumps(outcomes, ensure_ascii=False, indent=2), encoding='utf-8')
    assert outcomes['retry']['ok'] and outcomes['retry']['value'] == saved
    assert outcomes['clear']['ok'] and outcomes['clear']['value']['snapshot']['cleared']
    assert outcomes['preview']['ok'], outcomes['preview']
    assert outcomes['preview']['value']['report']['status'] == 'unknown'
    assert outcomes['history']['ok'], outcomes['history']
    assert outcomes['history']['value']['selected'] == saved
    assert outcomes['history']['value']['operator_current']['status'] == 'unknown'
    assert outcomes['task']['ok'], outcomes['task']
