"""Immutable application-scoped draft journal. No outgoing-send dependency."""
from copy import deepcopy

from sqlalchemy import Text,cast,func,select

from app.domain import entry_applications as applications
from app.domain.entry_notification_policy import NotificationPolicy,access,authorize,existing_full_admins,policy_from_document,validation
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,_hash,_id,_key,_plain
from app.domain.models import EntryNotificationDraft,_now
from app.domain.service_authz import PermissionDenied
from app.knowledge import notification_rules as rules
from app.knowledge.review import canonical

MAX_REVISIONS=128
MAX_EVENT_BYTES=131072
MAX_HISTORY_BYTES=4*1048576
# SQL JSON text includes escapes/separators. Canonical UTF-8 limits below stay
# distinct from this conservative bound on materialized database representation.
SQL_JSON_EXPANSION_BOUND=6
JSON_FIELDS=('command','policy','source_pin','result','authority')


def fail(code='notification_integrity_failed'):raise EntryStorageInvalid(code)


async def _run(engine,operation):
    async def guarded(session):
        try:return await operation(session)
        except rules.NotificationInvalid as exc:raise EntryStorageInvalid(str(exc)) from None
    return await applications._run(engine,guarded)


def _revision(value):
    if type(value) is not int or not 0<=value<=MAX_REVISIONS:fail('invalid_notification_revision')


def _request(value):
    try:return rules.request(value)
    except rules.NotificationInvalid as exc:raise EntryStorageInvalid(str(exc)) from None


async def _scope(session,case_id,application_id,*,lock=False):
    await applications._case(session,case_id,lock=lock)
    application=await applications._application(session,case_id,application_id,lock=lock)
    person=await applications._applicant(session,case_id,application.applicant_id)
    events=await applications._events(session,application)
    return application,person,events


def _pin(application,person,event):
    return dict(case_id=application.case_id,application_id=application.id,applicant_id=person.id,
        procedure=application.procedure,attempt=application.attempt,application_hash=application.snapshot_hash,
        applicant_hash=person.snapshot_hash,event_id=event.id,event_revision=event.revision,
        event_hash=event.snapshot_hash,event_status=event.status)


def _preview_data(application,person,event,*,revision,policy,parameters,on,version):
    document=policy.document()
    if parameters['template_id'] not in document['templates']:fail('notification_template_not_allowed')
    if version!=document['renderer_version']:fail('notification_renderer_changed')
    result=rules.render(parameters,version=version)
    if result['catalog_sha256']!=document['catalog_sha256']:fail('notification_catalog_changed')
    return dict(case_id=application.case_id,application_id=application.id,expected_revision=revision,
        source_pin=_pin(application,person,event),policy_hash=policy.digest,parameters=deepcopy(parameters),
        renderer_version=version,on=on,result=result)


def _command(case_id,application_id,revision,actor,parameters,policy_hash,preview_hash,version):
    return dict(case_id=case_id,application_id=application_id,expected_revision=revision,actor=actor,
        parameters=deepcopy(parameters),policy_hash=policy_hash,preview_hash=preview_hash,renderer_version=version)


def _payload(row):
    return dict(case_id=row.case_id,application_id=row.application_id,applicant_id=row.applicant_id,procedure=row.procedure,
        revision=row.revision,previous_id=row.previous_id,request_key=row.request_key,request_hash=row.request_hash,
        command=_plain(row.command),policy=_plain(row.policy),source_pin=_plain(row.source_pin),result=_plain(row.result),
        authority=_plain(row.authority),created_by=row.created_by,created_at=applications._utc(row.created_at))


def _receipt(row):
    return dict(id=row.id,case_id=row.case_id,application_id=row.application_id,applicant_id=row.applicant_id,
        revision=row.revision,request_key=row.request_key,snapshot_hash=row.snapshot_hash,
        created_by=row.created_by,created_at=applications._utc(row.created_at),command=_plain(row.command),
        source_pin=_plain(row.source_pin),result=_plain(row.result))


def _capacity(count,event_size,total):
    if count>MAX_REVISIONS or event_size>MAX_EVENT_BYTES or total>MAX_HISTORY_BYTES:fail('notification_history_limit')


