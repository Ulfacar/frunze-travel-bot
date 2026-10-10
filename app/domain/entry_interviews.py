"""Durable case/applicant interview and manual-review acknowledgement.

Only this adapter's drafts are suppressed. No provider/legacy bot route is bound.
"""
from copy import deepcopy
import json

from sqlalchemy import select

from app.domain import entry_applications as applications,applicant_profiles
from app.domain.entry_interview_policy import authorize,existing_full_admins,policy_from_document
from app.domain.entry_portal_policy import day,proof
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,_authorize,_hash,_id,_key
from app.domain.knowledge_review import _plain
from app.domain.models import EntryInterview,EntryInterviewEvent,_now
from app.domain.service_authz import PermissionDenied
from app.knowledge import interview_catalog as catalog,interview_rules as rules
from app.knowledge.review import canonical

MAX_EVENTS=256
MAX_EVENT_BYTES=1048576
MAX_JOURNAL_BYTES=16*1048576
OPERATIONAL={'interrupt','handoff','ack'}


def _fail(code='interview_integrity_failed'):raise EntryStorageInvalid(code)


def _access(actor):
    _authorize(actor)
    if actor.manager_id not in existing_full_admins():raise PermissionDenied('interview_operator_denied')


async def _run(engine,operation):
    async def guarded(session):
        try:return await operation(session)
        except rules.InterviewInvalid as exc:raise EntryStorageInvalid(str(exc)) from None
    return await applications._run(engine,guarded)


def _exact(value,keys):
    if type(value) is not dict or set(value)!=set(keys):_fail('invalid_interview_command')


def _bytes(value):return len(canonical(value).encode())


def _stamp(row):
    return dict(request_key=row.request_key,request_hash=row.request_hash,created_by=row.created_by,
                created_at=applications._utc(row.created_at))


def _header_payload(row):
    return dict(case_id=row.case_id,applicant_id=row.applicant_id,profile_id=row.profile_id,owner_login=row.owner_login,
        command=_plain(row.command),policy=_plain(row.policy),catalog=_plain(row.catalog),
        source_pin=_plain(row.source_pin),authority=_plain(row.authority),**_stamp(row))


def _event_payload(row):
    return dict(interview_id=row.interview_id,case_id=row.case_id,applicant_id=row.applicant_id,revision=row.revision,
        previous_id=row.previous_id,action=row.action,command=_plain(row.command),snapshot=_plain(row.snapshot),**_stamp(row))


async def _sources(session,case,person,profile_id):
    profile=None
    if profile_id is not None:
        _id(profile_id)
        rows,_,_=await applicant_profiles._history(session,case,person)
        row=next((v for v in rows if v.id==profile_id),None)
        if row is None:_fail('interview_profile_unavailable')
        profile=dict(id=row.id,revision=row.revision,snapshot_hash=row.snapshot_hash,
            knowledge_version_id=row.knowledge_version_id,result_hash=_hash(_plain(row.result_snapshot)),
            stop_reasons=_plain(row.result_snapshot).get('stop_reasons',[]))
    return dict(case_id=case.id,applicant_id=person.id,applicant_hash=person.snapshot_hash,profile=profile)


