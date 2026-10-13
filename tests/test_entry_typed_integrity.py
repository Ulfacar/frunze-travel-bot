"""Actual rehashed SQL substitutions must not pass typed semantic journal checks.

This is a consistency rehearsal, not proof against complete database forgery.
Original failures are retained in a frozen pre-fix tree before any runtime edit.
"""
import asyncio
import json
from copy import deepcopy
from datetime import date

import pytest
from sqlalchemy import select,text

from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid,_hash,import_work_calendars
from app.domain.models import (EntryDocumentRevision,EntryIssuedRevision,
    EntryProcessEvent,EntryInterviewEvent,EntryPortalAction,EntryDeadlineRevision,EntryQualification,EntryApplicationEvent)
from tests.test_admin_kg_entry import ADMIN,env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_interviews import admins
from tests import test_entry_documents as documents
from tests import test_entry_issued as issued
from tests import test_entry_processes as processes
from tests import test_entry_interviews as interviews
from tests import test_entry_portal as portal
from tests import test_entry_deadlines as deadlines
from tests import test_applicant_profiles as profiles
from app.domain import qualification_storage as qualification
from tests.test_entry_storage import calendars


CANDIDATES=('documents','documents_command','issued','issued_command','process','process_evidence',
            'interview','interview_command','portal','portal_command','deadline','deadline_anchor',
            'deadline_manual','deadline_replay','qualification','qualification_previous')


def prepare(env,kind):
    if kind.startswith('documents'):
        app=documents.setup(env)
        return documents.service,EntryDocumentRevision,'_payload',lambda:documents.read(env,app),(
            ('command','case_id') if kind.endswith('command') else ('snapshot','passport_revision'))
    if kind.startswith('issued'):
        app=issued.setup(env);issued.file(env,app)
        return issued.service,EntryIssuedRevision,'_payload',lambda:issued.read(env,app),(
            ('command','case_id') if kind.endswith('command') else ('snapshot','version'))
    if kind.startswith('process'):
        app=processes.setup(env)
        return processes.service,EntryProcessEvent,'_payload',lambda:processes.read(env,app),(
            ('evidence','facts','visa.identity','value') if kind=='process_evidence' else ('snapshot','stopped'))
    if kind.startswith('interview'):
        interview=interviews.start(env)
        return interviews.service,EntryInterviewEvent,'_event_payload',lambda:interviews.read(env,interview),(
            ('command','case_id') if kind=='interview_command' else ('snapshot','collection_blocked'))
    if kind.startswith('portal'):
        portal.setup(env);receipt=portal.receive(env);portal.action(env,receipt,'correlate')
        return portal.service,EntryPortalAction,'_action_payload',lambda:portal.read(env,receipt),(
            ('command','case_id') if kind.endswith('command') else ('snapshot','binding','application_id'))
    if kind=='deadline':
        app=deadlines.setup(env);deadlines.write(env,app,'recalculate',deadlines.selection(env))
        return deadlines.service,EntryDeadlineRevision,'_payload',lambda:deadlines.read(env,app),('snapshot','source','knowledge','version_id')
    if kind.startswith('deadline_'):
        app=deadlines.setup(env)
        travel=issued.write(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,
            source='stamp',passport_fingerprint='b'*64))
        imported=asyncio.run(import_work_calendars(env['engine'],actor=ADMIN,document=calendars()))
        selected=deadlines.selection(env,dict(kind='travel',id=travel['id']),[r['calendar_id'] for r in imported])
        deadlines.write(env,app,'recalculate',selected)
        if kind=='deadline_manual':deadlines.write(env,app,'manual',deadlines.manual())
        return deadlines.service,EntryDeadlineRevision,'_payload',lambda:deadlines.read(env,app,replay=kind=='deadline_replay'),(
            ('snapshot','anchor','id') if kind=='deadline_anchor' else ('snapshot','review','may_quote'))
    args=dict(actor=ADMIN,contact_id=env['contacts']['visa'],knowledge_version_id=env['version'],
              expected_revision=0,request_key='typed-check',request=profiles.request())
    asyncio.run(qualification.save_qualification(env['engine'],**args))
    if kind=='qualification_previous':
        asyncio.run(qualification.save_qualification(env['engine'],**(args|{'expected_revision':1,'request_key':'typed-second'})))
    def read():return asyncio.run(qualification.read_qualification(env['engine'],actor=ADMIN,contact_id=env['contacts']['visa']))
    return qualification,EntryQualification,'_payload',read,(
        ('provenance','previous','id') if kind=='qualification_previous' else ('provenance','context','knowledge_version_id'))


