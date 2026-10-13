"""Explicit permanent-stop authority and exact private Wappi route identities."""
from dataclasses import dataclass
import json
import re
from urllib.parse import urlsplit

from app.domain.entry_interview_policy import existing_full_admins
from app.domain.entry_storage import EntryStorageInvalid,_authorize,_hash
from app.domain.service_authz import PermissionDenied
from app.knowledge.quote_rules import day,exact,proof,token,QuoteInvalid


def fail(code='invalid_channel_guard'):raise EntryStorageInvalid(code)


def scope(base,profile):
    if type(base) is not str or not 1<=len(base)<=200 or type(profile) is not str:fail()
    if not re.fullmatch('[A-Za-z0-9_-]{1,64}',profile):fail()
    try:
        parsed=urlsplit(base)
        if (parsed.scheme!='https' or not parsed.hostname or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in ('','/') or parsed.port not in (None,443)):
            fail()
        origin='https://'+parsed.hostname.lower()
        if not re.fullmatch(r'https://[a-z0-9]+(?:[a-z0-9.-]*[a-z0-9])?',origin):fail()
    except ValueError:fail()
    return dict(base_url=origin,profile_id=profile)


def recipient(value):
    if type(value) is not str:fail('unsupported_channel_recipient')
    value=value[:-5] if value.endswith('@c.us') else value
    if not re.fullmatch('[1-9][0-9]{7,14}',value):fail('unsupported_channel_recipient')
    return value


def route(base,profile,destination):
    return dict(format='kg-wappi-route/1',channel='whatsapp',**scope(base,profile),recipient=recipient(destination))


def validate_route(value):
    try:
        exact(value,('format','channel','base_url','profile_id','recipient'))
        expected=route(value['base_url'],value['profile_id'],value['recipient'])
        if value!=expected:fail()
        return expected
    except (QuoteInvalid,KeyError,TypeError):fail()


def deployment_scopes():
    from app.config import settings
    values=settings.kg_channel_guard_scopes
    if type(values) is not list or len(values)>20:fail('invalid_channel_guard_activation')
    checked=[]
    for item in values:
        try:
            exact(item,('base_url','profile_id'))
            normalized=scope(item['base_url'],item['profile_id'])
            if item!=normalized:fail('invalid_channel_guard_activation')
        except (QuoteInvalid,KeyError,TypeError):fail('invalid_channel_guard_activation')
        checked.append(_hash(normalized))
    if len(set(checked))!=len(checked):fail('invalid_channel_guard_activation')
    return frozenset(checked)


def route_scope(value):return _hash(scope(value['base_url'],value['profile_id']))


@dataclass(frozen=True)
class ChannelPolicy:
    encoded:str

    def __post_init__(self):
        try:
            if type(self.encoded) is not str or _validated(json.loads(self.encoded))!=self.encoded:fail()
        except (TypeError,ValueError):fail('invalid_channel_stop_policy')

    def document(self):return json.loads(self.encoded)

    @property
    def digest(self):return _hash(self.document())


def _validated(value):
    try:
        exact(value,('format','reference','proof','privacy_reference','privacy_proof','operators','scopes','valid_from','review_due_on'))
        if value['format']!='kg-channel-stop-policy/1':fail()
        for key in ('reference','privacy_reference'):token(value[key])
        for key in ('proof','privacy_proof'):proof(value[key])
        if day(value['valid_from'])>day(value['review_due_on']):fail()
        operators=value['operators'];scopes=value['scopes']
        if (type(operators) is not list or not 1<=len(operators)<=20
            or any(type(v) is not str or not re.fullmatch('[a-z0-9_.-]{1,64}',v) or v in ('bot','system') for v in operators)
            or operators!=sorted(set(operators))):fail()
        if type(scopes) is not list or not 1<=len(scopes)<=20:fail()
        for item in scopes:proof(item)
        if scopes!=sorted(set(scopes)):fail()
        return json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False)
    except (QuoteInvalid,KeyError,TypeError,ValueError):fail('invalid_channel_stop_policy')


def policy_from_document(value):return ChannelPolicy(_validated(value))


def access(actor):
    _authorize(actor)
    if actor.manager_id not in existing_full_admins():raise PermissionDenied('channel_stop_operator_denied')


def authorize(actor,policy,descriptor,*,on):
    access(actor)
    if not isinstance(policy,ChannelPolicy):raise PermissionDenied('channel_stop_policy_required')
    document=policy.document()
    if actor.manager_id not in document['operators']:raise PermissionDenied('channel_stop_operator_denied')
    if not day(document['valid_from'])<=on<=day(document['review_due_on']):raise PermissionDenied('channel_stop_policy_expired')
    key=route_scope(descriptor)
    if key not in document['scopes'] or key not in deployment_scopes():raise PermissionDenied('channel_stop_scope_denied')
    return policy
