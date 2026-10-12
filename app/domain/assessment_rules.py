"""Bounded source interpretation for the separately approved assessment."""
from datetime import date

from app.domain.assessment_policy import PARAMETERS, REG_RULE_ID
from app.domain.approved_qualification import _policy_rules
from app.domain.entry_storage import _hash
from app.knowledge.conditions import _all, _evaluate
from app.knowledge.qualification import REGIMES

REGISTRATION = ('registration_exemption', 'registration_default', 'registration_term')
REG_DEADLINES = ('KG.DL.REGISTRATION_OUTSIDE_LIST', 'KG.DL.VISA_FREE_REGISTRATION')
PROFILE_MAP = {
    **{k: 'mapped' for k in '''citizenship entry_passport_country document_type passport_expiry
        passport_pages_ok purpose current_location entry_date exit_date violations previous_refusals_kg
        client_type applicants_count multiple_entries_needed entry_point tickets_bought urgency_deadline
        family requested_process escalation'''.split()},
    **{k: 'unsupported_if_present' for k in '''in_kg_since current_basis_in_kg current_visa_type
        current_basis_until registration_until purpose_details entry_point_other event_dates
        in_kg_entry_point purpose_declared_at_border previous_refusals_details'''.split()},
    'inviting_party': 'explicit_absence_only',
    'violations': {'overstay': 'mapped', 'fines': 'mapped', 'deportation_or_ban': 'mapped',
                   'ban_until': 'unsupported_if_present'},
}


def profile_scope(profile):
    for key, value in profile.items():
        classification = PROFILE_MAP.get(key)
        if classification is None:
            return 'additional_profile_evidence_requires_reconciliation'
        if classification == 'unsupported_if_present' and value not in (None, 'not_applicable', '', {}):
            return 'additional_profile_evidence_requires_reconciliation'
        if classification == 'explicit_absence_only' and value != {'exists': False}:
            return 'additional_profile_evidence_requires_reconciliation'
        if key == 'violations' and (set(value) - set(classification) or
                value.get('ban_until') not in (None, 'not_applicable', '')):
            return 'additional_profile_evidence_requires_reconciliation'
    return None


def registration_units(bundle):
    return {u['unit_id']: u for u in bundle['units']
            if u['kind'] in REGISTRATION or u['unit_id'] in REG_DEADLINES}


def validate_authority(document, qualification, bundle, catalog):
    if document['profile_map_hash'] != _hash(PROFILE_MAP):
        return 'assessment_profile_mapping_changed'
    units = {u['unit_id']: u for u in bundle['units']}
    regimes = {uid: u for uid, u in units.items() if u['kind'] in REGIMES}
    guards = {r['unit_id']: r for r in document['regimes']}
    routes = {r['unit_id']: r for r in qualification['rules']}
    if set(guards) != set(regimes) or set(routes) != set(regimes):
        return 'assessment_regime_set_incomplete'
    for pins, expected in ((document['regimes'], regimes),
                           (document['parameters'], {k: units.get(k) for k in PARAMETERS}),
                           (document['registration']['units'], registration_units(bundle))):
        if {p['unit_id'] for p in pins} != set(expected):
            return 'assessment_source_coverage_incomplete'
        if any(expected[p['unit_id']] is None or p['unit_hash'] != _hash(expected[p['unit_id']]) for p in pins):
            return 'assessment_source_interpretation_changed'
    known = set(bundle['countries'].values())
    conditional = {r['unit_id']: r for r in (catalog or {}).get('rules', [])}
    executable = []
    for uid, guard in guards.items():
        for p in guard['all']:
            codes = p.get('countries', []) + ([p['country']] if 'country' in p else [])
            if any(c not in known for c in codes):
                return 'assessment_guard_country_unknown'
        if uid == 'KG.VR.GENERAL':
            if (guard['disposition'] != 'manual' or len(guard['all']) != 1 or
                    guard['all'][0]['type'] != 'passport_country_not_in'):
                return 'assessment_default_partition_required'
        elif guard['disposition'] == 'manual':
            # Exact catalog applicability is retained even when its outcome is
            # blocked. The separate authority approves exclusion, not outcome.
            if uid in conditional and guard['all'] != conditional[uid]['all']:
                return 'assessment_manual_applicability_changed'
            countries = (regimes[uid]['value'] or {}).get('countries')
            if type(countries) is list:
                clause = next((p for p in guard['all'] if p['type'] == 'passport_country_in'), None)
                if clause is None or sorted(clause['countries']) != sorted(countries):
                    return 'assessment_manual_country_scope_changed'
        else:
            if regimes[uid]['kind'] != 'visa_free_regime' or guard['all'] != routes[uid]['all']:
                return 'assessment_executable_scope_unsupported'
            executable.append(uid)
    _, error = _policy_rules({'rules': [routes[k] for k in executable]},
                            {**bundle, 'units': [regimes[k] for k in executable]}, catalog)
    if error:
        return error
    expected_values = {'KG.RULE.COUNT_ENTRY_DAY': True, 'KG.RULE.COUNT_EXIT_DAY': True,
                       'KG.RULE.WINDOW_ANCHOR': 'each_day_backward_inclusive', REG_RULE_ID: True}
    for uid, expected in expected_values.items():
        value = units[uid]['value']
        if value is not None and (type(value.get('value')) is not type(expected) or value['value'] != expected):
            return 'assessment_counting_source_conflict'
    return None


