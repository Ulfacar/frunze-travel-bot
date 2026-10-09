"""Owned post-issue journal transactions; no sending or legal travel decision."""
from sqlalchemy import select

from app.domain import entry_applications as applications
from app.domain.entry_issued_rules import MAX_REVISIONS,MAX_BYTES,normalize,apply_operation,summarize
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid,_authorize,_id,_key,_hash
from app.domain.knowledge_review import _plain
from app.domain.models import EntryIssuedRevision,_now
from app.knowledge.review import canonical


def _payload(row):
    return dict(case_id=row.case_id,application_id=row.application_id,approval_event_id=row.approval_event_id,
        revision=row.revision,previous_id=row.previous_id,request_key=row.request_key,request_hash=row.request_hash,
        command=_plain(row.command),snapshot=_plain(row.snapshot),created_by=row.created_by,
        created_at=applications._utc(row.created_at))


def _command(case_id,application_id,expected_revision,operation,actor):
    return dict(case_id=case_id,application_id=application_id,expected_revision=expected_revision,operation=operation,actor=actor)


def _approval(application,events):
    last=events[-1]
    return last if (application.procedure in ('visa','exit_visa') and last.status=='approved' and
                    last.source in ('portal','official_document')) else None


async def _history(session,application,approval):
    rows=list((await session.scalars(select(EntryIssuedRevision).where(EntryIssuedRevision.application_id==application.id)
        .order_by(EntryIssuedRevision.revision).limit(MAX_REVISIONS+1))).all())
    if len(rows)>MAX_REVISIONS:raise EntryStorageInvalid('issued_history_limit')
    if rows and approval is None:raise EntryStorageInvalid('issued_integrity_failed')
    previous=None;snapshot=None;size=0
    for i,row in enumerate(rows,1):
        command=_plain(row.command);stored=_plain(row.snapshot)
        size+=len(canonical(command).encode())+len(canonical(stored).encode())
        if size>MAX_BYTES:raise EntryStorageInvalid('issued_history_limit')
        expected=_command(application.case_id,application.id,i-1,command['operation'],row.created_by)
        if (row.case_id!=application.case_id or row.approval_event_id!=approval.id or row.revision!=i or
            row.previous_id!=(previous.id if previous else None) or previous and row.id<=previous.id or
            command!=expected or row.request_hash!=_hash(command) or row.snapshot_hash!=_hash(_payload(row))):
            raise EntryStorageInvalid('issued_integrity_failed')
        operation=normalize(command['operation'],cutoff=applications._local_day(row.created_at))
        snapshot=apply_operation(snapshot,operation,actor=row.created_by,approved_on=approval.occurred_on.isoformat())
        if snapshot!=stored:raise EntryStorageInvalid('issued_integrity_failed')
        previous=row
    return rows,size


def _view(row):
    snapshot=_plain(row.snapshot)
    return dict(id=row.id,revision=row.revision,created_by=row.created_by,created_at=applications._utc(row.created_at),
                approval_event_id=row.approval_event_id,snapshot_hash=row.snapshot_hash,snapshot=snapshot,
                operation=_plain(row.command)['operation'],summary=summarize(snapshot))


async def record_issued_operation(engine,*,actor,case_id,application_id,expected_revision,request_key,operation):
    _authorize(actor);_id(case_id);_id(application_id);_key(request_key)
    if type(expected_revision) is not int or not 0<=expected_revision<MAX_REVISIONS:
        raise EntryStorageInvalid('invalid_issued_revision')
    operation=normalize(operation,cutoff=applications._today())
    command=_command(case_id,application_id,expected_revision,operation,actor.manager_id)
    async def write(session):
        case=await applications._case(session,case_id,lock=True)
        application=await applications._application(session,case_id,application_id,lock=True)
        events=await applications._events(session,application);approval=_approval(application,events)
        rows,size=await _history(session,application,approval)
        old=next((r for r in rows if r.request_key==request_key),None)
        if old:
            if old.request_hash!=_hash(command):raise EntryStorageConflict('request_key_reused')
            return _view(old)
        if len(rows)!=expected_revision:raise EntryStorageConflict('issued_revision_changed')
        if approval is None:raise EntryStorageInvalid('issued_approval_required')
        snapshot=apply_operation(_plain(rows[-1].snapshot) if rows else None,operation,actor=actor.manager_id,
                                 approved_on=approval.occurred_on.isoformat())
        if size+len(canonical(command).encode())+len(canonical(snapshot).encode())>MAX_BYTES:
            raise EntryStorageInvalid('issued_history_limit')
        row=EntryIssuedRevision(case_id=case_id,application_id=application_id,approval_event_id=approval.id,
            revision=len(rows)+1,previous_id=rows[-1].id if rows else None,request_key=request_key,
            request_hash=_hash(command),command=command,snapshot=snapshot,created_by=actor.manager_id,created_at=_now())
        row.snapshot_hash=_hash(_payload(row));session.add(row);await session.flush()
        if operation['action']=='travel':
            from app.domain.entry_deadline_tasks import sync_enabled
            await sync_enabled(session,case,application,actor.manager_id)
        return _view(row)
    return await applications._run(engine,write)


async def read_issued_history(engine,*,actor,case_id,application_id,revision=None):
    _authorize(actor);_id(case_id);_id(application_id)
    if revision is not None and (type(revision) is not int or not 1<=revision<=MAX_REVISIONS):
        raise EntryStorageInvalid('invalid_issued_revision')
    async def read(session):
        await applications._case(session,case_id)
        application=await applications._application(session,case_id,application_id)
        events=await applications._events(session,application);approval=_approval(application,events)
        rows,_=await _history(session,application,approval)
        selected=next((r for r in rows if r.revision==revision),None) if revision else rows[-1] if rows else None
        if revision and selected is None:raise EntryStorageInvalid('issued_revision_unavailable')
        return dict(application=applications._application_view(application),application_status=events[-1].status,
            approval_available=approval is not None,current_revision=len(rows),selected=_view(selected) if selected else None,
            history=[dict(revision=r.revision,created_by=r.created_by,created_at=applications._utc(r.created_at),
                          action=r.command['operation']['action']) for r in reversed(rows)])
    return await applications._run(engine,read)
