"""Trusted server policy for metadata package acceptance; no business defaults."""
from dataclasses import dataclass, asdict
from datetime import date
import re

from app.domain.entry_storage import EntryStorageInvalid, _authorize, _hash
from app.domain.service_authz import PermissionDenied


@dataclass(frozen=True)
class PackagePolicy:
    reference: str
    proof: str
    catalog_digest: str
    reviewers: tuple[str, ...]
    valid_from: str
    review_due_on: str
    privacy_reference: str
    privacy_proof: str
    source_review_reference: str
    source_review_proof: str
    reviewed_source_items: tuple[str, ...]
    consent_required: bool
    practice_checks_required: bool
    allow_metadata_acceptance: bool

    def __post_init__(self):
        codes=(self.reference,self.privacy_reference,self.source_review_reference)
        hashes=(self.proof,self.catalog_digest,self.privacy_proof,self.source_review_proof)
        if (any(type(v) is not str or not re.fullmatch(r'[A-Z][A-Z0-9._/-]{0,79}',v) for v in codes) or
            any(type(v) is not str or not re.fullmatch('[a-f0-9]{64}',v) for v in hashes) or
            type(self.reviewers) is not tuple or not 1<=len(self.reviewers)<=20 or
            any(type(v) is not str or not re.fullmatch(r'[a-z0-9_.-]{1,64}',v) or v in ('system','bot') for v in self.reviewers) or
            len(set(self.reviewers))!=len(self.reviewers) or type(self.reviewed_source_items) is not tuple or
            len(self.reviewed_source_items)>250 or any(type(v) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{1,40}',v) for v in self.reviewed_source_items) or
            len(set(self.reviewed_source_items))!=len(self.reviewed_source_items) or
            any(type(v) is not bool for v in (self.consent_required,self.practice_checks_required,self.allow_metadata_acceptance))):
            raise EntryStorageInvalid('invalid_document_package_policy')
        try:
            start=date.fromisoformat(self.valid_from); due=date.fromisoformat(self.review_due_on)
            if start.isoformat()!=self.valid_from or due.isoformat()!=self.review_due_on or due<start: raise ValueError
        except (TypeError,ValueError): raise EntryStorageInvalid('invalid_document_package_policy_date') from None

    def document(self):
        result=asdict(self); result['reviewers']=sorted(self.reviewers); result['reviewed_source_items']=sorted(self.reviewed_source_items)
        return result

    @property
    def digest(self): return _hash(self.document())


def policy_from_document(value):
    if type(value) is not dict or value.keys()!=PackagePolicy.__dataclass_fields__.keys():
        raise EntryStorageInvalid('invalid_document_package_policy')
    data=dict(value)
    if type(data['reviewers']) is not list or type(data['reviewed_source_items']) is not list:
        raise EntryStorageInvalid('invalid_document_package_policy')
    data['reviewers']=tuple(data['reviewers']); data['reviewed_source_items']=tuple(data['reviewed_source_items'])
    return PackagePolicy(**data)


def configured_policy(settings):
    return policy_from_document(settings.kg_document_package_policy) if settings.kg_document_package_policy else None


def authorize_acceptance(actor,policy,*,catalog_digest,day):
    _authorize(actor)
    if not isinstance(policy,PackagePolicy) or actor.manager_id not in policy.reviewers:
        raise PermissionDenied('document package reviewer is not authorized by policy')
    if not policy.allow_metadata_acceptance:
        raise PermissionDenied('metadata package acceptance is not authorized by policy')
    if policy.catalog_digest!=catalog_digest:
        raise EntryStorageInvalid('package_policy_definition_changed')
    if not date.fromisoformat(policy.valid_from)<=day<=date.fromisoformat(policy.review_due_on):
        raise EntryStorageInvalid('package_policy_outdated')