async def _header(session,case,person,interview_id):
    row=await session.scalar(select(EntryInterview).where(EntryInterview.id==interview_id,
        EntryInterview.case_id==case.id,EntryInterview.applicant_id==person.id))
    if row is None:_fail('interview_unavailable')
    policy=policy_from_document(_plain(row.policy));command=_plain(row.command);authority=_plain(row.authority)
    _exact(command,('action','case_id','applicant_id','profile_id','owner_login','language','actor','policy_hash'))
    if (command['action']!='start' or command['case_id']!=case.id or command['applicant_id']!=person.id or
        command['profile_id']!=row.profile_id or command['owner_login']!=row.owner_login or command['actor']!=row.created_by or
        command['language'] not in ('ru','en') or command['policy_hash']!=policy.digest or
        row.request_hash!=_hash(command) or row.snapshot_hash!=_hash(_header_payload(row)) or
        _plain(row.catalog)!=catalog.by_digest(policy.catalog_hash) or _plain(row.source_pin)!=await _sources(session,case,person,row.profile_id)):_fail()
    _exact(authority,('full_admins',))
    admins=authority['full_admins']
    if (type(admins) is not list or not admins or len(admins)>100 or any(type(v) is not str for v in admins) or
        admins!=sorted(set(admins)) or row.owner_login not in admins or row.created_by not in admins or
        row.owner_login not in policy.operators or row.created_by not in policy.operators or
        not day(policy.valid_from)<=applications._local_day(row.created_at)<=day(policy.review_due_on)):_fail()
    _key(row.request_key)
    return row,policy


def _operation(value,*,start=False):
    if type(value) is not dict or type(value.get('action')) is not str:_fail('invalid_interview_command')
    action=value['action']
    if action=='start' and start:_exact(value,('action',))
    elif action in ('answer','correct'):
        _exact(value,('action','changes','displayed'))
        if (type(value['changes']) is not dict or not 1<=len(value['changes'])<=3 or
            type(value['displayed']) is not list or not 1<=len(value['displayed'])<=3 or
            any(type(p) is not str or len(p)>100 for p in value['displayed']) or
            len(set(value['displayed']))!=len(value['displayed']) or not set(value['changes'])<=set(value['displayed'])):_fail('invalid_interview_batch')
    elif action=='remove':
        _exact(value,('action','paths'))
        if type(value['paths']) is not list or not 1<=len(value['paths'])<=3 or any(type(p) is not str or len(p)>100 for p in value['paths']) or len(set(value['paths']))!=len(value['paths']):_fail('invalid_interview_batch')
    elif action=='language':
        _exact(value,('action','language'))
        if value['language'] not in ('ru','en'):_fail('invalid_interview_language')
    elif action in ('pause','resume','refresh','handoff'):_exact(value,('action',))
    elif action=='interrupt':
        _exact(value,('action','reason'))
        if type(value['reason']) is not str or value['reason'] not in rules.INTERRUPTS:_fail('invalid_interview_interrupt')
    elif action=='ack':
        _exact(value,('action','card_hash','confirmed'));proof(value['card_hash'])
        if value['confirmed'] is not True:_fail('interview_confirmation_required')
    else:_fail('invalid_interview_action')
    if _bytes(value)>32768:_fail('interview_command_size')
    return value


def _initial(header):
    return dict(phase='unstarted',language=header.command['language'],answers={},handoff=None,ack=None,
        collection_blocked=False,consent_withdrawal=None,analysis=None,drafts=[],channel_suppression='not_integrated')


