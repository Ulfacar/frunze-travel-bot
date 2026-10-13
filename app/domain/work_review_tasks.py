"""Explicit internal review reminders, separate from official filing deadlines.

Reconciliation is an operator action. Calendar rows are retained conditional
reminders; opening a view does not promise automatic cancellation on revocation.
No provider, filing, workflow transition, money or client-message operation.
"""
from copy import deepcopy
from datetime import date,datetime
import json
import re

from sqlalchemy import select,func,cast,Text

from app.domain import entry_applications as apps,applicant_profiles,applicant_stay_history,work_deadlines
from app.domain.calendar_tasks import CalendarTaskService,_log_event
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,_authorize,_id,_key,_hash,_plain
from app.domain.models import EntryWorkReviewEvent,CalendarTask,CalendarTaskEvent,_now
from app.domain.work_review_policy import WorkReviewAuthority,from_document,FORMAT
from app.domain.service_authz import PermissionDenied
from app.knowledge.deadlines import _calculate
from app.knowledge.review import canonical

MAX_REVISIONS=64
MAX_EVENT_BYTES=1024*1024
MAX_BYTES=4*1024*1024
RESERVE=8192
ACTIVE=('planned','rescheduled')
ACTIONS=('refresh','restore','new_generation','complete','cancel')


def fail(code='work_review_integrity_failed'):raise EntryStorageInvalid(code)


def _operation(operation):
    if (type(operation) is not dict or operation.keys()!={'action','token','confirmed'} or
        type(operation['action']) is not str or operation['action'] not in ACTIONS or operation['confirmed'] is not True or
        type(operation['token']) is not str or not re.fullmatch('[a-f0-9]{64}',operation['token'])):
        fail('invalid_work_review_operation')
    return deepcopy(operation)


def _payload(row):
    keys=('case_id','applicant_id','application_id','procedure','revision','previous_id','task_id','action',
          'request_key','request_hash','command','snapshot','created_by')
    return {**{k:_plain(getattr(row,k)) for k in keys},'created_at':apps._utc(row.created_at)}


def _receipt(row):return dict(id=row.id,snapshot_hash=row.snapshot_hash,**_payload(row))


def _task_state(task):
    if task is None:return None
    return dict(id=task.id,status=task.status,date=task.scheduled_date.isoformat(),
        at=apps._utc(task.scheduled_at) if task.scheduled_at else None,owner=task.manager_id,
        claimed=bool(task.claimed_at or task.claimed_by),priority=task.priority)


def _stable_report(report):
    result=deepcopy(report)
    result.pop('evidence_hash',None)
    if result.get('current_stay'):
        result['current_stay'].pop('checked_at',None)
        result['current_stay'].pop('evidence_hash',None)
    return result


def _semantic(report,authority):
    if report.get('status')!='calculated' or authority is None:return None
    fact=authority.fact.document
    return _hash(dict(rule=report['rule_id'],case_id=report['case_id'],applicant_id=report['applicant_id'],
        entered_on=fact['entered_on'],passport_ref=fact['passport_ref'],lawful_until=fact['lawful_until'],
        due_on=report['due_on'],work_policy=authority.work.digest))


async def _scope(session,case_id,applicant_id,application_id):
    case=await apps._case(session,case_id,lock=True)
    application=await apps._application(session,case_id,application_id,lock=True)
    if application.applicant_id!=applicant_id or application.procedure!='unified_permit':fail('work_review_scope')
    _,person=await applicant_profiles._subject(session,case_id,applicant_id,write=True)
    return case,person,application


