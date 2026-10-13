"""Own process evidence for a manually chosen internal review, never a legal date."""
from sqlalchemy import select

from app.domain import entry_applications as apps, entry_anchors as anchors
from app.domain import entry_processes as processes, operator_sop_rules as rules
from app.domain import applicant_profiles as profiles, knowledge_publication as publication
from app.domain import conditional_deadline_sources as personal, conditional_deadline_evidence as retained
from app.domain import entry_interviews as interviews, specialist_interruptions as interruptions
from app.domain.entry_process_evidence import Sources, Evidence
from app.domain.entry_process_policy import authorize
from app.domain.entry_storage import _hash, _plain, EntryStorageInvalid
from app.domain.models import EntryProcessEvent, _now
from app.domain.operator_sop_policy import SopReviewAuthority
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.domain.specialist_evidence import publication_prefix
from app.knowledge.review import canonical


async def lock_admission(session):
    """Always before case locks; serializes cross-case quarantine observations."""
    from app.domain.entry_quarantine import lock_process_observation
    await lock_process_observation(session)


async def scope(session, case_id, applicant_id, application_id):
    case=await apps._case(session,case_id,lock=True)
    root=await apps._application(session,case_id,application_id,lock=True)
    if root.applicant_id!=applicant_id: rules.fail('operator_sop_subject_mismatch')
    context=Sources(session,case,root)
    last=await session.scalar(select(EntryProcessEvent).where(EntryProcessEvent.application_id==root.id)
        .order_by(EntryProcessEvent.revision.desc()).limit(1))
    await context.lock_apps([root.id,*(_plain(last.snapshot)['links'].values() if last else [])])
    person=await apps._applicant(session,case_id,applicant_id)
    return case,person,root,context


def finish(report,reason):
    report['reason']=reason
    report['evidence_hash']=_hash({k:v for k,v in report.items() if k not in ('checked_at','evidence_hash')})
    return report


async def source(session,authority,at,original=None,cache=None):
    cache={} if cache is None else cache
    context,full=await retained.cached(cache,'publication',lambda:publication._runtime_context(session))
    prefix=publication_prefix(full,original['publication_revision']) if original else full
    if not prefix['rows'] or prefix['active'] is None: rules.fail('operator_sop_publication_missing')
    if (apps._utc(prefix['rows'][-1].created_at)>apps._utc(at) or
            any(apps._utc(r.created_at)<apps._utc(at) for r in full['rows'][len(prefix['rows']):])):
        rules.fail('operator_sop_publication_time_invalid')
    version,bundle,projection=await context.source(prefix['active'])
    p=authority.policy.document
    if prefix['policies'][version.id]!=publication._policy(authority.publication):
        rules.fail('operator_sop_publication_policy_changed')
    value=dict(version_id=version.id,source_hash=version.source_hash,bundle_hash=version.bundle_hash,
        projection_hash=projection['projection_hash'],catalog_hash=projection['catalog_hash'],
        publication_revision=len(prefix['rows']),publication_hash=prefix['rows'][-1].snapshot_hash,
        manifest_hash=_hash(prefix['manifests'][version.id]),definition=rules.definition(p['rule_id']))
    if any(value[k]!=p[k] for k in ('source_hash','bundle_hash','projection_hash','catalog_hash')):
        rules.fail('operator_sop_source_changed')
    if original is not None and canonical(value)!=canonical(original): rules.fail('operator_sop_source_pin_invalid')
    return value


