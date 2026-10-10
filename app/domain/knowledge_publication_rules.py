"""Publication policy and per-rule eligibility. No default legal authority."""
from dataclasses import dataclass
from datetime import date, datetime, timezone
import re

from app.domain.entry_storage import EntryStorageInvalid, _authorize
from app.domain.service_authz import PermissionDenied


@dataclass(frozen=True)
class PublicationPolicy:
    """Trusted server configuration; never build from an HTTP request body."""
    reference: str
    fingerprint: str
    publishers: tuple[str, ...]

    def __post_init__(self):
        if (not isinstance(self.reference,str) or not re.fullmatch(r'[A-Z][A-Z0-9._/-]{0,79}',self.reference) or
            not isinstance(self.fingerprint,str) or not re.fullmatch('[a-f0-9]{64}',self.fingerprint) or
            type(self.publishers) is not tuple or not 1<=len(self.publishers)<=20 or
            any(not isinstance(p,str) or not re.fullmatch(r'[a-z0-9_.-]{1,64}',p) or p in ('bot','system') for p in self.publishers) or
            len(set(self.publishers))!=len(self.publishers)):
            raise EntryStorageInvalid('knowledge_publication_policy_invalid')


def configured_policy(settings):
    values=(settings.kg_knowledge_policy_ref,settings.kg_knowledge_policy_sha256,settings.kg_knowledge_publishers)
    if not any(values):return None
    return PublicationPolicy(values[0],values[1],tuple(values[2]))


def authorize_publisher(actor, policy):
    _authorize(actor)
    if not isinstance(policy,PublicationPolicy):raise PermissionDenied('knowledge publication policy is not configured')
    if actor.manager_id not in policy.publishers:raise PermissionDenied('knowledge publisher is not authorized by policy')


def _instant(value):
    if not isinstance(value,str):raise ValueError
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:raise ValueError
    return parsed.astimezone(timezone.utc)


def unavailable_reasons(unit, decision, *, day: date, now: datetime):
    """An unavailable unit never disables unrelated approved units in the version."""
    reasons=[]
    if unit['confirmation_status']!='confirmed':reasons.append('source_not_confirmed')
    if unit['label']!='none':reasons.append('source_label_requires_specialist')
    if unit['value'] is None:reasons.append('source_value_missing')
    if unit.get('blocked_value'):reasons.append('source_evidence_unresolved')
    if unit.get('conflict_ref'):reasons.append('source_conflict')
    start=unit.get('effective_from');end=unit.get('effective_to')
    if not start:reasons.append('effective_date_unknown')
    elif date.fromisoformat(start)>day:reasons.append('not_yet_effective')
    if end and date.fromisoformat(end)<day:reasons.append('no_longer_effective')
    if not unit.get('verified_by'):reasons.append('source_verifier_missing')
    try:
        if _instant(unit.get('verified_at'))>now:reasons.append('source_verification_in_future')
    except (ValueError,TypeError):reasons.append('source_verification_date_unknown')
    try:
        if _instant(unit.get('review_due_at'))<=now:reasons.append('source_review_expired')
    except (ValueError,TypeError):reasons.append('source_review_date_unknown')
    if (not unit.get('owner') or unit['owner'].strip().upper() in ('UNASSIGNED','UNKNOWN','НЕ НАЗНАЧЕН') or
        unit['owner'].strip().lower().startswith('unassigned:')):
        reasons.append('source_owner_unknown')
    if decision is None:
        reasons.append('review_evidence_missing')
    else:
        data=decision['decision']
        if data['verdict']!='confirmed':reasons.append('review_not_confirmed')
        if data['evidence_kind']!='official_source':reasons.append('official_source_review_required')
        if date.fromisoformat(data['verified_on'])>day:reasons.append('review_in_future')
        if not data['review_due_on'] or date.fromisoformat(data['review_due_on'])<day:reasons.append('review_expired')
    return reasons
