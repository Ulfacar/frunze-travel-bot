"""Broken current delegation cannot erase originals or hide stored corruption."""
import asyncio
import pytest
from sqlalchemy import text
from app.config import settings
from app.domain import entry_deadlines
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests import test_operator_sop_reviews as core


def test_malformed_registry_allows_retained_retry_cancel_but_does_not_mask_integrity(env,tmp_path,monkeypatch):
    prepared=core.setup(env,tmp_path);args=core.args(env,prepared);ta=core.task_args(args)
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[prepared[-1].document])
    saved,request=core.write(env,args)
    task=asyncio.run(core.tasks.reconcile_deadline_task(env['engine'],**ta,enable=True))
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[{}])
    current=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**ta))
    assert current['selected']==saved
    assert current['operator_current']['reason']=='operator_sop_authority_unavailable'
    assert current['operator_current']['review_due_on'] is None
    assert asyncio.run(core.service.record(env['engine'],**(request|dict(authority=None))))==saved
    async def pin_hash(value):
        async with env['engine'].begin() as connection:
            await connection.execute(text('UPDATE entry_sop_review_evidence SET receipt_hash=:h WHERE deadline_id=:id'),
                dict(h=value,id=saved['id']))
    asyncio.run(pin_hash('0'*64))
    with pytest.raises(EntryStorageInvalid,match='independent_pin'):
        asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**ta))
    asyncio.run(pin_hash(saved['snapshot_hash']))
    cleared=asyncio.run(core.service.record(env['engine'],**(args|dict(authority=None,expected_revision=1,
        request_key='RETAINED-CLEAR-BROKEN-REGISTRY',operation=dict(action='operator_review_clear',
            confirmed=True,evidence_hash=saved['snapshot_hash'])))))
    assert cleared['summary']['review_due_on'] is None
    after=asyncio.run(core.tasks.read_deadline_task(env['engine'],**ta))['current']
    assert after['task']['id']==task['task']['id'] and after['task']['status']=='cancelled'
