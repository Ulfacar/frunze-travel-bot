"""Typed observations used as date anchors; recording is not a legal decision."""
from dataclasses import dataclass
from datetime import date
import json
import re

from app.domain.entry_storage import EntryStorageInvalid, _hash, _id, _plain

FORMAT = 'kg-actual-anchor/1'
KINDS = {
    'visa_period': 'visa', 'permit_period': 'unified_permit',
    'resident_period': 'resident_card', 'registration_period': 'registration',
    'registration_payment_code': 'registration', 'address_change': 'registration',
    'passport_change': 'registration', 'purpose_change': 'registration',
    'employment_ended': 'unified_permit',
    'permit_terminated': 'unified_permit',
    'visa_renewal_context': 'visa',
}
PERIODS = frozenset(k for k in KINDS if k.endswith('_period'))
CHANGES = frozenset(('address_change', 'passport_change', 'purpose_change'))
EAEU = frozenset(('ARM', 'BLR', 'KAZ', 'KGZ', 'RUS'))
MAX_REVISIONS = 64
MAX_ACTIVE = 16
MAX_EVENT_BYTES = 16384
MAX_BYTES = 262144
WITHDRAW_RESERVE = 8192


def fail(code='invalid_actual_anchor'):
    raise EntryStorageInvalid(code)


def text(value, pattern):
    if type(value) is not str or not re.fullmatch(pattern, value): fail()
    return value


def day(value):
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value: raise ValueError
        return parsed
    except (TypeError, ValueError): fail('invalid_actual_anchor_date')


def shape(value, keys):
    if type(value) is not dict or value.keys() != set(keys): fail()


@dataclass(frozen=True, init=False)
class AnchorPolicy:
    encoded: str

    def __init__(self, document):
        shape(document, ('format', 'reference', 'proof', 'operators', 'kinds', 'valid_from', 'review_due_on'))
        if document['format'] != FORMAT: fail('invalid_actual_anchor_policy')
        text(document['reference'], r'[A-Z][A-Z0-9._/-]{0,79}')
        text(document['proof'], r'[a-f0-9]{64}')
        operators = document['operators']; kinds = document['kinds']
        if (type(operators) is not list or not 1 <= len(operators) <= 20 or
                any(type(v) is not str or not re.fullmatch(r'[a-z0-9_.-]{1,64}', v) or v in ('system', 'bot') for v in operators) or
                len(set(operators)) != len(operators) or type(kinds) is not list or not 1 <= len(kinds) <= len(KINDS) or
                any(type(v) is not str or v not in KINDS for v in kinds) or len(set(kinds)) != len(kinds) or
                day(document['valid_from']) > day(document['review_due_on'])):
            fail('invalid_actual_anchor_policy')
        object.__setattr__(self, 'encoded', json.dumps(document, sort_keys=True, separators=(',', ':')))

    @property
    def document(self): return json.loads(self.encoded)

    @property
    def digest(self): return _hash(self.document)


def normalize(kind, operation, cutoff):
    if type(kind) is not str or kind not in KINDS: fail()
    shape(operation, ('action', 'data', 'confirmed'))
    if operation['confirmed'] is not True: fail('actual_anchor_confirmation_required')
    data = operation['data']; action = operation['action']
    if action == 'withdraw':
        shape(data, ('on', 'reason', 'proof'))
        if data['reason'] not in ('wrong_document', 'superseded', 'no_longer_confirmed'): fail()
    elif action == 'record':
        shape(data, ('on', 'profile_id', 'profile_hash', 'application_event_id', 'reference', 'proof', 'source', 'value'))
        for name in ('profile_id', 'application_event_id'): _id(data[name])
        text(data['profile_hash'], r'[a-f0-9]{64}')
        text(data['reference'], r'[A-Z][A-Z0-9._/-]{0,79}')
        if data['source'] not in ('portal', 'official_document'): fail('actual_anchor_official_evidence_required')
        value = data['value']
        keys = ('valid_from', 'valid_until', 'document_ref', 'passport_ref') if kind in PERIODS else ()
        if kind in CHANGES: keys = ('before_ref', 'after_ref')
        if kind == 'registration_payment_code': keys = ('event_meaning',)
        if kind == 'visa_renewal_context': keys = ('period_anchor_id', 'period_anchor_hash', 'intent', 'current_type', 'target_type',
            'current_purpose', 'target_purpose', 'current_inviter_ref', 'target_inviter_ref', 'premise_proof')
        if kind == 'registration_period': keys += ('basis_type', 'tax_status', 'basis_proof')
        shape(value, keys)
        if kind == 'visa_renewal_context':
            _id(value['period_anchor_id'])
            for field in ('period_anchor_hash','current_inviter_ref','target_inviter_ref','premise_proof'): text(value[field], r'[a-f0-9]{64}')
            from app.knowledge.qualification_schema import REQUEST_SCHEMA
            definitions = REQUEST_SCHEMA['$defs']
            for field in ('current_type','target_type'):
                if value[field] not in definitions['visa_type']['enum']: fail('actual_anchor_renewal_type_required')
            for field in ('current_purpose','target_purpose'):
                if value[field] not in definitions['purpose']['enum']: fail('actual_anchor_renewal_purpose_required')
            if value['intent'] not in ('same_product_renewal','change_status'): fail('actual_anchor_renewal_intent_required')
            if value['intent']=='same_product_renewal' and (value['current_type']!=value['target_type'] or value['current_purpose']!=value['target_purpose']): fail('actual_anchor_renewal_intent_conflict')
        if kind in PERIODS and day(value['valid_from']) > day(value['valid_until']): fail('invalid_actual_anchor_period')
        for name in ('document_ref', 'passport_ref') if kind in PERIODS else ('before_ref', 'after_ref') if kind in CHANGES else ():
            text(value[name], r'[a-f0-9]{64}')
        if kind in CHANGES and value['before_ref'] == value['after_ref']: fail('actual_anchor_change_required')
        if kind == 'registration_payment_code' and value['event_meaning'] not in ('official_code_issued_on', 'official_code_received_on'):
            fail('actual_anchor_code_meaning_required')
        if kind == 'registration_period':
            if (value['basis_type'] not in ('employment', 'self_employed', 'appointment', 'family', 'visa', 'permit', 'resident_card', 'other') or
                    value['tax_status'] not in ('pending', 'confirmed', 'not_applicable', 'unknown')): fail()
            text(value['basis_proof'], r'[a-f0-9]{64}')
            if value['tax_status'] in ('pending', 'confirmed') and value['basis_type'] not in ('employment', 'self_employed', 'appointment', 'family'):
                fail('actual_anchor_tax_basis_conflict')
    else: fail()
    text(data['proof'], r'[a-f0-9]{64}')
    if day(data['on']) > cutoff: fail('actual_anchor_future_observation')
    return _plain(operation)


def configured(settings):
    value = getattr(settings, 'kg_actual_anchor_policy', None)
    return AnchorPolicy(value) if value is not None else None
