"""Immutable delegated internal planning with atomic links to existing quotations."""
from copy import deepcopy
import re

from sqlalchemy import select,cast,Text,func

from app.domain import entry_applications as apps,entry_quotes as quotes,specialist_evidence as evidence
from app.domain import specialist_facts as facts
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,_hash,_id,_key,_plain
from app.domain.entry_interview_policy import policy_from_document as interview_from_document,authorize as interview_authorize
from app.domain.entry_quote_policy import access,existing_full_admins,authorize as quote_authorize
from app.domain.knowledge_publication_rules import PublicationPolicy
from app.domain.specialist_policy import SpecialistPolicy,authorize,ALGORITHM
from app.domain.models import SpecialistDecisionEvent,EntryQuoteRevision,DomainError,_now
from app.domain.service_authz import PermissionDenied
from app.knowledge import quote_rules as rules,interview_rules
from app.knowledge.review import canonical

MAX_REVISIONS=64
MAX_EVENT_BYTES=1048576
MAX_BYTES=4*1048576
WITHDRAWAL_BYTES=8192
DISPOSITIONS={'manual_internal_plan','needs_evidence','declined'}
REASONS={'evidence_missing','outside_supported_scope','service_not_proceeding','correction_required'}


def fail(code='specialist_decision_integrity_failed'):raise EntryStorageInvalid(code)


async def _run(engine,operation):
    async def guarded(session):
        try:return await operation(session)
        except DomainError:raise
        except (rules.QuoteInvalid,interview_rules.InterviewInvalid,KeyError,TypeError,ValueError):
            raise EntryStorageInvalid('specialist_document_invalid') from None
    return await apps._run(engine,guarded)


def _revision(value):
    if type(value) is not int or not 0<=value<MAX_REVISIONS:fail('invalid_specialist_revision')


def _reason(value):
    rules.exact(value,('code','reference','proof','on'))
    if type(value['code']) is not str or value['code'] not in REASONS:fail('invalid_specialist_reason')
    rules.token(value['reference']);rules.proof(value['proof']);rules.day(value['on'])


def _operation(value):
    if type(value) is not dict:fail('invalid_specialist_operation')
    action=value.get('action')
    if action=='record':
        rules.exact(value,('action','application_id','capability_id','disposition','findings','reason',
            'expected_policy_hash','expected_context_hash'))
        if value['application_id'] is not None:_id(value['application_id'])
        if value['capability_id']!=facts.CAPABILITY or type(value['disposition']) is not str or value['disposition'] not in DISPOSITIONS:
            fail('unsupported_specialist_decision')
        rules.proof(value['expected_policy_hash']);rules.proof(value['expected_context_hash'])
        if value['disposition']=='manual_internal_plan':
            _id(value['application_id']);facts.validate_findings(value['findings'])
            if value['reason'] is not None:fail()
        else:
            if value['findings'] is not None:fail()
            _reason(value['reason'])
    elif action=='quote':
        rules.exact(value,('action','decision_id','decision_hash','preview','preview_hash'))
        _id(value['decision_id']);rules.proof(value['decision_hash']);rules.proof(value['preview_hash'])
        p=value['preview'];rules.exact(p,('decision_id','decision_hash','decision_revision','context_hash','quote'))
        _id(p['decision_id']);_id(p['decision_revision']);rules.proof(p['decision_hash']);rules.proof(p['context_hash'])
        q=p['quote'];rules.exact(q,('case_id','application_id','expected_revision','source_pin','policy_hash','parameters','calculator_version','result'))
        _id(q['case_id']);_id(q['application_id']);quotes._revision(q['expected_revision']);rules.proof(q['policy_hash'])
        quotes._request(q['parameters'])
        if p['decision_id']!=value['decision_id'] or p['decision_hash']!=value['decision_hash'] or _hash(p)!=value['preview_hash']:
            fail('specialist_quote_preview_invalid')
    elif action=='withdraw':
        rules.exact(value,('action','decision_id','decision_hash','reason','confirmed'))
        _id(value['decision_id']);rules.proof(value['decision_hash']);_reason(value['reason'])
        if value['confirmed'] is not True:fail('specialist_withdrawal_confirmation_required')
    else:fail('invalid_specialist_operation')
    return deepcopy(value)


def _command(actor,case_id,applicant_id,revision,operation):
    return dict(format=ALGORITHM,actor=actor,case_id=case_id,applicant_id=applicant_id,
        expected_revision=revision,operation=operation)


