"""Case/person stay evidence; immutable facts, currentness and withdrawal.

This journal never reads the payer's history, grants eligibility or publishes
rules. Callers composing a calculation use the same-session validated reader.
"""
from copy import deepcopy
import re

from sqlalchemy import select,func,cast,Text

from app.domain import applicant_profiles as profiles,entry_applications as applications
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,_authorize,_hash,_id,_key,_normalize_history
from app.domain.knowledge_review import _plain
from app.domain.models import EntryApplicant,EntryApplicantStayHistory,_now
from app.knowledge.review import canonical

MAX_REVISIONS=250
MAX_EVENT_BYTES=1048576
MAX_BYTES=16*1048576
WITHDRAWAL_BYTES=8192
REASONS={'uncertain_history','passport_changed','correction_required'}


def _invalid(code='applicant_history_integrity_failed'):raise EntryStorageInvalid(code)


def _operation(operation):
    if type(operation) is not dict or operation.get('confirmed') is not True:_invalid('applicant_history_confirmation_required')
    action=operation.get('action')
    if action=='save':
        if operation.keys()!={'action','confirmed','profile_id','passport_ref','document'}:_invalid('invalid_applicant_history_operation')
        _id(operation['profile_id'])
        ref=operation['passport_ref']
        if ref is not None and (type(ref) is not str or not re.fullmatch('[a-f0-9]{32}',ref)):_invalid('invalid_passport_reference')
        return {**operation,'document':_normalize_history(operation['document'])}
    if action=='withdraw':
        if operation.keys()!={'action','confirmed','reason'} or type(operation['reason']) is not str or operation['reason'] not in REASONS:
            _invalid('invalid_applicant_history_operation')
        return deepcopy(operation)
    _invalid('invalid_applicant_history_operation')


def _command(actor,case_id,applicant_id,revision,operation):
    return dict(format='kg-applicant-stay/1',actor=actor,case_id=case_id,applicant_id=applicant_id,
        expected_revision=revision,operation=operation)


def _payload(row):
    names=('case_id','applicant_id','profile_id','revision','previous_id','action','request_key',
           'request_hash','command','provenance','created_by')
    return {**{key:_plain(getattr(row,key)) for key in names},'created_at':applications._utc(row.created_at)}


def _size(row):return len(canonical(_payload(row)).encode())


async def _subject(session,case_id,applicant_id,*,write=False):
    case=await applications._case(session,case_id,lock=write)
    await session.scalar(select(EntryApplicant).where(EntryApplicant.id==applicant_id,
        EntryApplicant.case_id==case_id).with_for_update(read=not write,of=EntryApplicant))
    person=await applications._applicant(session,case_id,applicant_id)
    return case,person


