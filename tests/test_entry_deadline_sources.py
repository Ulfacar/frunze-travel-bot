"""Application deadline anchors must be real scoped facts, not caller dates."""
import asyncio
from datetime import date

import pytest

from app.domain import entry_applications as applications, entry_deadline_sources as sources
from app.domain.entry_storage import EntryStorageInvalid, import_work_calendars
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import person, application, record, enforce_sqlite_foreign_keys
from tests.test_entry_issued import setup, write
from tests.test_entry_storage import calendars


def selection(env, anchor=None, calendar_ids=None):
    return dict(knowledge_version_id=env['version'], calendar_ids=calendar_ids or [], anchor=anchor,
        policy=dict(status='proposed',timezone='Asia/Bishkek',count_anchor_day=False,month_end=None,hours_mode=None))


def calculate(env, app, data):
    async def run(session):
        case = await applications._case(session, env['cases']['visa'])
        selected = await applications._application(session, case.id, app['id'])
        return await sources.calculate_bound_deadline(session, case, selected, 'KG.DL.TEST', data)
    return asyncio.run(applications._run(env['engine'],run))


def test_actual_travel_anchor_calendar_pin_and_no_operational_date_from_draft(env):
    app = setup(env)
    travel = write(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,
                                       source='stamp',passport_fingerprint='b'*64))
    imported = asyncio.run(import_work_calendars(env['engine'],actor=ADMIN,document=calendars()))
    ids = [row['calendar_id'] for row in imported]
    data = selection(env, dict(kind='travel',id=travel['id']), ids)
    snapshot = calculate(env,app,data)
    assert snapshot['anchor']['value'] == '2026-09-07'
    assert snapshot['anchor']['snapshot_hash'] == travel['snapshot_hash']
    assert snapshot['review']['scenario']['due'] == '2026-09-02'
    assert {c['id'] for c in snapshot['source']['calendars']} == set(ids)
    result = sources.summary(snapshot)
    assert result['candidate_due'] == '2026-09-02'
    assert result['operational_due_on'] is None and not result['may_quote']
    assert not result['publication_approved']


def test_missing_calendar_anchor_and_wrong_semantics_stay_unknown(env):
    app = setup(env)
    empty = calculate(env,app,selection(env))
    assert 'actual_anchor_missing' in empty['blockers'] and empty['review'] is None
    travel = write(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,
                                       source='stamp',passport_fingerprint='b'*64))
    missing = calculate(env,app,selection(env,dict(kind='travel',id=travel['id'])))
    assert sources.summary(missing)['status'] == 'unknown'
    assert missing['blockers'] and not missing['review']['scenario']
    async def submitted():
        async with env['sm']() as session:
            selected = await applications._application(session,env['cases']['visa'],app['id'])
            rows = await applications._events(session,selected)
            return next(r.id for r in rows if r.status=='submitted')
    wrong = calculate(env,app,selection(env,dict(kind='application_event',id=asyncio.run(submitted()))))
    assert 'source_anchor_not_supported' in wrong['blockers'] and wrong['review'] is None


def test_foreign_and_nontravel_anchors_refused_and_newer_entry_requires_recalculation(env):
    app = setup(env)
    other = setup(env,'other',case='other')
    first = write(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,
                                      source='stamp',passport_fingerprint='b'*64))
    foreign = write(env,other,'travel',dict(direction='entry',on='2026-09-07',proof='a'*64,
                                          source='stamp',passport_fingerprint='b'*64),case='other')
    with pytest.raises(EntryStorageInvalid): calculate(env,app,selection(env,dict(kind='travel',id=foreign['id'])))
    write(env,app,'travel',dict(direction='entry',on='2026-09-09',proof='c'*64,
                              source='stamp',passport_fingerprint='b'*64))
    stale = calculate(env,app,selection(env,dict(kind='travel',id=first['id'])))
    assert 'actual_anchor_superseded' in stale['blockers']
    assert sources.summary(stale)['operational_due_on'] is None


def test_command_requires_actual_anchor_reference_and_dated_manual_proof():
    valid = dict(action='manual',confirmed=True,data=dict(due_on='2026-11-01',evidence_on='2026-10-01',
        proof='a'*64,source='portal',reason='official_date'))
    assert sources.normalize(valid,cutoff=date(2026,10,10))==valid
    for change in ({'proof':'url'}, {'evidence_on':'2999-01-01'}, {'source':'client_request'}, {'due_on':'2026-02-30'}):
        with pytest.raises(EntryStorageInvalid):
            sources.normalize({**valid,'data':{**valid['data'],**change}},cutoff=date(2026,10,10))
    base = dict(knowledge_version_id=1,calendar_ids=[],anchor=None,policy=None)
    for anchor in ({'kind':'planned','id':1}, {'kind':'travel','id':True}, {'kind':'travel','id':1,'date':'2026-01-01'}):
        with pytest.raises(EntryStorageInvalid):
            sources.normalize(dict(action='recalculate',confirmed=True,data={**base,'anchor':anchor}),cutoff=date(2026,10,10))
