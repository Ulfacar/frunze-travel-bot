"""Explicit synthetic attestation/source approval, never real legal authority."""
import asyncio
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json

import pytest

from app.domain import current_stay_stops as service
from app.domain.current_stay_policy import CurrentStayPolicy, CurrentStayFact, VERSION, PARAMETERS, STOPS
from app.domain.entry_storage import EntryStorageInvalid, _hash
from app.knowledge.stay_days import COUNT_RULE_IDS
from app.knowledge.work_calendar import WorkCalendars
from tests import test_connected_qualification as connected
from tests.test_connected_qualification import env, clock as connected_clock, route_clock, admins
from tests.test_admin_kg_entry import ADMIN, FIX
from tests.test_applicant_profiles import save as save_profile
from tests.test_applicant_stay_history import save as save_history, document, interval, withdraw
from tests.test_entry_applications import person, enforce_sqlite_foreign_keys
from tests.test_knowledge_publication import POLICY


@pytest.fixture(autouse=True)
def clock(connected_clock, monkeypatch):
    monkeypatch.setattr(service, '_now', lambda: datetime(2026, 10, 12, 15, tzinfo=timezone.utc))


def setup(env, tmp_path, *, basis='visa_free', headroom=4, exit_count=True, until='2026-10-30', visits=None, with_history=True):
    counts = dict(zip(COUNT_RULE_IDS, (True, exit_count, ['each_day_backward_inclusive'])))
    connected.source(env, tmp_path, additional=PARAMETERS, counting=counts)
    connected.policies(env)
    env['person'] = person(env)
    started = (date(2026, 10, 12) - timedelta(days=90-headroom-1)).isoformat()
    doc = connected.profile()
    doc.pop('condition_facts', None)
    doc['profile'].update(citizenship=['RUS'], entry_passport_country='RUS', current_location='in_kg',
        in_kg_since=started, current_basis_in_kg=basis, current_basis_until=until,
        current_visa_type='TS' if basis == 'visa' else 'not_applicable')
    doc['profile']['violations']['overstay'] = bool(until and until < '2026-10-12')
    env['profile_doc'] = doc
    env['saved'] = save_profile(env, env['person'], doc=doc)
    env['history'] = (save_history(env, env['person'], env['saved'], doc=document(history_complete=True,
        intervals=visits if visits is not None else [interval(entry_date=started, exit_date=None, basis=basis)]))
        if with_history else None)
    env['calendars'] = WorkCalendars(json.loads((FIX/'synthetic_work_calendars.json').read_text('utf-8')))
    ap = env['assessment_policy'].document; units = {u['unit_id']: u for u in env['bundle']['units']}
    env['current_policy'] = CurrentStayPolicy(dict(format='kg-current-stay-policy/1', algorithm=VERSION,
        scope='current_stay_stops_only', reference='SYNTHETIC-CURRENT', proof='f'*64,
        valid_from='2026-01-01', review_due_on='2026-12-31',
        **{k: ap[k] for k in ('source_hash', 'bundle_hash', 'projection_hash', 'catalog_hash', 'qualification_policy_hash', 'regimes')},
        parameters=[dict(unit_id=k, unit_hash=_hash(units[k])) for k in PARAMETERS],
        counting={k: v for k, v in ap['counting'].items() if k in
            ('algorithm', 'count_entry_day', 'count_exit_day', 'window_anchor', 'timezone')} |
            dict(count_exit_day=exit_count, reference='SYNTHETIC-COUNTING', proof='e'*64),
        calendar=dict(hash=env['calendars'].content_hash, reference='SYNTHETIC-CALENDAR', proof='d'*64,
            include_today=False, include_until=True, threshold=5, interpretation='strictly_less_than_threshold',
            valid_from='2026-01-01', review_due_on='2027-12-31'), stop_margin_days=3))
    env['fact_doc'] = dict(format='kg-current-stay-attestation/1', reference='SYNTHETIC-ACTUAL-PERMISSION', proof='c'*64,
        actor=ADMIN.manager_id, policy_hash=env['current_policy'].digest, case_id=env['cases']['visa'],
        applicant_id=env['person']['id'], profile_id=env['saved']['qualification_id'], profile_hash=env['saved']['snapshot_hash'],
        passport_ref='a'*32, as_of='2026-10-12', valid_from='2026-10-12', review_due_on='2026-10-12',
        location='in_kg', current_basis=basis, entered_on=started, lawful_until=until,
        lawful_until_semantics='attested_actual_permission_end_not_visa_validity_or_planned_exit', interview=None,
        history=dict(id=env['history']['id'], snapshot_hash=env['history']['snapshot_hash']) if with_history else None,
        conditions={k: dict(value=v, reference='SYNTHETIC-FACT-'+str(i), proof=str(i)*64)
            for i, (k, v) in enumerate(dict(residence_country='RUS', other_residence_absent=True,
                foreign_visa_absent=True, organized_group_absent=True).items(), 1)})
    return env