def _reduce_v1(header,policy,before,operation,*,revision,on,actor):
    action=operation['action'];state=deepcopy(before);phase=state['phase'];reasons=[]
    document=_plain(header.catalog)
    if action=='start':
        if phase!='unstarted' or revision!=1:_fail()
        state['phase']='active'
        state['answers']=rules.apply_answers({}, {'language':state['language']},revision=revision,on=on,pre_consent=policy.pre_consent,catalog_document=document)
        if header.source_pin['profile'] and header.source_pin['profile']['stop_reasons']:reasons.append('pinned_profile_requires_review')
    elif action=='ack':
        if phase!='pending' or actor!=header.owner_login:raise PermissionDenied('interview_owner_ack_required')
        if operation['card_hash']!=state['handoff']['hash']:raise EntryStorageConflict('interview_card_changed')
        state['phase']='acked';state['ack']=dict(revision=revision,actor=actor,on=on,card_hash=operation['card_hash'])
    elif action in ('interrupt','handoff'):
        withdrawal=action=='interrupt' and operation['reason']=='consent_withdrawn'
        if withdrawal and state['collection_blocked']:_fail('interview_collection_already_blocked')
        if phase not in ('active','paused') and not (withdrawal and phase in ('pending','acked')):_fail('interview_handoff_already_exists')
        reasons.append(operation['reason'] if action=='interrupt' else 'manual_review_requested')
    elif action in ('answer','correct','remove'):
        if state['collection_blocked']:_fail('interview_collection_blocked')
        if phase=='acked':
            if actor!=header.owner_login:raise PermissionDenied('interview_owner_required')
            if action=='answer':_fail('interview_autonomous_drafts_stopped')
        elif phase!='active':_fail('interview_collection_not_active')
        fresh=rules.analyze(state['answers'],on=on,language=state['language'],pre_consent=policy.pre_consent,catalog_document=document)
        if action=='answer':
            if fresh['stops']:raise EntryStorageConflict('interview_refresh_required')
            if operation['displayed']!=[q['path'] for q in before['drafts']]:raise EntryStorageConflict('interview_questions_changed')
        changes=operation.get('changes',{})
        if action=='correct' and set(operation['displayed'])!=set(changes):_fail('invalid_interview_correction')
        state['answers']=rules.apply_answers(state['answers'],changes,revision=revision,on=on,
            pre_consent=policy.pre_consent,removals=operation.get('paths',()),catalog_document=document)
        if rules.consent_complete(rules.Answers(before['answers'],catalog_document=document),on) and not rules.consent_complete(rules.Answers(state['answers'],catalog_document=document),on):
            reasons.append('consent_withdrawn')
        if 'language' in changes and changes['language'] in ('ru','en'):state['language']=changes['language']
    elif action=='language':
        if phase not in ('active','paused'):_fail('interview_autonomous_drafts_stopped')
        if operation['language']==state['language']:_fail('interview_no_change')
        state['language']=operation['language']
        state['answers']=rules.apply_answers(state['answers'], {'language':state['language']},revision=revision,on=on,pre_consent=policy.pre_consent,catalog_document=document)
    elif action in ('pause','resume'):
        expected='active' if action=='pause' else 'paused'
        if phase!=expected:_fail('interview_phase_conflict')
        state['phase']='paused' if action=='pause' else 'active'
    elif action=='refresh':
        if phase not in ('active','paused'):_fail('interview_autonomous_drafts_stopped')
    else:_fail()
    analysis=rules.analyze(state['answers'],on=on,language=state['language'],pre_consent=policy.pre_consent,catalog_document=document)
    reasons+=analysis['stops']
    if 'consent_withdrawn' in reasons and state['consent_withdrawal'] is None:
        state['consent_withdrawal']=dict(revision=revision,actor=actor,on=on)
    if 'consent_withdrawn' in reasons or 'consent_not_granted' in reasons:state['collection_blocked']=True
    if state['phase']=='active' and not analysis['questions'] and not reasons:
        reasons.append('incomplete_answers' if analysis['gaps'] else 'intake_complete')
    if reasons and state['handoff'] is None:
        card=dict(format='kg-interview-handoff/1',interview_id=header.id,case_id=header.case_id,
            applicant_id=header.applicant_id,applicant_hash=header.source_pin['applicant_hash'],owner_login=header.owner_login,
            revision=revision,on=on,language=state['language'],answers=deepcopy(state['answers']),
            gaps=deepcopy(analysis['gaps']),reasons=sorted(set(reasons)),conflicts=analysis['conflicts'],
            source_pin=_plain(header.source_pin),policy_hash=policy.digest,catalog_hash=policy.catalog_hash,
            consent_version=policy.consent_version,terms_version=policy.terms_version,
            legal_qualification='unknown',quote='unknown',confidence=None,channel_suppression='not_integrated')
        state['handoff']=dict(card=card,hash=_hash(card));state['phase']='pending'
    if state['phase']!='active':analysis['questions']=[]
    state['analysis']=analysis
    state['drafts']=deepcopy(analysis['questions']) if state['phase']=='active' else []
    return state


