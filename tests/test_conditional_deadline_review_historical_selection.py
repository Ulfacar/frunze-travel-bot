"""A cleared track must not label its selected old receipt as currently usable."""
import asyncio

from app.config import settings
from app.domain import conditional_deadlines as service,entry_deadlines
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock,setup,authority,arguments,write


def test_historical_selection_keeps_receipt_but_not_current_date_after_clear(env,tmp_path,monkeypatch):
    prepared=setup(env,tmp_path)
    rule='KG.DL.INTERNAL_EAEU_REG_REVIEW'; allowed=authority(env,rule)
    args=arguments(env,prepared,rule,allowed)
    saved,request=write(env,args)
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[allowed.document])
    cleared=asyncio.run(service.record(env['engine'],**(args|dict(authority=None,expected_revision=1,request_key='REVIEWER-CLEAR',
        operation=dict(action='conditional_clear',confirmed=True,evidence_hash=saved['snapshot_hash'])))))
    assert cleared['summary']['review_due_on'] is None
    assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==saved
    read_args={k:v for k,v in args.items() if k not in ('applicant_id','authority')}
    current=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**read_args))
    assert current['conditional_current']['review_due_on'] is None
    old=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],**read_args,revision=1,replay=True))
    assert old['selected']['snapshot']==saved['snapshot']
    assert old['conditional_current']['review_due_on'] is None,old['conditional_current']
