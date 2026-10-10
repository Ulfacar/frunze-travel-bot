"""Versioned internal quotation receipts, separate from contracts and payments."""
from copy import deepcopy

from sqlalchemy import select

from app.domain import entry_applications as applications
from app.domain.entry_quote_policy import QuotePolicy,access,authorize,existing_full_admins,policy_from_document
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,_hash,_id,_key,_plain
from app.domain.models import EntryApplication,EntryQuoteRevision,_now
from app.domain.service_authz import PermissionDenied
from app.knowledge import quote_rules as rules
from app.knowledge.review import canonical

MAX_REVISIONS=128
MAX_EVENT_BYTES=1048576
MAX_HISTORY_BYTES=8*1048576
TERMINAL={'approved','refused','closed'}


def fail(code='quote_integrity_failed'):raise EntryStorageInvalid(code)


async def _run(engine,operation):
    async def guarded(session):
        try:return await operation(session)
        except rules.QuoteInvalid as exc:raise EntryStorageInvalid(str(exc)) from None
    return await applications._run(engine,guarded)


def _revision(value):
    if type(value) is not int or not 0<=value<=MAX_REVISIONS:fail('invalid_quote_revision')


def _request(value):
    try:
        rules.exact(value,('recipe_id','additional_blocks','urgent'));rules.token(value['recipe_id'])
        if type(value['additional_blocks']) is not int or not 0<=value['additional_blocks']<=120:rules.fail('invalid_quote_blocks')
        if type(value['urgent']) is not bool:rules.fail('invalid_quote_urgent')
    except rules.QuoteInvalid as exc:raise EntryStorageInvalid(str(exc)) from None
    return deepcopy(value)


def _pin(application,person,event):
    return dict(case_id=application.case_id,application_id=application.id,applicant_id=person.id,
        procedure=application.procedure,attempt=application.attempt,application_hash=application.snapshot_hash,
        applicant_hash=person.snapshot_hash,event_id=event.id,event_revision=event.revision,
        event_hash=event.snapshot_hash,event_status=event.status)


async def _scope(session,case_id,application_id,*,lock=False):
    await applications._case(session,case_id,lock=lock)
    application=await applications._application(session,case_id,application_id,lock=lock)
    person=await applications._applicant(session,case_id,application.applicant_id)
    events=await applications._events(session,application)
    successor=await session.scalar(select(EntryApplication.id).where(EntryApplication.previous_id==application.id))
    return application,person,events,successor


def _live_scope(events,successor):
    if events[-1].status in TERMINAL or successor is not None:fail('quote_application_terminal')


def _preview_data(application,person,event,*,revision,policy,request,on,version=None):
    version=rules.VERSION if version is None else version
    recipe=policy.recipe(request['recipe_id'])
    if recipe['procedure']!=application.procedure:fail('quote_recipe_procedure_mismatch')
    result=rules.calculate(recipe,request,on=on,version=version)
    return dict(case_id=application.case_id,application_id=application.id,expected_revision=revision,
        source_pin=_pin(application,person,event),policy_hash=policy.digest,parameters=deepcopy(request),
        calculator_version=version,result=result)


def _command(case_id,application_id,revision,actor,request,policy_hash,preview_hash,version):
    return dict(case_id=case_id,application_id=application_id,expected_revision=revision,actor=actor,
        parameters=deepcopy(request),policy_hash=policy_hash,preview_hash=preview_hash,calculator_version=version)


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
    if count>MAX_REVISIONS or event_size>MAX_EVENT_BYTES or total>MAX_HISTORY_BYTES:fail('quote_history_limit')


