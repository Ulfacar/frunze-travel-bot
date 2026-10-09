"""E5-03C: real transactions on isolated SQLite, no runtime/production credentials."""
import asyncio
from copy import deepcopy
from datetime import date
import json
from pathlib import Path

import pytest
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.entry_storage import (EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable,
    import_work_calendars, read_stay_history, read_work_calendars, save_stay_history)
from app.domain.entry_calculations import read_calculation, replay_calculation, save_calculation
from app.domain.knowledge_import import create_kg_entry_set, import_bundle
from app.domain.models import (Contact, DomainBase, DomainError, ENTRY_STORAGE_MODELS, EntryCalculation,
    EntryCalculationCalendar, EntryCalculationInterval, KnowledgeVersion, StayHistory, StayInterval, WorkCalendar, WorkCalendarDay)
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied, SYSTEM_ACTOR
from app.knowledge.validation import load_document

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/kg_entry"
ADMIN = Actor("synthetic-admin", is_full_admin=True)
PASSPORT = "a" * 32


def history():
    return {"format":"kg-stay-history/1","as_of":"2026-10-01","history_complete":True,
        "intervals":[{"ref":"synthetic-visit","entry_date":"2026-09-20","exit_date":"2026-09-22",
            "basis":"visa_free","passport_country":"RUS","passport_ref":PASSPORT,
            "evidence":"passport_stamp","confirmed":True}]}


def stay_request():
    return {"rule_unit_id":"KG.VF.TEST","passport_ref":PASSPORT,
        "trip":{"mode":"new_entry","start_date":"2026-10-10","end_date":"2026-10-12","passport_country":"RUS","basis":"visa_free"},
        "policy":{"status":"proposed","count_entry_day":True,"count_exit_day":True,
                  "window_anchor":"each_day_backward_inclusive","timezone":"Asia/Bishkek"}}


def calendars():
    return load_document(FIX / "synthetic_work_calendars.json")


@pytest.fixture
def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path/'entry.sqlite3').as_posix()}",connect_args={"timeout":5})
    @event.listens_for(engine.sync_engine,"connect")
    def fk(connection, record): connection.execute("PRAGMA foreign_keys=ON")
    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(DomainBase.metadata.create_all)
        async with async_sessionmaker(engine).begin() as s: s.add_all([Contact(id=1),Contact(id=2)])
        set_id=await create_kg_entry_set(engine,actor=ADMIN)
        result=await import_bundle(engine,actor=ADMIN,set_id=set_id,directory=FIX/'synthetic_bundle',source=FIX/'synthetic_source.txt')
        assert result.accepted
        return result.version_id
    version=asyncio.run(setup())
    yield engine,version
    asyncio.run(engine.dispose())


async def save_history(db, document=None, *, key="history-1", revision=0, contact=1):
    return await save_stay_history(db[0],actor=ADMIN,contact_id=contact,expected_revision=revision,
                                   request_key=key,document=history() if document is None else document)


async def save_stay(db, history_id, *, key="calc-1", request=None, contact=1):
    return await save_calculation(db[0],actor=ADMIN,contact_id=contact,kind="stay",knowledge_version_id=db[1],
        history_id=history_id,request_key=key,request=stay_request() if request is None else request)


async def counts(engine):
    async with async_sessionmaker(engine)() as s:
        return [await s.scalar(select(func.count()).select_from(model)) for model in ENTRY_STORAGE_MODELS]


def test_history_retry_revision_and_owned_snapshot(db):
    async def scenario():
        doc=history()
        first=await save_history(db,doc)
        retry=await save_history(db,doc)
        assert retry=={**first,"reused":True}
        doc['intervals'][0]['exit_date']='2026-09-25'
        with pytest.raises(EntryStorageConflict,match='request_key'): await save_history(db,doc)
        with pytest.raises(EntryStorageConflict,match='stale'): await save_history(db,doc,key='stale')
        second=await save_history(db,doc,key='history-2',revision=1)
        assert second['revision']==2 and second['history_id']!=first['history_id']
        old=await read_stay_history(db[0],actor=ADMIN,contact_id=1,history_id=first['history_id'])
        assert old['document']==history()
        old['document']['intervals'].clear()
        assert (await read_stay_history(db[0],actor=ADMIN,contact_id=1,history_id=first['history_id']))['document']==history()
        assert await counts(db[0])==[2,2,0,0,0,0,0]
    asyncio.run(scenario())


