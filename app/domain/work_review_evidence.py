"""Historical checks use retained immutable heads, never today's active grant."""
from datetime import datetime,date

from sqlalchemy import select

from app.domain import entry_applications as apps,applicant_profiles as profiles,applicant_stay_history as stays
from app.domain import entry_interviews as interviews,knowledge_publication as publication,assessment_rules
from app.domain import current_stay_stops as current,work_deadlines
from app.domain import knowledge_decisions as decisions
from app.domain.knowledge_publication_rules import unavailable_reasons
from app.domain.current_stay_policy import STOPS
from app.domain.entry_storage import EntryStorageInvalid,_hash,_plain,_id
from app.domain.models import EntryInterview
from app.domain.specialist_evidence import publication_prefix
from app.knowledge import interview_rules
from app.knowledge.current_stay_checks import working_margin,observed_headroom
from app.knowledge.stay_days import StayDayReview,COUNT_RULE_IDS


def fail():raise EntryStorageInvalid('work_review_evidence_integrity_failed')


def head(rows,identifier,digest,at):
    found=next((r for r in rows if r.id==identifier),None)
    if found is None or found.snapshot_hash!=digest or apps._utc(found.created_at)>apps._utc(at):fail()
    # Later writes may share clock resolution with this observation. Their
    # immutable revision pins preserve the serial order selected under lock.
    if any(r.revision>found.revision and apps._utc(r.created_at)<apps._utc(at) for r in rows):fail()
    return found


async def verify_report(session,case,person,application,row,report,authority,app_pin):
    try:
        await _verify(session,case,person,application,row,report,authority,app_pin)
    except (KeyError,TypeError,ValueError,IndexError,AttributeError):fail()


