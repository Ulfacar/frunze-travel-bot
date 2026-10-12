"""Captured explicit server composition. No HTTP/LLM input or inferred approvals."""
from dataclasses import dataclass

from app.domain.dialogue_policy import DialoguePolicy
from app.domain.dialogue_session_policy import SessionPolicy
from app.domain.current_stay_policy import CurrentStayPolicy, CurrentStayFact
from app.domain.entry_channel_policy import ChannelPolicy
from app.domain.entry_interview_policy import InterviewPolicy
from app.domain.qualification_policy import QualificationPolicy
from app.domain.knowledge_publication_rules import PublicationPolicy
from app.domain.entry_storage import EntryStorageInvalid, _hash
from app.domain.knowledge_publication import _policy as publication_document
from app.knowledge.work_calendar import WorkCalendars


@dataclass(frozen=True)
class DialogueAuthority:
    policy: SessionPolicy
    dialogue: DialoguePolicy
    channel: ChannelPolicy
    interview: InterviewPolicy
    current: CurrentStayPolicy
    fact: CurrentStayFact
    qualification: QualificationPolicy
    publication: PublicationPolicy
    calendars: WorkCalendars

    def __post_init__(self):
        self.validate()
        # Own the calendar data; cached content_hash alone is not protection
        # against a caller later changing the mutable source object's internals.
        object.__setattr__(self, 'calendars', WorkCalendars(self.calendars.export()))

    def validate(self):
        for name, kind in (('policy', SessionPolicy), ('dialogue', DialoguePolicy), ('channel', ChannelPolicy),
            ('interview', InterviewPolicy), ('current', CurrentStayPolicy), ('fact', CurrentStayFact),
            ('qualification', QualificationPolicy), ('publication', PublicationPolicy), ('calendars', WorkCalendars)):
            if not isinstance(getattr(self, name), kind): raise EntryStorageInvalid('dialogue_authority_required')
        p = self.policy.document; d = self.dialogue.document
        if (p['dialogue_policy_hash'] != self.dialogue.digest or p['current_stay_policy_hash'] != self.current.digest or
            p['qualification_policy_hash'] != self.qualification.digest or
            p['publication_policy_hash'] != _hash(publication_document(self.publication)) or
            p['calendar_hash'] != WorkCalendars(self.calendars.export()).content_hash or
            d['channel_policy_hash'] != self.channel.digest or d['interview_policy_hash'] != self.interview.digest or
            self.current.document['qualification_policy_hash'] != self.qualification.digest or
            self.current.document['calendar']['hash'] != p['calendar_hash'] or
            self.fact.document['policy_hash'] != self.current.digest):
            raise EntryStorageInvalid('dialogue_authority_pins_changed')
        return self
