"""Closed reconciliation for a recorded internal B plan, never legal clearance."""
from app.domain import assessment_interview,assessment_rules
from app.domain.entry_storage import _hash
from app.knowledge import interview_rules as interviews,specialist_catalog,quote_rules as rules
from app.knowledge.conditions import _evaluate

CAPABILITY='B_MEETING_ABROAD_SINGLE'
VERSION='kg-specialist-facts/1'
MAPPED=assessment_interview.MAPPED | frozenset('''purpose_detail event.from event.to
inviter.exists inviter.type inviter.name inviter.tax_id inviter.contact inviter.phone
inviter.email inviter.letter inviter.constituent_documents inviter.portal_account
company.exists company.planned'''.split())
PROFILE_MAP={**assessment_rules.PROFILE_MAP,'purpose_details':'mapped','event_dates':'mapped',
             'inviting_party':'mapped'}
PENDING=('document_package','passport_six_calendar_months_after_visa_end',
         'registration_requirements','processing_time','entry_point_permission')
ALLOWED_HANDOFF={'pinned_profile_requires_review','manual_review_requested','manager_requested',
                 'intake_complete','incomplete_answers'}


def field_map(document):
    return {f['path']:('mapped' if f['path'] in MAPPED else
        'nondecision' if f['path'] in assessment_interview.NONDECISION else 'unsupported') for f in document['fields']}


def validate_findings(value):
    rules.exact(value,('reviewed_on','meeting_nonprofit','local_work','host_legal_entity_in_kg',
        'host_identity_hash','purpose_detail_hash','evidence'))
    rules.day(value['reviewed_on']);rules.proof(value['host_identity_hash']);rules.proof(value['purpose_detail_hash'])
    for key in ('meeting_nonprofit','local_work','host_legal_entity_in_kg'):
        if type(value[key]) is not bool:rules.fail('invalid_specialist_finding')
    evidence=value['evidence']
    if type(evidence) is not list or len(evidence)!=4:rules.fail('specialist_evidence_required')
    if [v.get('fact') for v in evidence if type(v) is dict]!=['alternatives','host','nonemployment','purpose']:
        rules.fail('specialist_evidence_required')
    for row in evidence:
        rules.exact(row,('fact','reference','proof','on'));rules.token(row['reference']);rules.proof(row['proof'])
        if rules.day(row['on'])>rules.day(value['reviewed_on']):rules.fail('specialist_future_evidence')
    return value


def source_scope(bundle,condition_catalog,pins):
    """Compare all eighteen applicability shapes, not just the chosen fee/rule."""
    definition=specialist_catalog.capability(CAPABILITY)
    expected={r['unit_id']:r for r in definition['regime_applicability']}
    actual={u['unit_id']:u for u in bundle['units'] if u['kind'] in
            ('visa_free_regime','visa_required_regime','special_regime')}
    if set(actual)!=set(expected) or {p['unit_id'] for p in pins}!=set(expected):
        return 'specialist_regime_census_changed'
    if any(p['unit_hash']!=_hash(actual[p['unit_id']]) for p in pins):return 'specialist_regime_hash_changed'
    conditional={r['unit_id']:r for r in (condition_catalog or {}).get('rules',[])}
    wanted={k for k,v in expected.items() if 'condition' in v['applicability']}
    if set(conditional)!=wanted:return 'specialist_condition_census_changed'
    for uid,unit in actual.items():
        shape=expected[uid]['applicability']
        if unit['kind']!=expected[uid]['kind']:return 'specialist_regime_kind_changed'
        if 'condition' in shape:
            # All six indexed conditional outcomes were blocked in this source.
            # A later typed country/document outcome is a new interpretation,
            # even if someone retained the old condition catalogue beside it.
            if unit['value'] is not None or conditional[uid]!=shape['condition']:
                return 'specialist_condition_changed'
        elif 'general' in shape:
            if unit['value']!=shape['general']:return 'specialist_general_procedure_changed'
        elif 'countries' in shape:
            countries=(unit['value'] or {}).get('countries')
            if type(countries) is not list or sorted(countries)!=shape['countries']:
                return 'specialist_country_partition_changed'
        elif (unit.get('blocked_value') or {}).get('country_iso3')!=shape['country'] or unit['value'] is not None:
            return 'specialist_country_partition_changed'
    return None


