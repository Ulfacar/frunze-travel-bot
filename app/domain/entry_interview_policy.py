"""Explicit operator/privacy authority for the local interview; defaults are empty."""
from dataclasses import asdict,dataclass
import re

from app.domain.entry_portal_policy import day,opaque,proof
from app.domain.entry_storage import EntryStorageInvalid,_authorize,_hash
from app.domain.service_authz import PermissionDenied
from app.knowledge import interview_catalog as catalog


def existing_full_admins():
    # Trust the current server configuration; never accept a browser owner registry.
    from app.config import settings
    from app.core.manager_scope import bot_scope_for
    result={settings.admin_user.strip().lower()} if settings.admin_user.strip() else set()
    for manager in settings.managers:
        public=dict(login=manager.login,name=manager.name,admin=manager.admin)
        if bot_scope_for(public,admin_user=settings.admin_user) is None:result.add(manager.login.strip().lower())
    return frozenset(result)


@dataclass(frozen=True)
class InterviewPolicy:
    reference:str
    proof:str
    source_reference:str
    source_proof:str
    privacy_reference:str
    privacy_proof:str
    consent_version:str
    terms_version:str
    catalog_hash:str
    operators:tuple[str,...]
    pre_consent:tuple[str,...]
    valid_from:str
    review_due_on:str

    def __post_init__(self):
        for value in (self.reference,self.source_reference,self.privacy_reference,self.consent_version,self.terms_version):opaque(value)
        for value in (self.proof,self.source_proof,self.privacy_proof,self.catalog_hash):proof(value)
        try:document=catalog.by_digest(self.catalog_hash)
        except ValueError:raise EntryStorageInvalid('invalid_interview_policy') from None
        if day(self.valid_from)>day(self.review_due_on):raise EntryStorageInvalid('invalid_interview_policy')
        if (type(self.operators) is not tuple or not 1<=len(self.operators)<=20 or len(set(self.operators))!=len(self.operators)
            or any(type(v) is not str or not re.fullmatch('[a-z0-9_.-]{1,64}',v) or v in ('bot','system') for v in self.operators)):
            raise EntryStorageInvalid('invalid_interview_operators')
        allowed={f['path'] for f in document['fields']}
        if (type(self.pre_consent) is not tuple or len(self.pre_consent)>len(allowed) or
            any(type(v) is not str or v not in allowed for v in self.pre_consent) or len(set(self.pre_consent))!=len(self.pre_consent)):
            raise EntryStorageInvalid('invalid_pre_consent_fields')
        required={'language','consent.given','consent.on','consent.evidence_ref','consent.evidence_sha256'}
        if not required<=set(self.pre_consent):raise EntryStorageInvalid('interview_consent_protocol_not_authorized')

    def document(self):
        value=asdict(self);value['operators']=sorted(self.operators);value['pre_consent']=sorted(self.pre_consent)
        return dict(format='kg-interview-policy/1',**value)

    @property
    def digest(self):return _hash(self.document())


def policy_from_document(value):
    try:
        if type(value) is not dict or value.get('format')!='kg-interview-policy/1':raise ValueError
        fields=dict(value);fields.pop('format')
        for key in ('operators','pre_consent'):
            if type(fields[key]) is not list:raise ValueError
            fields[key]=tuple(fields[key])
        result=InterviewPolicy(**fields)
        if result.document()!=value:raise ValueError
        return result
    except (ValueError,KeyError,TypeError):raise EntryStorageInvalid('invalid_interview_policy') from None


def authorize(actor,policy,*,on):
    _authorize(actor)
    if not isinstance(policy,InterviewPolicy):raise PermissionDenied('interview_policy_required')
    if actor.manager_id not in policy.operators or actor.manager_id not in existing_full_admins():raise PermissionDenied('interview_operator_denied')
    if not day(policy.valid_from)<=on<=day(policy.review_due_on):raise PermissionDenied('interview_policy_expired')
    return policy