# Retain v1 when adding a new reducer. Historical commands select their pinned version.
_REDUCERS={'kg-interview-reducer/1':_reduce_v1}


def _reduce(header,policy,before,operation,**context):
    reducer=_REDUCERS.get(header.catalog.get('reducer_version'))
    if reducer is None:_fail('unsupported_interview_reducer')
    return reducer(header,policy,before,operation,**context)


def _command(header,revision,actor,operation,policy_hash):
    return dict(interview_id=header.id,case_id=header.case_id,applicant_id=header.applicant_id,
        expected_revision=revision,actor=actor,operation=operation,policy_hash=policy_hash,reducer_version=header.catalog['reducer_version'])


def _result(row):
    return dict(id=row.id,interview_id=row.interview_id,revision=row.revision,snapshot_hash=row.snapshot_hash,state=_plain(row.snapshot))


def _capacity(action,revision,amount,total,state):
    # A pending card still needs ACK; a non-blocked interview always retains room
    # for a later minimal consent withdrawal, even after ACK at the count/byte limit.
    if action=='ack':reserve=0 if state['collection_blocked'] else 1
    elif action in ('interrupt','handoff'):
        reserve=(1 if state['phase']=='pending' else 0) if state['collection_blocked'] else 2
    else:reserve=3
    if revision>MAX_EVENTS-reserve or amount>MAX_EVENT_BYTES or total>MAX_JOURNAL_BYTES-reserve*MAX_EVENT_BYTES:
        _fail('interview_history_limit')


async def _append(session,header,rows,state,command,at,size):
    revision=len(rows)+1;operation=command['operation'];action=operation['action']
    if rows and applications._utc(at)<applications._utc(rows[-1].created_at):_fail('interview_clock_moved_back')
    row=EntryInterviewEvent(interview_id=header.id,case_id=header.case_id,applicant_id=header.applicant_id,
        revision=revision,previous_id=rows[-1].id if rows else None,action=action,request_key=command.pop('_request_key'),
        request_hash=_hash(command),command=command,snapshot=state,created_by=command['actor'],created_at=at)
    row.snapshot_hash=_hash(_event_payload(row));amount=_bytes(_event_payload(row))
    _capacity(action,revision,amount,size+amount,state)
    session.add(row);await session.flush();return _result(row)


async def _history(session,header,policy):
    rows=list((await session.scalars(select(EntryInterviewEvent).where(EntryInterviewEvent.interview_id==header.id)
        .order_by(EntryInterviewEvent.revision).limit(MAX_EVENTS+1))).all())
    if not rows or len(rows)>MAX_EVENTS:_fail()
    state=_initial(header);previous=None;size=0
    for revision,row in enumerate(rows,1):
        command=_plain(row.command)
        _exact(command,('interview_id','case_id','applicant_id','expected_revision','actor','operation','policy_hash','reducer_version'))
        operation=_operation(deepcopy(command['operation']),start=revision==1)
        expected_command=_command(header,revision-1,row.created_by,operation,command.get('policy_hash'))
        if (row.case_id!=header.case_id or row.applicant_id!=header.applicant_id or row.revision!=revision or
            row.previous_id!=(previous.id if previous else None) or previous and row.id<=previous.id or
            row.action!=operation['action'] or command!=expected_command or row.request_hash!=_hash(command) or
            row.snapshot_hash!=_hash(_event_payload(row)) or row.created_by not in policy.operators or
            row.created_by not in header.authority['full_admins']):_fail()
        _key(row.request_key)
        if revision==1 and (row.created_by!=header.created_by or row.request_key!=header.request_key or applications._utc(row.created_at)!=applications._utc(header.created_at)):_fail()
        if previous and applications._utc(row.created_at)<applications._utc(previous.created_at):_fail()
        if row.action in OPERATIONAL:
            if command['policy_hash'] is not None and command['policy_hash']!=policy.digest:_fail()
        elif command['policy_hash']!=policy.digest or not day(policy.valid_from)<=applications._local_day(row.created_at)<=day(policy.review_due_on):_fail()
        expected=_reduce(header,policy,state,operation,revision=revision,on=applications._local_day(row.created_at).isoformat(),actor=row.created_by)
        if expected!=_plain(row.snapshot):_fail()
        amount=_bytes(_event_payload(row));size+=amount
        _capacity(row.action,revision,amount,size,expected)
        state=expected;previous=row
    return rows,state,size


