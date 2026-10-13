"""Separate source-bound specialist delegation; no live approval is installed."""
from dataclasses import dataclass
import json
import re

from app.domain.entry_storage import EntryStorageInvalid,_hash
from app.domain.entry_quote_policy import access
from app.domain.service_authz import PermissionDenied
from app.knowledge import quote_rules as rules,specialist_catalog as catalog

FORMAT='kg-specialist-policy/1'
ALGORITHM='kg-specialist-decision/1'


def validated(value):
    rules.exact(value,('format','algorithm','reference','proof','operators','valid_from','review_due_on',
        'source_hash','bundle_hash','projection_hash','condition_catalog_hash','specialist_catalog_hash',
        'interview_policy_hash','interview_catalog_hash','capabilities'))
    if value['format']!=FORMAT or value['algorithm']!=ALGORITHM:rules.fail('invalid_specialist_policy')
    rules.token(value['reference']);rules.proof(value['proof'])
    if rules.day(value['valid_from'])>rules.day(value['review_due_on']):rules.fail('specialist_policy_date_order')
    for key in ('source_hash','bundle_hash','projection_hash','condition_catalog_hash','specialist_catalog_hash',
                'interview_policy_hash','interview_catalog_hash'):rules.proof(value[key])
    source=catalog.load()
    if value['source_hash']!=source['source_sha256'] or value['specialist_catalog_hash']!=catalog.CATALOG_SHA256:
        rules.fail('specialist_source_mismatch')
    operators=value['operators']
    if (type(operators) is not list or not 1<=len(operators)<=20 or
        any(type(v) is not str or not re.fullmatch('[a-z0-9_.-]{1,64}',v) or v in ('bot','system') for v in operators) or
        operators!=sorted(set(operators))):rules.fail('invalid_specialist_operators')
    capabilities=value['capabilities']
    if type(capabilities) is not list or not 1<=len(capabilities)<=20:rules.fail('invalid_specialist_capabilities')
    for cap in capabilities:
        rules.exact(cap,('id','source_pin_hash','review_reference','review_proof','review_on','quote_policy_hash','recipes','unit_pins'))
        rules.token(cap['id']);rules.token(cap['review_reference']);rules.proof(cap['review_proof'])
        rules.proof(cap['source_pin_hash']);rules.proof(cap['quote_policy_hash'])
        definition=catalog.capability(cap['id'])
        if cap['source_pin_hash']!=_hash(catalog.source_pin(cap['id'])):rules.fail('specialist_clause_pins_changed')
        if rules.day(cap['review_on'])>rules.day(value['valid_from']):rules.fail('specialist_future_source_review')
        recipes=cap['recipes'];units=cap['unit_pins']
        if type(recipes) is not list or not 1<=len(recipes)<=20:rules.fail('invalid_specialist_recipes')
        for row in recipes:
            rules.exact(row,('id','hash','minimum_days','maximum_days','urgent'))
            rules.token(row['id']);rules.proof(row['hash'])
            if (type(row['minimum_days']) is not int or type(row['maximum_days']) is not int or
                not 1<=row['minimum_days']<=row['maximum_days']<=definition['maximum_planned_days'] or
                type(row['urgent']) is not bool):rules.fail('invalid_specialist_recipe_scope')
        if [v['id'] for v in recipes]!=sorted(set(v['id'] for v in recipes)):rules.fail('duplicate_specialist_recipe')
        if type(units) is not list or not 1<=len(units)<=100:rules.fail('invalid_specialist_source_units')
        for row in units:
            rules.exact(row,('unit_id','unit_hash'));rules.proof(row['unit_hash'])
            if type(row['unit_id']) is not str or not re.fullmatch(r'KG\.[A-Z0-9_.]+',row['unit_id']):rules.fail('invalid_specialist_source_unit')
        if [v['unit_id'] for v in units]!=sorted(set(v['unit_id'] for v in units)):rules.fail('duplicate_specialist_unit')
        if {v['unit_id'] for v in units}!={v['unit_id'] for v in definition['regime_applicability']}:
            rules.fail('specialist_regime_census_incomplete')
    if [v['id'] for v in capabilities]!=sorted(set(v['id'] for v in capabilities)):rules.fail('duplicate_specialist_capability')
    if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())>262144:rules.fail('specialist_policy_size')
    return value


@dataclass(frozen=True,init=False)
class SpecialistPolicy:
    encoded:str

    def __init__(self,document):
        try:
            validated(document)
            object.__setattr__(self,'encoded',json.dumps(document,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False))
        except (ValueError,KeyError,TypeError,OverflowError,OSError):raise EntryStorageInvalid('invalid_specialist_policy') from None

    def document(self):return json.loads(self.encoded)

    @property
    def digest(self):return _hash(self.document())

    def capability(self,identifier):
        found=[v for v in self.document()['capabilities'] if v['id']==identifier]
        if len(found)!=1:raise PermissionDenied('specialist_capability_not_delegated')
        return found[0]


def authorize(actor,policy,*,on,capability_id=None):
    access(actor)
    if not isinstance(policy,SpecialistPolicy):raise PermissionDenied('specialist_delegation_required')
    value=policy.document()
    if actor.manager_id not in value['operators']:raise PermissionDenied('specialist_operator_not_delegated')
    if not rules.day(value['valid_from'])<=on<=rules.day(value['review_due_on']):raise PermissionDenied('specialist_delegation_expired')
    if capability_id is not None:policy.capability(capability_id)
    return policy


def configured_policy(settings):
    return SpecialistPolicy(settings.kg_specialist_policy) if settings.kg_specialist_policy else None
