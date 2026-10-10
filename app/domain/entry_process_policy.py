"""Explicit execution authority for selected edges of the source process draft."""
from dataclasses import dataclass, asdict
from datetime import date
import re

from app.domain.entry_storage import EntryStorageInvalid, _authorize, _hash
from app.domain.service_authz import PermissionDenied
from app.knowledge.process_preview import CATALOG_SHA256, load_process_catalog

ROOTS={'visa':('visa','V01'), 'unified_permit':('work','W01'),
       'registration':('stay','R01'), 'violation_protocol':('regularization','U01')}
ROLES={'visa':'visa','permit':'unified_permit','resident':'resident_card',
       'registration':'registration','protocol':'violation_protocol','exit_visa':'exit_visa'}
ROOT_ROLES={procedure:role for role,procedure in ROLES.items()}
AUTHORITATIVE={
    'consent_confirmed','documents_accepted','documents_current','documents_received',
    'receiving_party_docs_accepted','resident_package_received','corrections_needed','corrections_completed',
    'submission_recorded','application_reference_recorded','decision',
    'issued_document_downloaded','issued_document_checked','delivered_to_client','receipt_confirmed',
    'actual_entry_confirmed','actual_exit_or_end_confirmed','departure_confirmed','exit_visa_issued',
    'service_payment_confirmed','profile_complete','product_defined',
}
ATTESTATION_SOURCES={'client_statement','operator_check','official_document','portal','contract','payment_receipt'}
REFERENCE=r'[A-Z][A-Z0-9._/-]{0,79}'
HASH=r'[a-f0-9]{64}'


def edge_id(edge): return _hash(edge)


@dataclass(frozen=True)
class ProcessPolicy:
    reference: str
    proof: str
    catalog_digest: str
    operators: tuple[str,...]
    valid_from: str
    review_due_on: str
    source_reference: str
    source_proof: str
    allowed_edges: tuple[str,...]
    initial_procedures: tuple[str,...]
    manual_sources: tuple[tuple[str,tuple[str,...]],...]
    full_case_payment_procedures: tuple[str,...]

    def __post_init__(self):
        if (any(type(v) is not str or not re.fullmatch(REFERENCE,v) for v in (self.reference,self.source_reference)) or
            any(type(v) is not str or not re.fullmatch(HASH,v) for v in (self.proof,self.source_proof,self.catalog_digest)) or
            self.catalog_digest!=CATALOG_SHA256):
            raise EntryStorageInvalid('invalid_process_policy')
        for values,allowed in ((self.initial_procedures,set(ROOTS)),(self.full_case_payment_procedures,set(ROLES.values()))):
            if type(values) is not tuple or len(values)>6 or any(type(v) is not str or v not in allowed for v in values) or len(set(values))!=len(values):
                raise EntryStorageInvalid('invalid_process_policy')
        if (type(self.operators) is not tuple or not 1<=len(self.operators)<=20 or
            any(type(v) is not str or not re.fullmatch(r'[a-z0-9_.-]{1,64}',v) or v in ('system','bot') for v in self.operators) or
            len(set(self.operators))!=len(self.operators)):
            raise EntryStorageInvalid('invalid_process_policy')
        catalog=load_process_catalog().document();edges={edge_id(e) for e in catalog['edges']}
        if (type(self.allowed_edges) is not tuple or not 1<=len(self.allowed_edges)<=len(edges) or
            any(type(v) is not str or v not in edges for v in self.allowed_edges) or len(set(self.allowed_edges))!=len(self.allowed_edges)):
            raise EntryStorageInvalid('invalid_process_policy')
        # Completeness is an explicit review of a pinned individual profile;
        # its auxiliary attestation cannot replace the profile itself.
        manual=set(catalog['facts'])-AUTHORITATIVE|{'profile_review_complete'}
        if (type(self.manual_sources) is not tuple or len(self.manual_sources)>len(manual) or
            any(type(v) is not tuple or len(v)!=2 or type(v[0]) is not str or v[0] not in manual for v in self.manual_sources) or
            len({v[0] for v in self.manual_sources})!=len(self.manual_sources)):
            raise EntryStorageInvalid('invalid_process_policy')
        for _,sources in self.manual_sources:
            if (type(sources) is not tuple or not sources or len(sources)>len(ATTESTATION_SOURCES) or
                any(type(v) is not str or v not in ATTESTATION_SOURCES for v in sources) or len(set(sources))!=len(sources)):
                raise EntryStorageInvalid('invalid_process_policy')
        try:
            start=date.fromisoformat(self.valid_from);end=date.fromisoformat(self.review_due_on)
            if start.isoformat()!=self.valid_from or end.isoformat()!=self.review_due_on or end<start:raise ValueError
        except (TypeError,ValueError):raise EntryStorageInvalid('invalid_process_policy') from None

    def document(self):
        result=asdict(self)
        for key in ('operators','allowed_edges','initial_procedures','full_case_payment_procedures'):result[key]=sorted(result[key])
        result['manual_sources']={k:sorted(v) for k,v in result['manual_sources']}
        return result

    @property
    def digest(self):return _hash(self.document())


def policy_from_document(value):
    if type(value) is not dict or value.keys()!=ProcessPolicy.__dataclass_fields__.keys():
        raise EntryStorageInvalid('invalid_process_policy')
    data=dict(value)
    manual=data['manual_sources']
    if type(manual) is not dict or any(type(v) is not list for v in manual.values()):
        raise EntryStorageInvalid('invalid_process_policy')
    data['manual_sources']=tuple((key,tuple(values)) for key,values in manual.items())
    for key in ('operators','allowed_edges','initial_procedures','full_case_payment_procedures'):
        if type(data[key]) is not list:raise EntryStorageInvalid('invalid_process_policy')
        data[key]=tuple(data[key])
    return ProcessPolicy(**data)


def configured_policy(settings):
    return policy_from_document(settings.kg_process_execution_policy) if settings.kg_process_execution_policy else None


def authorize(actor,policy,*,day):
    _authorize(actor)
    if not isinstance(policy,ProcessPolicy) or actor.manager_id not in policy.operators:
        raise PermissionDenied('process operator is not authorized by policy')
    if not date.fromisoformat(policy.valid_from)<=day<=date.fromisoformat(policy.review_due_on):
        raise EntryStorageInvalid('process_policy_outdated')
