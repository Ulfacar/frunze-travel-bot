"""Explicitly delegated, conditional EP filing date for an actual visa-free stay.

The original draft's null deadline value is never changed or silently executed.
A separate server policy pins its interpretation, calendar and end-point rule.
No route approval, residence permission, tasks, writes or delivery is implied.
"""
from dataclasses import dataclass, asdict
from datetime import date
import re

from app.domain import current_stay_stops, entry_applications as apps, applicant_profiles, knowledge_publication, entry_interviews
from app.domain.current_stay_policy import CurrentStayPolicy
from app.domain.entry_storage import EntryStorageInvalid, _authorize, _hash, _id, _plain
from app.knowledge.deadlines import _calculate, DeadlineError
from app.knowledge.work_calendar import WorkCalendars, CalendarError

RULE='KG.DL.EP_BEFORE_VISA_FREE_END'
FORMAT='kg-work-filing-date/1'


@dataclass(frozen=True)
class WorkDeadlinePolicy:
    reference: str
    proof: str
    operators: tuple[str,...]
    valid_from: str
    review_due_on: str
    source_hash: str
    bundle_hash: str
    projection_hash: str
    catalog_hash: str
    rule_hash: str
    current_stay_policy_hash: str
    calendar_hash: str
    calendar_reference: str
    calendar_proof: str
    calendar_valid_from: str
    calendar_review_due_on: str
    count_anchor_day: bool
    boundary_inclusive: bool

    def __post_init__(self):
        for key,value in asdict(self).items():
            if key.endswith('_hash') or key in ('proof','calendar_proof'):
                if type(value) is not str or not re.fullmatch('[a-f0-9]{64}',value):raise EntryStorageInvalid('invalid_work_deadline_policy')
        for value in (self.reference,self.calendar_reference):
            if type(value) is not str or not re.fullmatch('[A-Z][A-Z0-9._/-]{0,79}',value):raise EntryStorageInvalid('invalid_work_deadline_policy')
        if (type(self.operators) is not tuple or not 1<=len(self.operators)<=20 or
                any(type(v) is not str or not re.fullmatch('[a-z0-9_.-]{1,64}',v) or v in ('system','bot') for v in self.operators) or
                len(set(self.operators))!=len(self.operators) or
                type(self.count_anchor_day) is not bool or type(self.boundary_inclusive) is not bool):
            raise EntryStorageInvalid('invalid_work_deadline_policy')
        for start,end in ((self.valid_from,self.review_due_on),(self.calendar_valid_from,self.calendar_review_due_on)):
            try:
                if date.fromisoformat(start).isoformat()!=start or date.fromisoformat(end).isoformat()!=end or start>end:raise ValueError
            except (TypeError,ValueError):raise EntryStorageInvalid('invalid_work_deadline_policy') from None

    @property
    def digest(self):return _hash(self.document())

    def document(self):
        return {**asdict(self),'operators':list(self.operators),'format':FORMAT,'rule_id':RULE,
            'amount':10,'unit':'working_days','direction':'before',
            'anchor':'attested_actual_visa_free_permission_end','scope':'conditional_ep_filing_date_only'}