def check(env, **changes):
    args = dict(actor=ADMIN, case_id=env['cases']['visa'], applicant_id=env['person']['id'],
        policy=env['current_policy'], fact=CurrentStayFact(env['fact_doc']), qualification_policy=env['qualification_policy'],
        publication_policy=POLICY, calendars=env['calendars'])
    return asyncio.run(service.evaluate(env['engine'], **(args | changes)))


@pytest.mark.parametrize('headroom', [4, 3, 2, 0, -1])
@pytest.mark.parametrize('exit_count', [False, True])
def test_observed_open_stay_not_fictional_exit(env, tmp_path, headroom, exit_count):
    setup(env, tmp_path, headroom=headroom, exit_count=exit_count)
    result = check(env); vf = result['checks']['visa_free_headroom']
    assert vf['status'] == ('triggered' if headroom <= 3 else 'not_triggered'), result
    assert vf['current_window_headroom'] == headroom and vf['days_until_exit'] is None
    projected = result['arithmetic']['scenario']['daily'][0]['scenario_headroom']
    assert projected == headroom + int(not exit_count)
    assert result['arithmetic']['mode'] == 'review_only' and not result['arithmetic']['publication_approved']
    assert result['permission_to_remain'] is None and result['delivery'] == 'not_sent'


@pytest.mark.parametrize('until,count,status', [('2026-10-19',4,'triggered'), ('2026-10-20',5,'not_triggered'), ('2026-10-21',5,'not_triggered')])
def test_exact_four_five_and_lower_bound_six(env, tmp_path, until, count, status):
    setup(env, tmp_path, basis='visa', until=until)
    result = check(env); margin = result['checks']['working_day_margin']
    assert margin['status'] == status and margin['working_days'] == count, result
    assert margin['exact'] == (until != '2026-10-21')
    assert result['checks']['visa_free_headroom']['applicability'] == 'actual_non_visa_free_basis'


@pytest.mark.parametrize('until,expired', [('2026-10-12',False), ('2026-10-11',True)])
def test_last_day_and_expired_are_distinct(env, tmp_path, until, expired):
    setup(env, tmp_path, basis='visa', until=until)
    result = check(env)
    assert result['checks']['expired_stay']['status'] == ('triggered' if expired else 'not_triggered')
    assert result['checks']['working_day_margin'].get('working_days') == (None if expired else 0)
    assert result['requires_specialist']


@pytest.mark.parametrize('change', ['policy', 'fact', 'calendar', 'publication', 'profile', 'history', 'passport', 'conditions', 'source', 'basis', 'fact_expired'])
def test_uncertainty_does_not_become_permission(env, tmp_path, change):
    setup(env, tmp_path)
    args = {}
    if change in ('policy', 'fact'): args[change] = None
    elif change == 'calendar': args['calendars'] = None
    elif change == 'publication': args['publication_policy'] = None
    elif change == 'profile': save_profile(env, env['person'], revision=1, key='correct', doc=env['profile_doc'])
    elif change == 'history': withdraw(env, env['person'], revision=1)
    elif change == 'passport': env['fact_doc']['passport_ref'] = 'b'*32
    elif change == 'conditions': env['fact_doc']['conditions']['other_residence_absent']['value'] = None
    elif change == 'source':
        p = env['current_policy'].document; p['source_hash'] = 'a'*64
        env['current_policy'] = CurrentStayPolicy(p); env['fact_doc']['policy_hash'] = env['current_policy'].digest
    elif change == 'basis': env['fact_doc']['current_basis'] = 'unknown'
    else: env['fact_doc'].update(as_of='2026-10-11', valid_from='2026-10-11', review_due_on='2026-10-11')
    result = check(env, **args)
    assert result['requires_specialist'] and any(v['status']=='unknown' for v in result['checks'].values()), result
    assert result['permission_to_remain'] is None


def test_history_overlap_and_window_edge(env, tmp_path):
    setup(env, tmp_path)
    current = env['history']['operation']['document']['intervals'][0]
    doc = document(history_complete=True, intervals=[interval(entry_date='2026-04-15', exit_date='2026-04-16'),
        {**current, 'ref':'current'}])
    h = save_history(env, env['person'], env['saved'], revision=1, key='edge', doc=doc)
    env['fact_doc']['history'] = dict(id=h['id'], snapshot_hash=h['snapshot_hash'])
    result = check(env)
    assert result['checks']['visa_free_headroom']['current_window_headroom'] == 3, result
    doc['intervals'][0].update(entry_date=current['entry_date'], exit_date=current['entry_date'])
    h = save_history(env, env['person'], env['saved'], revision=2, key='overlap', doc=doc)
    env['fact_doc']['history'] = dict(id=h['id'], snapshot_hash=h['snapshot_hash'])
    assert check(env)['checks']['visa_free_headroom']['reason'] == 'personal_history_overlapping_visits'


def test_attestation_strict_identifiers(env, tmp_path):
    setup(env, tmp_path)
    for key, value in [('case_id',True), ('applicant_id',1.0), ('profile_id','1')]:
        doc = deepcopy(env['fact_doc']); doc[key] = value
        with pytest.raises(EntryStorageInvalid): CurrentStayFact(doc)