@pytest.mark.parametrize('fault',['bad_order','future_entry','future_exit','duplicate_ref','two_open','open_conflict',
    'confirmed_statement','private','passport_number','bad_passport_ref','extra_confirmation','bad_date','cycle','nan'])
def test_bad_history_is_rejected_atomically(db,fault):
    async def scenario():
        doc=history(); row=doc['intervals'][0]
        if fault=='bad_order': row['exit_date']='2026-09-19'
        elif fault=='future_entry': row['entry_date']='2026-10-02'
        elif fault=='future_exit': row['exit_date']='2026-10-02'
        elif fault=='duplicate_ref': doc['intervals'].append(deepcopy(row))
        elif fault=='two_open':
            row['exit_date']=None;doc['intervals'].append({**row,'ref':'second'})
        elif fault=='open_conflict': doc['intervals'].append({**row,'ref':'open','entry_date':'2026-09-21','exit_date':None})
        elif fault=='confirmed_statement': row['evidence']='client_statement'
        elif fault=='private': doc['phone']='PRIVATE-CUSTOMER'
        elif fault=='passport_number': row['passport_number']='PRIVATE-CUSTOMER'
        elif fault=='bad_passport_ref': row['passport_ref']='PRIVATE-CUSTOMER'
        elif fault=='extra_confirmation': row['confirmed_by']='forged'
        elif fault=='bad_date': row['entry_date']='2026-02-30'
        elif fault=='cycle': doc['intervals'].append(doc)
        elif fault=='nan': doc['history_complete']=float('nan')
        with pytest.raises(EntryStorageInvalid) as caught: await save_history(db,doc)
        assert 'PRIVATE' not in str(caught.value) and len(str(caught.value))<100
        assert await counts(db[0])==[0]*7
    asyncio.run(scenario())


@pytest.mark.parametrize('actor',[None,{},Actor('manager',allowed_directions=frozenset({'visa'})),
    Actor('all',allowed_directions=frozenset({'visa','tours','tickets'})),Actor('',True),Actor('bot',True),SYSTEM_ACTOR,Actor('admin',1)])
def test_all_entry_operations_authorize_before_engine_or_payload(actor):
    calls=[save_stay_history(None,actor=actor,contact_id=1,expected_revision=0,request_key='x',document={}),
           read_stay_history(None,actor=actor,contact_id=1,history_id=1),
           import_work_calendars(None,actor=actor,document={}),read_work_calendars(None,actor=actor,calendar_ids=[]),
           save_calculation(None,actor=actor,contact_id=1,kind='stay',knowledge_version_id=1,request_key='x',request={}),
           read_calculation(None,actor=actor,contact_id=1,calculation_id=1),
           replay_calculation(None,actor=actor,contact_id=1,calculation_id=1)]
    for call in calls:
        with pytest.raises(PermissionDenied): asyncio.run(call)


def test_saved_stay_uses_db_history_and_replays_old_revision(db):
    async def scenario():
        saved=await save_history(db)
        first=await save_stay(db,saved['history_id'])
        assert first['result']['scenario']['daily'][-1]['scenario_presence_days']==6
        assert first['result']['exact_remaining_days'] is None and first['result']['may_quote'] is False
        assert first['input']['history'][0]['confirmed'] is True
        changed=history();changed['intervals'][0]['exit_date']='2026-09-25'
        newer=await save_history(db,changed,key='history-2',revision=1)
        later=await save_stay(db,newer['history_id'],key='calc-2')
        assert later['result']['scenario']['daily'][-1]['scenario_presence_days']==9
        replay=await replay_calculation(db[0],actor=ADMIN,contact_id=1,calculation_id=first['calculation_id'])
        assert replay['replay_verified'] and replay['result']==first['result']
        assert (await save_stay(db,saved['history_id']))=={**first,'reused':True}
        request=stay_request();request['trip']['end_date']='2026-10-13'
        with pytest.raises(EntryStorageConflict): await save_stay(db,saved['history_id'],request=request)
        first['result']['scenario']['daily'].clear()
        assert (await read_calculation(db[0],actor=ADMIN,contact_id=1,calculation_id=first['calculation_id']))['result']['scenario']['daily']
    asyncio.run(scenario())


