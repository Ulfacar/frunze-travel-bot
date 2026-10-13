"""Fresh, dependency-aware reconciliation; never infer consent from a profile."""
from datetime import date

from app.domain.entry_storage import _hash
from app.knowledge import interview_rules as rules

MAPPED = frozenset('''citizenships passport_country document_type passport_expiry
passport_two_blank_pages passport_undamaged location current_country purpose
entry_on exit_on multiple_entries party_type applicants_count family_count
applicant.age risk.overstay risk.fines risk.deportation risk.entry_ban
previous_refusal previous_visits history_count history.{i}.entry history.{i}.exit
history.{i}.passport_country reported_window reported_days previous_visa_count
foreign_residence.exists long_visa.exists organized_group.exists tickets_bought
planned_entry_point hard_deadline.exists consent.given consent.on
consent.evidence_ref consent.evidence_sha256 residence_country'''.split())
NONDECISION = frozenset('''contact_name language contact_phone contact_messenger
contact_role contact_email accommodation_address terms.accepted terms.on
terms.evidence_ref terms.evidence_sha256 payer commercial.contract
commercial.company_invoice commercial.closing_documents payment_preference
extra_services referral'''.split())


def field_map(document):
    # Every other field is explicitly unsupported if applicable. A new material
    # branch cannot silently become irrelevant by being added to the catalog.
    return {f['path']: ('mapped' if f['path'] in MAPPED else
            'nondecision' if f['path'] in NONDECISION else 'unsupported')
            for f in document['fields']}


def reconcile(state, *, catalog, policy, on, profile, history, authority):
    result = dict(reasons=[], facts=None, analysis=None)
    def stop(reason):
        return {**result, 'reasons': [reason]}
    if (authority['catalog_hash'] != policy.catalog_hash or
            authority['policy_hash'] != policy.digest or
            authority['field_map_hash'] != _hash(field_map(catalog))):
        return stop('interview_bridge_changed')
    fresh = rules.analyze(state['answers'], on=on, language=state['language'],
                          pre_consent=policy.pre_consent, catalog_document=catalog)
    result['analysis'] = {k: fresh[k] for k in ('gaps', 'stale', 'stops', 'conflicts', 'consent_complete')}
    if state['collection_blocked'] or state['consent_withdrawal'] or not fresh['consent_complete']:
        return stop('interview_consent_required')
    if fresh['stops'] or fresh['conflicts']:
        return stop('interview_stop_requires_specialist')
    if state['phase'] != 'acked':
        return stop('interview_' + state['phase'])
    card = (state['handoff'] or {}).get('card', {})
    if card.get('reasons') != ['intake_complete']:
        return stop('interview_handoff_requires_specialist')
    if fresh['gaps'] or fresh['stale']:
        return stop('interview_answers_incomplete_or_stale')
    a = rules.Answers(state['answers'], catalog_document=catalog)
    acknowledged = rules.Answers(card['answers'], catalog_document=catalog)
    mapping = field_map(catalog)
    for path, field in a.fields.items():
        if a.applicability(field) is not False:
            category = mapping[rules.template_path(path)]
            if category == 'unsupported':
                return stop('interview_branch_requires_specialist')
            if category == 'mapped' and a.get(path) != acknowledged.get(path):
                return stop('interview_changed_after_ack')
    p = profile
    citizens = a.get('citizenships')
    country = citizens[0] if type(citizens) is list and len(citizens) == 1 else a.get('passport_country')
    expected = {
        'document_type': p.get('document_type'), 'passport_expiry': p.get('passport_expiry'),
        'location': p.get('current_location'), 'purpose': p.get('purpose'),
        'entry_on': p.get('entry_date'), 'exit_on': p.get('exit_date'),
        'multiple_entries': p.get('multiple_entries_needed'), 'tickets_bought': p.get('tickets_bought'),
        'planned_entry_point': p.get('entry_point'), 'previous_refusal': p.get('previous_refusals_kg'),
        'risk.overstay': p.get('violations', {}).get('overstay'),
        'risk.fines': p.get('violations', {}).get('fines'),
    }
    if (citizens != sorted(p.get('citizenship', [])) or country != p.get('entry_passport_country') or
            any(a.get(k) != v for k, v in expected.items()) or
            p.get('violations', {}).get('deportation_or_ban') !=
                (a.get('risk.deportation') or a.get('risk.entry_ban'))):
        return stop('interview_profile_conflict')
    if (a.get('party_type') != 'individual' or a.get('applicants_count') != 1 or
            a.get('family_count') != 0 or type(a.get('applicant.age')) is not int or a.get('applicant.age') < 18 or
            a.get('current_country') in (None, 'KGZ', 'unknown', 'not_applicable') or
            a.get('passport_two_blank_pages') is not True or a.get('passport_undamaged') is not True or
            p.get('passport_pages_ok') is not True or a.get('hard_deadline.exists') is not False or
            p.get('urgency_deadline') not in (None, 'not_applicable') or
            a.get('planned_entry_point') != 'manas'):
        return stop('interview_scope_requires_specialist')
    for path in ('foreign_residence.exists', 'long_visa.exists', 'organized_group.exists'):
        field = a.fields[path]
        if a.applicability(field) is not False and a.get(path) is not False:
            return stop('special_regime_facts_require_specialist')
    intervals = history['document']['intervals']
    if a.get('previous_visits') is False:
        if intervals:
            return stop('interview_history_conflict')
    elif a.get('previous_visits') is True:
        count = a.get('history_count')
        if type(count) is not int or count != len(intervals) or not count:
            return stop('interview_history_conflict')
        reported = sorted((a.get(f'history.{i}.entry'), a.get(f'history.{i}.exit'),
                           a.get(f'history.{i}.passport_country')) for i in range(1, count + 1))
        actual = sorted((v['entry_date'], v['exit_date'], v['passport_country']) for v in intervals)
        if reported != actual or a.get('previous_visa_count') != 0:
            return stop('interview_history_conflict')
        window = a.get('reported_window')
        if window not in ('60', '120', '180', '360'):
            return stop('interview_reported_history_unresolved')
        right = date.fromisoformat(on).toordinal(); left = right - int(window) + 1
        days = sum(max(0, min(right, date.fromisoformat(v['exit_date']).toordinal()) -
                       max(left, date.fromisoformat(v['entry_date']).toordinal()) + 1) for v in intervals)
        if a.get('reported_days') != days:
            return stop('interview_reported_history_conflict')
    else:
        return stop('interview_history_incomplete')
    # Absence is explicit and fresh. The conditional long-visa question may be
    # inapplicable; it is then left unknown, never silently converted to false.
    facts = dict(schema_version='kg-entry-condition-facts/1', entry_passport_country=country,
                 document_type=p['document_type'], residence_documents=dict(complete=True, items=[
                     dict(country=a.get('residence_country'), kind='other', permanent=True)]),
                 tour_group=dict(organized=False))
    if a.get('long_visa.exists') is False:
        facts['foreign_visas'] = dict(complete=True, items=[])
    return {**result, 'facts': facts}