async def _history(session,case,person,application):
    lengths=list((await session.execute(select(EntryWorkReviewEvent.id,
        func.length(cast(EntryWorkReviewEvent.command,Text))+func.length(cast(EntryWorkReviewEvent.snapshot,Text)))
        .where(EntryWorkReviewEvent.application_id==application.id).order_by(EntryWorkReviewEvent.revision)
        .limit(MAX_REVISIONS+2))).all())
    if len(lengths)>MAX_REVISIONS+1 or any(n is None or n>2*MAX_EVENT_BYTES for _,n in lengths) or sum(n for _,n in lengths)>2*MAX_BYTES:
        fail('work_review_history_limit')
    rows=list((await session.scalars(select(EntryWorkReviewEvent).where(EntryWorkReviewEvent.application_id==application.id)
        .order_by(EntryWorkReviewEvent.revision))).all())
    task_ids={r.task_id for r in rows if r.task_id is not None}
    audit={}
    if task_ids:
        events=list((await session.scalars(select(CalendarTaskEvent).where(CalendarTaskEvent.task_id.in_(task_ids),
            CalendarTaskEvent.event=='work_review_bound').order_by(CalendarTaskEvent.id).limit(MAX_REVISIONS+2))).all())
        if len(events)!=len(rows):fail('work_review_task_audit')
        for event in events:
            try:
                if len(event.detail.encode())>1024:fail('work_review_task_audit')
                detail=json.loads(event.detail)
                if type(detail) is not dict or type(detail.get('receipt')) is not int or detail['receipt'] in audit:fail('work_review_task_audit')
                audit[detail['receipt']]=(event,detail)
            except (ValueError,TypeError,AttributeError):fail('work_review_task_audit')
    previous=None;total=0;verified={};profile_rows=None;stay_rows=None
    for revision,row in enumerate(rows,1):
        operation=_operation(_plain(row.command)['operation'])
        expected=dict(format=FORMAT,actor=row.created_by,case_id=case.id,applicant_id=person.id,
            application_id=application.id,expected_revision=revision-1,operation=operation)
        snapshot=_plain(row.snapshot);_key(row.request_key)
        binding=audit.get(row.id)
        if (binding is None or binding[0].task_id!=row.task_id or binding[0].actor!=row.created_by or
            canonical(binding[1])!=canonical(dict(receipt=row.id,hash=row.snapshot_hash,application_id=application.id,applicant_id=person.id))):
            fail('work_review_task_audit')
        if (row.case_id!=case.id or row.applicant_id!=person.id or row.procedure!='unified_permit' or row.revision!=revision or
            row.previous_id!=(previous.id if previous else None) or previous and row.id<=previous.id or
            canonical(row.command)!=canonical(expected) or row.action!=operation['action'] or row.request_hash!=_hash(expected) or
            row.snapshot_hash!=_hash(_payload(row)) or previous and apps._utc(row.created_at)<apps._utc(previous.created_at) or
            snapshot.keys()!={'format','previous_hash','application_hash','application_event','authority','report','semantic','task','attention','operators'} or
            snapshot['format']!=FORMAT or snapshot['previous_hash']!=(previous.snapshot_hash if previous else None) or
            snapshot['application_hash']!=application.snapshot_hash or row.created_by not in snapshot['operators'] or
            row.task_id!=(snapshot['task']['id'] if snapshot['task'] else None)):
            fail()
        if type(snapshot['operators']) is not list or any(type(v) is not str for v in snapshot['operators']):fail()
        if snapshot['authority'] is not None and snapshot['operators']!=from_document(snapshot['authority']).review.document['operators']:fail()
        if snapshot['authority'] is None and (previous is None or snapshot['operators']!=list(previous.snapshot['operators'])):fail()
        if (snapshot['authority'] is None)!=(snapshot['report'] is None):fail()
        if snapshot['authority'] is None and snapshot['semantic']!=previous.snapshot['semantic']:fail()
        if row.action in ('cancel','complete'):
            if (previous is None or snapshot['authority'] is not None or snapshot['report'] is not None or
                snapshot['semantic']!=previous.snapshot['semantic'] or row.task_id!=previous.task_id or
                not snapshot['task'] or snapshot['task']['status']!=('cancelled' if row.action=='cancel' else 'completed')):fail()
        size=len(canonical(_payload(row)).encode());total+=size
        if size>MAX_EVENT_BYTES or total>MAX_BYTES or revision>MAX_REVISIONS and row.action!='cancel':fail('work_review_history_limit')
        report=snapshot['report'];basis=snapshot['authority']
        if report is not None:
            if (report['status']!='calculated' or report['case_id']!=case.id or report['applicant_id']!=person.id or report['format']!=work_deadlines.FORMAT or
                report['evidence_hash']!=_hash({k:v for k,v in report.items() if k!='evidence_hash'}) or
                report['operational_action_allowed'] is not False or report['permission_to_work'] is not None or
                report['permission_to_remain'] is not None or report['may_quote'] is not False):fail()
        retained=snapshot['task']
        if retained is None:fail()
        if retained:
            if (retained.keys()!=set(('id','status','date','at','owner','claimed','priority')) or type(retained['id']) is not int or
                retained['claimed'] is not False or retained['status'] not in (*ACTIVE,'cancelled','completed') or
                retained['priority'] not in ('normal','high') or type(retained['owner']) is not str or not retained['owner'] or
                date.fromisoformat(retained['date']).isoformat()!=retained['date']):fail()
            if retained['at'] is not None:
                try:
                    moment=datetime.fromisoformat(retained['at'])
                    if moment.tzinfo is None or apps._utc(moment)!=retained['at']:fail()
                except (ValueError,TypeError):fail()
            if retained['status'] in ACTIVE and (report is None or retained['date']!=report['due_on'] or retained['at'] is not None):fail()
        if report and report['status']=='calculated':
            identity=_hash([basis,report,snapshot['application_event'],row.created_by,apps._utc(row.created_at)])
            if identity not in verified:
                authority=from_document(basis);p=authority.review.document
                from app.domain.work_review_evidence import verify_report
                await verify_report(session,case,person,application,row,report,authority,snapshot['application_event'])
                on=report['current_stay']['as_of']
                if (snapshot['task'] and snapshot['task']['status'] in ACTIVE and (
                        row.created_by not in p['operators'] or not p['valid_from']<=on<=p['review_due_on']) or
                    report['policy']!=authority.work.document() or snapshot['semantic']!=_semantic(report,authority) or
                    report['current_stay']['fact']['hash']!=authority.fact.digest):fail()
                source=report['source']
                if (any(source[k]!=getattr(authority.work,k) for k in ('source_hash','bundle_hash','projection_hash','catalog_hash','rule_hash')) or
                    report['rule_id']!=work_deadlines.RULE or report['source']['rule_hash']!=authority.work.rule_hash):fail()
                from app.domain.entry_calculations import _bundle
                bundle=await _bundle(session,source['version_id'])
                clause=next((u for u in bundle['units'] if u['unit_id']==work_deadlines.RULE),None)
                if clause is None or _hash(clause)!=authority.work.rule_hash or source['source_value']!=clause['value']:fail()
                fact=authority.fact.document
                if profile_rows is None:profile_rows=(await applicant_profiles._history(session,case,person))[0]
                profile=next((r for r in profile_rows if r.id==fact['profile_id']),None)
                if profile is None or profile.snapshot_hash!=fact['profile_hash']:fail()
                if stay_rows is None:stay_rows=(await applicant_stay_history._history(session,case,person))[0]
                stay=next((r for r in stay_rows if r.id==fact['history']['id']),None)
                if stay is None or stay.snapshot_hash!=fact['history']['snapshot_hash']:fail()
                interpretation=dict(value=10,unit='working_days',direction='before',anchor='actual_visa_free_permission_end',
                    shift_from_nonworking='none',boundary_inclusive=authority.work.boundary_inclusive)
                calculated=_calculate(interpretation,fact['lawful_until'],dict(count_anchor_day=authority.work.count_anchor_day,
                    month_end=None,hours_mode=None),authority.calendars)
                if report['calculation']!=calculated or report['due_on']!=calculated['due']:fail()
                verified[identity]=True
        previous=row
    return rows,total


