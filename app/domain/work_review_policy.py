"""Separate, default-empty authority for a conditional internal review reminder."""
from dataclasses import dataclass
import json

from app.domain.entry_storage import EntryStorageInvalid,_document,_hash
from app.domain.current_stay_policy import CurrentStayPolicy,CurrentStayFact
from app.domain.qualification_policy import QualificationPolicy
from app.domain.knowledge_publication_rules import PublicationPolicy
from app.domain.knowledge_publication import _policy as publication_document
from app.domain.work_deadlines import WorkDeadlinePolicy
from app.knowledge.bundle_schema import DATE,array,obj
from app.knowledge.condition_schema import HASH
from app.knowledge.work_calendar import WorkCalendars

FORMAT='kg-work-review-reminder/1'
POLICY=obj({'format':{'const':FORMAT},'scope':{'const':'conditional_ep_filing_date_review'},
    'reference':{'type':'string','pattern':'^[A-Z][A-Z0-9._/-]{0,79}$'},'proof':HASH,
    'operators':{**array({'type':'string','pattern':'^[a-z0-9_.-]{1,64}$'},maximum=20),'minItems':1},
    'valid_from':DATE,'review_due_on':DATE,'work_policy_hash':HASH,'qualification_policy_hash':HASH,
    'publication_policy_hash':HASH})


@dataclass(frozen=True,init=False)
class ReviewPolicy:
    encoded:str
    def __init__(self,document):
        d=_document(document,POLICY)
        if d['valid_from']>d['review_due_on'] or len(set(d['operators']))!=len(d['operators']) or set(d['operators'])&{'system','bot'}:
            raise EntryStorageInvalid('invalid_work_review_policy')
        object.__setattr__(self,'encoded',json.dumps(d,sort_keys=True,separators=(',',':')))
    @property
    def document(self):return json.loads(self.encoded)
    @property
    def digest(self):return _hash(self.document)


@dataclass(frozen=True)
class WorkReviewAuthority:
    review:ReviewPolicy
    work:WorkDeadlinePolicy
    current:CurrentStayPolicy
    fact:CurrentStayFact
    qualification:QualificationPolicy
    publication:PublicationPolicy
    calendars:WorkCalendars
    def __post_init__(self):
        self.validate()
        object.__setattr__(self,'calendars',WorkCalendars(self.calendars.export()))
    def validate(self):
        for name,kind in (('review',ReviewPolicy),('work',WorkDeadlinePolicy),('current',CurrentStayPolicy),
            ('fact',CurrentStayFact),('qualification',QualificationPolicy),('publication',PublicationPolicy),('calendars',WorkCalendars)):
            if not isinstance(getattr(self,name),kind):raise EntryStorageInvalid('work_review_authority_required')
        d=self.review.document
        if (d['work_policy_hash']!=self.work.digest or d['qualification_policy_hash']!=self.qualification.digest or
            d['publication_policy_hash']!=_hash(publication_document(self.publication)) or
            self.work.current_stay_policy_hash!=self.current.digest or
            self.current.document['qualification_policy_hash']!=self.qualification.digest or
            self.fact.document['policy_hash']!=self.current.digest or
            WorkCalendars(self.calendars.export()).content_hash!=self.work.calendar_hash):
            raise EntryStorageInvalid('work_review_authority_changed')
        return self
    def document(self):
        self.validate()
        return dict(review=self.review.document,work=self.work.document(),current=self.current.document,
            fact=self.fact.document,qualification=self.qualification.document,
            publication=publication_document(self.publication),calendars=self.calendars.export())
    def calculation_args(self):
        self.validate()
        return dict(policy=self.work,current_policy=self.current,fact=self.fact,qualification_policy=self.qualification,
            publication_policy=self.publication,calendars=WorkCalendars(self.calendars.export()))


def from_document(document):
    if type(document) is not dict or document.keys()!=set(('review','work','current','fact','qualification','publication','calendars')):
        raise EntryStorageInvalid('invalid_work_review_authority')
    try:
        wd=document['work'];work=WorkDeadlinePolicy(**{k:tuple(wd[k]) if k=='operators' else wd[k] for k in WorkDeadlinePolicy.__dataclass_fields__})
        if work.document()!=wd:raise ValueError
        pp=document['publication']
        pub=PublicationPolicy(pp['reference'],pp['fingerprint'],tuple(pp['publishers']))
        if publication_document(pub)!=pp:raise ValueError
        return WorkReviewAuthority(ReviewPolicy(document['review']),work,CurrentStayPolicy(document['current']),
            CurrentStayFact(document['fact']),QualificationPolicy(document['qualification']),pub,WorkCalendars(document['calendars']))
    except (KeyError,ValueError,TypeError):raise EntryStorageInvalid('invalid_work_review_authority') from None


def configured(settings,case_id,applicant_id):
    entries=getattr(settings,'kg_work_review_authorities',[])
    if type(entries) is not list or len(entries)>64:raise EntryStorageInvalid('invalid_work_review_authority')
    matching=[]
    for document in entries:
        authority=from_document(document);fact=authority.fact.document
        if fact['case_id']==case_id and fact['applicant_id']==applicant_id:matching.append(authority)
    if len(matching)>1:raise EntryStorageInvalid('ambiguous_work_review_authority')
    return matching[0] if matching else None
