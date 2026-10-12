"""Atomic interruption -> retained interview -> existing permanent route stop.

This domain component does not send, parse ordinary answers or install an
incoming hook. Those connections are separate H02 acceptance requirements.
"""
from dataclasses import asdict

from sqlalchemy import select, cast, Text, func

from app.domain import entry_applications as applications, entry_channel_stops as stops
from app.domain import entry_channel_policy as channels, entry_interviews as interviews
from app.domain.dialogue_policy import DialoguePolicy, delegated_document
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict, _hash, _plain, _transaction
from app.domain.knowledge_import import _sessions
from app.domain.models import EntryDialogueStopCause, EntryInterviewEvent, EntryInterview, _now
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge import dialogue_interrupts as triage_rules
from app.knowledge.review import canonical

MAX_CAUSE_BYTES = 65536
MAX_CAUSES = 256
MAX_REGISTRY_BYTES = MAX_CAUSES * MAX_CAUSE_BYTES


def _fail(code='dialogue_cause_integrity_failed'):
    raise EntryStorageInvalid(code)


def _payload(row):
    return dict(format='kg-dialogue-stop-cause/1', transport_key=row.transport_key,
        revision=row.revision, previous_id=row.previous_id, case_id=row.case_id,
        applicant_id=row.applicant_id, interview_id=row.interview_id, stop_id=row.stop_id,
        event_id=row.event_id, message_key=row.message_key, input_hash=row.input_hash,
        document=_plain(row.document), created_at=applications._utc(row.created_at))


def _result(row):
    document=_plain(row.document)
    return dict(id=row.id, revision=row.revision, case_id=row.case_id, applicant_id=row.applicant_id,
        interview_id=row.interview_id, stop_id=row.stop_id, event_id=row.event_id,
        snapshot_hash=row.snapshot_hash, reason=document['triage']['reason'],
        interpretation=document['triage']['interpretation'], collection_blocked=document['collection_blocked'],
        suppressed=True, delivery='not_sent', manager_acknowledgement='not_changed')


async def _registry(session, stop_rows):
    sizes=list((await session.execute(select(EntryDialogueStopCause.id,
        func.length(cast(EntryDialogueStopCause.document, Text))).order_by(EntryDialogueStopCause.id)
        .limit(MAX_CAUSES+1))).all())
    if len(sizes)>MAX_CAUSES or any(n is None or n>MAX_CAUSE_BYTES for _,n in sizes) or sum(n for _,n in sizes)>MAX_REGISTRY_BYTES:
        _fail('dialogue_cause_registry_limit')
    rows=list((await session.scalars(select(EntryDialogueStopCause).order_by(EntryDialogueStopCause.id).limit(MAX_CAUSES+1))).all())
    by_stop={r.id:r for r in stop_rows};latest={};requests=set();total=0;validated={}
    for row in rows:
        doc=_plain(row.document);total+=len(canonical(_payload(row)).encode())
        stops._exact(doc,('authority','triage','effect','before_event_id','before_event_hash',
                         'event_hash','stop_hash','collection_blocked','previous_hash'))
        stops._exact(doc['authority'],('policy','deployed_policy_hash'))
        auth=DialoguePolicy(doc['authority']['policy']);channels.proof(doc['authority']['deployed_policy_hash'])
        assignments=auth.document['assignments']
        if len(assignments)!=1:_fail()
        assignment=assignments[0];route=assignment['route'];stop=by_stop.get(row.stop_id)
        prev=latest.get(row.transport_key)
        if (stop is None or row.snapshot_hash!=_hash(_payload(row)) or total>MAX_REGISTRY_BYTES or
            len(canonical(_payload(row)).encode())>MAX_CAUSE_BYTES or
            row.transport_key!=_hash(route) or stop.transport_key!=row.transport_key or
            [assignment[k] for k in ('case_id','applicant_id','interview_id','dialog_id')]!=
            [row.case_id,row.applicant_id,row.interview_id,stop.dialog_id] or
            [stop.case_id,stop.applicant_id,stop.interview_id]!=[row.case_id,row.applicant_id,row.interview_id] or
            row.revision!=(prev.revision+1 if prev else 1) or row.revision>2 or
            row.previous_id!=(prev.id if prev else None) or doc['previous_hash']!=(prev.snapshot_hash if prev else None) or
            stop.snapshot_hash!=doc['stop_hash'] or (row.transport_key,row.message_key) in requests):_fail()
        for value in (row.message_key,row.input_hash,row.snapshot_hash,doc['event_hash'],doc['before_event_hash']):channels.proof(value)
        if row.interview_id not in validated:
            header=await session.get(EntryInterview,row.interview_id)
            if header is None or header.snapshot_hash!=_hash(interviews._header_payload(header)):_fail()
            pinned=interviews.policy_from_document(_plain(header.policy))
            history,_,_=await interviews._history(session,header,pinned)
            validated[row.interview_id]=(header,pinned,{e.id:e for e in history})
        header,pinned,events=validated[row.interview_id]
        before=events.get(doc['before_event_id']);event=events.get(row.event_id)
        if (before is None or event is None or assignment['header_hash']!=header.snapshot_hash or
            assignment['actor'] not in header.authority['full_admins'] or assignment['actor'] not in pinned.operators or
            auth.document['interview_policy_hash']!=pinned.digest or
            auth.document['channel_policy_hash']!=_hash(_plain(stop.policy)) or
            before.snapshot_hash!=doc['before_event_hash'] or event.snapshot_hash!=doc['event_hash'] or
            event.revision<before.revision or
            applications._utc(event.created_at)>applications._utc(row.created_at) or
            applications._utc(before.created_at)>applications._utc(row.created_at) or
            prev and applications._utc(prev.created_at)>applications._utc(row.created_at) or
            doc['collection_blocked'] is not event.snapshot['collection_blocked']):_fail()
        t=doc['triage'];stops._exact(t,('reason','families','source_rows','interpretation'))
        if (t['reason'] not in interviews.rules.INTERRUPTS or type(t['families']) is not list or
            any(f not in triage_rules.FAMILIES for f in t['families']) or
            t['source_rows']!=sorted({n for f in t['families'] for n in triage_rules.FAMILIES[f]}) or
            t['interpretation'] not in ('review_topic_only','collection_stop_request','possible_privacy_stop')):_fail()
        if doc['effect']=='interrupt_appended':
            if (event.previous_id!=before.id or event.action!='interrupt' or
                event.command['operation']!={'action':'interrupt','reason':t['reason']} or
                event.created_by!=assignment['actor'] or
                applications._utc(event.created_at)!=applications._utc(row.created_at)):_fail()
        elif doc['effect']=='existing_handoff_retained':
            if event.id!=before.id or before.snapshot['phase'] not in ('pending','acked'):_fail()
        else:_fail()
        if row.revision==1:
            on=applications._local_day(row.created_at).isoformat()
            if not auth.document['valid_from']<=on<=auth.document['review_due_on']:_fail()
        elif (t['reason']!='consent_withdrawn' or not doc['collection_blocked'] or
              prev.document['collection_blocked'] or event.revision<=events[prev.event_id].revision):_fail()
        latest[row.transport_key]=row;requests.add((row.transport_key,row.message_key))
    return rows,total