async def _task(session,case,application,rows):
    if not rows or rows[-1].task_id is None:return None
    task=await session.scalar(select(CalendarTask).where(CalendarTask.id==rows[-1].task_id).with_for_update(of=CalendarTask))
    if (task is None or task.contact_id!=case.contact_id or task.service_case_id!=case.id or task.direction!='visa' or
        task.kind!='followup' or task.user_id or task.status not in (*ACTIVE,'cancelled','completed')):fail('work_review_task_scope')
    other=await session.scalar(select(EntryWorkReviewEvent.id).where(EntryWorkReviewEvent.task_id==task.id,
        EntryWorkReviewEvent.application_id!=application.id).limit(1))
    if other:fail('work_review_task_scope')
    event=await session.scalar(select(CalendarTaskEvent).where(CalendarTaskEvent.task_id==task.id,
        CalendarTaskEvent.event=='work_review_bound').order_by(CalendarTaskEvent.id.desc()).limit(1))
    import json
    try:
        expected=dict(receipt=rows[-1].id,hash=rows[-1].snapshot_hash,application_id=application.id,applicant_id=application.applicant_id)
        if event is None or canonical(json.loads(event.detail))!=canonical(expected):fail('work_review_task_audit')
    except (ValueError,TypeError):fail('work_review_task_audit')
    return task


