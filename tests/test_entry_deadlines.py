import asyncio

import pytest
from sqlalchemy import text

from app.domain import entry_deadlines as service
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_deadline_sources import selection
from tests.test_entry_issued import setup, write as issued


def read(env,app,case='visa',**kwargs):
    return asyncio.run(service.read_deadline_history(env['engine'],actor=ADMIN,case_id=env['cases'][case],
        application_id=app['id'],rule_unit_id='KG.DL.TEST',**kwargs))


def write(env,app,action,data,revision=None,key=None,case='visa'):
    if revision is None:revision=read(env,app,case)['current_revision']
    return asyncio.run(service.record_deadline_operation(env['engine'],actor=ADMIN,case_id=env['cases'][case],
        application_id=app['id'],rule_unit_id='KG.DL.TEST',expected_revision=revision,request_key=key or f'{action}-{revision}',
        operation=dict(action=action,data=data,confirmed=True)))


def manual(proof='a'*64,reason='official_date',due_on='2026-10-20'):
    return dict(proof=proof,reason=reason,due_on=due_on,evidence_on='2026-09-10',source='portal')


def test_unknown_then_manual_correction_clear_and_recalculation_preserve_history(env):
    app=setup(env)
    with pytest.raises(EntryStorageInvalid,match='source_required'):write(env,app,'manual',manual())
    unknown=write(env,app,'recalculate',selection(env))
    assert unknown['summary']['status']=='unknown' and unknown['summary']['operational_due_on'] is None
    first=write(env,app,'manual',manual())
    assert first['summary']['operational_due_on']=='2026-10-20' and not first['summary']['may_quote']
    corrected=write(env,app,'manual',manual(reason='corrected_date',due_on='2026-10-19'))
    assert corrected['summary']['operational_due_on']=='2026-10-19'
    assert read(env,app,revision=first['revision'])['selected']==first
    cleared=write(env,app,'clear',dict(reason='wrong_document'))
    assert cleared['summary']['operational_due_on'] is None
    write(env,app,'manual',manual())
    recalculated=write(env,app,'recalculate',selection(env))
    assert recalculated['snapshot']['manual'] is None and recalculated['summary']['status']=='unknown'
    assert read(env,app,revision=corrected['revision'])['selected']==corrected


def test_new_actual_entry_invalidates_manual_date_without_destroying_old_evidence(env):
    app=setup(env)
    travel=issued(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,source='stamp',passport_fingerprint='b'*64))
    write(env,app,'recalculate',selection(env,dict(kind='travel',id=travel['id'])))
    saved=write(env,app,'manual',manual())
    newer=issued(env,app,'travel',dict(direction='entry',on='2026-09-09',proof='c'*64,source='stamp',passport_fingerprint='b'*64))
    current=read(env,app)['selected']
    assert current['snapshot']==saved['snapshot']
    assert read(env,app,replay=True)['selected']==current
    assert current['summary']['status']=='anchor_changed' and current['summary']['operational_due_on'] is None
    with pytest.raises(EntryStorageInvalid,match='recalculation_required'):write(env,app,'manual',manual())
    new=write(env,app,'recalculate',selection(env,dict(kind='travel',id=newer['id'])))
    assert new['snapshot']['manual'] is None and new['snapshot']['anchor']['value']=='2026-09-09'
    assert write(env,app,'manual',manual())['summary']['operational_due_on']=='2026-10-20'


def test_duplicate_requests_cas_and_person_scope(env):
    app=setup(env)
    first=write(env,app,'recalculate',selection(env),key='first')
    write(env,app,'manual',manual())
    assert write(env,app,'recalculate',selection(env),revision=0,key='first')==first
    with pytest.raises(EntryStorageConflict):write(env,app,'manual',manual(),revision=0,key='first')
    with pytest.raises(EntryStorageConflict):write(env,app,'manual',manual(),revision=0,key='stale')
    with pytest.raises(EntryStorageInvalid):read(env,app,case='other')
    with pytest.raises(EntryStorageInvalid):write(env,app,'manual',manual(),revision=0,case='other')
    assert read(env,app)['current_revision']==2


def test_corrupt_history_fails_closed_on_read_write_and_retry(env):
    app=setup(env)
    write(env,app,'recalculate',selection(env),key='first')
    async def corrupt():
        async with env['engine'].begin() as conn:
            await conn.execute(text("UPDATE entry_deadline_revisions SET snapshot_hash=:hash"),{'hash':'0'*64})
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):read(env,app)
    with pytest.raises(EntryStorageInvalid):write(env,app,'recalculate',selection(env),revision=0,key='first')
    with pytest.raises(EntryStorageInvalid):write(env,app,'manual',manual(),revision=1)