@pytest.mark.parametrize('kind',CANDIDATES)
@pytest.mark.parametrize('substitution',['coercible_bool_number','coercible_float'])
def test_rehashed_json_coercion_is_rejected(env,kind,substitution):
    service,model,payload_name,read,path=prepare(env,kind)
    read()
    async def corrupt():
        async with env['sm']() as session:
            row=await session.scalar(select(model).order_by(model.id.desc()).limit(1))
            payload=getattr(service,payload_name)(row);row_id=row.id
        target=payload
        for part in path[:-1]:target=target[part]
        original=target[path[-1]]
        assert type(original) in (bool,int) and original in (0,1)
        changed=(int(original) if type(original) is bool else bool(original)) if substitution=='coercible_bool_number' else float(original)
        assert changed==original and type(changed) is not type(original)
        target[path[-1]]=changed
        values=dict(value=json.dumps(payload[path[0]]),digest=_hash(payload),id=row_id)
        update_request=''
        if path[0]=='command':
            # Keep both checksums internally consistent; the typed semantic
            # comparison must still reject a command that names True as case1.
            values['request']=_hash(payload['command']);payload['request_hash']=values['request']
            values['digest']=_hash(payload);update_request=',request_hash=:request'
        async with env['engine'].begin() as conn:
            await conn.execute(text(f'UPDATE {model.__tablename__} SET {path[0]}=:value,snapshot_hash=:digest{update_request} WHERE id=:id'),values)
    asyncio.run(corrupt())
    with pytest.raises(EntryStorageInvalid):read()


def test_writer_accepted_integral_float_keeps_qualification_receipt_and_retry(env,monkeypatch):
    request=profiles.request()
    request['condition_facts']={'schema_version':'kg-entry-condition-facts/1',
                              'tour_group':{'participants_count':3.0}}
    args=dict(actor=ADMIN,contact_id=env['contacts']['visa'],knowledge_version_id=env['version'],
              expected_revision=0,request_key='float-control',request=request)
    saved=asyncio.run(qualification.save_qualification(env['engine'],**args))
    assert type(saved['input']['condition_facts']['tour_group']['participants_count']) is float
    monkeypatch.setattr(qualification,'_runtime',lambda:{'algorithm':'later-runtime'})
    assert asyncio.run(qualification.read_qualification(env['engine'],actor=ADMIN,
        contact_id=env['contacts']['visa']))==saved
    assert asyncio.run(qualification.save_qualification(env['engine'],**args))=={**saved,'reused':True}
    with pytest.raises(EntryStorageInvalid,match='runtime_changed'):
        asyncio.run(qualification.replay_qualification(env['engine'],actor=ADMIN,
            contact_id=env['contacts']['visa'],qualification_id=saved['qualification_id']))


@pytest.mark.parametrize('column',['knowledge_version_id','anchor_event_id','anchor_issued_id'])
def test_writer_accepted_integral_float_keeps_deadline_receipt_and_retry(env,monkeypatch,column):
    app=deadlines.setup(env);selection=deadlines.selection(env)
    if column=='knowledge_version_id':selection['knowledge_version_id']=float(selection['knowledge_version_id'])
    elif column=='anchor_issued_id':
        travel=deadlines.issued(env,app,'travel',dict(direction='entry',on='2026-09-07',proof='f'*64,
            source='stamp',passport_fingerprint='b'*64))
        selection['anchor']=dict(kind='travel',id=float(travel['id']))
    else:
        async def current_event():
            async with env['sm']() as session:
                return await session.scalar(select(EntryApplicationEvent.id).where(
                    EntryApplicationEvent.application_id==app['id'],EntryApplicationEvent.status=='approved'))
        selection['anchor']=dict(kind='application_event',id=float(asyncio.run(current_event())))
    saved=deadlines.write(env,app,'recalculate',selection,revision=0,key='float-control')
    original=saved['snapshot']['selection']
    assert type(original['knowledge_version_id'] if column=='knowledge_version_id' else original['anchor']['id']) is float
    assert deadlines.read(env,app,replay=True)['selected']==saved
    changed=deepcopy(selection)
    if column=='knowledge_version_id':changed['knowledge_version_id']=int(changed['knowledge_version_id'])
    else:changed['anchor']['id']=int(changed['anchor']['id'])
    with pytest.raises(EntryStorageConflict):
        deadlines.write(env,app,'recalculate',changed,revision=0,key='float-control')
    monkeypatch.setattr(deadlines.service,'_runtime',lambda:{'binding':'later-runtime'})
    assert deadlines.read(env,app)['selected']==saved
    assert deadlines.write(env,app,'recalculate',selection,revision=0,key='float-control')==saved
    with pytest.raises(EntryStorageInvalid,match='runtime_changed'):deadlines.read(env,app,replay=True)
    successor=deadlines.write(env,app,'manual',deadlines.manual())
    assert successor['revision']==2 and deadlines.read(env,app)['selected']==successor
    assert deadlines.write(env,app,'recalculate',selection,revision=0,key='float-control')==saved


@pytest.mark.parametrize('value',[True,1.5])
@pytest.mark.parametrize('column',['knowledge_version_id','anchor_event_id','anchor_issued_id'])
def test_invalid_boolean_or_fractional_identifier_is_not_coerced(column,value):
    from app.domain import entry_deadline_sources as sources
    selection=dict(knowledge_version_id=1,calendar_ids=[],anchor=None,
        policy=dict(status='proposed',timezone='Asia/Bishkek',count_anchor_day=False,month_end=None,hours_mode=None))
    if column=='knowledge_version_id':selection['knowledge_version_id']=value
    else:selection['anchor']=dict(kind='travel' if column=='anchor_issued_id' else 'application_event',id=value)
    with pytest.raises(EntryStorageInvalid):
        sources.normalize(dict(action='recalculate',data=selection,confirmed=True),cutoff=date(2026,10,11))