async def _history(session,case,person):
    if person.case_id!=case.id:_invalid('applicant_history_scope_mismatch')
    lengths=list((await session.execute(select(EntryApplicantStayHistory.id,
        func.length(cast(EntryApplicantStayHistory.command,Text))+
        func.length(cast(EntryApplicantStayHistory.provenance,Text))).where(
        EntryApplicantStayHistory.applicant_id==person.id).order_by(EntryApplicantStayHistory.revision)
        .limit(MAX_REVISIONS+1))).all())
    # Limit SQL text before decoding JSON. The later canonical payload bound is
    # exact; this larger preflight allows the DB serializer's spaces/escaping.
    if (len(lengths)>MAX_REVISIONS or any(n is None or n>2*MAX_EVENT_BYTES for _,n in lengths) or
        sum(n for _,n in lengths)>2*MAX_BYTES):_invalid('applicant_history_limit')
    rows=list((await session.scalars(select(EntryApplicantStayHistory).where(
        EntryApplicantStayHistory.applicant_id==person.id).order_by(EntryApplicantStayHistory.revision)
        .limit(MAX_REVISIONS+1))).all())
    if len(rows)>MAX_REVISIONS:_invalid('applicant_history_limit')
    profile_rows,_,_=await profiles._history(session,case,person)
    profile_by_id={row.id:row for row in profile_rows}
    previous=None;size=0
    for revision,row in enumerate(rows,1):
        operation=_operation(_plain(row.command).get('operation'))
        expected=_command(row.created_by,case.id,person.id,revision-1,operation)
        pinned=profile_by_id.get(row.profile_id)
        if pinned is None:_invalid()
        provenance=dict(format='kg-applicant-stay-source/1',applicant_hash=person.snapshot_hash,
            profile=dict(id=pinned.id,hash=pinned.snapshot_hash),
            previous=dict(id=previous.id,hash=previous.snapshot_hash) if previous else None)
        if (row.case_id!=case.id or row.revision!=revision or row.action!=operation['action'] or
            row.previous_id!=(previous.id if previous else None) or previous and row.id<=previous.id or
            canonical(row.command)!=canonical(expected) or row.request_hash!=_hash(expected) or row.snapshot_hash!=_hash(_payload(row)) or
            canonical(row.provenance)!=canonical(provenance) or type(row.created_by) is not str or
            not re.fullmatch('[a-z0-9_.-]{1,64}',row.created_by) or row.created_by in ('bot','system') or
            applications._utc(pinned.created_at)>applications._utc(row.created_at) or
            previous and applications._utc(row.created_at)<applications._utc(previous.created_at)):_invalid()
        _key(row.request_key)
        if row.action=='save':
            if row.profile_id!=operation['profile_id'] or operation['document']['as_of']>applications._local_day(row.created_at).isoformat():_invalid()
        elif not previous or previous.action=='withdraw' or row.profile_id!=previous.profile_id:_invalid()
        amount=_size(row);size+=amount
        if amount>MAX_EVENT_BYTES or size>MAX_BYTES:_invalid('applicant_history_limit')
        previous=row
    return rows,size,profile_rows


def _view(row):
    return dict(id=row.id,case_id=row.case_id,applicant_id=row.applicant_id,profile_id=row.profile_id,
        revision=row.revision,action=row.action,operation=_plain(row.command)['operation'],
        provenance=_plain(row.provenance),snapshot_hash=row.snapshot_hash,
        created_by=row.created_by,created_at=applications._utc(row.created_at))


def _evidence(rows,profile_rows,at):
    result=dict(status='missing',history_id=None,profile_id=None,snapshot_hash=None,document=None,
        passport_ref=None,findings=[],eligibility_evaluated=False,may_quote=False)
    if not rows:return result
    row=rows[-1];operation=_plain(row.command)['operation']
    result.update(history_id=row.id,profile_id=row.profile_id,snapshot_hash=row.snapshot_hash)
    if row.action=='withdraw':return {**result,'status':'withdrawn','findings':[operation['reason']]}
    document=deepcopy(operation['document']);findings=[]
    if not profile_rows or row.profile_id!=profile_rows[-1].id:findings.append('profile_changed')
    if applications._utc(row.created_at)>applications._utc(at):findings.append('clock_uncertain')
    if document['as_of']!=applications._local_day(at).isoformat():findings.append('history_needs_current_confirmation')
    if document['history_complete'] is not True:findings.append('history_incomplete')
    if operation['passport_ref'] is None:findings.append('current_passport_unknown')
    if any(not item['confirmed'] for item in document['intervals']):findings.append('history_unconfirmed')
    if any(item['basis']=='unknown' for item in document['intervals']):findings.append('stay_basis_unknown')
    if any(item['passport_ref'] is None or item['passport_ref']!=operation['passport_ref'] for item in document['intervals']):
        findings.append('passport_continuity_requires_review')
    if any(item['passport_country'] is None for item in document['intervals']):findings.append('passport_country_unknown')
    return {**result,'status':'review_required' if findings else 'recorded_inputs',
        'document':document,'passport_ref':operation['passport_ref'],'findings':findings}


async def current_in_session(session,case,person,*,at):
    """Caller owns parent locks; returned data belongs only to this person."""
    rows,_,profile_rows=await _history(session,case,person)
    return _evidence(rows,profile_rows,at)


