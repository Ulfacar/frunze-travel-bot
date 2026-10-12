"""Full source-shaped bundle with SYNTHETIC authority; no real approval."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest
import yaml
from sqlalchemy import event

from app.domain import connected_qualification as service, applicant_stay_history, entry_interviews
from app.domain import assessment_interview, assessment_rules
from app.domain.assessment_policy import AssessmentPolicy, FORMAT, ALGORITHM_VERSION, BRIDGE, PARAMETERS
from app.domain.entry_storage import EntryStorageInvalid, _hash
from app.domain.knowledge_import import create_kg_entry_set, import_bundle
from app.domain.qualification_policy import QualificationPolicy
from app.knowledge.bundle import validate_bundle
from app.knowledge import interview_catalog
from app.knowledge.stay_days import ALGORITHM
from tests.test_admin_kg_entry import ADMIN, FIX, env
from tests.test_approved_qualification import profile, clock as route_clock
from tests.test_applicant_profiles import save as save_profile
from tests.test_applicant_stay_history import document, interval, save as save_history, withdraw
from tests.test_entry_applications import person, enforce_sqlite_foreign_keys
from tests.test_entry_interviews import policy as interview_policy, admins, OWNER
from tests.test_knowledge_decisions import write as review, data as review_data
from tests.test_knowledge_publication import POLICY, publish, preview

ROOT = Path(__file__).resolve().parents[1]
EXECUTABLE = ('KG.VF.EAEU', 'KG.VF.ANNEX1_30_60', 'KG.VF.CIS_BILATERAL', 'KG.VF.NINETY_180', 'KG.VF.UZB')


@pytest.fixture(autouse=True)
def clock(route_clock, monkeypatch):
    from app.domain import entry_applications, applicant_profiles, knowledge_decisions, knowledge_publication
    at = datetime(2026, 10, 12, 12, tzinfo=timezone.utc)
    def now():
        nonlocal at
        at += timedelta(microseconds=1)
        return at
    for mod in (service, applicant_stay_history, entry_interviews, entry_applications,
                applicant_profiles, knowledge_decisions, knowledge_publication):
        monkeypatch.setattr(mod, '_now', now)


def source(env, tmp_path, *, additional=(), counting=None):
    folder = tmp_path / 'full-source-shaped'; folder.mkdir()
    bundle = {k: yaml.safe_load((ROOT / 'knowledge/kg_entry/draft-v1.1' / (k + '.yaml')).read_text('utf-8'))
              for k in ('meta', 'countries', 'units')}
    original = validate_bundle(**bundle, source_hash=bundle['meta']['source_hash']).normalized_bundle['units']
    bundle['meta'].update(source_hash=hashlib.sha256((FIX/'synthetic_source.txt').read_bytes()).hexdigest(),
                          source_document='SYNTHETIC full source shape; NOT legal approval')
    ids = list(EXECUTABLE) + ['KG.REG.DEFAULT', 'KG.REG.EXEMPT.RUS', 'KG.REG.EXEMPT.USA',
        'KG.REG.EXEMPT.TJK', 'KG.REG.EXEMPT.MDA', 'KG.ESC.STOP_12', 'KG.RULE.REG_DOES_NOT_EXTEND_VF']
    actual = {u['unit_id']: u for u in bundle['units']}
    ids += list(additional)
    if counting is not None:
        for uid, value in counting.items():
            actual[uid]['value'] = dict(value=value, unit='bool' if type(value) is bool else 'list')
    ids = list(dict.fromkeys(uid for uid in ids if uid in actual and actual[uid]['value'] is not None))
    for uid in ids:
        actual[uid].update(effective_from='2026-01-01', verified_at='2026-09-01T00:00:00Z',
            verified_by='synthetic-reviewer', review_due_at='2027-01-01T00:00:00Z', owner='synthetic-owner',
            source_ref='SYNTHETIC authority only; original source shape retained', label='none', confirmation_status='confirmed',
            blocked_value=None, conflict_ref=None)
    normalized = validate_bundle(**bundle, source_hash=bundle['meta']['source_hash'])
    assert normalized.ok, normalized.errors
    bundle = normalized.normalized_bundle
    catalog = json.loads((ROOT/'knowledge/kg_entry/conditions_v1_1/catalog.json').read_text('utf-8'))
    catalog.update(source_hash=bundle['meta']['source_hash'], bundle_hash=normalized.bundle_hash)
    for k, v in bundle.items():
        (folder/(k+'.yaml')).write_text(yaml.safe_dump(v, allow_unicode=True), 'utf-8')
    (tmp_path/'catalog.json').write_text(json.dumps(catalog), 'utf-8')
    async def seed():
        sid = await create_kg_entry_set(env['engine'], actor=ADMIN)
        return await import_bundle(env['engine'], actor=ADMIN, set_id=sid, directory=folder,
                                   source=FIX/'synthetic_source.txt', catalog=tmp_path/'catalog.json')
    imported = asyncio.run(seed()); assert imported.accepted, json.dumps(imported.report)
    env.update(version=imported.version_id, release=imported.version_id, bundle=bundle, catalog=catalog, published=ids)
    for uid in ids:
        review(env, decision=review_data() | {'review_due_on': '2026-12-31'}, unit=uid, key='synthetic-' + uid)
    for action in ('review', 'approve', 'activate'):
        publish(env, action, ids=ids)
    changed = set(counting or {})
    assert [(u['unit_id'], u['kind'], u['value']) for u in original if u['unit_id'] not in changed] == [
        (u['unit_id'], u['kind'], u['value']) for u in bundle['units'] if u['unit_id'] not in changed]
    assert {u['unit_id']: u.get('blocked_value') for u in original if u['unit_id'] not in ids} == {
        u['unit_id']: u.get('blocked_value') for u in bundle['units'] if u['unit_id'] not in ids}
    return env


def policies(env):
    bundle = env['bundle']; units = {u['unit_id']: u for u in bundle['units']}
    catalog = {r['unit_id']: r for r in env['catalog']['rules']}
    manifest = preview(env, ids=env['published'])['manifest']
    pins = {k: manifest[k] for k in ('bundle_hash', 'projection_hash', 'catalog_hash')}
    pins['source_hash'] = bundle['meta']['source_hash']
    rules = []; guards = []
    # Explicit synthetic partition, never assembled from whichever rules happen
    # to be available at evaluation time. These countries are the tested scope.
    partition = ['RUS', 'KAZ', 'BLR', 'ARM', 'USA', 'TJK', 'MDA', 'UZB']
    for uid, unit in units.items():
        if unit['kind'] not in ('visa_free_regime', 'visa_required_regime', 'special_regime'):
            continue
        if uid in catalog:
            clauses = deepcopy(catalog[uid]['all'])
        elif uid == 'KG.VR.GENERAL':
            clauses = [dict(type='passport_country_in', countries=partition)]
        else:
            countries = (unit['value'] or {}).get('countries') or [uid.rsplit('.', 1)[-1]]
            clauses = [dict(type='passport_country_in', countries=countries), dict(type='document_type_is', value='ordinary')]
        rules.append(dict(unit_id=uid, all=clauses, routes=[dict(purpose='tourism', product='NO_VISA')]
                          if uid in EXECUTABLE else []))
        guard = deepcopy(clauses)
        if uid == 'KG.VR.GENERAL':
            guard = [dict(type='passport_country_not_in', countries=partition)]
        guards.append(dict(unit_id=uid, unit_hash=_hash(unit), disposition='executable' if uid in EXECUTABLE else 'manual',
            interpretation_reference='SYNTHETIC-APPLICABILITY', interpretation_proof='b'*64, all=guard))
    env['qualification_policy'] = QualificationPolicy(dict(format='kg-qualification-policy/1', algorithm='kg-approved-route/1',
        reference='SYNTHETIC-ROUTE', proof='a'*64, valid_from='2026-01-01', review_due_on='2026-12-31',
        complete_regime_set=True, rules=rules, **pins))
    env['interview_policy'] = interview_policy()
    env['assessment_policy'] = AssessmentPolicy(dict(format=FORMAT, algorithm=ALGORITHM_VERSION,
        reference='SYNTHETIC-ASSESSMENT', proof='c'*64, valid_from='2026-01-01', review_due_on='2026-12-31',
        qualification_policy_hash=env['qualification_policy'].digest, profile_map_hash=_hash(assessment_rules.PROFILE_MAP), **pins,
        scope='adult_individual_abroad_ordinary_tourism_single_entry', regimes=guards,
        parameters=[dict(unit_id=k, unit_hash=_hash(units[k])) for k in PARAMETERS],
        registration=dict(mode='exemption_only', units=[dict(unit_id=k, unit_hash=_hash(u))
                          for k, u in assessment_rules.registration_units(bundle).items()]),
        counting=dict(algorithm=ALGORITHM, count_entry_day=True, count_exit_day=True,
            window_anchor='each_day_backward_inclusive', timezone='Asia/Bishkek', basis='visa_free',
            passport='same_confirmed', reported_window_anchor='as_of_backward_inclusive'), stop_margin_days=3,
        interview=dict(bridge=BRIDGE, catalog_hash=env['interview_policy'].catalog_hash,
            policy_hash=env['interview_policy'].digest, field_map_hash=_hash(assessment_interview.field_map(interview_catalog.document())),
            completion='acked_intake_complete')))


def complete_interview(env, profile, visits):
    ip = env['interview_policy']; p = profile['profile']; subject = env['person']
    values = dict(contact_name='Synthetic applicant', contact_phone='synthetic', contact_messenger='synthetic',
        contact_role='applicant', contact_email='synthetic@example.invalid', party_type='individual', applicants_count=1,
        citizenships=p['citizenship'], document_type='ordinary', passport_expiry=p['passport_expiry'],
        passport_two_blank_pages=True, passport_undamaged=True, residence_country=p['entry_passport_country'],
        location='abroad', current_country=p['entry_passport_country'], purpose=p['purpose'], entry_on=p['entry_date'],
        exit_on=p['exit_date'], multiple_entries=False, planned_entry_point='manas', tickets_bought=False,
        accommodation_address='Synthetic hotel', previous_visits=bool(visits), previous_refusal=False,
        family_count=0, payer='self', payment_preference='cash', extra_services=[], referral='Synthetic fixture')
    values.update({'consent.given': True, 'consent.on': '2026-10-12', 'consent.evidence_ref': 'SYN-CONSENT',
        'consent.evidence_sha256': 'a'*64, 'terms.accepted': False, 'foreign_residence.exists': False,
        'long_visa.exists': False, 'organized_group.exists': False, 'hard_deadline.exists': False,
        'applicant.age': 30, 'risk.overstay': False, 'risk.fines': False, 'risk.deportation': False,
        'risk.entry_ban': False, 'commercial.contract': False, 'commercial.company_invoice': False,
        'commercial.closing_documents': False})
    if visits:
        right = datetime(2026, 10, 12).date().toordinal(); left = right - 179
        days = sum(max(0, min(right, datetime.fromisoformat(v['exit_date']).date().toordinal()) -
            max(left, datetime.fromisoformat(v['entry_date']).date().toordinal()) + 1) for v in visits)
        values.update(history_count=len(visits), reported_window='180', reported_days=days, previous_visa_count=0)
        for i, v in enumerate(visits, 1):
            values.update({f'history.{i}.entry': v['entry_date'], f'history.{i}.exit': v['exit_date'],
                           f'history.{i}.passport_country': v['passport_country']})
    async def run():
        current = await entry_interviews.start_interview(env['engine'], actor=ADMIN, case_id=env['cases']['visa'],
            applicant_id=subject['id'], owner_login='reviewer', language=profile['language'], request_key='assessment-interview',
            expected_policy_hash=ip.digest, policy=ip, profile_id=env['saved']['qualification_id'])
        for _ in range(100):
            if current['state']['phase'] != 'active':
                break
            questions = current['state']['drafts']; assert questions, current['state']['analysis']
            changes = {q['path']: values[q['path']] for q in questions}
            current = await entry_interviews.record_action(env['engine'], actor=ADMIN, case_id=env['cases']['visa'],
                applicant_id=subject['id'], interview_id=current['interview_id'], expected_revision=current['revision'],
                request_key='answer-' + str(current['revision']), policy=ip, expected_policy_hash=ip.digest,
                operation=dict(action='answer', displayed=list(changes), changes=changes))
        assert current['state']['handoff']['card']['reasons'] == ['intake_complete'], current['state']['analysis']
        return await entry_interviews.record_action(env['engine'], actor=OWNER, case_id=env['cases']['visa'],
            applicant_id=subject['id'], interview_id=current['interview_id'], expected_revision=current['revision'],
            request_key='ack-assessment', policy=ip, expected_policy_hash=None,
            operation=dict(action='ack', confirmed=True, card_hash=current['state']['handoff']['hash']))
    env['interview'] = asyncio.run(run())


def setup(env, tmp_path, *, country='RUS', visits=None, end='2026-11-10', language='ru'):
    source(env, tmp_path); policies(env); env['person'] = person(env)
    doc = profile(); doc['language'] = language
    doc['profile'].update(citizenship=[country], entry_passport_country=country, exit_date=end)
    env['profile_doc'] = doc
    env['saved'] = save_profile(env, env['person'], doc=doc)
    env['history'] = save_history(env, env['person'], env['saved'], doc=document(history_complete=True, intervals=visits or []))
    complete_interview(env, doc, visits or [])
    return env


def assess(env, **changes):
    args = dict(actor=ADMIN, case_id=env['cases']['visa'], applicant_id=env['person']['id'],
        assessment_policy=env['assessment_policy'], qualification_policy=env['qualification_policy'],
        interview_policy=env['interview_policy'], publication_policy=POLICY)
    return asyncio.run(service.assess(env['engine'], **(args | changes)))


def test_full_source_empty_history_positive_without_writes(env, tmp_path):
    setup(env, tmp_path)
    statements = []
    def capture(conn, cursor, statement, params, context, many):
        statements.append(statement.lstrip().split()[0].upper())
    event.listen(env['engine'].sync_engine, 'before_cursor_execute', capture)
    try:
        result = assess(env)
    finally:
        event.remove(env['engine'].sync_engine, 'before_cursor_execute', capture)
    assert result['status'] == 'qualified_recorded_plan', result['reasons']
    assert result['selected_regime'] == 'KG.VF.EAEU' and result['selected_product'] == 'NO_VISA'
    assert result['visa_required'] is False and result['duration']['minimum_planned_headroom'] == 80
    assert result['registration']['exemption_days'] == 30 and result['registration']['actual_deadline'] is None
    assert not result['may_quote'] and not result['entry_eligibility_evaluated']
    assert result['arithmetic']['mode'] == 'review_only' and not result['arithmetic']['publication_approved']
    assert not {'INSERT', 'UPDATE', 'DELETE', 'CREATE', 'ALTER'} & set(statements)
    assert len(env['assessment_policy'].document['regimes']) == 18


@pytest.mark.parametrize('country,visits,end,reason,window', [
    ('RUS', [interval()], '2026-11-10', None, 180),
    ('USA', [], '2026-11-10', None, 60),
    ('USA', [], '2026-12-15', 'planned_stay_exceeds_allowance', 60),
    ('TJK', [], '2026-11-10', None, 120),
    ('RUS', [interval(entry_date='2026-04-01', exit_date='2026-06-19')], '2026-11-10', None, 180),
    ('RUS', [], '2026-12-02', 'registration_trip_exceeds_exemption', 180),
    ('UZB', [], '2026-11-10', 'registration_submission_requires_review', 120),
    ('MDA', [], '2026-11-10', 'registration_exemption_unavailable', None),
    ('RUS', [interval(entry_date='2026-07-01', exit_date='2026-09-19')], '2026-11-10', 'planned_stay_exceeds_allowance', 180),
    ('RUS', [interval(entry_date='2026-07-01', exit_date='2026-09-16')], '2026-11-10', 'stay_margin_requires_specialist', 180),
])
def test_personal_history_changes_result_and_other_window(env, tmp_path, country, visits, end, reason, window):
    setup(env, tmp_path, country=country, visits=visits, end=end)
    result = assess(env)
    assert result['reasons'] == ([reason] if reason else []), result['reasons']
    assert (result['selected_product'] == 'NO_VISA') is (reason is None)
    if window:
        assert result['duration']['window_days'] == window
    if visits and visits[0]['entry_date'] == '2026-04-01':
        daily = result['arithmetic']['scenario']['daily']
        assert daily[0]['reported_history_days'] > daily[-1]['reported_history_days']


def test_authority_boundaries_never_select(env, tmp_path):
    setup(env, tmp_path)
    for authority in ('assessment_policy', 'qualification_policy', 'interview_policy', 'publication_policy'):
        result = assess(env, **{authority: None})
        assert result['reasons'] and result['selected_product'] is None
        if authority == 'publication_policy':
            assert result['registration']['status'] != 'within_planned_exemption'
    for field, value, reason in (
        ('source_hash', 'f'*64, 'assessment_authority_source_changed'),
        ('qualification_policy_hash', 'f'*64, 'assessment_authority_source_changed'),
        ('review_due_on', '2026-10-11', 'assessment_authority_outside_validity'),
        ('review_due_on', '2026-11-05', 'assessment_authority_does_not_cover_trip')):
        doc = env['assessment_policy'].document; doc[field] = value
        result = assess(env, assessment_policy=AssessmentPolicy(doc))
        assert result['reasons'] == [reason] and result['selected_product'] is None
    doc = env['assessment_policy'].document; doc['regimes'].pop()
    assert assess(env, assessment_policy=AssessmentPolicy(doc))['reasons'] == ['assessment_regime_set_incomplete']
    from app.config import Settings
    from app.domain.assessment_policy import configured_policy
    assert configured_policy(Settings(_env_file=None)) is None


def test_personal_history_gates_and_withdrawal(env, tmp_path):
    setup(env, tmp_path)
    cases = [
        (document(history_complete=None), 'personal_history_review_required'),
        (document(history_complete=True, as_of='2026-10-11'), 'personal_history_review_required'),
        (document(history_complete=True, intervals=[interval(basis='visa')]), 'personal_history_basis_or_passport_requires_review'),
        (document(history_complete=True, intervals=[interval(passport_country='USA')]), 'personal_history_basis_or_passport_requires_review'),
        (document(history_complete=True, intervals=[interval(passport_ref='b'*32)]), 'personal_history_review_required'),
        (document(history_complete=True, intervals=[interval(confirmed=False)]), 'personal_history_review_required'),
        (document(history_complete=True, intervals=[interval(exit_date=None)]), 'personal_history_open_visit'),
        (document(history_complete=True, intervals=[interval(), interval(ref='other')]), 'personal_history_overlapping_visits'),
        (document(history_complete=True, intervals=[interval()]), 'interview_history_conflict'),
    ]
    revision = 1
    for doc, reason in cases:
        save_history(env, env['person'], env['saved'], revision=revision, key=f'negative-{revision}', doc=doc)
        revision += 1
        result = assess(env)
        assert result['reasons'] == [reason] and result['selected_regime'] is None
    withdraw(env, env['person'], revision=revision)
    assert assess(env)['reasons'] == ['personal_history_withdrawn']


def test_interview_correction_consent_and_profile_change(env, tmp_path):
    setup(env, tmp_path)
    current = env['interview']; ip = env['interview_policy']
    def action(operation):
        nonlocal current
        current = asyncio.run(entry_interviews.record_action(env['engine'], actor=OWNER, case_id=env['cases']['visa'],
            applicant_id=env['person']['id'], interview_id=current['interview_id'], expected_revision=current['revision'],
            request_key='post-ack-' + str(current['revision']), policy=ip,
            expected_policy_hash=None if operation['action'] == 'interrupt' else ip.digest, operation=operation))
    action(dict(action='correct', changes={'applicant.age': 31}, displayed=['applicant.age']))
    assert assess(env)['reasons'] == ['interview_changed_after_ack']
    action(dict(action='correct', changes={'applicant.age': 30}, displayed=['applicant.age']))
    assert assess(env)['selected_product'] == 'NO_VISA'
    action(dict(action='interrupt', reason='consent_withdrawn'))
    assert assess(env)['reasons'] == ['interview_consent_required']
    env['saved'] = save_profile(env, env['person'], revision=1, key='new-profile', doc=env['profile_doc'])
    assert assess(env)['reasons'] == ['personal_history_review_required']
    save_history(env, env['person'], env['saved'], revision=1, key='new-profile-history', doc=document(history_complete=True))
    assert assess(env)['reasons'] == ['interview_profile_changed']


def test_registration_distinctions_and_manual_unknowns(env, tmp_path):
    # These pure checks exercise preserved source conflicts directly; the
    # production importer itself rejects an exemption/default overlap.
    source(env, tmp_path); policies(env)
    bundle = deepcopy(env['bundle']); p = profile()['profile']
    p.update(entry_passport_country='MDA')
    r = assessment_rules.registration(bundle, p)
    assert r['reason'] == 'registration_exemption_unavailable' and r['term_source_id'] == 'KG.REG.TERM.MDA'
    p['entry_passport_country'] = 'UZB'
    r = assessment_rules.registration(bundle, p)
    assert r['reason'] == 'registration_submission_requires_review' and r['actual_deadline'] is None
    p.update(entry_passport_country='RUS', exit_date='2026-12-02')
    assert assessment_rules.registration(bundle, p)['reason'] == 'registration_trip_exceeds_exemption'
    next(u for u in bundle['units'] if u['unit_id'] == 'KG.REG.DEFAULT')['value']['not_in_list'].append('RUS')
    assert assessment_rules.registration(bundle, p)['reason'] == 'registration_source_conflict'
    authority = env['assessment_policy'].document
    outcomes = assessment_rules.applicability(authority, dict(entry_passport_country='RUS', document_type='ordinary'))
    assert outcomes['KG.SP.HK_MACAO']['status'] == 'unknown'
    outcomes = assessment_rules.applicability(authority, dict(entry_passport_country='IND', document_type='ordinary'))
    assert outcomes['KG.SP.CHN_IND_LONGTERM_VISA']['status'] == 'unknown'
    assert outcomes['KG.VR.GENERAL']['status'] == 'met'


def test_source_matrix_business_work_family_special_and_material_details(env, tmp_path):
    source(env, tmp_path); policies(env); env['person'] = person(env)
    matrix = [
        ({'citizenship': ['IND'], 'entry_passport_country': 'IND', 'purpose': 'business_meeting',
          'purpose_details': 'Synthetic business meeting', 'inviting_party': {'exists': False}},
         'business_mapping_requires_specialist'),
        ({'citizenship': ['UZB'], 'entry_passport_country': 'UZB', 'purpose': 'work_hire'}, 'profile_stop_requires_specialist'),
        ({'document_type': 'diplomatic'}, 'profile_stop_requires_specialist'),
        ({'applicants_count': 2, 'family': [{'relation': 'spouse', 'travels_together': True}]},
         'individual_assessment_scope_requires_specialist'),
        ({'purpose_details': 'Synthetic paid employment despite tourism enum'}, 'additional_profile_evidence_requires_reconciliation'),
        ({'violations': {'overstay': False, 'fines': False, 'deportation_or_ban': False, 'ban_until': '2027-01-01'}},
         'additional_profile_evidence_requires_reconciliation'),
        ({'event_dates': {'from': '2026-11-02', 'to': '2026-11-03'}}, 'additional_profile_evidence_requires_reconciliation'),
        ({'escalation': {'complaint': False, 'refund_question': False, 'legal_question': True, 'conflicting_answers': False}},
         'profile_stop_requires_specialist'),
    ]
    for revision, (changes, reason) in enumerate(matrix):
        doc = profile(); doc['profile'].update(changes)
        save_profile(env, env['person'], revision=revision, key=f'matrix-{revision}', doc=doc)
        result = assess(env)
        assert result['reasons'] == [reason], result['reasons']
        assert result['selected_product'] is None and not result['may_quote']


def test_case_person_payer_isolation_and_profile_corruption(env, tmp_path):
    from app.domain.entry_storage import save_stay_history
    from app.domain.permissions import Actor
    from app.domain.service_authz import PermissionDenied
    from sqlalchemy import text
    source(env, tmp_path); policies(env); env['person'] = person(env)
    env['saved'] = save_profile(env, env['person'], doc=profile())
    asyncio.run(save_stay_history(env['engine'], actor=ADMIN, contact_id=env['contacts']['visa'], expected_revision=0,
        request_key='payer-is-not-person', document=document(history_complete=True, intervals=[])))
    assert assess(env)['reasons'] == ['personal_history_missing']
    other = person(env, 'another-person')
    assert assess(env, applicant_id=other['id'])['reasons'] == ['individual_profile_missing']
    with pytest.raises(EntryStorageInvalid):
        assess(env, case_id=env['cases']['other'])
    for actor in (None, Actor('medina'), Actor('bot', True)):
        with pytest.raises(PermissionDenied):
            assess(env, actor=actor)
    async def corrupt():
        async with env['engine'].begin() as conn:
            await conn.execute(text('UPDATE entry_applicant_profiles SET snapshot_hash=:bad WHERE id=:id'),
                               dict(bad='f'*64, id=env['saved']['qualification_id']))
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):
        assess(env)
