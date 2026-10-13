import asyncio
from copy import deepcopy
from datetime import date,timedelta
import json
from pathlib import Path

from tests.test_conditional_deadlines import env,clock,enforce_sqlite_foreign_keys
from tests import test_conditional_deadlines as core
from app.domain import conditional_deadlines as service,entry_deadlines as legacy
from app.domain.conditional_deadline_policy import from_document
from app.domain.entry_storage import _hash
from app.domain.models import EntryDeadlineRevision
from app.knowledge.review import canonical
from app.knowledge.work_calendar import WorkCalendars


def test_exact_event_byte_boundary_keeps_terminal_clear_available(env,tmp_path):
    prepared=core.setup(env,tmp_path)
    rule='KG.DL.REGISTRATION_EXTENSION'
    original=core.authority(env,rule).document
    calendar=original['calendars']['calendars'][0]
    calendar['days']=[dict(date=(date(2026,1,1)+timedelta(days=i)).isoformat(),is_working=True,
        kind='weekend_override',title='A',source_ref='A') for i in range(128)]
    original['calendars']['calendars']=[calendar]
    original['policy']['calendar_hash']=WorkCalendars(original['calendars']).content_hash
    options=core.arguments(env,prepared,rule,from_document(original))
    preview=core.preview(env,options)
    assert preview['report']['review_due_on']=='2026-11-01'
    request=options|dict(expected_revision=0,request_key='C',operation=dict(action='conditional_review',
        confirmed=True,evidence_hash=preview['report']['evidence_hash']))
    def payload(authority):
        command=legacy._command(request['case_id'],request['application_id'],rule,0,request['operation'],request['actor'].manager_id)
        row=EntryDeadlineRevision(case_id=request['case_id'],application_id=request['application_id'],rule_unit_id=rule,
            knowledge_version_id=preview['report']['source']['version_id'],anchor_event_id=None,anchor_issued_id=None,
            revision=1,previous_id=None,request_key='C',request_hash=_hash(command),command=command,
            snapshot=dict(format=service.rules.FORMAT,authority=authority.document,report=preview['report'],cleared=False,previous_hash=None),
            created_by=request['actor'].manager_id,created_at=service._now())
        return legacy._payload(row)
    base_size=len(canonical(payload(request['authority'])).encode())
    remaining=service.MAX_EVENT_BYTES-base_size
    assert 0<remaining<=128*1999
    for row in calendar['days']:
        extra=min(remaining,1999);row['title']+='x'*extra;remaining-=extra
    assert remaining==0
    original['policy']['calendar_hash']=WorkCalendars(original['calendars']).content_hash
    request['authority']=from_document(original)
    expected_bytes=len(canonical(payload(request['authority'])).encode())
    assert expected_bytes==262144==service.MAX_EVENT_BYTES
    saved=asyncio.run(service.record(env['engine'],**request))
    async def actual_size():
        async with env['sm']() as session:
            row=await session.get(EntryDeadlineRevision,saved['id'])
            return len(canonical(legacy._payload(row)).encode())
    assert asyncio.run(actual_size())==expected_bytes
    details=dict(ordinary_bytes=expected_bytes,max_event=service.MAX_EVENT_BYTES,actual_normal_public_write=True)
    Path('runs/audit-event-reserve.json').write_text(json.dumps(details,indent=2)+'\n','utf8')
    clear=request|dict(authority=None,expected_revision=1,request_key='CLEAR',
        operation=dict(action='conditional_clear',confirmed=True,evidence_hash=saved['snapshot_hash']))
    cleared=asyncio.run(service.record(env['engine'],**clear))
    assert cleared['summary']['review_due_on'] is None
    assert asyncio.run(service.record(env['engine'],**(request|dict(authority=None))))==saved
    assert asyncio.run(service.record(env['engine'],**clear))==cleared