async def record_history(engine,*,actor,case_id,applicant_id,expected_revision,request_key,operation):
    _authorize(actor);_id(case_id);_id(applicant_id);_key(request_key)
    if type(expected_revision) is not int or not 0<=expected_revision<MAX_REVISIONS:_invalid('invalid_applicant_history_revision')
    operation=_operation(operation)
    command=_command(actor.manager_id,case_id,applicant_id,expected_revision,operation)
    async def write(session):
        case,person=await _subject(session,case_id,applicant_id,write=True)
        rows,size,profile_rows=await _history(session,case,person)
        old=next((row for row in rows if row.request_key==request_key),None)
        if old:
            if old.request_hash!=_hash(command):raise EntryStorageConflict('applicant_history_request_key_reused')
            return _view(old)
        if len(rows)!=expected_revision:raise EntryStorageConflict('applicant_history_revision_changed')
        at=_now();previous=rows[-1] if rows else None
        if previous and applications._utc(at)<applications._utc(previous.created_at):_invalid('applicant_history_clock_reversed')
        if operation['action']=='save':
            if not profile_rows or profile_rows[-1].id!=operation['profile_id']:raise EntryStorageConflict('applicant_history_profile_changed')
            profile=profile_rows[-1]
            if operation['document']['as_of']>applications._local_day(at).isoformat():_invalid('future_applicant_history')
            if len(rows)>=MAX_REVISIONS-1:_invalid('applicant_history_limit')
        else:
            if not previous or previous.action=='withdraw':_invalid('applicant_history_not_current')
            profile=next(row for row in profile_rows if row.id==previous.profile_id)
        if applications._utc(profile.created_at)>applications._utc(at):_invalid('applicant_history_clock_reversed')
        row=EntryApplicantStayHistory(case_id=case.id,applicant_id=person.id,profile_id=profile.id,
            revision=len(rows)+1,previous_id=previous.id if previous else None,action=operation['action'],
            request_key=request_key,request_hash=_hash(command),command=command,created_by=actor.manager_id,created_at=at,
            provenance=dict(format='kg-applicant-stay-source/1',applicant_hash=person.snapshot_hash,
                profile=dict(id=profile.id,hash=profile.snapshot_hash),
                previous=dict(id=previous.id,hash=previous.snapshot_hash) if previous else None))
        amount=_size(row)
        limit=MAX_BYTES if row.action=='withdraw' else MAX_BYTES-WITHDRAWAL_BYTES
        if amount>MAX_EVENT_BYTES or size+amount>limit:_invalid('applicant_history_limit')
        row.snapshot_hash=_hash(_payload(row));session.add(row);await session.flush()
        return _view(row)
    return await applications._run(engine,write)


async def read_history(engine,*,actor,case_id,applicant_id,revision=None):
    _authorize(actor);_id(case_id);_id(applicant_id)
    if revision is not None and (type(revision) is not int or not 1<=revision<=MAX_REVISIONS):_invalid('invalid_applicant_history_revision')
    async def read(session):
        case,person=await _subject(session,case_id,applicant_id)
        rows,size,profile_rows=await _history(session,case,person)
        selected=next((row for row in rows if row.revision==revision),None) if revision else rows[-1] if rows else None
        if revision and selected is None:_invalid('applicant_history_revision_unavailable')
        return dict(current_revision=len(rows),selected=_view(selected) if selected else None,
            language=_plain(profile_rows[-1].input_snapshot).get('language','ru') if profile_rows else 'ru',
            applicant_ordinal=person.ordinal,
            current=_evidence(rows,profile_rows,_now()),latest_profile_id=profile_rows[-1].id if profile_rows else None,
            ordinary_writes_available=len(rows)<MAX_REVISIONS-1 and size<MAX_BYTES-WITHDRAWAL_BYTES,
            history=[dict(id=row.id,revision=row.revision,action=row.action,created_by=row.created_by,
                created_at=applications._utc(row.created_at)) for row in reversed(rows)])
    return await applications._run(engine,read)
