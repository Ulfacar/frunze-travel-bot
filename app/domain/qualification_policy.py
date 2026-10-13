"""Explicit authority for executable predicates and product routing; empty by default."""
from dataclasses import dataclass
from datetime import date
import json

from app.domain.entry_storage import EntryStorageInvalid, _document, _hash
from app.knowledge.bundle_schema import DATE, array, enum, obj
from app.knowledge.condition_schema import HASH, PREDICATE
from app.knowledge.slots import slots_schema

PRODUCTS = ('NO_VISA', 'TS', 'B', 'S', 'RL', 'FF', 'L', 'EP', 'RES', 'REG')
_purposes = slots_schema()['$defs']['purpose']
_route = obj({'purpose': _purposes, 'product': enum(*PRODUCTS)})
_rule = obj({'unit_id': {'type': 'string', 'pattern': r'^KG\.(VF|VR|SP)\.[A-Z0-9_]+$'},
             'all': {**array(PREDICATE, maximum=12), 'minItems': 1},
             'routes': array(_route, maximum=30)})
SCHEMA = obj({
    'format': {'const': 'kg-qualification-policy/1'},
    'algorithm': {'const': 'kg-approved-route/1'},
    'reference': {'type': 'string', 'pattern': r'^[A-Z][A-Z0-9._/-]{0,79}$'},
    'proof': HASH, 'source_hash': HASH, 'bundle_hash': HASH, 'projection_hash': HASH,
    'catalog_hash': {'anyOf': [HASH, {'type': 'null'}]},
    'valid_from': DATE, 'review_due_on': DATE,
    'complete_regime_set': {'const': True},
    'rules': {**array(_rule, maximum=100), 'minItems': 1},
})


@dataclass(frozen=True, init=False)
class QualificationPolicy:
    """Server-owned, immutable JSON. It must never be populated from form fields."""
    encoded: str

    def __init__(self, document):
        checked = _document(document, SCHEMA)
        if date.fromisoformat(checked['review_due_on']) < date.fromisoformat(checked['valid_from']):
            raise EntryStorageInvalid('qualification_policy_date_order')
        identifiers = [r['unit_id'] for r in checked['rules']]
        if len(set(identifiers)) != len(identifiers):
            raise EntryStorageInvalid('qualification_policy_duplicate_rule')
        for rule in checked['rules']:
            kinds = [p['type'] for p in rule['all']]
            purposes = [r['purpose'] for r in rule['routes']]
            if (len(set(kinds)) != len(kinds) or len(set(purposes)) != len(purposes) or
                    any(p in (None, 'unknown', 'not_applicable') for p in purposes)):
                raise EntryStorageInvalid('qualification_policy_ambiguous_rule')
            if any(p['type'] == 'organized_tour_group' and p['minimum'] > p['maximum'] for p in rule['all']):
                raise EntryStorageInvalid('qualification_policy_group_range')
        encoded = json.dumps(checked, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        if len(encoded.encode('utf-8')) > 65536:
            raise EntryStorageInvalid('qualification_policy_size')
        object.__setattr__(self, 'encoded', encoded)

    @property
    def document(self):
        return json.loads(self.encoded)

    @property
    def digest(self):
        return _hash(self.document)


def configured_policy(settings):
    raw = settings.kg_qualification_policy
    return QualificationPolicy(raw) if raw else None