def _payload(row):
    names=('case_id','applicant_id','application_id','procedure','revision','previous_id','decision_id','quote_id',
        'action','request_key','request_hash','command','provenance','result','created_by')
    return {**{k:_plain(getattr(row,k)) for k in names},'created_at':apps._utc(row.created_at)}


def _receipt(row):return dict(id=row.id,snapshot_hash=row.snapshot_hash,**_payload(row))


def _capacity(count,size,total,action):
    if (count>MAX_REVISIONS or action!='withdraw' and count>=MAX_REVISIONS or size>MAX_EVENT_BYTES or
        total>MAX_BYTES-(0 if action=='withdraw' else WITHDRAWAL_BYTES) or
        action=='withdraw' and size>WITHDRAWAL_BYTES):fail('specialist_history_limit')


def _publication_policy(value):
    rules.exact(value,('reference','fingerprint','publishers'))
    if type(value['publishers']) is not list:fail()
    return PublicationPolicy(value['reference'],value['fingerprint'],tuple(value['publishers']))


def _basis(policy,interview_policy,publication_policy):
    if policy is None or interview_policy is None or publication_policy is None:
        raise PermissionDenied('specialist_authority_unavailable')
    return dict(policy=policy.document(),interview_policy=interview_policy.document(),
        publication_policy=dict(reference=publication_policy.reference,fingerprint=publication_policy.fingerprint,
            publishers=list(publication_policy.publishers)))


def _record_result(operation,observed,interview_policy,on):
    disposition=operation['disposition']
    if disposition=='manual_internal_plan':
        assessment=evidence.assess(observed,findings=operation['findings'],interview_policy=interview_policy,on=on)
        if assessment['reasons']:fail(assessment['reasons'][0])
    else:
        if operation['reason']['on']>on:fail('specialist_future_evidence')
        assessment=dict(format=facts.VERSION,reasons=sorted(set(observed['errors']+[operation['reason']['code']])),
            planned_days=None,alternatives=None,pending=list(facts.PENDING),source_eligibility='not_determined',
            permission_to_work=False,permission_to_stay=False)
    return dict(format=ALGORITHM,disposition=disposition,product='B' if disposition=='manual_internal_plan' else None,
        meaning='recorded_specialist_internal_plan',assessment=assessment,delivery='not_sent',
        contract='not_changed',payment='not_created')


def _quote_result(decision,quote):
    return dict(format=ALGORITHM,disposition='internal_quote_recorded',decision=dict(id=decision.id,hash=decision.snapshot_hash),
        quote=dict(id=quote.id,hash=quote.snapshot_hash,revision=quote.revision),arithmetic_complete=quote.result['complete'],
        meaning='internal_calculation_link',delivery='not_sent',contract='not_changed',payment='not_created')


def _active(rows):
    current=None
    for row in rows:
        if row.action=='record':current=row
        elif row.action=='withdraw':current=None
    return current