async def start_interview(engine,*,actor,case_id,applicant_id,owner_login,language,request_key,
                          expected_policy_hash,policy,profile_id=None):
    _access(actor);_id(case_id);_id(applicant_id);_key(request_key);proof(expected_policy_hash)
    if profile_id is not None:_id(profile_id)
    if type(owner_login) is not str or language not in ('ru','en'):_fail('invalid_interview_start')
    command=dict(action='start',case_id=case_id,applicant_id=applicant_id,profile_id=profile_id,
        owner_login=owner_login,language=language,actor=actor.manager_id,policy_hash=expected_policy_hash)
    async def write(session):
        case=await applications._case(session,case_id,lock=True);person=await applications._applicant(session,case_id,applicant_id)
        prior=await session.scalar(select(EntryInterview).where(EntryInterview.case_id==case_id,EntryInterview.request_key==request_key))
        if prior:
            if prior.applicant_id!=applicant_id or prior.request_hash!=_hash(command):raise EntryStorageConflict('interview_request_conflict')
            header,pinned=await _header(session,case,person,prior.id);rows,_,_=await _history(session,header,pinned)
            return _result(rows[0])
        authorize(actor,policy,on=applications._today())
        admins=existing_full_admins()
        if owner_login not in admins or owner_login not in policy.operators:raise PermissionDenied('interview_owner_unavailable')
        if expected_policy_hash!=policy.digest or policy.catalog_hash!=catalog.digest():raise EntryStorageConflict('interview_policy_changed')
        if await session.scalar(select(EntryInterview.id).where(EntryInterview.case_id==case_id,EntryInterview.applicant_id==applicant_id)):
            raise EntryStorageConflict('interview_already_exists')
        at=_now();authorize(actor,policy,on=applications._local_day(at))
        header=EntryInterview(case_id=case_id,applicant_id=applicant_id,profile_id=profile_id,owner_login=owner_login,
            request_key=request_key,request_hash=_hash(command),command=command,policy=policy.document(),catalog=catalog.document(),
            source_pin=await _sources(session,case,person,profile_id),authority={'full_admins':sorted(admins)},created_by=actor.manager_id,created_at=at)
        header.snapshot_hash=_hash(_header_payload(header));session.add(header);await session.flush()
        operation={'action':'start'};state=_reduce(header,policy,_initial(header),operation,revision=1,on=applications._local_day(at).isoformat(),actor=actor.manager_id)
        event_command=_command(header,0,actor.manager_id,operation,policy.digest);event_command['_request_key']=request_key
        return await _append(session,header,[],state,event_command,at,0)
    return await _run(engine,write)


