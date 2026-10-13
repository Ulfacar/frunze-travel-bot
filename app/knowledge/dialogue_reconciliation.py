"""Versioned current-stay dependency map; this is not a fresh attestation.

This pure check requires a domain caller to prove original anchor ancestry and
the durable displayed-prompt/turn receipts for every later interview event.
"""
from . import interview_catalog as catalog, interview_rules as rules
from .dialogue_questions import CATALOG_HASH

VERSION = 'kg-dialogue-reconciliation/1'
# These fields can affect the current-stay fact or a material field's freshness.
MATCHED = frozenset(('citizenships', 'passport_country', 'document_type', 'residence_country',
    'foreign_residence.exists', 'long_visa.exists', 'location', 'actual_entry.on', 'purpose',
    'organized_group.exists', 'previous_visits', 'current_basis', 'current_until',
    'passport_expiry', 'passport_two_blank_pages',
    'entry_on', 'exit_on', 'multiple_entries', 'tickets_bought', 'previous_refusal',
    'risk.overstay', 'risk.fines', 'risk.deportation', 'risk.entry_ban',
    'registration.until', 'inviter.exists'))
# Explicit whitelist, not an assumption that any new field is harmless. Typed
# stop/conflict analysis and the live current-stay reader still run afterwards.
NONMATERIAL = frozenset(('registration.exists', 'residence_petition'))
_CATALOG = catalog.by_digest(CATALOG_HASH)
FIELD_MAP = {f['path']: dict(disposition='must_match_attested' if f['path'] in MATCHED else
    'not_used_by_current_stay' if f['path'] in NONMATERIAL else 'operator_reconciliation_required',
    depends=sorted(set(f['depends']) | set(rules.CONDITION_INPUTS[f['when']]))) for f in _CATALOG['fields']}
MAP_HASH = rules.digest(dict(version=VERSION, catalog_hash=CATALOG_HASH, fields=FIELD_MAP))


def changed_fields(changes, *, answers, fact, profile, history, catalog_document):
    """Return an explicit refusal reason, or None for this narrow dependency check."""
    if catalog.digest(catalog_document) != CATALOG_HASH:
        return 'dialogue_reconciliation_catalog_changed'
    if type(changes) is not dict or not 1 <= len(changes) <= 3:
        return 'dialogue_reconciliation_changes_invalid'
    expected = dict(citizenships=sorted(profile.get('citizenship', [])),
        passport_country=profile.get('entry_passport_country'), document_type=profile.get('document_type'),
        residence_country=fact['conditions']['residence_country']['value'], location=fact['location'],
        purpose=profile.get('purpose'), current_basis=fact['current_basis'], current_until=fact['lawful_until'])
    expected['actual_entry.on'] = fact['entered_on']
    expected.update(passport_expiry=profile.get('passport_expiry'),
        passport_two_blank_pages=True if profile.get('passport_pages_ok') is True else None,
        entry_on=profile.get('entry_date'), exit_on=profile.get('exit_date'),
        multiple_entries=profile.get('multiple_entries_needed'), tickets_bought=profile.get('tickets_bought'),
        previous_refusal=profile.get('previous_refusals_kg'))
    expected['registration.until'] = profile.get('registration_until')
    expected['inviter.exists'] = profile.get('inviting_party', {}).get('exists')
    for path in ('overstay', 'fines'):
        expected['risk.'+path] = profile.get('violations', {}).get(path)
    for path in ('deportation', 'entry_ban'):
        expected['risk.'+path] = False if profile.get('violations', {}).get('deportation_or_ban') is False else None
    for path, leaf in (('foreign_residence.exists', 'other_residence_absent'),
                       ('long_visa.exists', 'foreign_visa_absent'), ('organized_group.exists', 'organized_group_absent')):
        expected[path] = False if fact['conditions'][leaf]['value'] is True else None
    expected['previous_visits'] = (False if history.get('status') == 'recorded_inputs' and
        not any(v['exit_date'] is not None for v in (history.get('document') or {}).get('intervals', [])) else None)
    current = rules.Answers(answers, catalog_document=catalog_document)
    for path, value in changes.items():
        kind = FIELD_MAP.get(path, {}).get('disposition')
        if kind not in ('must_match_attested', 'not_used_by_current_stay'):
            return 'dialogue_field_requires_operator_reconciliation'
        if value is None or value in ('unknown', 'not_applicable') or current.get(path) != value:
            return 'dialogue_changed_answer_not_fresh'
        if kind == 'must_match_attested' and (expected[path] is None or type(value) is not type(expected[path]) or value != expected[path]):
            return 'dialogue_answer_conflicts_with_original_attestation'
    return None