async def _verify(session,case,person,application,row,r,a,app_pin):
    c=r['current_stay'];fact=a.fact.document;policy=a.current.document
    for value in (r['case_id'],r['applicant_id'],c['case_id'],c['applicant_id'],c['source']['version_id'],
                  c['source']['publication_revision'],c['profile']['id'],c['profile']['revision'],app_pin['id'],app_pin['revision']):_id(value)
    if type(r['within_filing_deadline']) is not bool or type(c['requires_specialist']) is not bool:fail()
    at=datetime.fromisoformat(c['checked_at']);on=apps._local_day(at).isoformat()
    if (at.tzinfo is None or apps._utc(at)>apps._utc(row.created_at) or c['as_of']!=on or
        c['case_id']!=case.id or c['applicant_id']!=person.id or c['scope']!='current_stay_stops_only' or
        c['evidence_hash']!=_hash({k:v for k,v in c.items() if k!='evidence_hash'}) or
        r['status']!='calculated' or r['reason']!='conditional_filing_deadline_only' or
        r['scope']!='conditional_ep_filing_date_only' or r['rule_id']!=work_deadlines.RULE or
        r['eligibility_evaluated'] is not False or r['requires_specialist'] is not True or r['delivery']!='not_sent' or
        c['entry_eligibility_evaluated'] is not False or c['permission_to_remain'] is not None or
        c['may_quote'] is not False or c['delivery']!='not_sent' or
        c['authority']!=dict(hash=a.current.digest,reference=policy['reference']) or
        c['fact']!=dict(hash=a.fact.digest,reference=fact['reference'],actor=fact['actor'],provenance='explicit_server_attestation_not_government_verification') or
        fact['case_id']!=case.id or fact['applicant_id']!=person.id or fact['actor']!=row.created_by or fact['as_of']!=on or
        any(not p['valid_from']<=on<=p['review_due_on'] for p in (a.review.document,a.work.document(),policy,fact,a.qualification.document)) or
        row.created_by not in a.work.operators or row.created_by not in a.review.document['operators']):fail()
    events=await apps._events(session,application)
    event=head(events,app_pin['id'],app_pin['hash'],at)
    if app_pin!=dict(id=event.id,revision=event.revision,hash=event.snapshot_hash) or event.status in ('approved','refused','closed'):fail()
    prows,_,_=await profiles._history(session,case,person)
    profile=head(prows,fact['profile_id'],fact['profile_hash'],at);request=_plain(profile.input_snapshot);p=request['profile']
    if c['profile']!=dict(id=profile.id,revision=profile.revision,snapshot_hash=profile.snapshot_hash) or request['as_of']!=on:fail()
    if (p.get('citizenship')!=['UZB'] or p.get('entry_passport_country')!='UZB' or p.get('document_type')!='ordinary' or
        p.get('purpose')!='work_hire' or p.get('current_location')!='in_kg' or fact['location']!='in_kg' or
        p.get('current_basis_in_kg')!='visa_free' or fact['current_basis']!='visa_free' or
        p.get('in_kg_since')!=fact['entered_on'] or p.get('current_basis_until')!=fact['lawful_until']):fail()
    hrows,_,_=await stays._history(session,case,person)
    h=head(hrows,fact['history']['id'],fact['history']['snapshot_hash'],at)
    history=stays._evidence(hrows[:h.revision],prows[:profile.revision],at)
    if (history['status']!='recorded_inputs' or history['passport_ref']!=fact['passport_ref'] or
        c['history']!={k:history[k] for k in ('status','history_id','profile_id','snapshot_hash','findings')}):fail()
    intervals=history['document']['intervals'];opened=[v for v in intervals if v['exit_date'] is None]
    if (len(opened)!=1 or opened[0]['entry_date']!=fact['entered_on'] or
        any(v['basis']!='visa_free' or v['passport_country']!='UZB' for v in intervals)):fail()
    ordered=sorted(intervals,key=lambda v:v['entry_date'])
    if any(b['entry_date']<=(v['exit_date'] or on) for v,b in zip(ordered,ordered[1:])):fail()
    ids=list((await session.scalars(select(EntryInterview.id).where(EntryInterview.case_id==case.id,
        EntryInterview.applicant_id==person.id))).all())
    historical=[]
    for identifier in ids:
        header,ip=await interviews._header(session,case,person,identifier)
        if apps._utc(header.created_at)<apps._utc(at) or fact['interview'] is not None and header.id==fact['interview']['id']:
            historical.append((header,ip))
    if len(historical)>1 or bool(historical)!=(fact['interview'] is not None) or c['interview']!=fact['interview']:fail()
    if historical:
        header,ip=historical[0];rows,_,_=await interviews._history(session,header,ip)
        selected=next((v for v in rows if v.snapshot_hash==fact['interview']['head_hash']),None)
        if selected is None:fail()
        selected=head(rows,selected.id,selected.snapshot_hash,at);state=_plain(selected.snapshot)
        if (fact['interview']!=dict(id=header.id,header_hash=header.snapshot_hash,head_hash=selected.snapshot_hash) or
            header.profile_id!=profile.id or state['collection_blocked'] or state['answers'].get('purpose',{}).get('value')!='work_hire'):fail()
        answers=interview_rules.Answers(state['answers'],catalog_document=_plain(header.catalog))
        expected=dict(location='in_kg',current_basis='visa_free',current_until=fact['lawful_until'],citizenships=['UZB'],
            residence_country=fact['conditions']['residence_country']['value'],document_type='ordinary',passport_country='UZB')
        expected['actual_entry.on']=fact['entered_on']
        if any(k in state['answers'] and answers.get(k)!=v for k,v in expected.items()):fail()
        if any(k in state['answers'] for k in ('history_count','reported_window','reported_days')) or any(k.startswith('history.') for k in state['answers']):fail()
        if 'previous_visits' in state['answers'] and (answers.get('previous_visits') is not False or len(intervals)!=1):fail()
        for key,field in (('foreign_residence.exists','other_residence_absent'),('long_visa.exists','foreign_visa_absent'),('organized_group.exists','organized_group_absent')):
            if key in state['answers'] and (answers.get(key) is not False or fact['conditions'][field]['value'] is not True):fail()
    context,all_publications=await publication._runtime_context(session)
    source=c['source'];pub=publication_prefix(all_publications,source['publication_revision'])
    if (not pub['rows'] or apps._utc(pub['rows'][-1].created_at)>apps._utc(at) or pub['active']!=source['version_id'] or
        any(apps._utc(v.created_at)<apps._utc(at) for v in all_publications['rows'][source['publication_revision']:]) or
        pub['policies'][pub['active']]!=publication._policy(a.publication)):fail()
    version,bundle,projection=await context.source(pub['active']);units={v['unit_id']:v for v in bundle['units']}
    expected_source=dict(version_id=version.id,source_hash=version.source_hash,bundle_hash=version.bundle_hash,
        projection_hash=projection['projection_hash'],catalog_hash=projection['catalog_hash'],
        manifest_hash=_hash(pub['manifests'][version.id]),publication_revision=len(pub['rows']))
    if (source!=expected_source or profile.knowledge_version_id!=version.id or
        any(policy[k]!=source[k] or a.qualification.document[k]!=source[k] for k in ('source_hash','bundle_hash','projection_hash','catalog_hash')) or
        any(u['unit_hash']!=_hash(units[u['unit_id']]) for u in policy['parameters'])):fail()
    clause=units[work_deadlines.RULE]
    if r['source']!=dict(**source,rule_hash=a.work.rule_hash,source_value=clause['value'],
        interpretation='separately_delegated_original_clause',section=clause['section'],page=clause['page']):fail()
    if assessment_rules.validate_regimes(policy,a.qualification.document,bundle,projection['payload']['catalog']):fail()
    facts=current._conditions(fact,p)
    if any(k not in facts or v!=facts[k] for k,v in request.get('condition_facts',{}).items()):fail()
    outcomes=assessment_rules.applicability(policy,facts)
    if c['applicability']!=outcomes or any(v['status']=='unknown' or v['status']=='met' and v['disposition']=='manual' for v in outcomes.values()):fail()
    matches=[k for k,v in outcomes.items() if v['status']=='met']
    if len(matches)!=1:fail()
    uid=matches[0];counting=policy['counting']
    required=set(STOPS)|set(COUNT_RULE_IDS)|{k for k,v in outcomes.items() if v['disposition']=='executable'}
    manifest_units={v['unit_id']:v for v in pub['manifests'][version.id]['units']}
    for identifier in required:
        entry=manifest_units.get(identifier)
        if entry is None:fail()
        reviews=await context.reviews(version.id,units[identifier])
        selected=next((v for v in reviews if v.id==entry['decision_id']),None)
        if (selected is None or selected.snapshot_hash!=entry['decision_hash'] or
            apps._utc(selected.created_at)>apps._utc(at) or
            any(v.revision>selected.revision and apps._utc(v.created_at)<apps._utc(at) for v in reviews) or
            unavailable_reasons(units[identifier],decisions._view(selected),day=apps._local_day(at),now=publication._utc(at))):fail()
    expected_count=dict(zip(COUNT_RULE_IDS,(counting['count_entry_day'],counting['count_exit_day'],[counting['window_anchor']])))
    if any(units[k]['value'] is None or type(units[k]['value'].get('value')) is not type(v) or units[k]['value']['value']!=v for k,v in expected_count.items()):fail()
    inputs=dict(schema_version='kg-stay-review-input/1',rule_unit_id=uid,as_of=on,history_complete=True,
        history=[dict(id=v['ref'],entry_date=v['entry_date'],exit_date=v['exit_date'],basis=v['basis'],passport_country=v['passport_country'],passport_continuity='same',confirmed=True) for v in intervals],
        trip=dict(mode='continue_open',start_date=on,end_date=on,passport_country='UZB',basis='visa_free'),
        policy={'status':'proposed',**{k:counting[k] for k in ('count_entry_day','count_exit_day','window_anchor','timezone')}})
    arithmetic=StayDayReview(**bundle,source_hash=version.source_hash).evaluate(inputs)
    calendar=policy['calendar'];until=date.fromisoformat(fact['lawful_until']);today=date.fromisoformat(on)
    margin=(dict(status='not_triggered',applicability='expired_instead') if until<today else working_margin(
        today=today,until=until,calendars=a.calendars,include_today=calendar['include_today'],include_until=calendar['include_until']))
    checks=dict(expired_stay=dict(status='triggered' if until<today else 'not_triggered',applicability='applicable',lawful_until=until.isoformat()),
        working_day_margin=margin,visa_free_headroom={**observed_headroom(arithmetic),'rule_unit_id':uid})
    expected_calendar=None if until<today else dict(hash=a.calendars.content_hash,reference=calendar['reference'],
        include_today=calendar['include_today'],include_until=calendar['include_until'],status='separately_authorized_draft_data')
    from app.knowledge.review import canonical
    if canonical(c['calendar'])!=canonical(expected_calendar):fail()
    if (c['arithmetic']!=arithmetic or c['checks']!=checks or c['requires_specialist']!=any(v['status']!='not_triggered' for v in checks.values()) or
        r['within_filing_deadline']!=(on<=r['due_on'] if a.work.boundary_inclusive else on<r['due_on']) or
        r['calendar']!=dict(hash=a.calendars.content_hash,reference=a.work.calendar_reference) or
        a.calendars.content_hash!=calendar['hash'] or any(v['completeness']!='complete' for v in a.calendars.describe()) or
        not calendar['valid_from']<=on<=calendar['review_due_on'] or not a.work.calendar_valid_from<=on<=a.work.calendar_review_due_on or
        any(not calendar['valid_from']<=d['date']<=calendar['review_due_on'] for d in margin.get('days',[])) or
        any(not a.work.calendar_valid_from<=d['date']<=a.work.calendar_review_due_on for d in r['calculation']['calendar_trace'])):fail()