@pytest.mark.parametrize('field',['history','history_complete','confirmed','as_of','result','slots'])
def test_caller_cannot_override_stored_facts_or_result(db,field):
    async def scenario():
        saved=await save_history(db)
        req=stay_request();req[field]=[]
        with pytest.raises(EntryStorageInvalid): await save_stay(db,saved['history_id'],request=req)
        assert (await counts(db[0]))[4:]==[0,0,0]
    asyncio.run(scenario())


@pytest.mark.parametrize('continuity',['same','changed','unknown'])
def test_uncertain_history_and_passport_are_preserved(db,continuity):
    async def scenario():
        doc=history();doc['history_complete']=None
        doc['intervals'][0].update(evidence='client_statement',confirmed=False)
        saved=await save_history(db,doc)
        req=stay_request();req['passport_ref']={'same':PASSPORT,'changed':'b'*32,'unknown':None}[continuity]
        output=await save_stay(db,saved['history_id'],request=req)
        assert output['input']['history'][0]['passport_continuity']==continuity
        assert {'history_incomplete','history_unconfirmed'}.issubset(output['result']['findings'])
        assert ('passport_history_requires_review' in output['result']['findings'])==(continuity!='same')
        assert output['result']['exact_remaining_days'] is None
    asyncio.run(scenario())


def test_contact_history_and_calculation_cannot_be_mixed(db):
    async def scenario():
        first=await save_history(db)
        with pytest.raises(EntryStorageInvalid,match='history_unavailable'):
            await save_stay(db,first['history_id'],contact=2)
        with pytest.raises(EntryStorageInvalid,match='history_unavailable'):
            await read_stay_history(db[0],actor=ADMIN,contact_id=2,history_id=first['history_id'])
        result=await save_stay(db,first['history_id'])
        for function in (read_calculation,replay_calculation):
            with pytest.raises(EntryStorageInvalid,match='calculation_unavailable'):
                await function(db[0],actor=ADMIN,contact_id=2,calculation_id=result['calculation_id'])
        assert await counts(db[0])==[1,1,0,0,1,1,0]
    asyncio.run(scenario())


def test_calendar_versions_deadline_links_and_old_replay(db):
    async def scenario():
        stored=await import_work_calendars(db[0],actor=ADMIN,document=calendars())
        ids=[r['calendar_id'] for r in stored]
        again=await import_work_calendars(db[0],actor=ADMIN,document=calendars())
        assert again==[{**r,'reused':True} for r in stored]
        async def calc(key,selected):
            return await save_calculation(db[0],actor=ADMIN,contact_id=1,kind='deadline',knowledge_version_id=db[1],
                request_key=key,request=load_document(FIX/'synthetic_deadline_review.json'),calendar_ids=selected)
        old=await calc('deadline-1',ids)
        assert old['result']['scenario']['due']=='2026-10-08'
        assert old['result']['exact_deadline'] is None and old['result']['may_quote'] is False
        changed=calendars();changed['calendars']=changed['calendars'][:1]
        changed['calendars'][0]['days']=[d for d in changed['calendars'][0]['days'] if d['date']!='2026-10-13']
        with pytest.raises(EntryStorageConflict): await import_work_calendars(db[0],actor=ADMIN,document=changed)
        changed['calendars'][0]['version']=2
        newer=await import_work_calendars(db[0],actor=ADMIN,document=changed)
        latest=await calc('deadline-2',[newer[0]['calendar_id']])
        assert latest['result']['scenario']['due']=='2026-10-10'
        replay=await replay_calculation(db[0],actor=ADMIN,contact_id=1,calculation_id=old['calculation_id'])
        assert replay['result']==old['result'] and replay['replay_verified']
        assert (await calc('deadline-1',list(reversed(ids))))['reused'] is True
    asyncio.run(scenario())