async def observe(context,person,rule_id,authority,at,original=None,cache=None):
    """Recompute the exact retained process prefix; current reads use current heads."""
    cache={} if cache is None else cache
    case,root,session=context.case,context.root,context.session
    rows,state,_=await retained.cached(cache,'process',lambda:processes._history(context))
    if not rows: rules.fail('operator_sop_process_required')
    head=retained.picked(rows,original['process'],at) if original else rows[-1]
    state=_plain(head.snapshot); rows=rows[:head.revision]
    spec=rules.definition(rule_id); key=rule_id.removeprefix(rules.PREFIX)
    if apps._utc(head.created_at)>apps._utc(at): rules.fail('operator_sop_future_process')
    if state['stopped'] or state['stage'] not in spec['stages']: rules.fail('operator_sop_stage_unavailable')
    if state['catalog_digest']!=authority.process.catalog_digest: rules.fail('operator_sop_process_catalog_changed')
    last_policy=next((processes._policy(r) for r in reversed(rows) if r.policy is not None),None)
    if last_policy is None or last_policy.digest!=authority.process.digest: rules.fail('operator_sop_process_policy_changed')
    e=Evidence(context,state,rows,authority.process,authority.package,at=at,
        historical=original is not None,observed=original['observed'] if original else None)
    role=state['active_role']; active=await e.app(role)
    if active is None: rules.fail('operator_sop_active_application_missing')
    events=await e.events(active); usable=await e.usable(active)
    successors=e.prefix(context.successors[active.id],f'successors:{active.id}')
    # Exceptions are source duties at the own successful terminal source stage.
    allowed_terminal=(key in rules.TERMINAL_DUTIES and
        ((state['stage']=='V25' and root.procedure=='visa' and active.id==root.id) or
         (state['stage']=='R08' and root.procedure=='registration' and active.id==root.id) or
         (state['stage']=='U09' and root.procedure=='violation_protocol' and role=='exit_visa' and state['branch']=='exit_visa')))
    if not usable and not (allowed_terminal and events[-1].status=='closed' and not successors):
        rules.fail('operator_sop_application_terminal')
    if state['stage'].startswith('V') and (root.procedure!='visa' or active.id!=root.id):
        rules.fail('operator_sop_root_scope')
    if state['stage'].startswith('W') and root.procedure!='unified_permit': rules.fail('operator_sop_root_scope')
    if key=='ENTRY_BAN_REVIEW' and (root.procedure!='violation_protocol' or role!='exit_visa' or state['branch']!='exit_visa'):
        rules.fail('operator_sop_root_scope')
    if original:
        profile=retained.picked((await retained.cached(cache,'profiles',lambda:profiles._history(session,case,person)))[0],original['profile'],at)
        retained.picked(await context.application_events(active),original['application_event'],at)
        interview_pin,stop_pins=original['interview'],original['interruptions']
        header=None; ievents=[]
        if interview_pin:
            header,ip=await retained.cached(cache,('interview',interview_pin['id']),lambda:interviews._header(session,case,person,interview_pin['id']))
            ievents,_,_=await retained.cached(cache,('interview_events',header.id),lambda:interviews._history(session,header,ip))
            if header.snapshot_hash!=interview_pin['hash']: rules.fail('operator_sop_interview_pin_invalid')
            ievents=ievents[:retained.picked(ievents,interview_pin['head'],at).revision] if interview_pin['head'] else []
        loaded=await retained.cached(cache,('interruptions',_hash(interview_pin)),lambda:interruptions.load(session,
            case_id=case.id,applicant_id=person.id,interview=header,events=ievents))
        if interruptions.observe(loaded,at=at,retained=stop_pins)['errors']: rules.fail('operator_sop_retained_stop_invalid')
    else:
        profile,event,interview_pin,stop_pins,_=await personal.personal_context(session,case,person,active,at)
    facts={}
    # Package consent is a separate own-document collection boundary. A closed
    # source stage never exempts an explicit withdrawal from this check.
    for own_role in state['used_roles']:
        own_app=await e.app(own_role)
        package_rows,package_states,_,_=await context.package_history(own_app)
        selected=e.prefix(package_rows,f'packages:{own_app.id}')
        if selected:
            index=next(i for i,r in enumerate(package_rows) if r.id==selected[-1].id)
            consent=package_states[index].get('consent')
            facts[own_role+'.collection_consent']=consent
            if consent and consent['status']!='granted': rules.fail('operator_sop_collection_blocked')
    for name,expected in state['retained'].items():
        own_role,fact=name.split('.',1)
        # A terminal follow-up checks recorded facts, not renewed filing authority.
        if not usable and allowed_terminal: continue
        facts[name]=await e.resolve(own_role,fact)
        if type(facts[name]['value']) is not type(expected) or facts[name]['value']!=expected:
            rules.fail('operator_sop_process_prerequisites_changed')
    # An already satisfied wait is stale even if the operator has not moved stage.
    completed={
        'LEAD_RESPONSE':'conversation_started',
        'QUALIFICATION_2H':'profile_complete','QUALIFICATION_24H':'profile_complete','QUALIFICATION_72H':'profile_complete',
        'QUOTE_PREPARATION':'quote_sent','QUOTE_24H':'offer_accepted','QUOTE_72H':'offer_accepted',
        'PAYMENT_24H':'service_payment_confirmed','PAYMENT_48H':'service_payment_confirmed','PAYMENT_URGENT':'service_payment_confirmed',
        'DOCUMENTS_D1':'documents_current','DOCUMENTS_D3':'documents_current','DOCUMENTS_D7':'documents_current','DOCUMENTS_D14':'documents_current',
        'INVITER_FOLLOWUP':'receiving_party_docs_accepted','DOCUMENT_CHECK':'documents_current',
        'READY_SUBMISSION_REVIEW':'submission_recorded','QUOTA_REVIEW':'submission_recorded',
        'VERIFICATION_24H':'email_verified','VERIFICATION_48H':'email_verified','VERIFICATION_EXPIRY':'email_verified',
        'DOWNLOAD_REVIEW':'issued_document_downloaded','ISSUED_CHECK':'issued_document_checked','RECEIPT_REVIEW':'receipt_confirmed',
        'ENTRY_EVE_REVIEW':'actual_entry_confirmed','ENTRY_CONFIRMATION_REVIEW':'actual_entry_confirmed'}
    if key in completed:
        fact=completed[key];value=await e.resolve(role,fact);facts[role+'.'+fact]=value
        if value['value'] is True: rules.fail('operator_sop_wait_satisfied')
    if key in ('APPLICATION_STATUS','RES_STATUS','CORRECTION_REVIEW','SPECIALIST_HANDOFF'):
        fact='eligibility' if key=='SPECIALIST_HANDOFF' else 'decision'
        value=await e.resolve(role,fact);facts[role+'.'+fact]=value
        if ((key=='SPECIALIST_HANDOFF' and value['value'] in ('eligible','ineligible')) or
                (key in ('APPLICATION_STATUS','RES_STATUS') and value['value']!='pending') or
                (key=='CORRECTION_REVIEW' and value['value']!='revision_requested')):
            rules.fail('operator_sop_wait_satisfied')
    if key in ('CONTRACT_REVIEW','WORK_COMMERCIAL_24H','WORK_COMMERCIAL_48H'):
        payments,contracts=await context.ledger(e.recorded['streams'] if e.historical else None)
        e.prefix(payments,'payments','recorded_at')
        contracts=e.prefix(contracts,'contracts','recorded_at')
        if key=='CONTRACT_REVIEW':
            if contracts: rules.fail('operator_sop_wait_satisfied')
        else:
            # The source combines quote/contract/payment in one W03-W04 row.
            # W03 already requires accepted quotation; payment alone does not
            # establish a signed contract or end this combined review.
            paid=await e.resolve(role,'service_payment_confirmed')
            facts[role+'.service_payment_confirmed']=paid
            facts[role+'.signed_contract_recorded']=bool(contracts)
            if contracts and paid['value'] is True: rules.fail('operator_sop_wait_satisfied')
    if key=='STUDENT_ANNUAL':
        package_rows,states,definitions,_=await context.package_history(active)
        selected=e.prefix(package_rows,f'packages:{active.id}')
        if not selected or _plain(profile.input_snapshot)['profile'].get('purpose')!='study':
            rules.fail('operator_sop_student_scope')
        index=next(i for i,r in enumerate(package_rows) if r.id==selected[-1].id)
        if states[index].get('product')!='S': rules.fail('operator_sop_student_scope')
    result=dict(process=anchors.pin(head),stage=state['stage'],active_role=role,
        active_application_id=active.id,active_procedure=active.procedure,
        profile=anchors.pin(profile),application_event=anchors.pin(events[-1]),
        interview=interview_pin,interruptions=stop_pins,observed=e.observed,facts=facts)
    if original and any(canonical(result[k])!=canonical(original[k]) for k in result): rules.fail('operator_sop_evidence_changed')
    return result,profile


