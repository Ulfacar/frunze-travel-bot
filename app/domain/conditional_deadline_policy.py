"""Default-empty, server-only authority for source-specific review reminders."""
from dataclasses import dataclass

from app.domain.conditional_deadline_rules import ConditionalPolicy
from app.domain.entry_anchor_rules import AnchorPolicy, fail
from app.domain.entry_storage import _hash
from app.domain.knowledge_publication_rules import PublicationPolicy
from app.domain.knowledge_publication import _policy as publication_document
from app.knowledge.work_calendar import WorkCalendars


@dataclass(frozen=True)
class ConditionalAuthority:
    policy: ConditionalPolicy
    anchors: AnchorPolicy
    publication: PublicationPolicy
    calendars: WorkCalendars

    def __post_init__(self):
        self.validate()
        object.__setattr__(self, 'calendars', WorkCalendars(self.calendars.export()))

    def validate(self):
        if not isinstance(self.policy, ConditionalPolicy) or not isinstance(self.anchors, AnchorPolicy) or not isinstance(self.publication, PublicationPolicy) or not isinstance(self.calendars, WorkCalendars):
            fail('conditional_deadline_authority_required')
        p = self.policy.document
        if (p['anchor_policy_hash'] != self.anchors.digest or p['publication_policy_hash'] != _hash(publication_document(self.publication)) or
                WorkCalendars(self.calendars.export()).content_hash != p['calendar_hash']):
            fail('conditional_deadline_authority_changed')
        return self

    @property
    def document(self):
        self.validate()
        return dict(policy=self.policy.document, anchors=self.anchors.document,
            publication=publication_document(self.publication), calendars=self.calendars.export())


def from_document(document):
    from app.domain.entry_anchor_rules import shape
    shape(document, ('policy', 'anchors', 'publication', 'calendars'))
    pp = document['publication']; shape(pp, ('reference', 'fingerprint', 'publishers'))
    if type(pp['publishers']) is not list: fail('conditional_deadline_authority_invalid')
    return ConditionalAuthority(ConditionalPolicy(document['policy']), AnchorPolicy(document['anchors']),
        PublicationPolicy(pp['reference'], pp['fingerprint'], tuple(pp['publishers'])), WorkCalendars(document['calendars']))


def configured(settings, rule_id):
    values = getattr(settings, 'kg_conditional_deadline_authorities', [])
    if type(values) is not list or len(values) > 32: fail('conditional_deadline_authority_invalid')
    found = []
    for value in values:
        authority = from_document(value)
        if authority.policy.document['rule_id'] == rule_id: found.append(authority)
    if len(found) > 1: fail('conditional_deadline_authority_ambiguous')
    return found[0] if found else None