def test_missing_provisional_and_null_policy_are_saved_without_client_date(db):
    async def scenario():
        doc=calendars();doc['calendars'][0].update(completeness='provisional',provisional_note='Synthetic unknown holiday')
        stored=await import_work_calendars(db[0],actor=ADMIN,document=doc)
        for key,ids,reason in [('missing',[],'calendar_missing'),('provisional',[stored[0]['calendar_id']],'calendar_provisional')]:
            result=await save_calculation(db[0],actor=ADMIN,contact_id=1,kind='deadline',knowledge_version_id=db[1],
                request_key=key,request=load_document(FIX/'synthetic_deadline_review.json'),calendar_ids=ids)
            assert result['result']['blocked_by']==[reason] and result['result']['scenario'] is None
            assert (await replay_calculation(db[0],actor=ADMIN,contact_id=1,calculation_id=result['calculation_id']))['replay_verified']
    asyncio.run(scenario())


@pytest.mark.parametrize('table',['stay_intervals','work_calendar_days','entry_calculation_intervals','entry_calculation_calendars'])
def test_failure_after_parent_flush_rolls_back_entire_operation(db,table):
    async def scenario():
        saved=await save_history(db) if table=='entry_calculation_intervals' else None
        selected=await import_work_calendars(db[0],actor=ADMIN,document=calendars()) if table=='entry_calculation_calendars' else []
        before=await counts(db[0]); fired=False
        def fail(conn,cursor,statement,params,context,many):
            nonlocal fired
            if statement.startswith('INSERT INTO '+table):
                fired=True;raise RuntimeError('PRIVATE-PAYLOAD')
        event.listen(db[0].sync_engine,'before_cursor_execute',fail)
        try:
            with pytest.raises(EntryStorageUnavailable) as error:
                if table=='stay_intervals': await save_history(db)
                elif table=='work_calendar_days': await import_work_calendars(db[0],actor=ADMIN,document=calendars())
                elif table=='entry_calculation_intervals': await save_stay(db,saved['history_id'])
                else:
                    await save_calculation(db[0],actor=ADMIN,contact_id=1,kind='deadline',knowledge_version_id=db[1],
                        request_key='x',request=load_document(FIX/'synthetic_deadline_review.json'),calendar_ids=[r['calendar_id'] for r in selected])
            assert 'PRIVATE' not in str(error.value)
        finally:event.remove(db[0].sync_engine,'before_cursor_execute',fail)
        assert fired and await counts(db[0])==before
    asyncio.run(scenario())


def test_concurrent_same_request_is_idempotent_and_different_revision_conflicts(db):
    async def scenario():
        a,b=await asyncio.gather(save_history(db),save_history(db))
        assert a['history_id']==b['history_id'] and a['reused']!=b['reused']
        results=await asyncio.gather(save_history(db,key='next-a',revision=1),save_history(db,key='next-b',revision=1),return_exceptions=True)
        assert sum(isinstance(v,dict) for v in results)==1
        assert sum(isinstance(v,EntryStorageConflict) for v in results)==1
        a,b=await asyncio.gather(save_stay(db,a['history_id']),save_stay(db,a['history_id']))
        assert a['calculation_id']==b['calculation_id'] and a['reused']!=b['reused']
    asyncio.run(scenario())


def test_runtime_change_blocks_replay_but_not_reading_saved_result(db,monkeypatch):
    async def scenario():
        saved=await save_history(db); calc=await save_stay(db,saved['history_id'])
        monkeypatch.setattr('app.domain.entry_calculations._runtime',lambda kind:{'algorithm':'changed'})
        with pytest.raises(EntryStorageInvalid,match='replay_runtime_changed'):
            await replay_calculation(db[0],actor=ADMIN,contact_id=1,calculation_id=calc['calculation_id'])
        assert (await read_calculation(db[0],actor=ADMIN,contact_id=1,calculation_id=calc['calculation_id']))['result']==calc['result']
    asyncio.run(scenario())


