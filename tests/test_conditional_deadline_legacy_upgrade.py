import asyncio
import importlib.util
from pathlib import Path
import json

import pytest
from tests.test_admin_kg_entry import env,ADMIN
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests import test_entry_deadlines as helpers,test_entry_deadline_tasks as task_helpers
from app.domain import entry_deadlines as current
from app.domain.entry_storage import EntryStorageInvalid


def test_actual_pre_d_writer_receipts_read_retry_and_explicit_replay_drift(env,monkeypatch):
    path=Path(__file__).resolve().parent/'fixtures/entry_deadlines_pre_d.py'
    spec=importlib.util.spec_from_file_location('app.domain._audit_actual_legacy_deadlines',path)
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    assert old._runtime()!=current._runtime()
    with monkeypatch.context() as m:
        m.setattr(helpers,'service',old)
        app=task_helpers.seed(env)
        retained=helpers.read(env,app,replay=True)
        original=retained['selected']
        assert original['snapshot']['runtime']==old._runtime()
        assert original['summary']['operational_due_on']=='2026-10-20'
    upgraded=helpers.read(env,app)
    assert upgraded.pop('conditional_current') is None
    assert upgraded==retained
    retry=helpers.write(env,app,'manual',helpers.manual(),revision=1,key='manual-1')
    assert retry==original
    with pytest.raises(EntryStorageInvalid,match='deadline_replay_runtime_changed'):
        helpers.read(env,app,replay=True)
    task=task_helpers.sync(env,app,enable=True)
    assert task['task']['date']=='2026-10-20'
    helpers.write(env,app,'clear',dict(reason='wrong_document'))
    assert task_helpers.read(env,app)['current']['task']['status']=='cancelled'
    assert helpers.write(env,app,'manual',helpers.manual(),revision=1,key='manual-1')==original
    Path('runs/audit-actual-legacy-upgrade.json').write_text(json.dumps(dict(
        seed_commit='5e91ddb',actual_archived_handler=True,original_runtime=old._runtime(),
        current_runtime=current._runtime(),historical_read_equal=True,old_retry_equal=True,
        unchanged_manual_date=True,new_clear_cancelled_existing_task=True,
        explicit_replay='refused:deadline_replay_runtime_changed'),indent=2)+'\n','utf8')
