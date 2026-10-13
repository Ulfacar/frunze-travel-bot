"""Separate, server-owned authority for connected personal assessments.

Provenance strings are not external signatures. No real authority is installed
by this module; synthetic test approvals must never be used in production.
"""
from dataclasses import dataclass
from datetime import date
import json

from app.domain.entry_storage import EntryStorageInvalid, _document, _hash
from app.knowledge.bundle_schema import DATE, ISO3, array, enum, obj
from app.knowledge.condition_schema import HASH, PREDICATE
from app.knowledge.stay_days import ALGORITHM, COUNT_RULE_IDS

FORMAT = 'kg-connected-assessment-policy/1'
ALGORITHM_VERSION = 'kg-connected-assessment/1'
BRIDGE = 'kg-interview-assessment-bridge/1'
STOP_ID = 'KG.ESC.STOP_12'
REG_RULE_ID = 'KG.RULE.REG_DOES_NOT_EXTEND_VF'
PARAMETERS = (*COUNT_RULE_IDS, STOP_ID, REG_RULE_ID)
_ref = {'type': 'string', 'pattern': r'^[A-Z][A-Z0-9._/-]{0,79}$'}
_pin = obj({'unit_id': {'type': 'string', 'pattern': r'^KG\.[A-Z0-9_.]+$'}, 'unit_hash': HASH})
_not_in = obj({'type': {'const': 'passport_country_not_in'},
               'countries': {**array(ISO3, maximum=300), 'minItems': 1, 'uniqueItems': True}})
_guard = obj({**_pin['properties'], 'disposition': enum('executable', 'manual'),
              'interpretation_reference': _ref, 'interpretation_proof': HASH,
              'all': {**array({'anyOf': [PREDICATE, _not_in]}, maximum=12), 'minItems': 1}})
SCHEMA = obj({
    'format': {'const': FORMAT}, 'algorithm': {'const': ALGORITHM_VERSION},
    'reference': _ref, 'proof': HASH, 'valid_from': DATE, 'review_due_on': DATE,
    'qualification_policy_hash': HASH, 'profile_map_hash': HASH, 'source_hash': HASH, 'bundle_hash': HASH,
    'projection_hash': HASH, 'catalog_hash': {'anyOf': [HASH, {'type': 'null'}]},
    'scope': {'const': 'adult_individual_abroad_ordinary_tourism_single_entry'},
    'regimes': {**array(_guard, maximum=100), 'minItems': 1},
    'parameters': array(_pin, maximum=len(PARAMETERS)),
    'registration': obj({'mode': {'const': 'exemption_only'},
                         'units': array(_pin, maximum=500)}),
    'counting': obj({'algorithm': {'const': ALGORITHM},
        'count_entry_day': {'const': True}, 'count_exit_day': {'const': True},
        'window_anchor': {'const': 'each_day_backward_inclusive'},
        'timezone': {'const': 'Asia/Bishkek'},
        'basis': {'const': 'visa_free'}, 'passport': {'const': 'same_confirmed'},
        'reported_window_anchor': {'const': 'as_of_backward_inclusive'}}),
    'stop_margin_days': {'const': 3},
    'interview': obj({'bridge': {'const': BRIDGE}, 'catalog_hash': HASH,
        'policy_hash': HASH, 'field_map_hash': HASH, 'completion': {'const': 'acked_intake_complete'}}),
})


@dataclass(frozen=True, init=False)
class AssessmentPolicy:
    encoded: str

    def __init__(self, document):
        checked = _document(document, SCHEMA)
        if date.fromisoformat(checked['valid_from']) > date.fromisoformat(checked['review_due_on']):
            raise EntryStorageInvalid('assessment_policy_date_order')
        for rows in (checked['regimes'], checked['parameters'], checked['registration']['units']):
            if len({r['unit_id'] for r in rows}) != len(rows):
                raise EntryStorageInvalid('assessment_policy_duplicate_unit')
        if {r['unit_id'] for r in checked['parameters']} != set(PARAMETERS):
            raise EntryStorageInvalid('assessment_policy_parameters_incomplete')
        for row in checked['regimes']:
            types = [p['type'] for p in row['all']]
            if len(types) != len(set(types)) or ('passport_country_not_in' in types and
                    (row['unit_id'] != 'KG.VR.GENERAL' or row['disposition'] != 'manual')):
                raise EntryStorageInvalid('assessment_policy_ambiguous_guard')
        encoded = json.dumps(checked, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if len(encoded.encode('utf-8')) > 131072:
            raise EntryStorageInvalid('assessment_policy_size')
        object.__setattr__(self, 'encoded', encoded)

    @property
    def document(self):
        return json.loads(self.encoded)

    @property
    def digest(self):
        return _hash(self.document)


def configured_policy(settings):
    raw = settings.kg_assessment_policy
    return AssessmentPolicy(raw) if raw else None