def test_calendar_and_complete_regime_authority_fail_independently(env, tmp_path):
    setup(env, tmp_path)
    original = env['current_policy']
    for change in ('wrong_calendar_hash', 'expired_calendar', 'incomplete_regimes', 'changed_count', 'expired_policy', 'narrowed_manual'):
        p = original.document
        if change == 'wrong_calendar_hash': p['calendar']['hash'] = 'a'*64
        elif change == 'expired_calendar': p['calendar']['review_due_on'] = '2026-10-11'
        elif change == 'incomplete_regimes': p['regimes'] = p['regimes'][:-1]
        elif change == 'changed_count': p['counting']['count_exit_day'] = False
        elif change == 'expired_policy': p['review_due_on'] = '2026-10-11'
        else:
            next(r for r in p['regimes'] if r['unit_id']=='KG.VR.SIMPLIFIED_ALL')['all'].append(
                dict(type='permanent_residence_in', countries=['USA']))
        env['current_policy'] = CurrentStayPolicy(p); env['fact_doc']['policy_hash'] = env['current_policy'].digest
        result = check(env)
        target = 'working_day_margin' if 'calendar' in change else 'visa_free_headroom'
        assert result['checks'][target]['status'] == 'unknown' and result['requires_specialist'], (change, result)


def test_known_history_cannot_be_ignored_by_actual_visa_branch(env, tmp_path):
    setup(env, tmp_path, basis='visa', visits=[interval(entry_date='2026-07-19', exit_date=None, basis='visa_free')])
    result = check(env)
    assert all(c.get('reason') == 'current_stay_history_location_or_basis_conflict' for c in result['checks'].values())
    withdrawn = withdraw(env, env['person'], revision=1)
    assert all(c.get('reason') == 'current_stay_history_changed' for c in check(env)['checks'].values())
    env['fact_doc']['history'] = dict(id=withdrawn['id'], snapshot_hash=withdrawn['snapshot_hash'])
    assert all(c.get('reason') == 'current_stay_history_withdrawn' for c in check(env)['checks'].values())


def test_abroad_applicability_requires_explicit_current_fact_and_no_open_stay(env, tmp_path):
    setup(env, tmp_path)
    doc = deepcopy(env['profile_doc']); doc['profile']['current_location'] = 'abroad'
    for key in ('in_kg_since','current_basis_in_kg','current_basis_until','current_visa_type'):
        doc['profile'].pop(key, None)
    saved = save_profile(env, env['person'], revision=1, key='abroad-profile', doc=doc)
    h = save_history(env, env['person'], saved, revision=1, key='abroad-history', doc=document(history_complete=True))
    env['fact_doc'].update(location='abroad', current_basis='unknown', entered_on=None, lawful_until=None,
        profile_id=saved['qualification_id'], profile_hash=saved['snapshot_hash'],
        history=dict(id=h['id'], snapshot_hash=h['snapshot_hash']))
    result = check(env)
    assert all(v['applicability']=='currently_abroad' and v['status']=='not_triggered' for v in result['checks'].values()), result
    h = save_history(env, env['person'], saved, revision=2, key='contradict-abroad',
        doc=document(history_complete=True, intervals=[interval(exit_date=None)]))
    env['fact_doc']['history'] = dict(id=h['id'], snapshot_hash=h['snapshot_hash'])
    assert all(v['status']=='unknown' for v in check(env)['checks'].values())


def test_new_interview_invalidates_unlinked_attestation(env, tmp_path):
    setup(env, tmp_path)
    current = asyncio.run(connected.entry_interviews.start_interview(env['engine'], actor=ADMIN,
        case_id=env['cases']['visa'], applicant_id=env['person']['id'], owner_login='reviewer',
        language='ru', request_key='current-interview', expected_policy_hash=env['interview_policy'].digest,
        policy=env['interview_policy'], profile_id=env['saved']['qualification_id']))
    assert all(v.get('reason')=='current_stay_interview_changed' for v in check(env)['checks'].values())
    view = asyncio.run(connected.entry_interviews.read_interview(env['engine'], actor=ADMIN,
        case_id=env['cases']['visa'], applicant_id=env['person']['id'], interview_id=current['interview_id']))
    env['fact_doc']['interview'] = dict(id=current['interview_id'], header_hash=view['interview']['snapshot_hash'],
        head_hash=current['snapshot_hash'])
    assert check(env)['checks']['visa_free_headroom']['current_window_headroom'] == 4


def test_independent_visa_fact_does_not_fabricate_missing_history(env, tmp_path):
    setup(env, tmp_path, basis='visa', with_history=False)
    result = check(env)
    assert result['history']['status'] == 'missing' and not result['requires_specialist'], result
    assert result['checks']['visa_free_headroom']['applicability'] == 'actual_non_visa_free_basis'
    # Once a history exists, old null pin no longer proves an unchanged context.
    save_history(env, env['person'], env['saved'], doc=document(history_complete=None))
    assert all(v.get('reason') == 'current_stay_history_changed' for v in check(env)['checks'].values())
