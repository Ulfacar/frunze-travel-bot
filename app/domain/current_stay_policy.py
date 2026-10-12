"""Separate current-stay interpretation and narrowly scoped factual attestation.

These server-only objects install no real approvals. References are provenance,
not signatures; neither accepts a selected regime or a client supplied remainder.
"""
from dataclasses import dataclass
import json

from app.domain.assessment_policy import _guard, _pin, _ref
from app.domain.entry_storage import EntryStorageInvalid, _document, _hash, _id
from app.knowledge.bundle_schema import BOOL, DATE, ISO3, array, enum, obj
from app.knowledge.condition_schema import HASH
from app.knowledge.stay_days import ALGORITHM, COUNT_RULE_IDS

VERSION = 'kg-current-stay-checks/1'
STOPS = ('KG.ESC.STOP_03', 'KG.ESC.STOP_04', 'KG.ESC.STOP_12')
PARAMETERS = (*COUNT_RULE_IDS, *STOPS)
ID = {'type': 'integer', 'minimum': 1}
NULL = {'type': 'null'}
POLICY = obj({
    'format': {'const': 'kg-current-stay-policy/1'}, 'algorithm': {'const': VERSION},
    'scope': {'const': 'current_stay_stops_only'}, 'reference': _ref, 'proof': HASH,
    'valid_from': DATE, 'review_due_on': DATE, 'source_hash': HASH, 'bundle_hash': HASH,
    'projection_hash': HASH, 'catalog_hash': {'anyOf': [HASH, NULL]},
    'qualification_policy_hash': HASH, 'regimes': {**array(_guard, maximum=100), 'minItems': 1},
    'parameters': array(_pin, maximum=len(PARAMETERS)),
    'counting': obj({'algorithm': {'const': ALGORITHM}, 'count_entry_day': BOOL, 'count_exit_day': BOOL,
        'window_anchor': {'const': 'each_day_backward_inclusive'}, 'timezone': {'const': 'Asia/Bishkek'},
        'reference': _ref, 'proof': HASH}),
    'calendar': obj({'hash': HASH, 'reference': _ref, 'proof': HASH,
        'include_today': BOOL, 'include_until': BOOL, 'threshold': {'const': 5, 'type': 'integer'},
        'interpretation': {'const': 'strictly_less_than_threshold'},
        'valid_from': DATE, 'review_due_on': DATE}),
    'stop_margin_days': {'const': 3, 'type': 'integer'},
})


def claim(value):
    return obj({'value': value, 'reference': _ref, 'proof': HASH})


FACT = obj({
    'format': {'const': 'kg-current-stay-attestation/1'}, 'reference': _ref, 'proof': HASH,
    'actor': {'type': 'string', 'pattern': r'^[a-z0-9_.-]{1,64}$'},
    'policy_hash': HASH, 'case_id': ID, 'applicant_id': ID, 'profile_id': ID, 'profile_hash': HASH,
    'passport_ref': {'type': 'string', 'pattern': '^[a-f0-9]{32}$'},
    'as_of': DATE, 'valid_from': DATE, 'review_due_on': DATE,
    'location': enum('abroad', 'in_kg'),
    'current_basis': enum('visa_free', 'visa', 'unknown'), 'entered_on': {'anyOf': [DATE, NULL]},
    'lawful_until': {'anyOf': [DATE, NULL]},
    'lawful_until_semantics': {'const': 'attested_actual_permission_end_not_visa_validity_or_planned_exit'},
    'interview': {'anyOf': [NULL, obj({'id': ID, 'header_hash': HASH, 'head_hash': HASH})]},
    'history': {'anyOf': [NULL, obj({'id': ID, 'snapshot_hash': HASH})]},
    'conditions': obj({
        'residence_country': claim({'anyOf': [ISO3, NULL]}),
        'other_residence_absent': claim({'anyOf': [BOOL, NULL]}),
        'foreign_visa_absent': claim({'anyOf': [BOOL, NULL]}),
        'organized_group_absent': claim({'anyOf': [BOOL, NULL]}),
    }),
})


def _encode(document, schema, *, limit):
    checked = _document(document, schema)
    if checked['valid_from'] > checked['review_due_on']:
        raise EntryStorageInvalid('current_stay_authority_date_order')
    encoded = json.dumps(checked, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if len(encoded.encode()) > limit:
        raise EntryStorageInvalid('current_stay_authority_size')
    return checked, encoded


@dataclass(frozen=True, init=False)
class CurrentStayPolicy:
    encoded: str

    def __init__(self, document):
        checked, encoded = _encode(document, POLICY, limit=131072)
        for rows in (checked['regimes'], checked['parameters']):
            if len({r['unit_id'] for r in rows}) != len(rows):
                raise EntryStorageInvalid('current_stay_duplicate_unit')
        if {r['unit_id'] for r in checked['parameters']} != set(PARAMETERS):
            raise EntryStorageInvalid('current_stay_parameters_incomplete')
        for row in checked['regimes']:
            types = [p['type'] for p in row['all']]
            if len(types) != len(set(types)):
                raise EntryStorageInvalid('current_stay_ambiguous_guard')
        c = checked['calendar']
        if c['valid_from'] > c['review_due_on']:
            raise EntryStorageInvalid('current_stay_calendar_date_order')
        object.__setattr__(self, 'encoded', encoded)

    @property
    def document(self): return json.loads(self.encoded)

    @property
    def digest(self): return _hash(self.document)


@dataclass(frozen=True, init=False)
class CurrentStayFact:
    encoded: str

    def __init__(self, document):
        checked, encoded = _encode(document, FACT, limit=16384)
        for key in ('case_id', 'applicant_id', 'profile_id'):
            _id(checked[key])
        if checked['interview'] is not None: _id(checked['interview']['id'])
        if checked['history'] is not None: _id(checked['history']['id'])
        if (checked['actor'] in ('bot', 'system') or
                checked['entered_on'] is not None and checked['entered_on'] > checked['as_of'] or
                not checked['valid_from'] <= checked['as_of'] <= checked['review_due_on']):
            raise EntryStorageInvalid('current_stay_fact_invalid')
        if (checked['location'] == 'in_kg' and checked['entered_on'] is None or
                checked['location'] == 'abroad' and (checked['entered_on'] is not None or
                    checked['lawful_until'] is not None or checked['current_basis'] != 'unknown')):
            raise EntryStorageInvalid('current_stay_fact_location_conflict')
        object.__setattr__(self, 'encoded', encoded)

    @property
    def document(self): return json.loads(self.encoded)

    @property
    def digest(self): return _hash(self.document)
