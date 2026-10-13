"""Native interview withdrawal must invalidate conditional dates without channel causes."""
import asyncio
from datetime import datetime,timezone

import pytest

from app.config import settings
from app.domain import entry_interviews,entry_deadlines,conditional_deadlines
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock,setup,authority,arguments,preview,write
from tests import test_entry_interviews as interview


def test_native_interview_privacy_blocks_review_even_without_channel_session(env,tmp_path,monkeypatch):
    monkeypatch.setattr(entry_interviews,'_now',lambda:datetime(2026,10,13,10,tzinfo=timezone.utc))
    prepared=setup(env,tmp_path)
    rule='KG.DL.INTERNAL_EAEU_REG_REVIEW'
    args=arguments(env,prepared,rule,authority(env,rule))
    first=preview(env,args)['report']
    assert first['review_due_on']=='2026-10-19'
    iv=interview.start(env,prepared[0],owner_login='admin')
    baseline=preview(env,args)['report']
    assert baseline['review_due_on']=='2026-10-19'
    blocked=interview.action(env,iv,'interrupt',operation={'action':'interrupt','reason':'consent_withdrawn'},policy=None)
    assert blocked['state']['collection_blocked'] and blocked['state']['consent_withdrawal']
    result=preview(env,args)['report']
    assert result['review_due_on'] is None,result


def test_existing_receipt_stays_exact_but_new_write_is_denied_after_native_withdrawal(env,tmp_path,monkeypatch):
    monkeypatch.setattr(entry_interviews,'_now',lambda:datetime(2026,10,13,10,tzinfo=timezone.utc))
    prepared=setup(env,tmp_path)
    rule='KG.DL.INTERNAL_EAEU_REG_REVIEW';allowed=authority(env,rule)
    args=arguments(env,prepared,rule,allowed)
    iv=interview.start(env,prepared[0],owner_login='admin')
    saved,request=write(env,args)
    monkeypatch.setattr(settings,'kg_conditional_deadline_authorities',[allowed.document])
    interview.action(env,iv,'interrupt',operation={'action':'interrupt','reason':'consent_withdrawn'},policy=None)
    view=asyncio.run(entry_deadlines.read_deadline_history(env['engine'],
        **{k:v for k,v in args.items() if k not in ('applicant_id','authority')}))
    assert view['conditional_current']['review_due_on'] is None
    assert asyncio.run(conditional_deadlines.record(env['engine'],**(request|{'authority':None})))==saved
    with pytest.raises(EntryStorageInvalid,match='collection_or_dialogue_blocked'):
        asyncio.run(conditional_deadlines.record(env['engine'],**(request|dict(expected_revision=1,request_key='AFTER-WITHDRAWAL'))))
