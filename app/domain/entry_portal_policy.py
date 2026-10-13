"""Explicit local authority for portal observations; no shipped real mappings."""
from dataclasses import asdict, dataclass
from datetime import date
import re
import unicodedata

from app.domain.entry_storage import EntryStorageInvalid, _authorize, _hash
from app.domain.service_authz import PermissionDenied

KINDS = {'verification', 'payment', 'correction', 'approval', 'refusal'}
SOURCES = {'portal', 'official_document'}
REFERENCE = r'[A-Z][A-Z0-9._/-]{0,79}'
HASH = r'[a-f0-9]{64}'
PARSER_VERSION = 'literal-observation-v1'


def opaque(value):
    if type(value) is not str or not re.fullmatch(REFERENCE, value):
        raise EntryStorageInvalid('invalid_portal_evidence_reference')
    return value


def proof(value):
    if type(value) is not str or not re.fullmatch(HASH, value):
        raise EntryStorageInvalid('invalid_portal_evidence_proof')
    return value


def day(value):
    try:
        result = date.fromisoformat(value)
        if result.isoformat() != value: raise ValueError
        return result
    except (TypeError, ValueError):
        raise EntryStorageInvalid('invalid_portal_date') from None


def _label(value, *, prefix=False):
    if (type(value) is not str or not 3 <= len(value) <= 100 or
        any(unicodedata.category(c).startswith('C') or c in '<>"\\' for c in value) or
        value.lstrip() != value or (not prefix and value.rstrip() != value) or
        (prefix and not value.endswith(': '))):
        raise EntryStorageInvalid('invalid_portal_policy')


@dataclass(frozen=True)
class PortalPolicy:
    reference: str
    proof: str
    source_namespace: str
    source_reference: str
    source_proof: str
    privacy_reference: str
    privacy_proof: str
    operators: tuple[str, ...]
    valid_from: str
    review_due_on: str
    allow_paste: bool
    manual_sources: tuple[str, ...]
    verification_sources: tuple[str, ...]
    reference_label: str
    date_label: str
    status_label: str
    status_labels: tuple[tuple[str, str], ...]

    def __post_init__(self):
        for v in (self.reference, self.source_namespace, self.source_reference, self.privacy_reference): opaque(v)
        for v in (self.proof, self.source_proof, self.privacy_proof): proof(v)
        if day(self.valid_from) > day(self.review_due_on): raise EntryStorageInvalid('invalid_portal_policy')
        if (type(self.operators) is not tuple or not 1 <= len(self.operators) <= 20 or
            any(type(v) is not str or not re.fullmatch(r'[a-z0-9_.-]{1,64}', v) or v in ('system', 'bot') for v in self.operators) or
            len(set(self.operators)) != len(self.operators) or type(self.allow_paste) is not bool or
            type(self.manual_sources) is not tuple or len(self.manual_sources) > 2 or
            any(type(v) is not str or v not in SOURCES for v in self.manual_sources) or
            len(set(self.manual_sources)) != len(self.manual_sources)):
            raise EntryStorageInvalid('invalid_portal_policy')
        if (type(self.verification_sources) is not tuple or not 1 <= len(self.verification_sources) <= 2 or
            any(type(v) is not str or v not in SOURCES for v in self.verification_sources) or
            len(set(self.verification_sources)) != len(self.verification_sources)):
            raise EntryStorageInvalid('invalid_portal_policy')
        prefixes = (self.reference_label, self.date_label, self.status_label)
        for label in prefixes: _label(label, prefix=True)
        if len(set(prefixes)) != 3 or any(a.startswith(b) for a in prefixes for b in prefixes if a != b):
            raise EntryStorageInvalid('invalid_portal_policy')
        if (type(self.status_labels) is not tuple or not 1 <= len(self.status_labels) <= 20 or
            any(type(v) is not tuple or len(v) != 2 or type(v[0]) is not str or v[0] not in KINDS for v in self.status_labels)):
            raise EntryStorageInvalid('invalid_portal_policy')
        labels = [label for _, label in self.status_labels]
        for label in labels:
            _label(label)
            if label.startswith(prefixes):
                raise EntryStorageInvalid('invalid_portal_policy')
        if len(set(labels)) != len(labels): raise EntryStorageInvalid('invalid_portal_policy')

    def document(self):
        value = asdict(self)
        value['operators'] = sorted(value['operators'])
        value['manual_sources'] = sorted(value['manual_sources'])
        value['verification_sources'] = sorted(value['verification_sources'])
        value['status_labels'] = [list(v) for v in sorted(value['status_labels'])]
        return value

    @property
    def digest(self): return _hash(self.document())


def policy_from_document(value):
    if type(value) is not dict or value.keys() != PortalPolicy.__dataclass_fields__.keys():
        raise EntryStorageInvalid('invalid_portal_policy')
    data = dict(value)
    for key in ('operators', 'manual_sources', 'verification_sources', 'status_labels'):
        if type(data[key]) is not list: raise EntryStorageInvalid('invalid_portal_policy')
        data[key] = tuple(data[key])
    if any(type(v) is not list for v in data['status_labels']): raise EntryStorageInvalid('invalid_portal_policy')
    data['status_labels'] = tuple(tuple(v) for v in data['status_labels'])
    return PortalPolicy(**data)


def configured_policy(settings):
    return policy_from_document(settings.kg_portal_observation_policy) if settings.kg_portal_observation_policy else None


def authorize(actor, policy, *, on, channel=None):
    _authorize(actor)
    if not isinstance(policy, PortalPolicy) or actor.manager_id not in policy.operators:
        raise PermissionDenied('portal observation operator is not authorized')
    if not day(policy.valid_from) <= on <= day(policy.review_due_on):
        raise EntryStorageInvalid('portal_policy_outdated')
    if channel == 'paste' and not policy.allow_paste or channel in SOURCES and channel not in policy.manual_sources:
        raise PermissionDenied('portal observation channel is not authorized')
    if channel is not None and channel not in SOURCES | {'paste'}:
        raise EntryStorageInvalid('invalid_portal_channel')
