"""Trusted quotation recipes; no live tariff or source approval is shipped."""
from dataclasses import dataclass
import json
import re

from app.domain.entry_interview_policy import existing_full_admins
from app.domain.entry_storage import EntryStorageInvalid,_authorize
from app.domain.service_authz import PermissionDenied
from app.knowledge import quote_rules as rules


def _validated(value):
    rules.exact(value,('format','reference','proof','operators','valid_from','review_due_on','recipes'))
    if value['format']!='kg-quote-policy/1':rules.fail('invalid_quote_policy')
    rules.token(value['reference']);rules.proof(value['proof'])
    if rules.day(value['valid_from'])>rules.day(value['review_due_on']):rules.fail('invalid_quote_validity')
    operators=value['operators'];recipes=value['recipes']
    if (type(operators) is not list or not 1<=len(operators)<=20 or
        any(type(v) is not str or not re.fullmatch('[a-z0-9_.-]{1,64}',v) or v in ('bot','system') for v in operators)
        or operators!=sorted(set(operators))):rules.fail('invalid_quote_operators')
    if type(recipes) is not list or not 1<=len(recipes)<=20:rules.fail('invalid_quote_catalog')
    for recipe in recipes:rules.validate_recipe(recipe)
    ids=[r['id'] for r in recipes]
    if ids!=sorted(set(ids)):rules.fail('invalid_quote_catalog')
    if len(json.dumps(value,ensure_ascii=False,allow_nan=False).encode())>262144:rules.fail('quote_policy_size_limit')
    return value


@dataclass(frozen=True)
class QuotePolicy:
    encoded:str

    def __post_init__(self):
        try:
            if type(self.encoded) is not str or len(self.encoded.encode())>262144:raise ValueError
            value=json.loads(self.encoded);_validated(value)
            if self.encoded!=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False):raise ValueError
        except (ValueError,KeyError,TypeError,OverflowError):raise EntryStorageInvalid('invalid_quote_policy') from None

    def document(self):return json.loads(self.encoded)

    @property
    def digest(self):return rules.digest(self.document())

    @property
    def operators(self):return tuple(self.document()['operators'])

    def recipe(self,identifier):
        matches=[value for value in self.document()['recipes'] if value['id']==identifier]
        if len(matches)!=1:raise EntryStorageInvalid('quote_recipe_unavailable')
        return matches[0]


def policy_from_document(value):
    try:
        _validated(value)
        return QuotePolicy(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False))
    except (ValueError,KeyError,TypeError,OverflowError):raise EntryStorageInvalid('invalid_quote_policy') from None


def access(actor):
    _authorize(actor)
    if actor.manager_id not in existing_full_admins():raise PermissionDenied('quote_operator_denied')


def authorize(actor,policy,*,on):
    access(actor)
    if not isinstance(policy,QuotePolicy):raise PermissionDenied('quote_policy_required')
    if actor.manager_id not in policy.operators:raise PermissionDenied('quote_operator_denied')
    value=policy.document()
    if not rules.day(value['valid_from'])<=on<=rules.day(value['review_due_on']):raise PermissionDenied('quote_policy_expired')
    return policy