async def _history(session,case,person,observations):
    sizes=list((await session.execute(select(SpecialistDecisionEvent.id,
        func.length(cast(SpecialistDecisionEvent.command,Text))+func.length(cast(SpecialistDecisionEvent.provenance,Text))+
        func.length(cast(SpecialistDecisionEvent.result,Text))).where(SpecialistDecisionEvent.applicant_id==person.id)
        .order_by(SpecialistDecisionEvent.revision).limit(MAX_REVISIONS+1))).all())
    if len(sizes)>MAX_REVISIONS or any(n is None or n>2*MAX_EVENT_BYTES for _,n in sizes) or sum(n for _,n in sizes)>2*MAX_BYTES:
        fail('specialist_history_limit')
    rows=list((await session.scalars(select(SpecialistDecisionEvent).where(SpecialistDecisionEvent.applicant_id==person.id)
        .order_by(SpecialistDecisionEvent.revision).limit(MAX_REVISIONS+1))).all())
    previous=None;current=None;total=0;quote_cache={}
    for revision,row in enumerate(rows,1):
        command=_plain(row.command);rules.exact(command,('format','actor','case_id','applicant_id','expected_revision','operation'))
        operation=_operation(command['operation']);expected=_command(row.created_by,case.id,person.id,revision-1,operation)
        _key(row.request_key)
        if (type(row.created_by) is not str or not re.fullmatch('[a-z0-9_.-]{1,64}',row.created_by) or
            row.created_by in ('bot','system') or row.case_id!=case.id or row.revision!=revision or
            row.previous_id!=(previous.id if previous else None) or previous and row.id<=previous.id or
            row.action!=operation['action'] or canonical(command)!=canonical(expected) or row.request_hash!=_hash(expected) or
            row.snapshot_hash!=_hash(_payload(row)) or previous and apps._utc(row.created_at)<apps._utc(previous.created_at)):
            fail()
        provenance=_plain(row.provenance)
        keys=('format','previous','authority','basis','pins') if row.action=='record' else ('format','previous','authority','decision')
        rules.exact(provenance,keys);rules.exact(provenance['authority'],('full_admins',))
        admins=provenance['authority']['full_admins']
        if (type(admins) is not list or any(type(v) is not str for v in admins) or admins!=sorted(set(admins)) or
            row.created_by not in admins or provenance['format']!=ALGORITHM or
            provenance['previous']!=(dict(id=previous.id,hash=previous.snapshot_hash) if previous else None)):fail()
        on=apps._local_day(row.created_at).isoformat()
        if row.action=='record':
            rules.exact(provenance['basis'],('policy','interview_policy','publication_policy'))
            basis=provenance['basis'];policy=SpecialistPolicy(basis['policy']);ip=interview_from_document(basis['interview_policy'])
            pp=_publication_policy(basis['publication_policy']);doc=policy.document()
            if (row.decision_id is not None or row.quote_id is not None or row.application_id!=operation['application_id'] or
                row.procedure!=('visa' if row.application_id else None) or row.created_by not in doc['operators'] or
                row.created_by not in ip.operators or not doc['valid_from']<=on<=doc['review_due_on'] or
                not ip.valid_from<=on<=ip.review_due_on or policy.digest!=operation['expected_policy_hash']):fail()
            observed=await observations.observe(at=row.created_at,application_id=row.application_id,policy=policy,
                interview_policy=ip,publication_policy=pp,retained=provenance['pins'])
            if operation['expected_context_hash']!=observed['context_hash']:fail()
            result=_record_result(operation,observed,ip,on);current=row
        else:
            if (current is None or row.decision_id!=current.id or operation['decision_id']!=current.id or
                operation['decision_hash']!=current.snapshot_hash or
                provenance['decision']!=dict(id=current.id,hash=current.snapshot_hash) or row.application_id!=current.application_id or
                row.procedure!=current.procedure):fail()
            if row.action=='withdraw':
                if row.quote_id is not None or operation['reason']['on']>on:fail()
                result=dict(format=ALGORITHM,disposition='withdrawn',decision=provenance['decision'],delivery='not_sent')
                current=None
            else:
                if current.result['disposition']!='manual_internal_plan' or row.quote_id is None:fail()
                app,events,_=await observations.application(row.application_id)
                if app.id not in quote_cache:quote_cache[app.id]=(await quotes._history(session,app,person,events))[0]
                quote=next((q for q in quote_cache[app.id] if q.id==row.quote_id),None)
                if quote is None or apps._utc(quote.created_at)>apps._utc(row.created_at) or quote.created_by!=row.created_by:fail()
                p=operation['preview'];q=p['quote']
                if (p['decision_revision']!=current.revision or p['context_hash']!=_hash(current.provenance['pins']) or
                    q['expected_revision']!=quote.revision-1 or q['policy_hash']!=quote.command['policy_hash'] or
                    _hash(q)!=quote.command['preview_hash'] or q['parameters']!=quote.command['parameters'] or
                    q['source_pin']!=quote.source_pin or q['result']!=quote.result or
                    quote.request_key!='SP-'+_hash(command)[:61]):fail()
                policy=SpecialistPolicy(_plain(current.provenance)['basis']['policy'])
                original_ip=interview_from_document(_plain(current.provenance)['basis']['interview_policy'])
                if (row.created_by not in policy.document()['operators'] or row.created_by not in original_ip.operators or
                    apps._utc(quote.created_at)<apps._utc(current.created_at) or on!=current.provenance['pins']['on']):fail()
                original_pp=_publication_policy(_plain(current.provenance)['basis']['publication_policy'])
                observed=await observations.observe(at=row.created_at,application_id=current.application_id,policy=policy,
                    interview_policy=original_ip,publication_policy=original_pp,retained=_plain(current.provenance)['pins'])
                if evidence.assess(observed,findings=_plain(current.command)['operation']['findings'],
                    interview_policy=original_ip,on=on)['reasons']:fail()
                _recipe(policy,quotes.policy_from_document(_plain(quote.policy)),q['parameters'],current.result['assessment']['planned_days'])
                if apps._local_day(quote.created_at).isoformat()!=current.provenance['pins']['on']:fail()
                result=_quote_result(current,quote)
        if canonical(_plain(row.result))!=canonical(result):fail()
        size=len(canonical(_payload(row)).encode());total+=size;_capacity(revision,size,total,row.action);previous=row
    return rows,total


