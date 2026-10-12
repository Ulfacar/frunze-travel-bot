"""Scoped immutable stop evidence; a retained ACK never clears later concerns."""
from sqlalchemy import select,cast,Text,func

from app.domain import entry_channel_stops as old_stops,dialogue_stops as old_causes,dialogue_journal as journal
from app.domain import entry_applications as apps
from app.domain.entry_storage import EntryStorageInvalid,_hash,_plain,_id
from app.domain.models import EntryDialogueSession,EntryDialogueEvent
from app.knowledge import quote_rules as rules


def fail():raise EntryStorageInvalid('specialist_interruption_integrity_failed')


def pin(row):return dict(id=row.id,revision=row.revision,hash=row.snapshot_hash)


async def load(session,*,case_id,applicant_id,interview,events):
    """Case lock is already held. Never acquire transport locks in this order.

    STOP writers hold the case lock; delivery outcomes do not. Validate a bounded
    observed prefix and retain only stop identities, so an outcome isn't a new
    personal fact and can't make a recorded planning context fluctuate.
    """
    subject=(case_id,applicant_id)
    stops,_=await old_stops._registry(session,subject=subject)
    causes,_=await old_causes._registry(session,stops,subject=subject)
    scope=[EntryDialogueSession.case_id==case_id,EntryDialogueSession.applicant_id==applicant_id]
    sizes=list((await session.execute(select(EntryDialogueSession.id,
        func.length(cast(EntryDialogueSession.document,Text))).where(*scope).order_by(EntryDialogueSession.id)
        .limit(journal.MAX_SESSIONS+1))).all())
    if len(sizes)>journal.MAX_SESSIONS or any(n is None or n>journal.MAX_HEADER_BYTES for _,n in sizes):fail()
    headers=list((await session.scalars(select(EntryDialogueSession).where(*scope).order_by(EntryDialogueSession.id)
        .limit(journal.MAX_SESSIONS+1))).all())
    if (stops or causes or headers) and interview is None:fail()
    if any(r.interview_id!=interview.id for r in [*stops,*causes,*headers]):fail()
    sessions=[];total=0
    for header in headers:
        journal.validate_header(header)
        cutoff=await session.scalar(select(func.max(EntryDialogueEvent.revision)).where(
            EntryDialogueEvent.session_id==header.id))
        rows,_,size=await journal.history(session,header,interview=interview,events=events,
            through_revision=cutoff or 0,legacy_subject=subject)
        total+=size
        if total>journal.MAX_JOURNAL_BYTES:fail()
        sessions.append(dict(header=header,stops=[r for r in rows if r.kind=='stop']))
    return dict(causes=causes,sessions=sessions)


def observe(loaded,*,at,retained=None):
    causes=loaded['causes'];sessions=loaded['sessions']
    if retained is not None:
        rules.exact(retained,('causes','sessions'))
        if type(retained['causes']) is not list or type(retained['sessions']) is not list:fail()
        wanted=retained['causes'];by_id={r.id:r for r in causes}
        chosen=[]
        for item in wanted:
            rules.exact(item,('id','revision','hash'));_id(item['id']);_id(item['revision']);rules.proof(item['hash'])
            row=by_id.get(item['id'])
            if row is None or pin(row)!=item or row in chosen:fail()
            if row.previous_id is not None and row.previous_id not in {r.id for r in chosen}:fail()
            chosen.append(row)
        if any(row not in chosen and apps._utc(row.created_at)<=apps._utc(at) for row in causes):fail()
        causes=chosen;by_id={r['header'].id:r for r in sessions};chosen=[]
        for item in retained['sessions']:
            rules.exact(item,('id','header_hash','stops'));_id(item['id']);rules.proof(item['header_hash'])
            if type(item['stops']) is not list:fail()
            value=by_id.get(item['id'])
            if value is None or value['header'].snapshot_hash!=item['header_hash'] or any(
                v['header'].id==item['id'] for v in chosen):fail()
            rows=value['stops'][:len(item['stops'])]
            if [pin(row) for row in rows]!=item['stops']:fail()
            if any(apps._utc(r.created_at)<=apps._utc(at) for r in value['stops'][len(rows):]):fail()
            chosen.append(dict(header=value['header'],stops=rows))
        chosen_ids={v['header'].id for v in chosen}
        if any(v['header'].id not in chosen_ids and apps._utc(v['header'].created_at)<=apps._utc(at) for v in sessions):fail()
        sessions=chosen
    pins=dict(causes=[pin(r) for r in causes],sessions=[dict(id=v['header'].id,header_hash=v['header'].snapshot_hash,
        stops=[pin(r) for r in v['stops']]) for v in sessions])
    if retained is not None and _hash(retained)!=_hash(pins):fail()
    errors=[]
    for row in causes:
        doc=_plain(row.document)
        if doc['triage']['reason']!='manager_requested' or doc['collection_blocked']:
            errors.append('specialist_retained_interrupt_requires_review')
        if apps._utc(row.created_at)>apps._utc(at):errors.append('specialist_interrupt_from_future')
    for item in sessions:
        if apps._utc(item['header'].created_at)>apps._utc(at):errors.append('specialist_interrupt_from_future')
        for row in item['stops']:
            doc=_plain(row.document)['payload']
            if doc['reason']!='manager_requested' or doc['collection_blocked']:
                errors.append('specialist_retained_interrupt_requires_review')
            if apps._utc(row.created_at)>apps._utc(at):errors.append('specialist_interrupt_from_future')
    return dict(pins=pins,errors=sorted(set(errors)))
