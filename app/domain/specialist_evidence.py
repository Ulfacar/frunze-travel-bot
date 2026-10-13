"""Locked current observations and replay of the same immutable personal heads."""
from sqlalchemy import select

from app.domain import entry_applications as apps,entry_quotes as quotes
from app.domain import applicant_profiles as profiles,applicant_stay_history as stays,entry_interviews as interviews
from app.domain import knowledge_publication as publication,specialist_facts as facts
from app.domain import specialist_interruptions as interruptions
from app.domain.entry_storage import EntryStorageInvalid,_hash,_plain,_id
from app.domain.models import EntryApplicant,EntryInterview,EntryApplication
from app.knowledge import quote_rules as rules,specialist_catalog


def fail():raise EntryStorageInvalid('specialist_evidence_integrity_failed')


def pin(row):
    return dict(id=row.id,revision=row.revision,hash=row.snapshot_hash) if row else None


def selected(rows,retained):
    if retained is None:return []
    rules.exact(retained,('id','revision','hash'));_id(retained['id']);_id(retained['revision']);rules.proof(retained['hash'])
    if retained['revision']>len(rows) or pin(rows[retained['revision']-1])!=retained:fail()
    return rows[:retained['revision']]


async def lock_subject(session,case_id,applicant_id,application_id=None):
    case=await apps._case(session,case_id,lock=True)
    if application_id is not None:
        application=await apps._application(session,case_id,application_id,lock=True)
        if application.applicant_id!=applicant_id or application.procedure!='visa':fail()
    await session.scalar(select(EntryApplicant).where(EntryApplicant.id==applicant_id,
        EntryApplicant.case_id==case_id).with_for_update(of=EntryApplicant))
    return case,await apps._applicant(session,case_id,applicant_id)


def publication_prefix(history,count):
    if type(count) is not int or not 0<=count<=len(history['rows']):fail()
    states={};manifests={};releases=set();policies={};active=None
    rows=history['rows'][:count]
    for row in rows:
        if row.action=='review':policies[row.version_id]=_plain(row.command)['policy']
        active=publication._transition(states,manifests,releases,active,row.action,row.version_id,_plain(row.snapshot))
    return dict(rows=rows,states=states,manifests=manifests,releases=releases,policies=policies,active=active)