async def _current(session,actor,case,person,application,rows,task,authority):
    report=None;eligible=False
    if authority is not None:
        if not isinstance(authority,WorkReviewAuthority):fail('work_review_authority_required')
        authority.validate()
        report=await work_deadlines.evaluate_in_session(session,actor=actor,case_id=case.id,applicant_id=person.id,
            **authority.calculation_args())
        on=(report.get('current_stay') or {}).get('as_of')
        p=authority.review.document
        eligible=bool(on and p['valid_from']<=on<=p['review_due_on'] and actor.manager_id in p['operators'] and report['status']=='calculated')
    events=await apps._events(session,application)
    if events[-1].status in ('approved','refused','closed'):eligible=False
    checked=(report or {}).get('current_stay')
    observed_at=checked['checked_at'] if checked else apps._utc(_now())
    if any(apps._utc(value.created_at)>observed_at for value in (application,events[-1])):eligible=False
    owner=(case.owner_login or '').strip().lower()
    attention='' if eligible and owner else 'unknown_date' if not eligible else 'missing_owner'
    state=_task_state(task)
    if task and state['claimed']:attention='claimed'
    expected=rows[-1].snapshot['task'] if rows else None
    if task and task.status in ACTIVE and expected and (state['date']!=expected['date'] or state['at'] is not None):attention='schedule_conflict'
    token=_hash(dict(revision=len(rows),head=rows[-1].snapshot_hash if rows else None,application=events[-1].snapshot_hash,
        report=_stable_report(report) if report else None,authority=authority.review.digest if authority else None,task=state,owner=owner))
    return dict(token=token,revision=len(rows),report=report,attention=attention,eligible=eligible,
        task=state,owner=owner,semantic=_semantic(report,authority) if report else None,
        application_event=dict(id=events[-1].id,revision=events[-1].revision,hash=events[-1].snapshot_hash))


async def read(engine,*,actor,case_id,applicant_id,application_id,authority=None):
    _authorize(actor)
    for value in (case_id,applicant_id,application_id):_id(value)
    async def run(session):
        case,person,application=await _scope(session,case_id,applicant_id,application_id)
        rows,_=await _history(session,case,person,application);task=await _task(session,case,application,rows)
        current=await _current(session,actor,case,person,application,rows,task,authority)
        return dict(application=apps._application_view(application),current=current,history=[_receipt(r) for r in reversed(rows)])
    return await apps._run(engine,run)


