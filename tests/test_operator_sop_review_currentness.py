"""Independent connected current source tests, original frozen E R1."""
import asyncio

import pytest

from app.config import settings
from app.domain import entry_interviews,entry_deadlines
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests import test_operator_sop_reviews as core,test_entry_interviews as interview


def test_answered_lead_cannot_get_new_unanswered_lead_review_while_stage_lags(env,tmp_path):
    prepared=core.setup(env,tmp_path);arguments=core.args(env,prepared)
    assert core.preview(env,arguments)['report']['status']=='available'
    core.processes.attest(env,prepared[1],'conversation_started')
    assert core.processes.read(env,prepared[1])['selected']['snapshot']['stage']=='V01'
    fresh=core.preview(env,arguments)['report']
    assert fresh['status']!='available',fresh


def test_native_privacy_preserves_old_receipt_but_refuses_fresh_review(env,tmp_path,monkeypatch):
    prepared=core.setup(env,tmp_path);arguments=core.args(env,prepared)
    saved,request=core.write(env,arguments)
    monkeypatch.setattr(settings,'kg_operator_sop_authorities',[prepared[-1].document])
    iv=interview.start(env,prepared[0],owner_login='admin')
    interview.action(env,iv,'interrupt',operation={'action':'interrupt','reason':'consent_withdrawn'},policy=None)
    denied=core.preview(env,arguments)['report']
    assert denied['status']=='unknown'
    assert asyncio.run(core.service.record(env['engine'],**(request|{'authority':None})))==saved
    current=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**core.task_args(arguments)))
    assert current['operator_current']['review_due_on'] is None
    with pytest.raises(EntryStorageInvalid):core.write(env,arguments,key='NEW-AFTER-PRIVACY')