def _recipe(policy,quote_policy,parameters,days):
    cap=policy.capability(facts.CAPABILITY)
    if quote_policy.digest!=cap['quote_policy_hash']:raise EntryStorageConflict('specialist_quote_policy_changed')
    matches=[r for r in cap['recipes'] if r['id']==parameters['recipe_id']]
    if len(matches)!=1:fail('specialist_recipe_not_delegated')
    row=matches[0];recipe=quote_policy.recipe(row['id'])
    if (row['hash']!=_hash(recipe) or recipe['procedure']!='visa' or parameters['additional_blocks']!=0 or
        parameters['urgent']!=row['urgent'] or not row['minimum_days']<=days<=row['maximum_days']):
        fail('specialist_recipe_scope_mismatch')


async def _append(session,rows,total,*,case,person,actor,command,request_key,at,application_id,decision,quote,result,basis=None,pins=None):
    action=command['operation']['action'];previous=rows[-1] if rows else None
    if previous and apps._utc(previous.created_at)>apps._utc(at):fail('specialist_clock_moved_backwards')
    provenance=dict(format=ALGORITHM,previous=dict(id=previous.id,hash=previous.snapshot_hash) if previous else None,
        authority=dict(full_admins=sorted(existing_full_admins())))
    if action=='record':provenance.update(basis=basis,pins=pins)
    else:provenance['decision']=dict(id=decision.id,hash=decision.snapshot_hash)
    row=SpecialistDecisionEvent(case_id=case.id,applicant_id=person.id,application_id=application_id,
        procedure='visa' if application_id else None,revision=len(rows)+1,previous_id=previous.id if previous else None,
        decision_id=decision.id if decision else None,quote_id=quote.id if quote else None,action=action,
        request_key=request_key,request_hash=_hash(command),command=command,provenance=provenance,result=result,
        created_by=actor.manager_id,created_at=at)
    amount=len(canonical(_payload(row)).encode());_capacity(row.revision,amount,total+amount,action)
    row.snapshot_hash=_hash(_payload(row));session.add(row);await session.flush()
    return row


async def review_context(engine,*,actor,case_id,applicant_id,application_id,policy,interview_policy,publication_policy):
    access(actor);_id(case_id);_id(applicant_id)
    if application_id is not None:_id(application_id)
    async def read(session):
        case,person=await evidence.lock_subject(session,case_id,applicant_id,application_id)
        observation=evidence.Evidence(session,case,person);await observation.publication_lock();at=_now()
        authorize(actor,policy,on=apps._local_day(at),capability_id=facts.CAPABILITY)
        interview_authorize(actor,interview_policy,on=apps._local_day(at))
        rows,_=await _history(session,case,person,observation)
        current=await observation.observe(at=at,application_id=application_id,policy=policy,
            interview_policy=interview_policy,publication_policy=publication_policy)
        return dict(revision=len(rows),context=current,policy_hash=policy.digest)
    return await _run(engine,read)