def reconcile(request,state,history,*,catalog,interview_policy,findings,on):
    """Current answers may be explicitly reconciled after the immutable ACK.

    The journal adapter verifies original header/ACK and all current heads. The
    typed findings attest this reconciliation; old handoff answers aren't edited.
    """
    result=dict(format=VERSION,reasons=[],planned_days=None,alternatives=None,pending=list(PENDING),
        source_eligibility='not_determined',permission_to_work=False,permission_to_stay=False)
    def stop(reason):return {**result,'reasons':[reason]}
    validate_findings(findings)
    if findings['reviewed_on']!=on:return stop('specialist_review_needs_current_confirmation')
    fresh=interviews.analyze(state['answers'],on=on,language=state['language'],
        pre_consent=interview_policy.pre_consent,catalog_document=catalog)
    if state['collection_blocked'] or state['consent_withdrawal'] or not fresh['consent_complete']:
        return stop('specialist_consent_required')
    if state['phase']!='acked' or not state['ack'] or not state['handoff']:
        return stop('specialist_ack_required')
    if state['ack']['card_hash']!=state['handoff']['hash'] or state['handoff']['hash']!=_hash(state['handoff']['card']):
        return stop('specialist_ack_changed')
    if not set(state['handoff']['card']['reasons'])<=ALLOWED_HANDOFF:
        return stop('specialist_handoff_outside_scope')
    if fresh['stops'] or fresh['conflicts']:return stop('specialist_risk_outside_scope')
    if fresh['gaps'] or fresh['stale']:return stop('specialist_interview_incomplete_or_stale')
    a=interviews.Answers(state['answers'],catalog_document=catalog)
    for path,f in a.fields.items():
        if a.applicability(f) is not False and field_map(catalog)[interviews.template_path(path)]=='unsupported':
            return stop('specialist_interview_branch_unsupported')
    p=request['profile']
    if request['format']!='kg-qualification-review-input/2' or request['as_of']!=on:
        return stop('specialist_profile_needs_current_confirmation')
    for key,value in p.items():
        kind=PROFILE_MAP.get(key)
        if kind is None or kind=='unsupported_if_present' and value not in (None,'not_applicable','',{}):
            return stop('specialist_profile_branch_unsupported')
        if key=='violations' and (set(value)-set(kind) or value.get('ban_until') not in (None,'not_applicable','')):
            return stop('specialist_profile_branch_unsupported')
    required=dict(citizenship=['IND'],entry_passport_country='IND',document_type='ordinary',
        current_location='abroad',purpose='business_meeting',client_type='b2c',applicants_count=1,
        family=[],multiple_entries_needed=False,requested_process='visa',previous_refusals_kg=False,
        passport_pages_ok=True)
    if any(p.get(k)!=v or type(p.get(k)) is not type(v) for k,v in required.items()):
        return stop('specialist_profile_outside_scope')
    if any(p.get('violations',{}).get(k) is not False for k in ('overstay','fines','deportation_or_ban')) or any(
        p.get('escalation',{}).get(k) is not False for k in ('complaint','refund_question','legal_question','conflicting_answers')):
        return stop('specialist_profile_risk_outside_scope')
    if p.get('urgency_deadline') not in (None,'not_applicable',''):
        return stop('specialist_urgency_outside_scope')
    start=p.get('entry_date');end=p.get('exit_date')
    if not start or not end or not on<start<=end:return stop('specialist_plan_not_future')
    days=(rules.day(end)-rules.day(start)).days+1;result['planned_days']=days
    if not 1<=days<=specialist_catalog.capability(CAPABILITY)['maximum_planned_days']:
        return stop('specialist_plan_outside_scope')
    if not p.get('passport_expiry') or p['passport_expiry']<end:return stop('specialist_passport_expires_before_trip')
    expected={'citizenships':p['citizenship'],'document_type':p['document_type'],'passport_expiry':p['passport_expiry'],
        'location':p['current_location'],'purpose':p['purpose'],'purpose_detail':p.get('purpose_details'),
        'entry_on':start,'exit_on':end,'multiple_entries':False,'tickets_bought':p.get('tickets_bought'),
        'planned_entry_point':p.get('entry_point'),'previous_refusal':False,'risk.overstay':False,'risk.fines':False,
        'risk.deportation':False,'risk.entry_ban':False,'party_type':'individual','applicants_count':1,'family_count':0,
        'passport_two_blank_pages':True,'passport_undamaged':True,'company.exists':False,'company.planned':False,
        'foreign_residence.exists':False,'long_visa.exists':False,'residence_country':'IND',
        'hard_deadline.exists':False,'inviter.exists':True,'inviter.type':'company'}
    if any(a.get(k)!=v or type(a.get(k)) is not type(v) for k,v in expected.items()):
        return stop('specialist_interview_profile_conflict_or_scope')
    if type(a.get('applicant.age')) is not int or a.get('applicant.age')<18 or a.get('current_country') in (None,'unknown','not_applicable','KGZ'):
        return stop('specialist_applicant_scope_unknown')
    dates=p.get('event_dates',{})
    if (set(dates)!={'from','to'} or dates!={'from':a.get('event.from'),'to':a.get('event.to')} or
        not dates['from'] or not dates['to'] or not start<=dates['from']<=dates['to']<=end):
        return stop('specialist_meeting_dates_conflict')
    inviter=p.get('inviting_party',{})
    if (set(inviter)-{'exists','type','can_issue_letter','has_portal_cabinet'} or inviter.get('exists') is not True or
        inviter.get('type')!='company' or inviter.get('can_issue_letter') is not True or
        inviter.get('has_portal_cabinet')!=a.get('inviter.portal_account') or
        type(inviter.get('has_portal_cabinet')) is not bool):return stop('specialist_host_profile_conflict')
    if any(type(a.get(k)) is not bool for k in ('inviter.letter','inviter.constituent_documents','inviter.portal_account')):
        return stop('specialist_host_documents_unknown')
    identity={k:a.get(k) for k in ('inviter.name','inviter.tax_id','inviter.contact','inviter.phone','inviter.email')}
    if any(v in (None,'unknown','not_applicable') for v in identity.values()):return stop('specialist_host_identity_missing')
    if (findings['host_identity_hash']!=_hash(identity) or findings['purpose_detail_hash']!=_hash(p['purpose_details']) or
        findings['meeting_nonprofit'] is not True or findings['local_work'] is not False or
        findings['host_legal_entity_in_kg'] is not True):return stop('specialist_findings_conflict')
    if history['status']!='recorded_inputs' or history['document']['intervals'] or a.get('previous_visits') is not False:
        return stop('specialist_personal_history_outside_scope')
    # The first capability has no prior visits. Expanded history requires a new
    # supported mapping; neither the payer nor a planned entry proves past travel.
    facts=request.get('condition_facts',{})
    if set(facts)-{'schema_version','residence_documents','foreign_visas'}:
        return stop('specialist_additional_conditions_unsupported')
    residence=facts.get('residence_documents')
    if residence is not None and (residence.get('complete') is not True or any(
        item!={'country':'IND','kind':'other','permanent':True} for item in residence['items'])):
        return stop('specialist_residence_facts_conflict')
    if 'foreign_visas' in facts:
        status,_=_evaluate(dict(type='foreign_visa',issuers=['USA','GBR','SCHENGEN'],validity_years_gt=3),facts)
        if status!='not_met':return stop('specialist_long_visa_facts_conflict')
    # A negative >3-year answer is not represented as "no foreign visas".
    result['alternatives']=dict(foreign_residence='explicit_negative',qualifying_long_visa='explicit_negative',
        ordinary_individual='confirmed',selected_procedure='general',excluded_outcomes='not_approved')
    result['pending']+=['invitation_letter'] if not a.get('inviter.letter') else []
    result['pending']+=['host_constituent_documents'] if not a.get('inviter.constituent_documents') else []
    return result