async def _history(session,application,person,events):
    rows=list((await session.scalars(select(EntryQuoteRevision).where(EntryQuoteRevision.application_id==application.id)
        .order_by(EntryQuoteRevision.revision).limit(MAX_REVISIONS+1))).all())
    by_id={e.id:e for e in events};previous=None;total=0
    for revision,row in enumerate(rows,1):
        command=_plain(row.command);pin=_plain(row.source_pin);authority=_plain(row.authority)
        rules.exact(command,('case_id','application_id','expected_revision','actor','parameters','policy_hash','preview_hash','calculator_version'))
        _revision(command['expected_revision'])
        if type(command['calculator_version']) is not str:fail()
        rules.exact(authority,('full_admins',))
        operators=authority['full_admins']
        if type(operators) is not list or any(type(x) is not str for x in operators) or operators!=sorted(set(operators)):fail()
        policy=policy_from_document(_plain(row.policy));parameters=_request(command['parameters']);_key(row.request_key)
        if (row.case_id!=application.case_id or row.applicant_id!=person.id or row.procedure!=application.procedure
            or row.revision!=revision or row.previous_id!=(previous.id if previous else None)
            or previous and row.id<=previous.id or row.created_by not in operators or row.created_by not in policy.operators):fail()
        if previous and applications._utc(row.created_at)<applications._utc(previous.created_at):fail('quote_clock_moved_backwards')
        day=applications._local_day(row.created_at);document=policy.document()
        if not rules.day(document['valid_from'])<=day<=rules.day(document['review_due_on']):fail()
        if type(pin) is not dict or type(pin.get('event_id')) is not int:fail()
        event=by_id.get(pin['event_id'])
        if event is None or canonical(pin)!=canonical(_pin(application,person,event)) or event.status in TERMINAL:fail()
        if previous and event.revision<previous.source_pin['event_revision']:fail()
        if applications._utc(event.created_at)>applications._utc(row.created_at):fail()
        expected=_preview_data(application,person,event,revision=revision-1,policy=policy,request=parameters,
            on=day.isoformat(),version=command['calculator_version'])
        expected_command=_command(application.case_id,application.id,revision-1,row.created_by,parameters,policy.digest,
            _hash(expected),command['calculator_version'])
        if (canonical(command)!=canonical(expected_command) or canonical(_plain(row.result))!=canonical(expected['result'])
            or row.request_hash!=_hash(command) or row.snapshot_hash!=_hash(_payload(row))):fail()
        size=len(canonical(_payload(row)).encode());total+=size;_capacity(revision,size,total);previous=row
    return rows,total


def _overlay(row,latest,application,person,events,successor,actor,policy):
    reasons=[];today=applications._today()
    if row.id!=latest.id:reasons.append('quote_superseded')
    if row.command['calculator_version']!=rules.VERSION:reasons.append('quote_calculator_changed')
    if _plain(row.source_pin)!=_pin(application,person,events[-1]):reasons.append('quote_application_changed')
    if events[-1].status in TERMINAL or successor is not None:reasons.append('quote_application_terminal')
    if not row.result['complete']:reasons.append('quote_incomplete')
    try:
        authorize(actor,policy,on=today)
        if policy.digest!=row.command['policy_hash']:reasons.append('quote_policy_changed')
        recipe=policy.recipe(row.command['parameters']['recipe_id'])
        if not rules.day(recipe['valid_from'])<=today<=rules.day(recipe['review_due_on']):reasons.append('quote_recipe_expired_or_future')
    except (EntryStorageInvalid,PermissionDenied,rules.QuoteInvalid):reasons.append('quote_policy_unavailable')
    return dict(usable=not reasons,reasons=sorted(set(reasons)),on=today.isoformat(),
        meaning='internal_arithmetic_only',legal_eligibility='not_assessed',settlement_fx='not_available')


async def preview_quote(engine,*,actor,case_id,application_id,parameters,policy):
    access(actor);_id(case_id);_id(application_id);parameters=_request(parameters)
    authorize(actor,policy,on=applications._today())
    async def read(session):
        application,person,events,successor=await _scope(session,case_id,application_id)
        _live_scope(events,successor);rows,_=await _history(session,application,person,events)
        at=_now();authorize(actor,policy,on=applications._local_day(at))
        value=_preview_data(application,person,events[-1],revision=len(rows),policy=policy,request=parameters,
            on=applications._local_day(at).isoformat())
        return dict(preview=value,preview_hash=_hash(value))
    return await _run(engine,read)