def test_recalculation_keeps_exact_source_version_and_bounded_history(env,monkeypatch):
    app=setup(env)
    row=write(env,app,'recalculate',selection(env))
    assert row['snapshot']['source']['knowledge']['version_id']==env['version']
    assert row['snapshot']['runtime']['calculation']['algorithm']
    assert read(env,app,replay=True)['selected']==row
    runtime=service._runtime()
    monkeypatch.setattr(service,'_runtime',lambda:{**runtime,'binding':'upgraded'})
    assert read(env,app)['selected']==row
    with pytest.raises(EntryStorageInvalid,match='runtime_changed'):read(env,app,replay=True)
    monkeypatch.setattr(service,'MAX_BYTES',1)
    with pytest.raises(EntryStorageInvalid,match='history_limit'):read(env,app)
    with pytest.raises(EntryStorageInvalid,match='history_limit'):write(env,app,'manual',manual(),revision=1)


@pytest.mark.parametrize('actor',[None,{},Actor('manager'),Actor('bot',True)])
def test_domain_authorization_precedes_payload_and_engine(actor):
    args=dict(actor=actor,case_id=1,application_id=1)
    with pytest.raises(PermissionDenied):
        asyncio.run(service.read_deadline_options(None,**args))
    with pytest.raises(PermissionDenied):
        asyncio.run(service.read_deadline_history(None,**args,rule_unit_id='bad'))
    with pytest.raises(PermissionDenied):
        asyncio.run(service.record_deadline_operation(None,**args,rule_unit_id='bad',expected_revision=0,request_key='a',operation={}))


def test_new_calendar_version_changes_candidate_without_rewriting_old_deadline(env):
    from app.domain.entry_storage import import_work_calendars
    from tests.test_entry_storage import calendars
    app=setup(env)
    travel=issued(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,source='stamp',passport_fingerprint='b'*64))
    anchor=dict(kind='travel',id=travel['id'])
    initial=asyncio.run(import_work_calendars(env['engine'],actor=ADMIN,document=calendars()))
    first=write(env,app,'recalculate',selection(env,anchor,[r['calendar_id'] for r in initial]))
    write(env,app,'manual',manual())
    changed=calendars();year=changed['calendars'][0];year['version']=2
    year['days'].append(dict(date='2026-09-04',is_working=False,kind='public_holiday',title='Synthetic new rest day',source_ref='synthetic-only'))
    latest=asyncio.run(import_work_calendars(env['engine'],actor=ADMIN,document=changed))
    second=write(env,app,'recalculate',selection(env,anchor,[r['calendar_id'] for r in latest]))
    assert first['summary']['candidate_due']=='2026-09-02' and second['summary']['candidate_due']=='2026-09-01'
    assert second['summary']['operational_due_on'] is None
    assert read(env,app,revision=first['revision'],replay=True)['selected']==first
    assert read(env,app,replay=True)['selected']==second


def test_imported_rule_with_unknown_value_never_guesses_a_deadline(env,tmp_path):
    import shutil
    import yaml
    from app.domain.knowledge_import import create_kg_entry_set, import_bundle
    from tests.test_admin_kg_entry import FIX
    app=setup(env)
    travel=issued(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,source='stamp',passport_fingerprint='b'*64))
    folder=tmp_path/'unknown-bundle';shutil.copytree(FIX/'synthetic_bundle',folder)
    units=yaml.safe_load((folder/'units.yaml').read_text('utf-8'))
    rule=next(r for r in units if r['unit_id']=='KG.DL.TEST')
    rule.update(blocked_value={'source':rule['value'],'reason':'Synthetic rule awaiting interpretation'},
                value=None,confirmation_status='needs_verification',label='verify')
    (folder/'units.yaml').write_text(yaml.safe_dump(units,allow_unicode=True),'utf-8')
    meta=yaml.safe_load((folder/'meta.yaml').read_text('utf-8'));meta['version_label']='synthetic unknown deadline'
    (folder/'meta.yaml').write_text(yaml.safe_dump(meta),'utf-8')
    async def load():
        set_id=await create_kg_entry_set(env['engine'],actor=ADMIN)
        return await import_bundle(env['engine'],actor=ADMIN,set_id=set_id,directory=folder,source=FIX/'synthetic_source.txt')
    imported=asyncio.run(load())
    assert imported.accepted,imported.report['errors']
    data=selection(env,dict(kind='travel',id=travel['id']));data['knowledge_version_id']=imported.version_id
    row=write(env,app,'recalculate',data)
    assert row['summary']['candidate_due'] is None and 'rule_value_missing' in row['summary']['blockers']
    assert row['summary']['operational_due_on'] is None and not row['summary']['may_quote']


def test_concurrent_deadline_writes_have_one_successor(env):
    app=setup(env)
    async def race():
        kwargs=dict(actor=ADMIN,case_id=env['cases']['visa'],application_id=app['id'],rule_unit_id='KG.DL.TEST',expected_revision=0,
            operation=dict(action='recalculate',data=selection(env),confirmed=True))
        return await asyncio.gather(*(service.record_deadline_operation(env['engine'],request_key=k,**kwargs)
                                     for k in ('left','right')),return_exceptions=True)
    results=asyncio.run(race())
    assert sum(isinstance(r,dict) for r in results)==1
    assert sum(isinstance(r,EntryStorageConflict) for r in results)==1
    assert read(env,app)['current_revision']==1
