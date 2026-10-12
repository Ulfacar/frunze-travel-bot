"""Exact conditional ten-working-day date, independently supplied authority."""
import asyncio
from dataclasses import replace

import pytest

from app.domain import work_deadlines as service
from app.domain.current_stay_policy import CurrentStayFact
from app.domain.entry_storage import _hash
from tests import test_current_stay_stops as current
from tests.test_current_stay_stops import env,clock,connected_clock,route_clock,admins,ADMIN,POLICY
from tests.test_applicant_profiles import save as save_profile
from tests.test_applicant_stay_history import save as save_history,document,interval,withdraw
from tests.test_entry_applications import enforce_sqlite_foreign_keys


def setup(env,tmp_path):
    current.setup(env,tmp_path,until='2026-10-30')
    doc=env['profile_doc'];doc['profile'].update(citizenship=['UZB'],entry_passport_country='UZB',purpose='work_hire')
    saved=save_profile(env,env['person'],doc=doc,revision=1,key='work-profile')
    history=save_history(env,env['person'],saved,revision=1,key='work-history',doc=document(history_complete=True,
        intervals=[interval(entry_date=doc['profile']['in_kg_since'],exit_date=None,passport_country='UZB')]))
    env['fact_doc'].update(profile_id=saved['qualification_id'],profile_hash=saved['snapshot_hash'],
        history=dict(id=history['id'],snapshot_hash=history['snapshot_hash']))
    env['fact_doc']['conditions']['residence_country']['value']='UZB'
    ap=env['current_policy'].document
    rule=next(r for r in env['bundle']['units'] if r['unit_id']==service.RULE)
    env['work_policy']=service.WorkDeadlinePolicy(reference='SYNTHETIC-WORK-FILING',proof='7'*64,operators=('admin',),
        valid_from='2026-01-01',review_due_on='2026-12-31',
        **{k:ap[k] for k in ('source_hash','bundle_hash','projection_hash','catalog_hash')},
        rule_hash=_hash(rule),current_stay_policy_hash=env['current_policy'].digest,
        calendar_hash=env['calendars'].content_hash,calendar_reference='SYNTHETIC-CALENDAR',calendar_proof='8'*64,
        calendar_valid_from='2026-01-01',calendar_review_due_on='2027-12-31',
        count_anchor_day=False,boundary_inclusive=True)
    return env


def check(env,**changes):
    args=dict(actor=ADMIN,case_id=env['cases']['visa'],applicant_id=env['person']['id'],policy=env['work_policy'],
        current_policy=env['current_policy'],fact=CurrentStayFact(env['fact_doc']),
        qualification_policy=env['qualification_policy'],publication_policy=POLICY,calendars=env['calendars'])
    return asyncio.run(service.evaluate(env['engine'],**(args|changes)))


def test_exact_ten_day_date_is_separate_from_threshold_and_requires_authority(env,tmp_path):
    setup(env,tmp_path)
    result=check(env)
    assert result['status']=='calculated',result
    assert result['due_on']=='2026-10-16'
    assert sum(d['counted'] for d in result['calculation']['calendar_trace'])==10
    assert result['current_stay']['checks']['working_day_margin']['working_days']==5
    assert result['current_stay']['checks']['working_day_margin']['exact'] is False
    assert result['source']['source_value'] is None
    assert result['permission_to_remain'] is result['permission_to_work'] is None
    assert result['may_quote'] is False and result['within_filing_deadline'] is True
    assert check(env,policy=None)['due_on'] is None
    for key,value in [('rule_hash','1'*64),('calendar_hash','2'*64),('current_stay_policy_hash','3'*64),
        ('review_due_on','2026-10-11'),('calendar_valid_from','2026-10-17')]:
        blocked=check(env,policy=replace(env['work_policy'],**{key:value}))
        assert blocked['status']=='unknown' and blocked['due_on'] is None,(key,blocked)
    withdraw(env,env['person'],revision=2)
    assert check(env)['due_on'] is None