def _message(route, provider_id, text, kind, voice):
    channels.validate_route(route)
    if type(provider_id) is not str or not 1<=len(provider_id)<=200 or any(ord(c)<32 for c in provider_id):
        _fail('dialogue_message_identity_required')
    if type(text) is not str or len(text)>65536 or type(kind) is not str or len(kind)>32 or type(voice) is not bool:
        _fail('dialogue_message_invalid')
    return _hash({'route':route,'provider_id':provider_id}),_hash(dict(text=text,kind=kind,voice=voice))


async def record_interrupt(engine, *, route, provider_id, text, resolver,
                           policy=None, channel_policy=None, kind='text', voice=False):
    """Internal authority comes only from the supplied server policy object.

    Returns None for an unassigned route or a closed conversational greeting;
    this never authorizes advice, collection or legacy LLM fallthrough.
    """
    key,body_hash=_message(route,provider_id,text,kind,voice)
    if policy is not None and not isinstance(policy,DialoguePolicy):_fail('dialogue_policy_required')
    async def write(session):
        await stops._lock(session,route,writer=True)
        stop_rows,stop_size=await stops._registry(session)
        rows,total=await _registry(session,stop_rows)
        own=[r for r in rows if r.transport_key==_hash(route)]
        assignment=policy.assignment(route) if policy is not None else None
        if own:
            stored=DialoguePolicy(_plain(own[0].document)['authority']['policy'])
            original=stored.document['assignments'][0]
            if assignment is not None and assignment!=original:raise EntryStorageConflict('dialogue_assignment_changed')
            assignment=original
        if assignment is None:return None
        actor=Actor(manager_id=assignment['actor'],is_full_admin=True)
        channels.access(actor)
        if own:
            old=next((r for r in own if r.message_key==key),None)
            if old:
                if old.input_hash!=body_hash:raise EntryStorageConflict('dialogue_message_changed')
                return _result(old)
        case=await applications._case(session,assignment['case_id'],lock=True)
        person=await applications._applicant(session,case.id,assignment['applicant_id'])
        header,pinned=await interviews._header(session,case,person,assignment['interview_id'])
        events,state,_=await interviews._history(session,header,pinned)
        at=_now();on=applications._local_day(at).isoformat()
        if assignment['header_hash']!=header.snapshot_hash:raise EntryStorageConflict('dialogue_header_changed')
        if actor.manager_id not in header.authority['full_admins'] or actor.manager_id not in pinned.operators:
            raise PermissionDenied('dialogue_operator_denied')
        if applications._utc(events[-1].created_at)>applications._utc(at):_fail('dialogue_clock_reversed')
        consent_question=any(q['path']=='consent.given' for q in state['drafts'])
        t=triage_rules.triage(text,kind=kind,voice=voice,consent_question=consent_question)
        if own and (t.reason!='consent_withdrawn' or state['collection_blocked']):return _result(own[-1])
        if t.reason is None:return None
        if not own:
            if policy is None or not policy.document['valid_from']<=on<=policy.document['review_due_on']:
                raise PermissionDenied('dialogue_policy_expired')
            if (policy.document['interview_policy_hash']!=pinned.digest or channel_policy is None or
                policy.document['channel_policy_hash']!=channel_policy.digest):
                raise PermissionDenied('dialogue_policy_changed')
        target=dict(actor=actor,case_id=case.id,applicant_id=person.id,interview_id=header.id,
                    dialog_id=assignment['dialog_id'])
        # Existing permanent route identity and a stored delegation permit a later
        # withdrawal even after policy expiry/removal; no new collection is granted.
        if not own:
            _,_,_,identity,descriptor,_,at=await stops._context(session,**target,resolver=resolver,
                policy=channel_policy,lock=True)
            if descriptor!=route:raise EntryStorageConflict('dialogue_route_changed')
            on=applications._local_day(at).isoformat()
            if not policy.document['valid_from']<=on<=policy.document['review_due_on']:
                raise PermissionDenied('dialogue_policy_expired')
        before=events[-1];effect='existing_handoff_retained'
        if state['phase'] in ('active','paused') or t.reason=='consent_withdrawn' and not state['collection_blocked']:
            await interviews._record_action_in_session(session,actor=actor,case_id=case.id,applicant_id=person.id,
                interview_id=header.id,expected_revision=len(events),request_key='interrupt-'+key[:54],
                operation={'action':'interrupt','reason':t.reason},at=at)
            events,state,_=await interviews._history(session,header,pinned)
            effect='interrupt_appended'
        stop=next((r for r in stop_rows if r.transport_key==_hash(route)),None)
        if stop is not None and (stop.interview_id!=header.id or stop.dialog_id!=assignment['dialog_id']):
            raise EntryStorageConflict('dialogue_route_already_assigned')
        if stop is None:
            if len(stop_rows)>=stops.MAX_STOPS:_fail('channel_stop_registry_limit')
            preview=stops._preview_payload(header,events[-1],identity,route,channel_policy,on)
            command=stops._command(actor.manager_id,case.id,person.id,header.id,identity['id'],len(events),
                channel_policy.digest,_hash(preview))
            saved=await stops._save_stop_in_session(session,actor=actor,header=header,events=events,state=state,
                identity=identity,descriptor=route,policy=channel_policy,request_key='cause-'+key[:58],
                command=command,preview=preview,at=at,total=stop_size)
            stop_rows,_=await stops._registry(session)
            stop=next(r for r in stop_rows if r.id==saved['id'])
        if len(rows)>=MAX_CAUSES or not own and len({r.transport_key for r in rows})>=MAX_CAUSES//2:
            _fail('dialogue_cause_registry_limit')
        triage=asdict(t);triage['families']=list(triage['families']);triage['source_rows']=list(triage['source_rows'])
        authority=_plain(own[0].document)['authority'] if own else delegated_document(policy,assignment)
        row=EntryDialogueStopCause(transport_key=_hash(route),revision=len(own)+1,
            previous_id=own[-1].id if own else None,case_id=case.id,applicant_id=person.id,interview_id=header.id,
            stop_id=stop.id,event_id=events[-1].id,message_key=key,input_hash=body_hash,created_at=at,
            snapshot_hash='0'*64,document=dict(authority=authority,triage=triage,effect=effect,
                before_event_id=before.id,before_event_hash=before.snapshot_hash,event_hash=events[-1].snapshot_hash,
                stop_hash=stop.snapshot_hash,collection_blocked=state['collection_blocked'],
                previous_hash=own[-1].snapshot_hash if own else None))
        # Like retained journals, the database-generated ID is not hashed.
        row.snapshot_hash=_hash(_payload(row));session.add(row);await session.flush()
        await _registry(session,stop_rows)
        return _result(row)
    return await _transaction(engine,write)
