"""Explicit authority to store internal drafts; never authority to send them."""
from dataclasses import dataclass
import json
import re

from app.domain.entry_interview_policy import existing_full_admins
from app.domain.entry_storage import EntryStorageInvalid,_authorize
from app.domain.service_authz import PermissionDenied
from app.knowledge import quote_rules as validation


def _validated(value):
    validation.exact(value,('format','reference','proof','privacy_reference','privacy_proof',
        'source_reference','source_proof','operators','valid_from','review_due_on',
        'renderer_version','catalog_sha256','templates'))
    if value['format']!='kg-notification-storage-policy/1':raise ValueError
    for key in ('reference','privacy_reference','source_reference'):validation.token(value[key])
    for key in ('proof','privacy_proof','source_proof','catalog_sha256'):validation.proof(value[key])
    if validation.day(value['valid_from'])>validation.day(value['review_due_on']):raise ValueError
    if type(value['renderer_version']) is not str or not re.fullmatch(r'kg-notification-renderer/[1-9][0-9]{0,3}',value['renderer_version']):raise ValueError
    operators=value['operators'];templates=value['templates']
    if (type(operators) is not list or not 1<=len(operators)<=20 or
        any(type(v) is not str or not re.fullmatch('[a-z0-9_.-]{1,64}',v) or v in ('bot','system') for v in operators)
        or operators!=sorted(set(operators))):raise ValueError
    if (type(templates) is not list or not 1<=len(templates)<=32 or
        any(type(v) is not str or not re.fullmatch(r'KG\.TPL\.A[0-9]{2}',v) for v in templates)
        or templates!=sorted(set(templates))):raise ValueError
    return value


@dataclass(frozen=True)
class NotificationPolicy:
    encoded:str

    def __post_init__(self):
        try:
            if type(self.encoded) is not str or len(self.encoded.encode())>16384:raise ValueError
            value=json.loads(self.encoded);_validated(value)
            if self.encoded!=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False):raise ValueError
        except (ValueError,KeyError,TypeError,OverflowError):raise EntryStorageInvalid('invalid_notification_policy') from None

    def document(self):return json.loads(self.encoded)

    @property
    def digest(self):return validation.digest(self.document())

    @property
    def operators(self):return tuple(self.document()['operators'])


def policy_from_document(value):
    try:
        _validated(value)
        return NotificationPolicy(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False))
    except (ValueError,KeyError,TypeError,OverflowError):raise EntryStorageInvalid('invalid_notification_policy') from None


def access(actor):
    _authorize(actor)
    if actor.manager_id not in existing_full_admins():raise PermissionDenied('notification_operator_denied')


def authorize(actor,policy,*,on):
    access(actor)
    if not isinstance(policy,NotificationPolicy):raise PermissionDenied('notification_policy_required')
    value=policy.document()
    if actor.manager_id not in policy.operators:raise PermissionDenied('notification_operator_denied')
    if not validation.day(value['valid_from'])<=on<=validation.day(value['review_due_on']):raise PermissionDenied('notification_policy_expired')
    return policy