async def record_decision(engine,*,actor,case_id,applicant_id,expected_revision,request_key,operation,
                          policy=None,interview_policy=None,publication_policy=None,quote_policy=None):
    access(actor);_id(case_id);_id(applicant_id);_revision(expected_revision);_key(request_key)
    try:operation=_operation(operation)
    except (rules.QuoteInvalid,KeyError,TypeError,ValueError):fail('specialist_document_invalid')
    command=_command(actor.manager_id,case_id,applicant_id,expected_revision,operation)
    async def write(session):
        application_id=operation.get('application_id')
        if operation['action']!='record':
            target=await session.scalar(select(SpecialistDecisionEvent).where(SpecialistDecisionEvent.id==operation['decision_id'],
                SpecialistDecisionEvent.case_id==case_id,SpecialistDecisionEvent.applicant_id==applicant_id))
            if target is None:fail('specialist_decision_unavailable')
            application_id=target.application_id
        case,person=await evidence.lock_subject(session,case_id,applicant_id,application_id)
        observation=evidence.Evidence(session,case,person)
        rows,total=await _history(session,case,person,observation)
        old=await session.scalar(select(SpecialistDecisionEvent).where(SpecialistDecisionEvent.case_id==case_id,
            SpecialistDecisionEvent.request_key==request_key))
        if old:
            if old.applicant_id!=applicant_id or old.request_hash!=_hash(command):raise EntryStorageConflict('specialist_request_conflict')
            return dict(receipt=_receipt(old),duplicate=True)
        if len(rows)!=expected_revision:raise EntryStorageConflict('specialist_revision_changed')
        current=_active(rows)
        if operation['action']=='withdraw':
            at=_now()
            if (current is None or current.id!=operation['decision_id'] or current.snapshot_hash!=operation['decision_hash']):
                raise EntryStorageConflict('specialist_decision_changed')
            if operation['reason']['on']>apps._local_day(at).isoformat():fail('specialist_future_evidence')
            result=dict(format=ALGORITHM,disposition='withdrawn',decision=dict(id=current.id,hash=current.snapshot_hash),delivery='not_sent')
            row=await _append(session,rows,total,case=case,person=person,actor=actor,command=command,request_key=request_key,
                at=at,application_id=application_id,decision=current,quote=None,result=result)
        else:
            await observation.publication_lock();at=_now();on=apps._local_day(at)
            authorize(actor,policy,on=on,capability_id=facts.CAPABILITY);interview_authorize(actor,interview_policy,on=on)
            observed=await observation.observe(at=at,application_id=application_id,policy=policy,
                interview_policy=interview_policy,publication_policy=publication_policy)
            if operation['action']=='record':
                if policy.digest!=operation['expected_policy_hash'] or observed['context_hash']!=operation['expected_context_hash']:
                    raise EntryStorageConflict('specialist_context_changed')
                result=_record_result(operation,observed,interview_policy,on.isoformat())
                row=await _append(session,rows,total,case=case,person=person,actor=actor,command=command,request_key=request_key,
                    at=at,application_id=application_id,decision=None,quote=None,result=result,
                    basis=_basis(policy,interview_policy,publication_policy),pins=observed['pins'])
            else:
                previewed=await _preview(session,observation,current,operation['decision_id'],operation['decision_hash'],
                    operation['preview']['quote']['parameters'],actor,policy,interview_policy,publication_policy,quote_policy,at,observed)
                if previewed!=operation['preview']:raise EntryStorageConflict('specialist_quote_preview_changed')
                q=previewed['quote'];key='SP-'+_hash(command)[:61]
                if await session.scalar(select(EntryQuoteRevision.id).where(EntryQuoteRevision.case_id==case_id,EntryQuoteRevision.request_key==key)):
                    raise EntryStorageConflict('specialist_quote_key_already_used')
                saved=await quotes._save_in_session(session,actor=actor,case_id=case_id,application_id=application_id,
                    parameters=q['parameters'],expected_revision=q['expected_revision'],request_key=key,
                    expected_policy_hash=q['policy_hash'],expected_preview_hash=_hash(q),calculator_version=q['calculator_version'],policy=quote_policy)
                quote=await session.get(EntryQuoteRevision,saved['receipt']['id']);at=_now()
                # The quote clock can cross midnight. Recheck fresh facts before
                # the enclosing commit; an invalid link rolls the quote back too.
                again=await observation.observe(at=at,application_id=application_id,policy=policy,
                    interview_policy=interview_policy,publication_policy=publication_policy)
                authorize(actor,policy,on=apps._local_day(at),capability_id=facts.CAPABILITY)
                if again['context_hash']!=previewed['context_hash'] or again['errors']:raise EntryStorageConflict('specialist_context_changed')
                row=await _append(session,rows,total,case=case,person=person,actor=actor,command=command,request_key=request_key,
                    at=at,application_id=application_id,decision=current,quote=quote,result=_quote_result(current,quote))
        return dict(receipt=_receipt(row),duplicate=False)
    return await _run(engine,write)