async def _history(session,application,person,events):
    model=EntryNotificationDraft
    size=sum(func.length(cast(getattr(model,k),Text)) for k in JSON_FIELDS)
    count,total_sql,largest= (await session.execute(select(func.count(model.id),func.coalesce(func.sum(size),0),
        func.coalesce(func.max(size),0)).where(model.application_id==application.id))).one()
    _capacity(count,0,0)
    if (largest>MAX_EVENT_BYTES*SQL_JSON_EXPANSION_BOUND or
        total_sql>MAX_HISTORY_BYTES*SQL_JSON_EXPANSION_BOUND):fail('notification_history_limit')
    rows=list((await session.scalars(select(model).where(model.application_id==application.id)
        .order_by(model.revision).limit(MAX_REVISIONS+1))).all())
    by_id={e.id:e for e in events};previous=None;total=0
    for revision,row in enumerate(rows,1):
        command=_plain(row.command);pin=_plain(row.source_pin);authority=_plain(row.authority)
        validation.exact(command,('case_id','application_id','expected_revision','actor','parameters','policy_hash','preview_hash','renderer_version'))
        _revision(command['expected_revision']);_id(command['case_id']);_id(command['application_id'])
        validation.exact(authority,('full_admins',));operators=authority['full_admins']
        if type(operators) is not list or not operators or len(operators)>128 or any(type(x) is not str for x in operators) or operators!=sorted(set(operators)):fail()
        policy=policy_from_document(_plain(row.policy));parameters=_request(command['parameters']);_key(row.request_key)
        if (row.case_id!=application.case_id or row.applicant_id!=person.id or row.procedure!=application.procedure
            or row.revision!=revision or row.previous_id!=(previous.id if previous else None)
            or previous and row.id<=previous.id or row.created_by not in operators or row.created_by not in policy.operators):fail()
        if previous and applications._utc(row.created_at)<applications._utc(previous.created_at):fail('notification_clock_moved_backwards')
        day=applications._local_day(row.created_at);document=policy.document()
        if not validation.day(document['valid_from'])<=day<=validation.day(document['review_due_on']):fail()
        if type(pin) is not dict or type(pin.get('event_id')) is not int:fail()
        event=by_id.get(pin['event_id'])
        if event is None or canonical(pin)!=canonical(_pin(application,person,event)):fail()
        if previous and event.revision<previous.source_pin['event_revision']:fail()
        if applications._utc(event.created_at)>applications._utc(row.created_at):fail()
        expected=_preview_data(application,person,event,revision=revision-1,policy=policy,parameters=parameters,
            on=day.isoformat(),version=command['renderer_version'])
        expected_command=_command(application.case_id,application.id,revision-1,row.created_by,parameters,policy.digest,
            _hash(expected),command['renderer_version'])
        if (canonical(command)!=canonical(expected_command) or canonical(_plain(row.result))!=canonical(expected['result'])
            or row.request_hash!=_hash(command) or row.snapshot_hash!=_hash(_payload(row))):fail()
        event_size=len(canonical(_payload(row)).encode());total+=event_size
        _capacity(revision,event_size,total);previous=row
    if len(rows)!=count:fail()
    return rows,total


def _overlay(row,application,person,events,actor,policy):
    reasons=[];today=applications._today()
    if canonical(_plain(row.source_pin))!=canonical(_pin(application,person,events[-1])):reasons.append('notification_application_changed')
    if row.command['renderer_version']!=rules.VERSION:reasons.append('notification_renderer_changed')
    try:
        authorize(actor,policy,on=today)
        if policy.digest!=row.command['policy_hash']:reasons.append('notification_policy_changed')
        if rules.catalog().document()!=rules.catalog(row.command['renderer_version']).document():reasons.append('notification_catalog_changed')
    except (EntryStorageInvalid,PermissionDenied,rules.NotificationInvalid):reasons.append('notification_policy_or_source_unavailable')
    return dict(context_current=not reasons,reasons=sorted(set(reasons)),on=today.isoformat(),
        meaning='internal_draft_only',send_allowed=False,publication_approved=False)


async def preview_draft(engine,*,actor,case_id,application_id,parameters,policy):
    access(actor);_id(case_id);_id(application_id);parameters=_request(parameters)
    authorize(actor,policy,on=applications._today())
    async def read(session):
        application,person,events=await _scope(session,case_id,application_id)
        rows,_=await _history(session,application,person,events)
        at=_now();authorize(actor,policy,on=applications._local_day(at))
        value=_preview_data(application,person,events[-1],revision=len(rows),policy=policy,parameters=parameters,
            on=applications._local_day(at).isoformat(),version=rules.VERSION)
        return dict(preview=value,preview_hash=_hash(value))
    return await _run(engine,read)


