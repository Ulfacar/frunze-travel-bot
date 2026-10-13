"""Current, source-bound route candidates; personal allowance is a separate gate.

No writes, historical algorithm changes, automatic product assignment or messages.
All competing regimes must be represented and available, even excluded ones.
"""
from copy import deepcopy
from datetime import datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.domain import applicant_profiles as profiles, entry_applications as transactions
from app.domain import knowledge_publication as publication
from app.domain.entry_storage import EntryStorageInvalid, _authorize, _hash, _id, _plain
from app.domain.models import EntryInterview
from app.domain.qualification_policy import QualificationPolicy
from app.knowledge.conditions import _all, _evaluate
from app.knowledge.qualification import REGIMES, QualificationError, QualificationReview

FORMAT = 'kg-approved-route/1'
KG = ZoneInfo('Asia/Bishkek')
LIMITS = ['individual_stay_history_required', 'registration_review_required', 'final_qualification_required']


def _base(case_id, applicant_id):
    return dict(format=FORMAT, case_id=case_id, applicant_id=applicant_id, status='specialist_review',
        candidate=None, selected_regime=None, selected_product=None, visa_required=None,
        entry_eligibility_evaluated=False, exact_remaining_days=None, exact_deadline=None,
        may_quote=False, calculations_performed=False, requires_specialist=True, delivery='not_sent',
        reasons=[], unresolved=list(LIMITS), next_questions=[], missing_facts=[], stop_reasons=[],
        source=None, profile=None, policy_hash=None, checked_at=None, language='ru')


def _policy_rules(document, bundle, catalog):
    """Reject omissions and unsupported semantics before evaluating any facts."""
    units = {u['unit_id']: u for u in bundle['units'] if u['kind'] in REGIMES}
    rules = {r['unit_id']: r for r in document['rules']}
    if set(units) != set(rules):
        return None, 'qualification_regime_set_incomplete'
    known = set(bundle['countries'].values())
    conditional = {r['unit_id']: r for r in (catalog or {}).get('rules', [])}
    for identifier, rule in rules.items():
        unit = units[identifier]
        value = unit['value'] or {}
        countries = value.get('countries')
        if (unit['kind'] == 'special_regime' or type(countries) is not list or not countries or
                unit['kind'] == 'visa_required_regime' and value.get('scope') not in ('all_types', 'business_tourist')):
            return None, 'qualification_source_semantics_unsupported'
        country_guard = next((p for p in rule['all'] if p['type']=='passport_country_in'), None)
        if country_guard is None or sorted(country_guard['countries']) != sorted(countries):
            return None, 'qualification_predicates_do_not_cover_source'
        allowed_product = 'NO_VISA' if unit['kind']=='visa_free_regime' else 'TS'
        if any(route['product'] != allowed_product or
               unit['kind']=='visa_required_regime' and route['purpose'] != 'tourism' for route in rule['routes']):
            return None, 'qualification_product_does_not_cover_source'
        for predicate in rule['all']:
            predicate_countries = predicate.get('countries', []) + ([predicate['country']] if 'country' in predicate else [])
            if any(code not in known for code in predicate_countries):
                return None, 'qualification_predicate_country_unknown'
            if predicate['type']=='visa_type_is' and predicate['value'] != allowed_product:
                return None, 'qualification_predicate_route_conflict'
            if predicate['type']=='stay_within_months':
                # This slice has no approved date-boundary/counting policy. A
                # saved boolean cannot replace a source-bound trip calculation.
                return None, 'qualification_source_semantics_unsupported'
        if identifier in conditional:
            source = conditional[identifier]
            if source['unresolved'] or _hash(source['all']) != _hash(rule['all']):
                return None, 'qualification_condition_unresolved_or_changed'
            expected_outcome = (dict(stay_days=value['days'], window_days=value['window_days'])
                if unit['kind']=='visa_free_regime' else dict(gknb_approval=value['gknb_approval']))
            if source['source_outcome'] != expected_outcome:
                return None, 'qualification_condition_outcome_unsupported'
        else:
            # This contract only supports literal country sets without a catalog.
            # all_others, special regimes and unparsed qualifiers remain unresolved.
            expected = [dict(type='passport_country_in', countries=sorted(countries)),
                        dict(type='document_type_is', value='ordinary')]
            actual = deepcopy(rule['all'])
            for clause in actual:
                if 'countries' in clause:
                    clause['countries'] = sorted(clause['countries'])
            if sorted(actual, key=lambda p: p['type']) != sorted(expected, key=lambda p: p['type']):
                return None, 'qualification_predicates_do_not_cover_source'
    return rules, None


