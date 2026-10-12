"""Actual typed renewal premises remain bound to own current facts."""
import asyncio
from copy import deepcopy
from datetime import datetime,timezone

import pytest

from app.domain import entry_interviews,conditional_deadlines as service
from app.domain.entry_storage import EntryStorageInvalid
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_conditional_deadlines import clock,setup,renewal,authority,arguments,preview,write,actual
from tests import test_entry_interviews as interview


def test_renewal_requires_matching_type_purpose_inviter_and_current_actual_period(env,tmp_path):
    prepared=setup(env,tmp_path,'visa_period');prepared,context=renewal(env,prepared)
    rule='KG.DL.VISA_EXTENSION';args=arguments(env,prepared,rule,authority(env,rule))
    assert preview(env,args)['report']['review_due_on'] is None
    original=deepcopy(context['operation']['data']['value'])
    def save_context(value):
        candidate=actual.args(env,prepared,'visa_renewal_context','RENEWAL')
        candidate['operation']['data']['value']=value
        return actual.write(env,candidate)
    save_context(original)
    assert preview(env,args)['report']['review_due_on']=='2026-10-26'
    saved,request=write(env,args)
    for changed in (
        {'intent':'change_status','current_type':'M'},
        {'intent':'change_status','target_type':'TS'},
        {'intent':'change_status','target_purpose':'business_meeting'},
        {'target_inviter_ref':'1'*64},
    ):
        save_context(original|changed)
        denied=preview(env,args)['report']
        assert denied['review_due_on'] is None,denied
        save_context(original)
        assert preview(env,args)['report']['review_due_on']=='2026-10-26'
    new_period=actual.args(env,prepared,'visa_period')
    new_period['operation']['data']['proof']='9'*64
    corrected=actual.write(env,new_period)
    stale=preview(env,args)['report']
    assert stale['reason']=='conditional_deadline_renewal_premises_conflict',stale
    save_context(original|{'period_anchor_id':corrected['id'],'period_anchor_hash':corrected['snapshot_hash']})
    assert preview(env,args)['report']['review_due_on']=='2026-10-26'
    assert asyncio.run(service.record(env['engine'],**(request|{'authority':None})))==saved


def test_supplied_interview_date_cannot_disagree_with_actual_visa_period(env,tmp_path,monkeypatch):
    monkeypatch.setattr(entry_interviews,'_now',lambda:datetime(2026,10,13,10,tzinfo=timezone.utc))
    prepared=setup(env,tmp_path,'visa_period');prepared,context=renewal(env,prepared)
    actual.write(env,context)
    args=arguments(env,prepared,'KG.DL.VISA_EXTENSION',authority(env,'KG.DL.VISA_EXTENSION'))
    iv=interview.start(env,prepared[0],owner_login='admin')
    assert preview(env,args)['report']['review_due_on']=='2026-10-26'
    for key,value in [('location','in_kg'),('current_basis','visa'),('current_visa_type','B'),('current_until','2026-11-02')]:
        interview.correct(env,iv,{key:value})
    denied=preview(env,args)['report']
    assert denied['review_due_on'] is None,denied