async def save_draft(engine,*,actor,case_id,application_id,parameters,expected_revision,request_key,
                     expected_policy_hash,expected_preview_hash,renderer_version,policy=None):
    access(actor);_id(case_id);_id(application_id);_revision(expected_revision);_key(request_key);parameters=_request(parameters)
    try:validation.proof(expected_policy_hash);validation.proof(expected_preview_hash)
    except ValueError:fail('invalid_notification_proof')
    if type(renderer_version) is not str or len(renderer_version)>64:fail('notification_renderer_unavailable')
    command=_command(case_id,application_id,expected_revision,actor.manager_id,parameters,expected_policy_hash,
        expected_preview_hash,renderer_version)
    async def write(session):
        application,person,events=await _scope(session,case_id,application_id,lock=True)
        rows,total=await _history(session,application,person,events)
        old=next((r for r in rows if r.request_key==request_key),None)
        if old:
            if old.request_hash!=_hash(command):raise EntryStorageConflict('notification_request_conflict')
            return dict(receipt=_receipt(old),current=_overlay(old,application,person,events,actor,policy))
        if len(rows)!=expected_revision:raise EntryStorageConflict('notification_revision_changed')
        at=_now();authorize(actor,policy,on=applications._local_day(at))
        if policy.digest!=expected_policy_hash:raise EntryStorageConflict('notification_policy_changed')
        if renderer_version!=rules.VERSION:fail('notification_renderer_changed')
        if rows and applications._utc(at)<applications._utc(rows[-1].created_at):fail('notification_clock_moved_backwards')
        if applications._utc(at)<applications._utc(events[-1].created_at):fail('notification_clock_moved_backwards')
        preview=_preview_data(application,person,events[-1],revision=len(rows),policy=policy,parameters=parameters,
            on=applications._local_day(at).isoformat(),version=renderer_version)
        if _hash(preview)!=expected_preview_hash:raise EntryStorageConflict('notification_preview_changed')
        row=EntryNotificationDraft(case_id=case_id,application_id=application_id,applicant_id=person.id,procedure=application.procedure,
            revision=len(rows)+1,previous_id=rows[-1].id if rows else None,request_key=request_key,request_hash=_hash(command),command=command,
            policy=policy.document(),source_pin=preview['source_pin'],result=preview['result'],authority={'full_admins':sorted(existing_full_admins())},
            created_by=actor.manager_id,created_at=at)
        row.snapshot_hash=_hash(_payload(row));size=len(canonical(_payload(row)).encode());_capacity(row.revision,size,total+size)
        session.add(row);await session.flush()
        return dict(receipt=_receipt(row),current=_overlay(row,application,person,events,actor,policy))
    return await _run(engine,write)


async def read_drafts(engine,*,actor,case_id,application_id,policy=None):
    access(actor);_id(case_id);_id(application_id)
    async def read(session):
        application,person,events=await _scope(session,case_id,application_id)
        rows,total=await _history(session,application,person,events)
        enabled=False;templates=[]
        try:
            authorize(actor,policy,on=applications._today());document=policy.document()
            if document['renderer_version']!=rules.VERSION:fail('notification_renderer_changed')
            catalog=rules.catalog();engine=rules.renderer(rules.VERSION)
            if document['catalog_sha256']!=engine.CATALOG_SHA256:fail('notification_catalog_changed')
            templates=[t for t in catalog.document()['templates'] if t['unit_id'] in document['templates']]
            enabled=bool(templates) and len(rows)<MAX_REVISIONS and total<MAX_HISTORY_BYTES
        except (EntryStorageInvalid,PermissionDenied,rules.NotificationInvalid):pass
        return dict(application=applications._application_view(application),applicant_id=person.id,revision=len(rows),
            can_save=enabled,templates=templates,policy_hash=policy.digest if isinstance(policy,NotificationPolicy) else None,
            history=[dict(receipt=_receipt(row),current=_overlay(row,application,person,events,actor,policy)) for row in reversed(rows)])
    return await _run(engine,read)
