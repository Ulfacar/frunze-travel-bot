"""Explicit per-route automation delegation; no real assignment is installed."""
from dataclasses import dataclass
import json

from app.domain.entry_storage import EntryStorageInvalid, _document, _hash, _id
from app.domain import entry_channel_policy as channel
from app.knowledge.bundle_schema import DATE, array, obj
from app.knowledge.condition_schema import HASH
from app.knowledge.dialogue_interrupts import VERSION

REF = {'type': 'string', 'pattern': r'^[A-Z][A-Z0-9._/-]{0,79}$'}
ID = {'type': 'integer', 'minimum': 1}
ROUTE = obj({'format': {'const': 'kg-wappi-route/1'}, 'channel': {'const': 'whatsapp'},
    'base_url': {'type': 'string'}, 'profile_id': {'type': 'string'}, 'recipient': {'type': 'string'}})
ASSIGNMENT = obj({'route': ROUTE, 'case_id': ID, 'applicant_id': ID, 'interview_id': ID, 'dialog_id': ID,
    'actor': {'type': 'string', 'pattern': r'^[a-z0-9_.-]{1,64}$'}, 'header_hash': HASH,
    'reference': REF, 'proof': HASH})
SCHEMA = obj({'format': {'const': 'kg-dialogue-policy/1'}, 'reference': REF, 'proof': HASH,
    'privacy_reference': REF, 'privacy_proof': HASH, 'valid_from': DATE, 'review_due_on': DATE,
    'triage_version': {'const': VERSION}, 'interview_policy_hash': HASH, 'channel_policy_hash': HASH,
    'assignments': {**array(ASSIGNMENT, maximum=128), 'minItems': 1}})


@dataclass(frozen=True, init=False)
class DialoguePolicy:
    encoded: str

    def __init__(self, document):
        checked = _document(document, SCHEMA)
        if checked['valid_from'] > checked['review_due_on']:
            raise EntryStorageInvalid('dialogue_policy_date_order')
        routes = set()
        for row in checked['assignments']:
            for key in ('case_id','applicant_id','interview_id','dialog_id'):
                _id(row[key])
            route = channel.validate_route(row['route'])
            if _hash(route) in routes or row['actor'] in ('bot', 'system'):
                raise EntryStorageInvalid('dialogue_assignment_conflict')
            routes.add(_hash(route))
        encoded = json.dumps(checked, sort_keys=True, separators=(',', ':'), allow_nan=False)
        if len(encoded.encode()) > 131072:
            raise EntryStorageInvalid('dialogue_policy_size')
        object.__setattr__(self, 'encoded', encoded)

    @property
    def document(self):
        return json.loads(self.encoded)

    @property
    def digest(self):
        return _hash(self.document)

    def assignment(self, route):
        return next((r for r in self.document['assignments'] if r['route'] == route), None)


def delegated_document(policy, assignment):
    """Receipt retains just its one assignment, with the original policy hash."""
    result = policy.document
    result['assignments'] = [assignment]
    return {'policy': result, 'deployed_policy_hash': policy.digest}