@pytest.mark.parametrize('fault',['history','interval','confirmation_time','history_time','calculation_time','calendar','calendar_day','result','input','provenance','interval_link','calendar_link','knowledge'])
def test_privileged_sql_corruption_is_detected_not_returned(db,fault):
    async def scenario():
        saved=await save_history(db)
        cs=await import_work_calendars(db[0],actor=ADMIN,document=calendars())
        use_deadline=fault in ('calendar','calendar_day','calendar_link')
        if use_deadline:
            calc=await save_calculation(db[0],actor=ADMIN,contact_id=1,kind='deadline',knowledge_version_id=db[1],request_key='x',
                request=load_document(FIX/'synthetic_deadline_review.json'),calendar_ids=[r['calendar_id'] for r in cs])
        else: calc=await save_stay(db,saved['history_id'])
        stmts={
            'history':"UPDATE stay_histories SET history_complete=false",
            'interval':"UPDATE stay_intervals SET exit_date='2026-09-25'",
            'confirmation_time':"UPDATE stay_intervals SET confirmed_at='2026-01-01 00:00:00'",
            'history_time':"UPDATE stay_histories SET created_at='2026-01-01 00:00:00'",
            'calculation_time':"UPDATE entry_calculations SET created_at='2026-01-01 00:00:00'",
            'calendar':"UPDATE work_calendars SET version=9",
            'calendar_day':"UPDATE work_calendar_days SET title='PRIVATE-PAYLOAD'",
            'result':"UPDATE entry_calculations SET result_snapshot='{}'",
            'input':"UPDATE entry_calculations SET input_snapshot='{}'",
            'provenance':"UPDATE entry_calculations SET provenance='{}'",
            'interval_link':"DELETE FROM entry_calculation_intervals",
            'calendar_link':"DELETE FROM entry_calculation_calendars",
            'knowledge':"UPDATE knowledge_versions SET bundle_hash=:bad",
        }
        async with db[0].begin() as conn: await conn.execute(text(stmts[fault]),{'bad':'0'*64})
        with pytest.raises(DomainError) as error:
            await replay_calculation(db[0],actor=ADMIN,contact_id=1,calculation_id=calc['calculation_id'])
        assert 'PRIVATE' not in str(error.value)
    asyncio.run(scenario())


@pytest.mark.parametrize('operation', ['history', 'calculation', 'calendar'])
def test_lost_commit_acknowledgement_reconciles_without_duplicate(db, operation):
    from sqlalchemy.orm import Session
    async def scenario():
        history_id = (await save_history(db))['history_id'] if operation == 'calculation' else None
        async def write():
            if operation == 'history': return await save_history(db)
            if operation == 'calculation': return await save_stay(db, history_id)
            return await import_work_calendars(db[0], actor=ADMIN, document=calendars())
        def lost_ack(session):
            raise RuntimeError('PRIVATE-lost-commit-acknowledgement')
        checked_out = set()
        def checkout(connection, record, proxy):
            checked_out.add(id(record))
        def checkin(connection, record):
            checked_out.discard(id(record))
        event.listen(db[0].sync_engine, 'checkout', checkout)
        event.listen(db[0].sync_engine, 'checkin', checkin)
        event.listen(Session, 'after_commit', lost_ack)
        try:
            with pytest.raises(EntryStorageUnavailable, match='commit_outcome_unknown_retry_same_request'):
                await write()
        finally:
            event.remove(Session, 'after_commit', lost_ack)
            event.remove(db[0].sync_engine, 'checkout', checkout)
            event.remove(db[0].sync_engine, 'checkin', checkin)
        assert not checked_out
        committed = await counts(db[0])
        again = await write()
        assert all(r['reused'] for r in (again if isinstance(again, list) else [again]))
        assert await counts(db[0]) == committed
    asyncio.run(scenario())


