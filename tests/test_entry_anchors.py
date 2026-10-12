"""Real own-person facts, correction/withdrawal and preserved historical receipts."""
import asyncio
from copy import deepcopy

import pytest

from app.domain import entry_anchors as service, entry_anchor_rules as rules
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import person, application, record as app_event, read as app_read, enforce_sqlite_foreign_keys
from tests import test_applicant_profiles as profiles, test_entry_issued as issued


def policy():
    return rules.AnchorPolicy(dict(format=rules.FORMAT, reference='SYNTHETIC-ACTUAL-DATES', proof='a'*64,
        operators=['admin'], kinds=list(rules.KINDS), valid_from='2026-01-01', review_due_on='2027-12-31'))


def setup(env, kind='registration_period', key='ONE'):
    subject = person(env, key); app = application(env, subject, key, procedure=rules.KINDS[kind])
    doc = profiles.request(); doc['profile'].update(citizenship=['RUS'], entry_passport_country='RUS', purpose='work_hire')
    profile = profiles.save(env, subject, doc=doc, key=key)
    app_event(env, app, key+'-SUBMIT', reference='AP'+str(app['id']).zfill(6))
    app_event(env, app, key+'-APPROVE', status='approved', occurred_on='2026-09-02', reference='AP'+str(app['id']).zfill(6))
    if kind == 'visa_period': issued.file(env, app); issued.review(env, app)
    return subject, app, profile


def read(env, prepared, **changes):
    subject, app, _ = prepared
    return asyncio.run(service.read(env['engine'], **(dict(actor=ADMIN, case_id=app['case_id'], applicant_id=subject['id'],
        application_id=app['id'], policy=policy()) | changes)))


def args(env, prepared, kind='registration_period', anchor_key='CERTIFICATE', **changes):
    subject, app, profile = prepared
    value = dict(valid_from='2026-09-03', valid_until='2026-11-01', document_ref='a'*64, passport_ref='b'*64) if kind in rules.PERIODS else {}
    if kind == 'registration_period': value.update(basis_type='employment', tax_status='pending', basis_proof='e'*64)
    if kind in rules.CHANGES: value.update(before_ref='1'*64, after_ref='2'*64)
    revision = read(env, prepared)['revision']
    data = dict(on='2026-09-05', profile_id=profile['qualification_id'], profile_hash=profile['snapshot_hash'],
        application_event_id=app_read(env, app)['current']['id'], reference='SYNTHETIC-DOCUMENT', proof='c'*64,
        source='official_document', value=value)
    return dict(actor=ADMIN, case_id=app['case_id'], applicant_id=subject['id'], application_id=app['id'], kind=kind,
        anchor_key=anchor_key, expected_revision=revision, request_key=f'{app["id"]}-{anchor_key}-{revision}',
        operation=dict(action='record', data=data, confirmed=True), policy=policy()) | changes


def write(env, arguments): return asyncio.run(service.record(env['engine'], **arguments))


def test_four_actual_period_kinds_preserve_expired_dates_and_require_own_approval(env):
    for kind in sorted(rules.PERIODS):
        prepared = setup(env, kind, key=kind.upper()); request = args(env, prepared, kind)
        request['operation']['data']['value']['valid_until'] = '2026-09-10'
        saved = write(env, request)
        current = read(env, prepared)
        assert current['observations'][0]['usable']
        assert saved['operation']['data']['value']['valid_until'] == '2026-09-10'
        assert write(env, request | {'policy': None}) == saved
        with pytest.raises(PermissionDenied): write(env, args(env, prepared, kind, policy=None))
        # Other person's actual approval and profile cannot become this anchor.
        other = setup(env, kind, key=kind.upper()+'OTHER')
        for name, value in [('profile_id', other[2]['qualification_id']), ('application_event_id', app_read(env, other[1])['current']['id'])]:
            wrong = args(env, prepared, kind); wrong['operation']['data'][name] = value
            with pytest.raises(EntryStorageConflict): write(env, wrong)


def test_correction_profile_currentness_withdrawal_and_exact_old_retry(env):
    prepared = setup(env); request = args(env, prepared); saved = write(env, request)
    correction = args(env, prepared); correction['operation']['data']['value']['valid_until'] = '2026-11-02'
    corrected = write(env, correction)
    assert read(env, prepared)['observations'][0]['receipt']['id'] == corrected['id']
    doc = profiles.request(); doc['profile'].update(citizenship=['RUS'], entry_passport_country='RUS', purpose='work_hire')
    profiles.save(env, prepared[0], doc=doc, revision=1, key='NEW-PROFILE')
    current = read(env, prepared)
    assert not current['observations'][0]['usable']
    assert 'actual_anchor_profile_changed' in current['observations'][0]['reasons']
    assert write(env, request | {'policy': None}) == saved
    withdrawal = args(env, prepared, policy=None)
    withdrawal['operation'] = dict(action='withdraw', confirmed=True, data=dict(on='2026-09-06', reason='no_longer_confirmed', proof='d'*64))
    removed = write(env, withdrawal)
    assert read(env, prepared)['observations'][0]['reasons'] == ['actual_anchor_withdrawn']
    assert write(env, request | {'policy': None}) == saved
    assert write(env, withdrawal) == removed


def test_repeated_effective_changes_remain_distinct_and_periods_cannot_compete(env):
    prepared = setup(env); write(env, args(env, prepared))
    with pytest.raises(EntryStorageInvalid, match='period_ambiguous'):
        write(env, args(env, prepared, anchor_key='SECOND-CERTIFICATE'))
    for key, on in [('MOVE-ONE', '2026-09-05'), ('MOVE-TWO', '2026-09-12')]:
        request = args(env, prepared, 'address_change', key); request['operation']['data']['on'] = on
        write(env, request)
    observations = read(env, prepared)['observations']
    assert {v['receipt']['anchor_key'] for v in observations if v['usable']} == {'CERTIFICATE', 'MOVE-ONE', 'MOVE-TWO'}
    assert [v['receipt']['operation']['data']['on'] for v in observations if v['receipt']['kind']=='address_change'] == ['2026-09-05', '2026-09-12']


def test_strict_dates_ids_approval_and_actual_visa_file(env):
    prepared = setup(env, 'visa_period'); request = args(env, prepared, 'visa_period')
    for path, value in [('profile_id', True), ('on', '2099-01-01')]:
        wrong = deepcopy(request); wrong['operation']['data'][path] = value
        with pytest.raises(EntryStorageInvalid): write(env, wrong)
    wrong = deepcopy(request); wrong['operation']['data']['value']['document_ref'] = 'f'*64
    with pytest.raises(EntryStorageInvalid, match='document_mismatch'): write(env, wrong)
    assert write(env, request)['kind'] == 'visa_period'
    issued.write(env, prepared[1], 'passport_change', dict(on='2026-09-06', passport_fingerprint='f'*64))
    assert 'actual_anchor_document_changed' in read(env, prepared)['observations'][0]['reasons']