async def save_quote(engine,*,actor,case_id,application_id,parameters,expected_revision,request_key,
                     expected_policy_hash,expected_preview_hash,calculator_version,policy=None):
    access(actor);_id(case_id);_id(application_id);_revision(expected_revision);_key(request_key);parameters=_request(parameters)
    try:rules.proof(expected_policy_hash);rules.proof(expected_preview_hash)
    except rules.QuoteInvalid as exc:raise EntryStorageInvalid(str(exc)) from None
    if type(calculator_version) is not str or len(calculator_version)>64:fail('unsupported_quote_calculator')
    command=_command(case_id,application_id,expected_revision,actor.manager_id,parameters,expected_policy_hash,
        expected_preview_hash,calculator_version)
    async def write(session):
        application,person,events,successor=await _scope(session,case_id,application_id,lock=True)
        rows,total=await _history(session,application,person,events)
        old=await session.scalar(select(EntryQuoteRevision).where(EntryQuoteRevision.case_id==case_id,EntryQuoteRevision.request_key==request_key))
        if old:
            if old.application_id!=application_id or old.request_hash!=_hash(command):raise EntryStorageConflict('quote_request_conflict')
            return dict(receipt=_receipt(old),current=_overlay(old,rows[-1],application,person,events,successor,actor,policy))
        _live_scope(events,successor)
        if len(rows)!=expected_revision:raise EntryStorageConflict('quote_revision_changed')
        at=_now();authorize(actor,policy,on=applications._local_day(at))
        if policy.digest!=expected_policy_hash:raise EntryStorageConflict('quote_policy_changed')
        if calculator_version!=rules.VERSION:fail('unsupported_quote_calculator')
        if rows and applications._utc(at)<applications._utc(rows[-1].created_at):fail('quote_clock_moved_backwards')
        if applications._utc(at)<applications._utc(events[-1].created_at):fail('quote_clock_moved_backwards')
        preview=_preview_data(application,person,events[-1],revision=len(rows),policy=policy,request=parameters,
            on=applications._local_day(at).isoformat(),version=calculator_version)
        if _hash(preview)!=expected_preview_hash:raise EntryStorageConflict('quote_preview_changed')
        row=EntryQuoteRevision(case_id=case_id,application_id=application_id,applicant_id=person.id,procedure=application.procedure,
            revision=len(rows)+1,previous_id=rows[-1].id if rows else None,request_key=request_key,request_hash=_hash(command),command=command,
            policy=policy.document(),source_pin=preview['source_pin'],result=preview['result'],authority={'full_admins':sorted(existing_full_admins())},
            created_by=actor.manager_id,created_at=at)
        row.snapshot_hash=_hash(_payload(row));size=len(canonical(_payload(row)).encode());_capacity(row.revision,size,total+size)
        session.add(row);await session.flush()
        return dict(receipt=_receipt(row),current=_overlay(row,row,application,person,events,successor,actor,policy))
    return await _run(engine,write)


async def read_quotes(engine,*,actor,case_id,application_id,policy=None):
    access(actor);_id(case_id);_id(application_id)
    async def read(session):
        application,person,events,successor=await _scope(session,case_id,application_id)
        rows,total=await _history(session,application,person,events)
        enabled=False;recipes=[]
        try:
            authorize(actor,policy,on=applications._today());_live_scope(events,successor)
            recipes=[r for r in policy.document()['recipes'] if r['procedure']==application.procedure]
            enabled=bool(recipes) and len(rows)<MAX_REVISIONS and total<MAX_HISTORY_BYTES
        except (EntryStorageInvalid,PermissionDenied):pass
        return dict(application=applications._application_view(application),applicant_id=person.id,revision=len(rows),
            can_calculate=enabled,recipes=recipes,policy_hash=policy.digest if isinstance(policy,QuotePolicy) else None,
            history=[dict(receipt=_receipt(row),current=_overlay(row,rows[-1],application,person,events,successor,actor,policy)) for row in reversed(rows)])
    return await _run(engine,read)
