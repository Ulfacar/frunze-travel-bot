"""Real declared count/byte capacities, with no reduced limits."""
from copy import deepcopy

import pytest

from app.domain.entry_storage import EntryStorageInvalid
from app.domain import entry_anchor_rules as rules
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_anchors import setup, args, write, read, policy


def request_at(base, revision, key, *, withdrawal=False):
    result = deepcopy(base)
    result.update(expected_revision=revision, request_key=f'RESERVE-{revision}', anchor_key=key)
    if withdrawal:
        result['policy'] = None
        result['operation'] = dict(action='withdraw', confirmed=True,
            data=dict(on='2026-09-06', reason='no_longer_confirmed', proof='d'*64))
    return result


def test_actual_64_records_still_allow_terminal_withdrawal_and_old_retry(env):
    prepared = setup(env, kind='address_change')
    base = args(env, prepared, kind='address_change', anchor_key='CHANGE')
    first = None
    for revision in range(64):
        receipt = write(env, request_at(base, revision, 'CHANGE'))
        first = first or receipt
    assert read(env, prepared)['revision'] == 64
    with pytest.raises(EntryStorageInvalid, match='history_limit'):
        write(env, request_at(base, 64, 'CHANGE'))
    cancelled = request_at(base, 64, 'CHANGE', withdrawal=True)
    assert write(env, cancelled)['revision'] == 65
    current = read(env, prepared)
    assert current['terminal'] and not any(row['usable'] for row in current['observations'])
    assert write(env, request_at(base, 0, 'CHANGE') | {'policy': None}) == first
    assert write(env, cancelled)['revision'] == 65


def test_real_byte_boundary_reserves_all_16_active_keys(env):
    prepared = setup(env, kind='address_change')
    doc = policy().document
    doc['operators'] += ['reviewer'+str(i).zfill(2)+'x'*54 for i in range(19)]
    wide = rules.AnchorPolicy(doc)
    base = args(env, prepared, kind='address_change', anchor_key='CHANGE-0', policy=wide)
    revision = 0
    for i in range(16):
        write(env, request_at(base, revision, f'CHANGE-{i}'))
        revision += 1
    assert len(read(env, prepared, policy=wide)['observations']) == 16
    while revision < 64:
        try:
            write(env, request_at(base, revision, 'CHANGE-0'))
        except EntryStorageInvalid as exc:
            assert 'history_limit' in str(exc)
            break
        revision += 1
    assert 16 <= revision < 64, 'This must exercise bytes, not only record count'
    stopped = revision
    for i in range(16):
        receipt = write(env, request_at(base, revision, f'CHANGE-{i}', withdrawal=True))
        assert receipt['revision'] == revision+1
        revision += 1
    current = read(env, prepared, policy=None)
    assert current['revision'] == stopped+16
    assert all(x['reasons']==['actual_anchor_withdrawn'] for x in current['observations'])
