"""Current personal regime assessment, composed under one locked transaction.

No saved result, client admission guarantee, payer history, quote or delivery.
Historical route, arithmetic and interview receipts keep their original meaning.
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.domain import applicant_profiles as profiles, applicant_stay_history as stays
from app.domain import entry_applications as transactions, entry_interviews as interviews
from app.domain import knowledge_publication as publication
from app.domain import assessment_interview, assessment_rules
from app.domain.assessment_policy import AssessmentPolicy, ALGORITHM_VERSION, REG_RULE_ID, STOP_ID
from app.domain.entry_interview_policy import InterviewPolicy, authorize as authorize_interview
from app.domain.entry_storage import EntryStorageInvalid, _authorize, _hash, _id, _plain
from app.domain.models import EntryInterview, _now
from app.domain.qualification_policy import QualificationPolicy
from app.domain.service_authz import PermissionDenied
from app.knowledge.qualification import QualificationError, QualificationReview
from app.knowledge.stay_days import StayDayReview, StayReviewError

KG = ZoneInfo('Asia/Bishkek')


async def assess(engine, *, actor, case_id, applicant_id, assessment_policy=None,
                 qualification_policy=None, interview_policy=None, publication_policy=None):
    _authorize(actor); _id(case_id); _id(applicant_id)
    for value, expected in ((assessment_policy, AssessmentPolicy), (qualification_policy, QualificationPolicy),
                            (interview_policy, InterviewPolicy)):
        if value is not None and not isinstance(value, expected):
            raise EntryStorageInvalid('invalid_assessment_authority')

    async def read(session):
        await transactions._case(session, case_id, lock=True)
        case, person = await profiles._subject(session, case_id, applicant_id)
        context, publication_history = await publication._runtime_context(session)
        now = _now(); today = transactions._local_day(now); on = today.isoformat()
        result = dict(format=ALGORITHM_VERSION, case_id=case_id, applicant_id=applicant_id,
            checked_at=transactions._utc(now), language='ru', status='specialist_review', reasons=[],
            selected_regime=None, selected_product=None, visa_required=None, requires_specialist=True,
            entry_eligibility_evaluated=False, may_quote=False, delivery='not_sent',
            exact_deadline=None, exact_remaining_days=None, source=None, profile=None, history=None,
            interview=None, authority=None, candidate=None, registration=None, arithmetic=None,
            duration=None, stop_reasons=[], missing_facts=[], next_questions=[])
        def stop(reason):
            result['reasons'] = [reason]
            return result
        rows, _, _ = await profiles._history(session, case, person)
        if not rows:
            return stop('individual_profile_missing')
        row = rows[-1]; request = _plain(row.input_snapshot); p = request['profile']
        result.update(language=request['language'], profile=dict(id=row.id, revision=row.revision, snapshot_hash=row.snapshot_hash))
        if publication._utc(row.created_at) > publication._utc(now) or request['as_of'] != on:
            return stop('individual_profile_needs_current_confirmation')
        active = publication_history['active']
        if active is None:
            return stop('no_active_publication')
        version, bundle, projection = await context.source(active)
        manifest = publication_history['manifests'][active]
        result['source'] = dict(version_id=active, version_label=bundle['meta']['version_label'],
            source_hash=version.source_hash, bundle_hash=version.bundle_hash,
            projection_hash=projection['projection_hash'], catalog_hash=projection['catalog_hash'],
            manifest_hash=_hash(manifest), publication_revision=len(publication_history['rows']))
        if row.knowledge_version_id != active:
            return stop('individual_profile_source_changed')
        if assessment_policy is None or qualification_policy is None:
            return stop('assessment_authority_missing')
        authority = assessment_policy.document; qualification = qualification_policy.document
        result['authority'] = dict(assessment_hash=assessment_policy.digest, qualification_hash=qualification_policy.digest,
            reference=authority['reference'], counting_interpretation='separately_approved_interpretation',
            valid_from=authority['valid_from'], review_due_on=authority['review_due_on'])
        if authority['qualification_policy_hash'] != qualification_policy.digest or any(
                doc[k] != result['source'][k] for doc in (authority, qualification)
                for k in ('source_hash', 'bundle_hash', 'projection_hash', 'catalog_hash')):
            return stop('assessment_authority_source_changed')
        catalog = projection['payload']['catalog']
        error = assessment_rules.validate_authority(authority, qualification, bundle, catalog)
        if error:
            return stop(error)
        if any(not doc['valid_from'] <= on <= doc['review_due_on'] for doc in (authority, qualification)):
            return stop('assessment_authority_outside_validity')
        review = QualificationReview(**bundle, source_hash=version.source_hash, catalog=catalog)
        try:
            fresh = review.evaluate(request)
        except QualificationError:
            return stop('individual_profile_answers_conflict')
        result.update({k: fresh[k] for k in ('stop_reasons', 'missing_facts', 'next_questions')})
        if fresh['stop_reasons']:
            result['next_questions'] = []
            return stop('profile_stop_requires_specialist')
        if fresh['missing_facts']:
            return stop('individual_profile_incomplete')
        if (request['format'] != 'kg-qualification-review-input/2' or p.get('current_location') != 'abroad' or
                p.get('document_type') != 'ordinary' or p.get('client_type') != 'b2c' or
                p.get('applicants_count') != 1 or p.get('family') != [] or
                p.get('multiple_entries_needed') is not False or p.get('purpose') != 'tourism' or
                p.get('requested_process') != 'visa' or
                any(p.get('escalation', {}).get(k) is not False for k in
                    ('complaint', 'refund_question', 'legal_question', 'conflicting_answers'))):
            return stop('business_mapping_requires_specialist' if p.get('purpose') == 'business_meeting'
                        else 'individual_assessment_scope_requires_specialist')
        error = assessment_rules.profile_scope(p)
        if error:
            return stop(error)
        end = p['exit_date']
        if p['passport_expiry'] < end:
            return stop('passport_expires_before_departure')
        if any(doc['review_due_on'] < end for doc in (authority, qualification)):
            return stop('assessment_authority_does_not_cover_trip')
        history = await stays.current_in_session(session, case, person, at=now)
        result['history'] = {k: history[k] for k in ('status', 'history_id', 'profile_id', 'snapshot_hash', 'findings')}
        error = assessment_rules.validate_history(history, p)
        if error:
            return stop(error)
        identifiers = list((await session.scalars(select(EntryInterview.id).where(
            EntryInterview.case_id == case_id, EntryInterview.applicant_id == applicant_id).limit(2))).all())
        if not identifiers:
            return stop('interview_missing')
        if len(identifiers) != 1:
            raise EntryStorageInvalid('assessment_interview_ambiguous')
        header, pinned = await interviews._header(session, case, person, identifiers[0])
        events, state, _ = await interviews._history(session, header, pinned)
        result['interview'] = dict(id=header.id, header_hash=header.snapshot_hash, revision=len(events),
            head_hash=events[-1].snapshot_hash, phase=state['phase'], policy_hash=pinned.digest, catalog_hash=pinned.catalog_hash)
        if publication._utc(events[-1].created_at) > publication._utc(now):
            return stop('interview_clock_uncertain')
        if header.profile_id != row.id:
            return stop('interview_profile_changed')
        if interview_policy is None or interview_policy.digest != pinned.digest:
            return stop('interview_authority_changed')
        try:
            authorize_interview(actor, interview_policy, on=today)
        except PermissionDenied:
            return stop('interview_authority_unavailable')
        if interview_policy.review_due_on < end:
            return stop('interview_authority_does_not_cover_trip')
        bridge = assessment_interview.reconcile(state, catalog=_plain(header.catalog), policy=pinned,
            on=on, profile=p, history=history, authority=authority['interview'])
        if bridge['reasons']:
            result['interview']['findings'] = bridge['analysis']
            return stop(bridge['reasons'][0])
        facts = bridge['facts']
        for key, value in request.get('condition_facts', {}).items():
            if key not in facts or facts[key] != value:
                return stop('profile_condition_facts_conflict')
        outcomes = assessment_rules.applicability(authority, facts)
        if any(o['status'] == 'unknown' for o in outcomes.values()):
            return stop('competing_regime_facts_unknown')
        if any(o['status'] == 'met' and o['disposition'] == 'manual' for o in outcomes.values()):
            return stop('applicable_manual_regime_requires_specialist')
        matches = [uid for uid, o in outcomes.items() if o['status'] == 'met']
        if len(matches) != 1:
            return stop('competing_regimes_match' if matches else 'no_supported_regime_matches')
        uid = matches[0]
        routes = [r for rule in qualification['rules'] if rule['unit_id'] == uid
                  for r in rule['routes'] if r['purpose'] == p['purpose']]
        if len(routes) != 1 or routes[0]['product'] != 'NO_VISA':
            return stop('purpose_route_not_approved')
        registration = assessment_rules.registration(bundle, p)
        if registration['status'] == 'requires_review':
            # A term cannot repair a blocked exemption or absent/default
            # coverage. Preserve that specific source problem without claiming
            # a computed allowance or an approved registration deadline.
            result['registration'] = registration
            return stop(registration['reason'])
        required = sorted({k for k, o in outcomes.items() if o['disposition'] == 'executable'} |
                          set(registration['source_ids']) | {'KG.REG.DEFAULT', STOP_ID, REG_RULE_ID})
        runtime = await publication._runtime_in_session(context, publication_history,
            policy=publication_policy, ids=required, at=now)
        if runtime['unavailable']:
            result['registration'] = dict(status='requires_review', reason=registration['reason'] or 'assessment_source_unavailable',
                actual_deadline=None, actual_registration_established=False, exemption_days=None, planned_days=None)
            return stop('assessment_source_unavailable')
        end_at = datetime.combine(datetime.fromisoformat(end).date(), time.max, tzinfo=KG)
        future = {u['unit_id']: u['reasons'] for u in await context.availability(active, manifest, at=end_at)}
        if any(future.get(k, ['missing']) for k in required):
            return stop('source_does_not_cover_trip')
        result['registration'] = registration
        source = next(u for u in runtime['available'] if u['unit_id'] == uid)
        result['candidate'] = {k: source[k] for k in ('unit_id', 'title', 'page', 'section', 'source_ref')}
        counting = authority['counting']
        calculation_input = dict(schema_version='kg-stay-review-input/1', rule_unit_id=uid, as_of=on,
            history_complete=True, history=[dict(id=v['ref'], entry_date=v['entry_date'], exit_date=v['exit_date'],
                basis=v['basis'], passport_country=v['passport_country'], passport_continuity='same', confirmed=True)
                for v in history['document']['intervals']],
            trip=dict(mode='new_entry', start_date=p['entry_date'], end_date=end,
                      passport_country=p['entry_passport_country'], basis='visa_free'),
            policy={'status': 'proposed', **{k: counting[k] for k in
                    ('count_entry_day', 'count_exit_day', 'window_anchor', 'timezone')}})
        try:
            arithmetic = StayDayReview(**bundle, source_hash=version.source_hash).evaluate(calculation_input)
        except StayReviewError:
            return stop('personal_stay_arithmetic_unsupported')
        result['arithmetic'] = arithmetic  # Unmodified, original review-only result.
        scenario = arithmetic['scenario']
        if scenario is None:
            return stop('personal_stay_arithmetic_unresolved')
        result['duration'] = dict(limit_days=scenario['limit_days'], window_days=scenario['window_days'],
            minimum_planned_headroom=min(d['scenario_headroom'] for d in scenario['daily']),
            first_exceeded_date=scenario['first_exceeded_date'],
            first_margin_date=next((d['date'] for d in scenario['daily']
                if d['scenario_headroom'] <= authority['stop_margin_days']), None))
        if scenario['first_exceeded_date']:
            return stop('planned_stay_exceeds_allowance')
        if result['duration']['first_margin_date']:
            return stop('stay_margin_requires_specialist')
        if registration['status'] != 'within_planned_exemption':
            return stop(registration['reason'])
        result.update(status='qualified_recorded_plan', selected_regime=uid, selected_product='NO_VISA',
            visa_required=False, requires_specialist=False)
        return result

    return await transactions._run(engine, read)