async def _preview(session,observation,current,decision_id,decision_hash,parameters,actor,policy,ip,pp,qp,at,observed=None):
    if current is None or current.id!=decision_id or current.snapshot_hash!=decision_hash or current.result['disposition']!='manual_internal_plan':
        raise EntryStorageConflict('specialist_decision_changed')
    on=apps._local_day(at);authorize(actor,policy,on=on,capability_id=facts.CAPABILITY)
    interview_authorize(actor,ip,on=on);quote_authorize(actor,qp,on=on)
    if _basis(policy,ip,pp)!=_plain(current.provenance)['basis']:raise EntryStorageConflict('specialist_authority_changed')
    observed=observed or await observation.observe(at=at,application_id=current.application_id,policy=policy,
        interview_policy=ip,publication_policy=pp)
    if observed['pins']!=_plain(current.provenance)['pins']:raise EntryStorageConflict('specialist_facts_changed')
    assessment=evidence.assess(observed,findings=_plain(current.command)['operation']['findings'],interview_policy=ip,on=on.isoformat())
    if assessment['reasons']:fail(assessment['reasons'][0])
    _recipe(policy,qp,parameters,assessment['planned_days'])
    app,events,successor=await observation.application(current.application_id);quotes._live_scope(events,successor)
    rows,_=await quotes._history(session,app,observation.person,events)
    value=quotes._preview_data(app,observation.person,events[-1],revision=len(rows),policy=qp,request=parameters,on=on.isoformat())
    return dict(decision_id=current.id,decision_hash=current.snapshot_hash,decision_revision=current.revision,
        context_hash=observed['context_hash'],quote=value)


async def preview_decision_quote(engine,*,actor,case_id,applicant_id,decision_id,decision_hash,parameters,
                                 policy,interview_policy,publication_policy,quote_policy):
    access(actor);_id(case_id);_id(applicant_id);_id(decision_id);parameters=quotes._request(parameters);rules.proof(decision_hash)
    async def read(session):
        target=await session.scalar(select(SpecialistDecisionEvent).where(SpecialistDecisionEvent.id==decision_id,
            SpecialistDecisionEvent.case_id==case_id,SpecialistDecisionEvent.applicant_id==applicant_id))
        if target is None:fail('specialist_decision_unavailable')
        case,person=await evidence.lock_subject(session,case_id,applicant_id,target.application_id)
        observation=evidence.Evidence(session,case,person);rows,_=await _history(session,case,person,observation)
        await observation.publication_lock();at=_now()
        previewed=await _preview(session,observation,_active(rows),decision_id,decision_hash,parameters,actor,
            policy,interview_policy,publication_policy,quote_policy,at)
        return dict(preview=previewed,preview_hash=_hash(previewed),revision=len(rows))
    return await _run(engine,read)


async def read_decisions(engine,*,actor,case_id,applicant_id,policy=None,interview_policy=None,publication_policy=None):
    access(actor);_id(case_id);_id(applicant_id)
    async def read(session):
        case,person=await evidence.lock_subject(session,case_id,applicant_id)
        observation=evidence.Evidence(session,case,person);rows,total=await _history(session,case,person,observation)
        current=_active(rows);reasons=['specialist_no_current_plan']
        if current is not None and current.result['disposition']=='manual_internal_plan':
            reasons=[]
            try:
                await observation.publication_lock();at=_now();on=apps._local_day(at)
                authorize(actor,policy,on=on,capability_id=facts.CAPABILITY);interview_authorize(actor,interview_policy,on=on)
                if _basis(policy,interview_policy,publication_policy)!=_plain(current.provenance)['basis']:
                    reasons.append('specialist_authority_changed')
                observed=await observation.observe(at=at,application_id=current.application_id,policy=policy,
                    interview_policy=interview_policy,publication_policy=publication_policy)
                if observed['pins']!=_plain(current.provenance)['pins']:reasons.append('specialist_facts_changed')
                reasons+=evidence.assess(observed,findings=_plain(current.command)['operation']['findings'],
                    interview_policy=interview_policy,on=on.isoformat())['reasons']
            except PermissionDenied:reasons.append('specialist_authority_unavailable')
        return dict(revision=len(rows),history=[_receipt(r) for r in reversed(rows)],
            current=dict(decision_id=current.id if current else None,usable_for_internal_quote=not reasons,
                reasons=sorted(set(reasons)),meaning='internal_planning_only',delivery='not_sent'),
            can_withdraw=current is not None and len(rows)<MAX_REVISIONS,
            can_record=len(rows)<MAX_REVISIONS-1 and total<MAX_BYTES-WITHDRAWAL_BYTES)
    return await _run(engine,read)