async def evaluate(session,*,actor,case,person,application,rule_id,authority=None,at=None,context=None):
    if at is None and authority is not None: await publication._runtime_context(session)
    at=_now() if at is None else at
    report=dict(format=rules.FORMAT,case_id=case.id,applicant_id=person.id,application_id=application.id,
        rule_id=rule_id,checked_at=apps._utc(at),on=apps._local_day(at).isoformat(),status='unknown',
        source=None,evidence=None,scope='operator_selected_internal_review_only',operational_due_on=None,
        calculated=False,official=False,delivery='not_sent',filing_allowed=False,may_quote=False)
    rules.definition(rule_id)
    if authority is None: return finish(report,'operator_sop_authority_missing')
    if not isinstance(authority,SopReviewAuthority): rules.fail('operator_sop_authority_invalid')
    authority.validate();p=authority.policy.document
    if p['rule_id']!=rule_id or actor not in p['operators']: return finish(report,'operator_sop_operator_unavailable')
    if not p['valid_from']<=report['on']<=p['review_due_on']: return finish(report,'operator_sop_authority_expired')
    try:
        authorize(Actor(actor,True),authority.process,day=apps._local_day(at))
        report['source']=await source(session,authority,at)
        context=context or Sources(session,case,application)
        report['evidence'],profile=await observe(context,person,rule_id,authority,at)
        if profile.knowledge_version_id!=report['source']['version_id']: rules.fail('operator_sop_profile_source_changed')
        report['status']='available'
        return finish(report,'operator_selected_review_available')
    except PermissionDenied:
        return finish(report,'operator_sop_process_authority_unavailable')
    except EntryStorageInvalid as exc:
        if str(exc)=='process_policy_outdated':
            return finish(report,'operator_sop_process_authority_expired')
        if not str(exc).startswith(('operator_sop_','conditional_deadline_')): raise
        return finish(report,str(exc))