async def propose_route(engine, *, actor, case_id, applicant_id, qualification_policy=None,
                        publication_policy=None, expected_profile_id=None):
    _authorize(actor)
    _id(case_id); _id(applicant_id)
    if expected_profile_id is not None:
        _id(expected_profile_id)
    if qualification_policy is not None and not isinstance(qualification_policy, QualificationPolicy):
        raise EntryStorageInvalid('invalid_qualification_policy')

    async def read(session):
        # Interview writers serialize on the case, profile writers on the person,
        # publication/decision writers on the knowledge set, in this order.
        await transactions._case(session, case_id, lock=True)
        case, person = await profiles._subject(session, case_id, applicant_id)
        context, history = await publication._runtime_context(session)
        rows, _, _ = await profiles._history(session, case, person)
        result = _base(case_id, applicant_id)
        if not rows:
            result['reasons'] = ['individual_profile_missing']
            return result
        row = rows[-1]
        result['profile'] = dict(id=row.id, revision=row.revision, snapshot_hash=row.snapshot_hash)
        request = _plain(row.input_snapshot)
        result['language'] = request['language']
        if expected_profile_id is not None and expected_profile_id != row.id:
            result['reasons'] = ['individual_profile_changed']
            return result
        if await session.scalar(select(EntryInterview.id).where(EntryInterview.case_id == case_id,
                                                                EntryInterview.applicant_id == applicant_id)):
            # Until the explicit typed-fact reconciliation is implemented, even an
            # active interview cannot be silently ignored in favour of an older profile.
            result['reasons'] = ['interview_reconciliation_required']
            return result
        active = history['active']
        if active is None:
            result['reasons'] = ['no_active_publication']
            return result
        version, bundle, projection = await context.source(active)
        manifest = history['manifests'][active]
        result['source'] = dict(version_id=active, version_label=bundle['meta']['version_label'],
            source_hash=version.source_hash, bundle_hash=version.bundle_hash,
            projection_hash=projection['projection_hash'], catalog_hash=projection['catalog_hash'],
            manifest_hash=_hash(manifest), publication_revision=len(history['rows']))
        if row.knowledge_version_id != active:
            result['reasons'] = ['individual_profile_source_changed']
            return result
        if qualification_policy is None:
            result['reasons'] = ['qualification_policy_missing']
            return result
        document = qualification_policy.document
        result['policy_hash'] = qualification_policy.digest
        if any(document[key] != result['source'][key] for key in
               ('source_hash', 'bundle_hash', 'projection_hash', 'catalog_hash')):
            result['reasons'] = ['qualification_policy_source_changed']
            return result
        # context.source has independently rebuilt and checked this projection.
        catalog = projection['payload']['catalog']
        rules, error = _policy_rules(document, bundle, catalog)
        if error:
            result['reasons'] = [error]
            return result
        runtime = await publication._runtime_in_session(context, history, policy=publication_policy,
                                                       ids=sorted(rules))
        if runtime['unavailable']:
            result['reasons'] = ['competing_regime_unavailable']
            return result
        now = datetime.fromisoformat(runtime['available'][0]['checked_at'])
        today = transactions._local_day(now)
        result['checked_at'] = transactions._utc(now)
        if publication._utc(row.created_at) > publication._utc(now) or request['as_of'] != today.isoformat():
            result['reasons'] = ['individual_profile_needs_current_confirmation']
            return result
        if not document['valid_from'] <= today.isoformat() <= document['review_due_on']:
            result['reasons'] = ['qualification_policy_outside_validity']
            return result
        review = QualificationReview(**bundle, source_hash=version.source_hash, catalog=catalog)
        try:
            fresh = review.evaluate({**request, 'as_of': today.isoformat()})
        except QualificationError:
            # Historical receipts remain valid evidence of what was saved.
            # A stricter current semantic check needs corrected answers, not
            # a service-outage response or an inferred eligibility decision.
            result['reasons'] = ['individual_profile_answers_conflict']
            return result
        result.update(stop_reasons=fresh['stop_reasons'], missing_facts=fresh['missing_facts'],
                      next_questions=fresh['next_questions'])
        p = request['profile']
        if fresh['stop_reasons']:
            result['reasons'] = ['profile_stop_requires_specialist']
            result['next_questions'] = []
            return result
        if request['format'] != 'kg-qualification-review-input/2':
            result['reasons'] = ['extended_individual_profile_required']
            return result
        if fresh['missing_facts']:
            result['reasons'] = ['individual_profile_incomplete']
            result['status'] = 'needs_input'
            return result
        if (p.get('current_location') != 'abroad' or p.get('document_type') != 'ordinary' or
                p.get('client_type') != 'b2c' or p.get('applicants_count') != 1 or
                p.get('family') != [] or p.get('multiple_entries_needed') is not False or
                p.get('purpose') not in ('tourism', 'transit') or
                p.get('requested_process') != 'visa' or
                any(p.get('escalation', {}).get(k) is not False for k in
                    ('complaint', 'refund_question', 'legal_question', 'conflicting_answers'))):
            result['reasons'] = ['individual_route_scope_requires_specialist']
            return result
        end = p['exit_date']
        if p['passport_expiry'] < end:
            result['reasons'] = ['passport_expires_before_departure']
            return result
        if document['review_due_on'] < end:
            result['reasons'] = ['qualification_policy_does_not_cover_trip']
            return result
        end_at = datetime.combine(datetime.fromisoformat(end).date(), time.max, tzinfo=KG)
        future = await context.availability(active, manifest, at=end_at)
        if any(item['reasons'] for item in future if item['unit_id'] in rules):
            result['reasons'] = ['source_does_not_cover_trip']
            return result
        facts = deepcopy(request.get('condition_facts', {'schema_version': 'kg-entry-condition-facts/1'}))
        facts.update(entry_passport_country=p['entry_passport_country'], document_type=p['document_type'])
        outcomes = {uid: _all([_evaluate(clause, facts) for clause in rule['all']]) for uid, rule in rules.items()}
        if any(status == 'unknown' for status, _ in outcomes.values()):
            result['reasons'] = ['competing_regime_facts_unknown']
            result['missing_facts'] = sorted({path for status, paths in outcomes.values() if status == 'unknown' for path in paths})
            return result
        matches = [uid for uid, (status, _) in outcomes.items() if status == 'met']
        if len(matches) != 1:
            result['reasons'] = ['competing_regimes_match' if matches else 'no_supported_regime_matches']
            return result
        uid = matches[0]
        routes = [route for route in rules[uid]['routes'] if route['purpose'] == p['purpose']]
        if len(routes) != 1:
            result['reasons'] = ['purpose_route_not_approved']
            return result
        source = next(unit for unit in runtime['available'] if unit['unit_id'] == uid)
        result.update(status='candidate_for_review', candidate=dict(unit_id=uid, product=routes[0]['product'],
            title=source['title'], page=source['page'], section=source['section'], source_ref=source['source_ref']),
            reasons=['individual_allowance_and_registration_not_evaluated'])
        # A possible route is not a final qualification. These fields intentionally
        # remain None/False even for a fully approved, unambiguous source candidate.
        return result

    return await transactions._run(engine, read)