async def evaluate(engine,*,actor,case_id,applicant_id,policy=None,current_policy=None,fact=None,
                   qualification_policy=None,publication_policy=None,calendars=None):
    _authorize(actor);_id(case_id);_id(applicant_id)
    if policy is not None and not isinstance(policy,WorkDeadlinePolicy):raise EntryStorageInvalid('invalid_work_deadline_policy')
    async def read(session):
        result=dict(format=FORMAT,case_id=case_id,applicant_id=applicant_id,status='unknown',reason=None,
            due_on=None,within_filing_deadline=None,rule_id=RULE,scope='conditional_ep_filing_date_only',
            eligibility_evaluated=False,permission_to_remain=None,permission_to_work=None,may_quote=False,delivery='not_sent',
            requires_specialist=True,operational_action_allowed=False,
            current_stay=None,source=None,policy=None,calendar=None,calculation=None)
        def finish(reason):
            result['reason']=reason;result['evidence_hash']=_hash(result);return result
        # Establish case access/scope even when no calculation authority exists.
        await apps._case(session,case_id,lock=True)
        case,person=await applicant_profiles._subject(session,case_id,applicant_id,write=True)
        if policy is None or actor.manager_id not in policy.operators:return finish('work_deadline_authority_missing')
        if not isinstance(current_policy,CurrentStayPolicy) or current_policy.digest!=policy.current_stay_policy_hash:
            return finish('current_stay_authority_changed')
        current=await current_stay_stops.evaluate_in_session(session,actor=actor,case_id=case_id,applicant_id=applicant_id,
            policy=current_policy,fact=fact,qualification_policy=qualification_policy,
            publication_policy=publication_policy,calendars=calendars)
        result['current_stay']=current
        on=current['as_of'];result['policy']=policy.document()
        if not policy.valid_from<=on<=policy.review_due_on:return finish('work_deadline_authority_expired')
        if any(v['status']=='unknown' for v in current['checks'].values()):return finish('current_stay_unresolved')
        if not current['history'] or current['history']['status']!='recorded_inputs':return finish('personal_stay_unresolved')
        rows,_,_=await applicant_profiles._history(session,case,person)
        profile=_plain(rows[-1].input_snapshot)['profile']
        if (profile.get('current_location')!='in_kg' or profile.get('current_basis_in_kg')!='visa_free' or
                profile.get('purpose')!='work_hire' or profile.get('citizenship')!=['UZB'] or
                profile.get('entry_passport_country')!='UZB' or profile.get('document_type')!='ordinary'):
            return finish('work_deadline_applicability_unresolved')
        if current['interview'] is not None:
            header,pinned=await entry_interviews._header(session,case,person,current['interview']['id'])
            _,state,_=await entry_interviews._history(session,header,pinned)
            if state['answers'].get('purpose',{}).get('value')!='work_hire':
                return finish('work_deadline_interview_purpose_unresolved')
        anchor=(current['checks']['expired_stay']).get('lawful_until')
        if anchor is None:return finish('actual_permission_end_unresolved')
        source=current['source']
        if not source or any(source[k]!=getattr(policy,k) for k in ('source_hash','bundle_hash','projection_hash','catalog_hash')):
            return finish('work_deadline_source_changed')
        context,published=await knowledge_publication._runtime_context(session)
        if published['active']!=source['version_id']:return finish('work_deadline_source_changed')
        _,bundle,_=await context.source(source['version_id'])
        rule=next((r for r in bundle['units'] if r['unit_id']==RULE),None)
        if rule is None or _hash(rule)!=policy.rule_hash:return finish('work_deadline_clause_changed')
        interpretation=dict(value=10,unit='working_days',direction='before',anchor='actual_visa_free_permission_end',
            shift_from_nonworking='none',boundary_inclusive=policy.boundary_inclusive)
        if rule['value'] is not None and rule['value']!=interpretation:return finish('work_deadline_clause_conflicts')
        result['source']=dict(**source,rule_hash=policy.rule_hash,source_value=rule['value'],
            interpretation='separately_delegated_original_clause',section=rule['section'],page=rule['page'])
        if (not isinstance(calendars,WorkCalendars) or calendars.content_hash!=policy.calendar_hash or
                any(c['completeness']!='complete' for c in calendars.describe()) or
                not policy.calendar_valid_from<=on<=policy.calendar_review_due_on):
            return finish('approved_work_calendar_unavailable')
        try:
            calculation=_calculate(interpretation,anchor,dict(count_anchor_day=policy.count_anchor_day,
                month_end=None,hours_mode=None),calendars)
        except (CalendarError,DeadlineError) as exc:return finish(exc.code)
        if any(not policy.calendar_valid_from<=d['date']<=policy.calendar_review_due_on for d in calculation['calendar_trace']):
            return finish('work_calendar_authority_does_not_cover_scan')
        result.update(status='calculated',due_on=calculation['due'],calculation=calculation,
            within_filing_deadline=(on<=calculation['due'] if policy.boundary_inclusive else on<calculation['due']),
            calendar=dict(hash=calendars.content_hash,reference=policy.calendar_reference))
        return finish('conditional_filing_deadline_only')
    return await apps._run(engine,read)
