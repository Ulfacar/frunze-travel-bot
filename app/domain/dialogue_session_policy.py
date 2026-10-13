"""Explicit authority for typed turns and original-fact reconciliation."""
from dataclasses import dataclass
import json

from app.domain.entry_storage import EntryStorageInvalid, _document, _hash
from app.domain.dialogue_policy import REF
from app.domain import entry_channel_policy as channels
from app.knowledge.bundle_schema import DATE, obj
from app.knowledge.condition_schema import HASH
from app.knowledge import dialogue_questions as questions, dialogue_reconciliation as reconciliation

VERSION = 'kg-dialogue-session/1'
SCHEMA = obj({'format': {'const': 'kg-dialogue-session-policy/1'}, 'reference': REF, 'proof': HASH,
    'valid_from': DATE, 'review_due_on': DATE, 'algorithm': {'const': VERSION},
    'question_map_hash': {'const': questions.MAP_HASH}, 'reconciliation_map_hash': {'const': reconciliation.MAP_HASH},
    'dialogue_policy_hash': HASH, 'current_stay_policy_hash': HASH, 'qualification_policy_hash': HASH,
    'publication_policy_hash': HASH, 'calendar_hash': HASH,
    'retained_privacy_processing': {'const': 'original_operator_if_currently_authorized_no_new_collection'},
    'delivery': {'const': 'durable_claim_single_attempt_provider_acceptance_required'}})


@dataclass(frozen=True, init=False)
class SessionPolicy:
    encoded: str

    def __init__(self, document):
        checked = _document(document, SCHEMA)
        if checked['valid_from'] > checked['review_due_on']:
            raise EntryStorageInvalid('dialogue_session_policy_date_order')
        object.__setattr__(self, 'encoded', json.dumps(checked, sort_keys=True, separators=(',', ':'), allow_nan=False))

    @property
    def document(self): return json.loads(self.encoded)

    @property
    def digest(self): return _hash(self.document)


def managed_routes(values):
    """Deployment boundary independent of removable collection authority."""
    if type(values) is not list or len(values) > 128:
        channels.fail('invalid_managed_dialogue_routes')
    routes = [channels.validate_route(v) for v in values]
    if len({_hash(v) for v in routes}) != len(routes):
        channels.fail('invalid_managed_dialogue_routes')
    return {_hash(v): v for v in routes}