async def record_action(engine,*,actor,case_id,applicant_id,interview_id,expected_revision,request_key,operation,
                        policy=None,expected_policy_hash=None):
    _access(actor);_id(case_id);_id(applicant_id);_id(interview_id);_key(request_key)
    if type(expected_revision) is not int or not 1<=expected_revision<=MAX_EVENTS:_fail('invalid_interview_revision')
    operation=_operation(deepcopy(operation))
    if expected_policy_hash is not None:proof(expected_policy_hash)
    async def write(session):
        case=await applications._case(session,case_id,lock=True);person=await applications._applicant(session,case_id,applicant_id)
        header,pinned=await _header(session,case,person,interview_id);rows,state,size=await _history(session,header,pinned)
        command=_command(header,expected_revision,actor.manager_id,operation,expected_policy_hash)
        old=next((r for r in rows if r.request_key==request_key),None)
        if old:
            if old.request_hash!=_hash(command):raise EntryStorageConflict('interview_request_conflict')
            return _result(old)
        if actor.manager_id not in header.authority['full_admins'] or actor.manager_id not in pinned.operators:raise PermissionDenied('interview_operator_denied')
        if expected_revision!=len(rows):raise EntryStorageConflict('interview_revision_changed')
        if operation['action'] not in OPERATIONAL:
            authorize(actor,policy,on=applications._today())
            if policy.digest!=pinned.digest or expected_policy_hash!=pinned.digest:raise EntryStorageConflict('interview_policy_changed')
        elif expected_policy_hash is not None and expected_policy_hash!=pinned.digest:raise EntryStorageConflict('interview_policy_changed')
        at=_now()
        if operation['action'] not in OPERATIONAL:authorize(actor,policy,on=applications._local_day(at))
        after=_reduce(header,pinned,state,operation,revision=len(rows)+1,on=applications._local_day(at).isoformat(),actor=actor.manager_id)
        command['_request_key']=request_key
        return await _append(session,header,rows,after,command,at,size)
    return await _run(engine,write)


async def read_interview(engine,*,actor,case_id,applicant_id,interview_id=None,policy=None):
    _access(actor);_id(case_id);_id(applicant_id)
    if interview_id is not None:_id(interview_id)
    async def read(session):
        case=await applications._case(session,case_id);person=await applications._applicant(session,case_id,applicant_id)
        target=interview_id or await session.scalar(select(EntryInterview.id).where(EntryInterview.case_id==case_id,EntryInterview.applicant_id==applicant_id))
        if target is None:return dict(interview=None)
        header,pinned=await _header(session,case,person,target);rows,state,size=await _history(session,header,pinned)
        enabled=False
        try:
            authorize(actor,policy,on=applications._today());enabled=policy.digest==pinned.digest and actor.manager_id in header.authority['full_admins']
        except (PermissionDenied,EntryStorageInvalid):pass
        fresh=rules.analyze(state['answers'],on=applications._today().isoformat(),language=state['language'],pre_consent=pinned.pre_consent,catalog_document=_plain(header.catalog))
        if state['phase']!='active':fresh['questions']=[]
        can_operate=actor.manager_id in header.authority['full_admins'] and actor.manager_id in pinned.operators
        drafts=state['drafts'] if enabled and state['phase']=='active' and not fresh['stops'] else []
        normal_room=len(rows)<MAX_EVENTS-3 and size<MAX_JOURNAL_BYTES-3*MAX_EVENT_BYTES
        return dict(interview=dict(id=header.id,case_id=case_id,applicant_id=applicant_id,owner_login=header.owner_login,
                snapshot_hash=header.snapshot_hash,source_pin=_plain(header.source_pin),policy_hash=pinned.digest,
                catalog_hash=pinned.catalog_hash,catalog_version=header.catalog['version']),
            revision=len(rows),state=state,current_analysis=fresh,drafts=drafts,policy_enabled=enabled,
            can_collect=enabled and state['phase'] in ('active','acked') and not state['collection_blocked'] and
                (state['phase']!='acked' or actor.manager_id==header.owner_login) and normal_room,
            can_control=enabled and state['phase'] in ('active','paused') and normal_room,
            can_handoff=can_operate and state['phase'] in ('active','paused'),
            can_ack=can_operate and state['phase']=='pending' and actor.manager_id==header.owner_login,
            can_withdraw=can_operate and not state['collection_blocked'],
            history=[dict(id=r.id,revision=r.revision,action=r.action,actor=r.created_by,at=applications._utc(r.created_at),
                snapshot_hash=r.snapshot_hash,operation=_plain(r.command)['operation']) for r in rows])
    return await _run(engine,read)