class Evidence:
    """One transaction cache. Caller holds case, application and applicant locks."""
    def __init__(self,session,case,person):
        self.session=session;self.case=case;self.person=person
        self.profiles=None;self.stays=None;self.interview=None;self.applications={}
        self.context=None;self.publication=None
        self.interruptions=None

    async def publication_lock(self):
        if self.context is None:
            self.context,self.publication=await publication._runtime_context(self.session)

    async def histories(self):
        if self.profiles is None:
            self.profiles,_,_=await profiles._history(self.session,self.case,self.person)
            self.stays,_,_=await stays._history(self.session,self.case,self.person)
            ids=list((await self.session.scalars(select(EntryInterview.id).where(
                EntryInterview.case_id==self.case.id,EntryInterview.applicant_id==self.person.id).limit(2))).all())
            if len(ids)>1:fail()
            if ids:
                header,policy=await interviews._header(self.session,self.case,self.person,ids[0])
                events,_,_=await interviews._history(self.session,header,policy)
                self.interview=(header,policy,events)
            self.interruptions=await interruptions.load(self.session,case_id=self.case.id,applicant_id=self.person.id,
                interview=self.interview[0] if self.interview else None,events=self.interview[2] if self.interview else [])

    async def application(self,identifier):
        if identifier not in self.applications:
            app=await apps._application(self.session,self.case.id,identifier)
            if app.applicant_id!=self.person.id or app.procedure!='visa':fail()
            events=await apps._events(self.session,app)
            successor=await self.session.scalar(select(EntryApplication).where(EntryApplication.previous_id==app.id))
            self.applications[identifier]=(app,events,successor)
        return self.applications[identifier]

    def _no_earlier_successor(self,rows,selected_count,at):
        # Later immutable heads are allowed. Equal-time ordering is ambiguous and fails closed; a retained head
        # cannot omit a replacement timestamped at or before its observation.
        if selected_count<len(rows) and apps._utc(rows[selected_count].created_at)<=apps._utc(at):fail()

    async def observe(self,*,at,application_id,policy,interview_policy,publication_policy,retained=None):
        await self.publication_lock();await self.histories()
        on=apps._local_day(at).isoformat();errors=[];pdoc=policy.document()
        cap=policy.capability(facts.CAPABILITY)
        if retained is not None:
            rules.exact(retained,('on','case_id','applicant_id','applicant_hash','profile','history','interview',
                'application','successor','publication','interruptions'))
            if (retained['on']!=on or retained['case_id']!=self.case.id or retained['applicant_id']!=self.person.id or
                retained['applicant_hash']!=self.person.snapshot_hash):fail()
        prows=self.profiles if retained is None else selected(self.profiles,retained['profile'])
        hrows=self.stays if retained is None else selected(self.stays,retained['history'])
        if retained is not None:
            self._no_earlier_successor(self.profiles,len(prows),at)
            self._no_earlier_successor(self.stays,len(hrows),at)
        profile=prows[-1] if prows else None;history=stays._evidence(hrows,prows,at)
        pins=dict(on=on,case_id=self.case.id,applicant_id=self.person.id,applicant_hash=self.person.snapshot_hash,
            profile=pin(profile),history=pin(hrows[-1]) if hrows else None,interview=None,application=None,successor=None,
            publication=None)
        interrupt=interruptions.observe(self.interruptions,at=at,retained=retained['interruptions'] if retained is not None else None)
        pins['interruptions']=interrupt['pins'];errors+=interrupt['errors']
        timed=[self.person,*(prows[-1:] if prows else []),*(hrows[-1:] if hrows else [])]
        state=None;catalog=None
        if (retained is not None and retained['interview'] is None and self.interview and
            apps._utc(self.interview[0].created_at)<=apps._utc(at)):fail()
        if self.interview and (retained is None or retained['interview'] is not None):
            header,original_ip,events=self.interview
            if retained is not None:
                r=retained['interview'];rules.exact(r,('id','header_hash','original_profile_id','head','policy_hash','catalog_hash','ack_hash'))
                events=selected(events,r['head'])
                if not events:fail()
                self._no_earlier_successor(self.interview[2],len(events),at)
            state=_plain(events[-1].snapshot);catalog=_plain(header.catalog)
            pins['interview']=dict(id=header.id,header_hash=header.snapshot_hash,original_profile_id=header.profile_id,
                head=pin(events[-1]),policy_hash=original_ip.digest,catalog_hash=original_ip.catalog_hash,
                ack_hash=_hash(state['ack']))
            timed.extend([header,events[-1]])
            if (interview_policy is None or interview_policy.digest!=original_ip.digest or
                pdoc['interview_policy_hash']!=original_ip.digest or pdoc['interview_catalog_hash']!=original_ip.catalog_hash):
                errors.append('specialist_interview_authority_changed')
            elif not interview_policy.valid_from<=on<=interview_policy.review_due_on:
                errors.append('specialist_interview_authority_expired')
        else:errors.append('specialist_interview_missing')
        if application_id is not None:
            app,events,successor=await self.application(application_id)
            if retained is not None:
                r=retained['application']
                if type(r) is not dict or type(r.get('event_revision')) is not int or not 1<=r['event_revision']<=len(events):fail()
                events=events[:r['event_revision']]
                self._no_earlier_successor(self.applications[application_id][1],len(events),at)
                if retained['successor'] is None:
                    if successor is not None and apps._utc(successor.created_at)<=apps._utc(at):fail()
                    successor=None
            pins['application']=quotes._pin(app,self.person,events[-1])
            pins['successor']=dict(id=successor.id,hash=successor.snapshot_hash) if successor else None
            timed.extend([app,events[-1]])
            if successor:timed.append(successor)
            if successor is not None or events[-1].status in quotes.TERMINAL:errors.append('specialist_application_terminal')
        else:errors.append('specialist_application_missing')
        count=len(self.publication['rows']) if retained is None else retained['publication']['revision']
        if retained is not None:self._no_earlier_successor(self.publication['rows'],count,at)
        pub=publication_prefix(self.publication,count);active=pub['active']
        if pub['rows']:timed.append(pub['rows'][-1])
        pins['publication']=dict(revision=count,head=pin(pub['rows'][-1]) if pub['rows'] else None,
            version_id=active,source_hash=None,bundle_hash=None,projection_hash=None,condition_catalog_hash=None,
            manifest_hash=None,policy=None,required_reviews=[])
        if active is None:errors.append('specialist_source_not_active')
        else:
            version,bundle,projection=await self.context.source(active);manifest=pub['manifests'][active]
            source=pins['publication'];source.update(source_hash=version.source_hash,bundle_hash=version.bundle_hash,
                projection_hash=projection['projection_hash'],condition_catalog_hash=projection['catalog_hash'],
                manifest_hash=_hash(manifest),policy=pub['policies'][active])
            if any(source[k]!=pdoc[k] for k in ('source_hash','bundle_hash','projection_hash','condition_catalog_hash')):
                errors.append('specialist_source_authority_changed')
            if profile is None:errors.append('specialist_profile_missing')
            elif profile.knowledge_version_id!=active:errors.append('specialist_profile_source_changed')
            why=facts.source_scope(bundle,projection['payload']['catalog'],cap['unit_pins'])
            if why:errors.append(why)
            if publication_policy is None or publication._policy(publication_policy)!=pub['policies'][active]:
                errors.append('specialist_publication_policy_changed')
            availability={v['unit_id']:v['reasons'] for v in await self.context.availability(active,manifest,at=at)}
            for uid in specialist_catalog.capability(facts.CAPABILITY)['current_source_units']:
                unit=next((u for u in bundle['units'] if u['unit_id']==uid),None)
                if unit is None:fail()
                reviews=await self.context.reviews(active,unit)
                observed=[r for r in reviews if publication._utc(r.created_at)<=publication._utc(at)]
                source['required_reviews'].append(dict(unit_id=uid,unit_hash=_hash(unit),head=pin(observed[-1]) if observed else None))
                if availability.get(uid,['unpublished']):errors.append('specialist_source_unavailable')
                if retained is None and len(observed)!=len(reviews):errors.append('specialist_source_clock_uncertain')
        if profile is None:errors.append('specialist_profile_missing')
        if any(apps._utc(v.created_at)>apps._utc(at) for v in timed):errors.append('specialist_evidence_from_future')
        if retained is not None and _hash(retained)!=_hash(pins):fail()
        return dict(pins=pins,context_hash=_hash(pins),errors=sorted(set(errors)),
            request=_plain(profile.input_snapshot) if profile else None,state=state,history=history,catalog=catalog)


def assess(observed,*,findings,interview_policy,on):
    if observed['errors']:
        return dict(format=facts.VERSION,reasons=observed['errors'],planned_days=None,alternatives=None,
            pending=list(facts.PENDING),source_eligibility='not_determined',permission_to_work=False,permission_to_stay=False)
    return facts.reconcile(observed['request'],observed['state'],observed['history'],catalog=observed['catalog'],
        interview_policy=interview_policy,findings=findings,on=on)