def applicability(document, facts):
    result = {}
    for row in document['regimes']:
        checks = []
        for predicate in row['all']:
            if predicate['type'] == 'passport_country_not_in':
                country = facts.get('entry_passport_country')
                checks.append(('unknown', ['entry_passport_country']) if country in (None, 'unknown') else
                              ('not_met' if country in predicate['countries'] else 'met', []))
            else:
                checks.append(_evaluate(predicate, facts))
        status, missing = _all(checks)
        result[row['unit_id']] = dict(status=status, missing=missing, disposition=row['disposition'])
    return result


def validate_history(history, profile):
    if history['status'] != 'recorded_inputs':
        return 'personal_history_' + history['status']
    intervals = history['document']['intervals']
    for visit in intervals:
        if (visit['passport_country'] != profile['entry_passport_country'] or visit['basis'] != 'visa_free' or
                not visit['confirmed'] or visit['passport_ref'] != history['passport_ref']):
            return 'personal_history_basis_or_passport_requires_review'
        if visit['exit_date'] is None:
            return 'personal_history_open_visit'
        if visit['exit_date'] >= profile['entry_date']:
            return 'personal_history_plan_overlap'
    ordered = sorted(intervals, key=lambda v: (v['entry_date'], v['exit_date']))
    if any(b['entry_date'] <= a['exit_date'] for a, b in zip(ordered, ordered[1:])):
        return 'personal_history_overlapping_visits'
    return None


def registration(bundle, profile):
    country = profile['entry_passport_country']
    units = registration_units(bundle)
    exemption = units.get('KG.REG.EXEMPT.' + country)
    default = units.get('KG.REG.DEFAULT')
    term = units.get('KG.REG.TERM.' + country)
    result = dict(status='requires_review', reason=None, source_ids=[], term_source_id=term['unit_id'] if term else None,
                  actual_deadline=None, actual_registration_established=False, exemption_days=None,
                  planned_days=(date.fromisoformat(profile['exit_date']) - date.fromisoformat(profile['entry_date'])).days + 1)
    if default is None or default['value'] is None:
        return {**result, 'reason': 'registration_default_coverage_unknown'}
    covered_default = country in default['value']['not_in_list']
    if exemption and covered_default:
        return {**result, 'reason': 'registration_source_conflict', 'source_ids': [exemption['unit_id'], default['unit_id']]}
    if exemption:
        result['source_ids'] = [exemption['unit_id']]
        if exemption['value'] is None:
            return {**result, 'reason': 'registration_exemption_unavailable'}
        result['exemption_days'] = exemption['value']['days']
        if result['planned_days'] <= result['exemption_days']:
            return {**result, 'status': 'within_planned_exemption'}
        return {**result, 'status': 'obligation_requires_review', 'reason': 'registration_trip_exceeds_exemption'}
    if covered_default:
        return {**result, 'status': 'obligation_requires_review', 'reason': 'registration_submission_requires_review',
                'source_ids': [default['unit_id']]}
    return {**result, 'reason': 'registration_country_coverage_unknown'}