def test_calendar_collection_conflict_rolls_back_earlier_new_version(db):
    async def scenario():
        await import_work_calendars(db[0], actor=ADMIN, document=calendars())
        before = await counts(db[0])
        doc = calendars()
        doc['calendars'][0]['version'] = 2
        doc['calendars'][1]['source_ref'] = 'Synthetic conflict'
        with pytest.raises(EntryStorageConflict):
            await import_work_calendars(db[0], actor=ADMIN, document=doc)
        assert await counts(db[0]) == before
    asyncio.run(scenario())


def test_scoped_foreign_keys_enforce_contact_and_revision_without_service(db):
    from sqlalchemy.exc import IntegrityError
    async def scenario():
        first = await save_history(db)
        calc = await save_stay(db, first['history_id'])
        newer = await save_history(db, key='revision-2', revision=1)
        other = await save_history(db, contact=2)
        async with async_sessionmaker(db[0])() as s:
            new_interval = await s.scalar(select(StayInterval.id).where(StayInterval.history_id == newer['history_id']))
        statements = [
            ("UPDATE entry_calculations SET contact_id=2 WHERE id=:calc", {}),
            ("UPDATE stay_intervals SET contact_id=2 WHERE history_id=:first", {}),
            ("UPDATE stay_histories SET previous_id=:other WHERE id=:new", {}),
            ("INSERT INTO entry_calculation_intervals VALUES (:calc,:interval,:first)", {}),
        ]
        params = {'calc': calc['calculation_id'], 'first': first['history_id'], 'new': newer['history_id'],
                  'other': other['history_id'], 'interval': new_interval}
        for sql, _ in statements:
            with pytest.raises(IntegrityError):
                async with db[0].begin() as conn:
                    await conn.execute(text(sql), params)
        assert (await replay_calculation(db[0], actor=ADMIN, contact_id=1, calculation_id=calc['calculation_id']))['replay_verified']
    asyncio.run(scenario())


def test_replay_detects_result_drift_even_when_runtime_identity_unchanged(db, monkeypatch):
    import app.domain.entry_calculations as module
    async def scenario():
        saved = await save_history(db)
        calc = await save_stay(db, saved['history_id'])
        evaluate = module._evaluate
        def changed(*args):
            inputs, result = evaluate(*args)
            result['scenario']['max_presence_days'] += 1
            return inputs, result
        monkeypatch.setattr(module, '_evaluate', changed)
        with pytest.raises(EntryStorageInvalid, match='replay_result_changed'):
            await replay_calculation(db[0], actor=ADMIN, contact_id=1, calculation_id=calc['calculation_id'])
    asyncio.run(scenario())


def test_calendar_export_is_sorted_owned_copy():
    from app.knowledge.work_calendar import WorkCalendars
    document = calendars()
    document['calendars'].reverse()
    book = WorkCalendars(document)
    exported = book.export()
    assert [r['year'] for r in exported['calendars']] == [2026, 2027]
    exported['calendars'][0]['days'].clear()
    assert book.day(date(2026, 10, 13))['is_working'] is False
    assert WorkCalendars(book.export()).content_hash == book.content_hash


def test_orm_nested_mutations_and_bulk_rewrites_are_refused(db):
    async def scenario():
        saved=await save_history(db); calc=await save_stay(db,saved['history_id'])
        await import_work_calendars(db[0],actor=ADMIN,document=calendars())
        for model,field in [(StayHistory,'created_by'),(StayInterval,'basis'),(WorkCalendar,'status'),
                            (WorkCalendarDay,'title'),(EntryCalculation,'created_by')]:
            async with async_sessionmaker(db[0])() as s:
                row=await s.scalar(select(model).limit(1));setattr(row,field,'rewritten')
                with pytest.raises(DomainError,match='immutable'): await s.flush()
        async with async_sessionmaker(db[0])() as s:
            row=await s.get(EntryCalculation,calc['calculation_id'])
            with pytest.raises(DomainError): row.input_snapshot['history'].clear()
        for model in ENTRY_STORAGE_MODELS:
            async with async_sessionmaker(db[0])() as s:
                with pytest.raises(DomainError,match='bulk'): await s.execute(delete(model))
    asyncio.run(scenario())
