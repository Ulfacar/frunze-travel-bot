"""Explicit authority for bounded binary quarantine; no privacy/business defaults."""
from dataclasses import asdict, dataclass
from datetime import date
import re

from app.domain.entry_storage import EntryStorageInvalid, _authorize, _hash
from app.domain.service_authz import PermissionDenied

HARD_FILE_BYTES = 8 * 1024 * 1024
HARD_APPLICATION_BYTES = 256 * 1024 * 1024
MEDIA = {'application/pdf': {'.pdf'}, 'image/jpeg': {'.jpg', '.jpeg'}}


@dataclass(frozen=True)
class QuarantinePolicy:
    reference: str
    proof: str
    storage: str
    uploaders: tuple[str, ...]
    allowed_types: tuple[str, ...]
    valid_from: str
    review_due_on: str
    max_file_bytes: int
    max_application_files: int
    max_application_bytes: int
    privacy_reference: str
    privacy_proof: str
    retention_reference: str
    retention_proof: str

    def __post_init__(self):
        codes=(self.reference,self.privacy_reference,self.retention_reference)
        hashes=(self.proof,self.privacy_proof,self.retention_proof)
        if (self.storage!='domain_database' or
            any(type(v) is not str or not re.fullmatch(r'[A-Z][A-Z0-9._/-]{0,79}',v) for v in codes) or
            any(type(v) is not str or not re.fullmatch('[a-f0-9]{64}',v) for v in hashes) or
            type(self.uploaders) is not tuple or not 1<=len(self.uploaders)<=20 or
            any(type(v) is not str or not re.fullmatch(r'[a-z0-9_.-]{1,64}',v) or v in ('system','bot') for v in self.uploaders) or
            len(set(self.uploaders))!=len(self.uploaders) or type(self.allowed_types) is not tuple or
            not self.allowed_types or any(type(v) is not str or v not in MEDIA for v in self.allowed_types) or len(set(self.allowed_types))!=len(self.allowed_types) or
            type(self.max_file_bytes) is not int or not 8<=self.max_file_bytes<=HARD_FILE_BYTES or
            type(self.max_application_files) is not int or not 1<=self.max_application_files<=500 or
            type(self.max_application_bytes) is not int or not self.max_file_bytes<=self.max_application_bytes<=HARD_APPLICATION_BYTES):
            raise EntryStorageInvalid('invalid_quarantine_policy')
        try:
            start=date.fromisoformat(self.valid_from); due=date.fromisoformat(self.review_due_on)
            if start.isoformat()!=self.valid_from or due.isoformat()!=self.review_due_on or due<start: raise ValueError
        except (TypeError,ValueError): raise EntryStorageInvalid('invalid_quarantine_policy') from None

    def document(self):
        result=asdict(self)
        result['uploaders']=sorted(self.uploaders); result['allowed_types']=sorted(self.allowed_types)
        return result

    @property
    def digest(self): return _hash(self.document())


def policy_from_document(document):
    if type(document) is not dict or document.keys()!=QuarantinePolicy.__dataclass_fields__.keys():
        raise EntryStorageInvalid('invalid_quarantine_policy')
    value=dict(document)
    for field in ('uploaders','allowed_types'):
        if type(value[field]) is not list: raise EntryStorageInvalid('invalid_quarantine_policy')
        value[field]=tuple(value[field])
    return QuarantinePolicy(**value)


def configured_policy(settings):
    value=settings.kg_document_quarantine_policy
    return policy_from_document(value) if value else None


def authorize_upload(actor,policy,*,day):
    _authorize(actor)
    if not isinstance(policy,QuarantinePolicy) or actor.manager_id not in policy.uploaders:
        raise PermissionDenied('document upload is not authorized by policy')
    if not date.fromisoformat(policy.valid_from)<=day<=date.fromisoformat(policy.review_due_on):
        raise EntryStorageInvalid('quarantine_policy_outdated')


def validate_file(data,*,filename,media_type,policy,expected_sha256=None):
    """Signature checks classify bytes; they never prove content safe."""
    import hashlib
    from pathlib import PurePosixPath
    if (type(filename) is not str or not 1<=len(filename)<=255 or
        any(c in filename for c in '/\\:') or any(ord(c)<32 or ord(c)==127 for c in filename) or
        filename.rstrip(' .')!=filename or media_type not in policy.allowed_types or
        PurePosixPath(filename).suffix.lower() not in MEDIA[media_type]):
        raise EntryStorageInvalid('quarantine_file_type_invalid')
    if type(data) is not bytes or not 8<=len(data)<=policy.max_file_bytes:
        raise EntryStorageInvalid('quarantine_file_size_invalid')
    matches=(re.match(rb'%PDF-(?:1\.[0-7]|2\.0)[\r\n]',data[:10]) is not None if media_type=='application/pdf'
             else data.startswith(b'\xff\xd8\xff'))
    if not matches: raise EntryStorageInvalid('quarantine_file_type_invalid')
    digest=hashlib.sha256(data).hexdigest()
    if expected_sha256 is not None and (type(expected_sha256) is not str or expected_sha256!=digest):
        raise EntryStorageInvalid('quarantine_checksum_mismatch')
    return digest
