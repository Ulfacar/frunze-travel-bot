"""Exact B.8 situations on persisted own-person state and connected services."""
import asyncio
import json
from copy import deepcopy
from datetime import date,timedelta

import pytest

from tests import test_work_deadlines as deadline
from tests import test_connected_qualification as qualification
from tests import test_entry_interviews as interview
from tests import test_work_process_v2 as work
from tests import test_applicant_profiles as profiles
from tests import test_applicant_stay_history as stays
from tests.test_work_deadlines import env,clock,connected_clock,route_clock,admins
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_source_sop_products import open_case


def acknowledge(env,iv):
    if interview.read(env,iv)['state']['phase']=='pending':interview.action(env,iv,'ack')


def pin(env,iv):
    view=interview.read(env,iv)
    env['fact_doc']['interview']=dict(id=iv['interview_id'],header_hash=view['interview']['snapshot_hash'],
        head_hash=view['history'][-1]['snapshot_hash'])
    return view


def test_b8_usa_45_days_english_intake_exceeds_short_regime_and_retains_uncertainty(env,tmp_path):
    opening=open_case(env,'B8-USA45')
    qualification.setup(env,tmp_path,country='USA',end='2026-12-15',language='en')
    result=qualification.assess(env)
    assert (date.fromisoformat(env['profile_doc']['profile']['exit_date'])-date.fromisoformat(env['profile_doc']['profile']['entry_date'])).days+1==45
    assert 'planned_stay_exceeds_allowance' in result['reasons'],result
    assert result['selected_product'] is None and result['selected_regime'] is None
    assert not result['may_quote'] and not result['entry_eligibility_evaluated']
    assert result['duration']['window_days']==60
    assert env['saved']['result']['applicant_id']==env['person']['id']
    assert env['cases']['visa']==opening['case_id'] and env['interview']['state']['language']=='en'
    # An unknown visit history cannot be treated as the same empty history.
    saved=stays.save(env,env['person'],env['saved'],revision=1,key='UNKNOWN-HISTORY',
        doc=stays.document(history_complete=False,intervals=[]))
    unknown=qualification.assess(env)
    assert unknown['selected_product'] is None and not unknown['may_quote']
    assert 'personal_history_review_required' in unknown['reasons']
    assert 'history_incomplete' in unknown['history']['findings']


def test_b8_uz_garment_exact_entry_employer_handoff_deadline_and_own_permit(env,tmp_path,monkeypatch):
    open_case(env,'B8-UZ-WORK')
    deadline.setup(env,tmp_path)
    doc=deepcopy(env['profile_doc'])
    doc['profile'].update(in_kg_since='2026-09-21',current_basis_until='2026-11-19',
        purpose_details='Garment factory employment in Bishkek')
    assert (date(2026,10,12)-date.fromisoformat(doc['profile']['in_kg_since'])).days==21
    saved=profiles.save(env,env['person'],doc=doc,revision=2,key='EXACT-WORK-PROFILE')
    history=stays.save(env,env['person'],saved,revision=2,key='EXACT-WORK-HISTORY',
        doc=stays.document(history_complete=True,intervals=[stays.interval(entry_date='2026-09-21',exit_date=None,passport_country='UZB')]))
    env['saved']=saved;env['profile_doc']=doc
    env['fact_doc'].update(profile_id=saved['qualification_id'],profile_hash=saved['snapshot_hash'],entered_on='2026-09-21',
        lawful_until='2026-11-19',history=dict(id=history['id'],snapshot_hash=history['snapshot_hash']))
    assert deadline.check(env,fact=None)['due_on'] is None
    iv=interview.start(env,env['person'],profile_id=saved['qualification_id']);acknowledge(env,iv)
    for changes in (
        {'citizenships':['UZB'],'location':'in_kg','purpose':'work_hire'},
        {'actual_entry.on':'2026-09-21','actual_entry.point':'Manas','current_basis':'visa_free','current_until':'2026-11-19'},
        {'inviter.exists':True,'employment.garment':True},
        {'inviter.type':'company','inviter.name':'SYNTHETIC-BISHKEK-FACTORY','inviter.contact':'Synthetic HR',
         'inviter.phone':'synthetic','employment.position':'sewing operator','employment.workplace':'Bishkek'},
        {'employment.chamber_member':'unknown','employment.quota':False,'permit.exists':False},
    ):
        items=list(changes.items())
        for start in range(0,len(items),3):
            interview.correct(env,iv,dict(items[start:start+3]),actor=interview.OWNER);acknowledge(env,iv)
    view=pin(env,iv)
    assert view['state']['answers']['inviter.contact']['value']=='Synthetic HR'
    assert view['state']['answers']['employment.chamber_member']['value']=='unknown'
    result=deadline.check(env)
    assert result['status']=='calculated' and result['due_on']=='2026-11-05',result
    assert result['current_stay']['checks']['visa_free_headroom']['current_window_headroom']==38
    assert result['permission_to_work'] is result['permission_to_remain'] is None
    assert result['operational_action_allowed'] is False and result['requires_specialist']
    assert not result['may_quote']
    # UZ's 60-day registration TERM is not an exemption or a garment discount.
    uz=next(u for u in env['bundle']['units'] if u['unit_id']=='KG.VF.UZB')
    original=json.loads(uz['source_text'])
    assert original['registration_term_days']==60 and original['registration_exempt_days'] is None
    assert 'registration_term_days' not in uz['value']
    # The process has its own explicit operator delegation and observation time;
    # current_stay's daily evidence is not promoted into route authorization.
    monkeypatch.setattr(work.service,'_now',deadline.current.service._now)
    subject=env['person']
    root=work.application(env,subject,'B8-PERMIT',procedure='unified_permit')
    work.write(env,root,'initialize',dict(catalog_digest=work.WORK_CATALOG_SHA256,on=work.today(),employer_reference='SYNTHETIC-BISHKEK-FACTORY'),revision=0)
    work.attest(env,root,'profile_review_complete',profile_id=saved['qualification_id'])
    entered=work.transition(env,root,'W02')
    assert 'visa' not in entered['snapshot']['links']
    assert root['applicant_id']==env['person']['id']==subject['id']
    # Reported factory/HR facts and a known date do not prove employer approval,
    # quota, an accepted offer or eligibility for a TPP concession.
    with pytest.raises(work.EntryStorageInvalid,match='prerequisites'):work.transition(env,root,'W03')
    # Changing a collected purpose invalidates the separate exact date until
    # re-confirmed; it does not rewrite the original employer-review receipt.
    interview.correct(env,iv,{'purpose':'business_meeting'},actor=interview.OWNER);acknowledge(env,iv);pin(env,iv)
    blocked=deadline.check(env)
    assert blocked['due_on'] is None
    assert work.read(env,root,revision=entered['revision'])['selected']['evidence']==entered['evidence']