async def record(engine,*,actor,case_id,applicant_id,application_id,expected_revision,request_key,operation,authority=None):
    _authorize(actor)
    for value in (case_id,applicant_id,application_id):_id(value)
    _key(request_key);operation=_operation(operation)
    if type(expected_revision) is not int or not 0<=expected_revision<=MAX_REVISIONS:fail('invalid_work_review_revision')
    command=dict(format=FORMAT,actor=actor.manager_id,case_id=case_id,applicant_id=applicant_id,
        application_id=application_id,expected_revision=expected_revision,operation=operation)
    async def run(session):
        case,person,application=await _scope(session,case_id,applicant_id,application_id)
        rows,total=await _history(session,case,person,application)
        old=await session.scalar(select(EntryWorkReviewEvent).where(EntryWorkReviewEvent.case_id==case_id,EntryWorkReviewEvent.request_key==request_key))
        if old:
            if old.application_id!=application_id or old.request_hash!=_hash(command):raise EntryStorageConflict('work_review_request_reused')
            return _receipt(old)
        if len(rows)!=expected_revision:raise EntryStorageConflict('work_review_revision_changed')
        action=operation['action']
        if len(rows)>MAX_REVISIONS or len(rows)==MAX_REVISIONS and action!='cancel':fail('work_review_history_limit')
        task=await _task(session,case,application,rows)
        current=await _current(session,actor,case,person,application,rows,task,authority)
        if current['token']!=operation['token']:raise EntryStorageConflict('work_review_context_changed')
        if task and (task.claimed_at or task.claimed_by):raise EntryStorageConflict('work_review_task_claimed')
        previous=rows[-1] if rows else None
        terminal=action in ('cancel','complete')
        granted=current['eligible'] and not terminal
        operators=authority.review.document['operators'] if granted else list(previous.snapshot['operators']) if previous else []
        if actor.manager_id not in operators:raise PermissionDenied('work review operator is not authorized')
        attention=current['attention']
        if action in ('restore','new_generation') and (not current['eligible'] or not current['owner']):
            fail('work_review_current_evidence_required')
        if action in ('cancel','complete'):
            if task is None or task.status not in ACTIVE:fail('work_review_active_task_required')
            if action=='complete' and not current['eligible']:fail('work_review_current_evidence_required')
            await (CalendarTaskService.cancel if action=='cancel' else CalendarTaskService.complete)(session,task,actor=actor.manager_id)
            attention='cancelled' if action=='cancel' else 'completed'
        elif not current['eligible'] or not current['owner']:
            if previous is None:fail('work_review_current_evidence_required')
            if task and task.status in ACTIVE:await CalendarTaskService.cancel(session,task,actor=actor.manager_id)
        else:
            if attention=='schedule_conflict' and action!='restore':raise EntryStorageConflict('work_review_schedule_conflict')
            if task and task.status not in ACTIVE:
                if action!='new_generation' or current['semantic']==previous.snapshot['semantic']:
                    fail('work_review_terminal_task_preserved')
                task=None
            elif action=='new_generation':fail('work_review_new_generation_unavailable')
            due=date.fromisoformat(current['report']['due_on'])
            if task is None:
                task=await CalendarTaskService.create(session,manager_id=current['owner'],direction='visa',kind='followup',
                    contact_id=case.contact_id,scheduled_date=due,created_by=actor.manager_id,
                    comment=f'Проверить условный срок ЕР · заявка №{application.id}, заявитель №{person.id}. '
                        'Сохранённый расчёт требует новой проверки основания. Подача и право пребывания не подтверждены.')
                task.service_case_id=case.id
            else:
                if task.scheduled_date!=due or task.scheduled_at is not None:
                    await CalendarTaskService.reschedule(session,task,new_date=due,actor=actor.manager_id)
                if task.manager_id!=current['owner']:
                    old_owner=task.manager_id;task.manager_id=current['owner']
                    await _log_event(session,task,'reassigned',actor=actor.manager_id,detail=canonical(dict(previous=old_owner,current=task.manager_id)))
            attention=''
        # Cancellation retains just the last verified receipt hash, not another
        # full personal evidence copy; capacity always leaves one terminal slot.
        snapshot=dict(format=FORMAT,previous_hash=previous.snapshot_hash if previous else None,
            application_hash=application.snapshot_hash,application_event=current['application_event'],
            authority=authority.document() if granted else None,
            report=current['report'] if granted else None,semantic=current['semantic'] if granted else previous.snapshot['semantic'] if previous else None,
            task=_task_state(task),attention=attention,operators=operators)
        row=EntryWorkReviewEvent(case_id=case.id,applicant_id=person.id,application_id=application.id,procedure=application.procedure,
            revision=len(rows)+1,previous_id=previous.id if previous else None,task_id=task.id if task else None,action=action,
            request_key=request_key,request_hash=_hash(command),command=command,snapshot=snapshot,created_by=actor.manager_id,
            created_at=_now())
        checked=(current.get('report') or {}).get('current_stay')
        if (previous and apps._utc(row.created_at)<apps._utc(previous.created_at) or
            checked and apps._utc(row.created_at)<checked['checked_at']):fail('work_review_clock_moved_back')
        size=len(canonical(_payload(row)).encode())
        if size>MAX_EVENT_BYTES or total+size>MAX_BYTES-(0 if action=='cancel' else RESERVE) or action=='cancel' and size>RESERVE:
            fail('work_review_history_limit')
        row.snapshot_hash=_hash(_payload(row));session.add(row);await session.flush()
        if task:await _log_event(session,task,'work_review_bound',actor=actor.manager_id,
            detail=canonical(dict(receipt=row.id,hash=row.snapshot_hash,application_id=application.id,applicant_id=person.id)))
        return _receipt(row)
    return await apps._run(engine,run)
