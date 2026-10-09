"""Owned transactions and replay-validated immutable document metadata history."""
from sqlalchemy import select

from app.domain import entry_applications as applications
from app.domain.entry_document_rules import (PRODUCTS,MAX_REVISIONS,MAX_HISTORY_BYTES,normalize,apply_operation,summarize)
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid,_authorize,_id,_key,_hash
from app.domain.knowledge_review import _plain
from app.domain.models import EntryDocumentRevision,EntryApplication,_now
from app.knowledge.document_checklist import load_document_catalog,checklist,DocumentChecklistError
from app.knowledge.review import canonical


def _payload(row):
    return dict(case_id=row.case_id,application_id=row.application_id,revision=row.revision,
        previous_id=row.previous_id,request_key=row.request_key,request_hash=row.request_hash,
        command=_plain(row.command),snapshot=_plain(row.snapshot),created_by=row.created_by,
        created_at=applications._utc(row.created_at))


def _command(*,case_id,application_id,expected_revision,operation,actor):
    return dict(case_id=case_id,application_id=application_id,expected_revision=expected_revision,
                operation=operation,actor=actor)


async def _history(session,application):
    rows=list((await session.scalars(select(EntryDocumentRevision).where(
        EntryDocumentRevision.application_id==application.id).order_by(EntryDocumentRevision.revision).limit(MAX_REVISIONS+1))).all())
    if len(rows)>MAX_REVISIONS:raise EntryStorageInvalid('document_history_limit')
    previous=None;snapshot=None;size=0
    for i,row in enumerate(rows,1):
        command=_plain(row.command);stored=_plain(row.snapshot)
        size+=len(canonical(stored).encode())+len(canonical(command).encode())
        if size>MAX_HISTORY_BYTES:raise EntryStorageInvalid('document_history_limit')
        expected=_command(case_id=application.case_id,application_id=application.id,expected_revision=i-1,
                          operation=command['operation'],actor=row.created_by)
        if (row.case_id!=application.case_id or row.revision!=i or row.previous_id!=(previous.id if previous else None)
            or previous and row.id<=previous.id or command!=expected or row.request_hash!=_hash(command)
            or row.snapshot_hash!=_hash(_payload(row))):raise EntryStorageInvalid('document_integrity_failed')
        op=normalize(command['operation'],cutoff=applications._local_day(row.created_at))
        if i==1 and op['data']['product'] not in PRODUCTS[application.procedure]:
            raise EntryStorageInvalid('document_product_mismatch')
        snapshot=apply_operation(snapshot,op,actor=row.created_by,definition=stored.get('definition') if i==1 else None)
        if snapshot!=stored:raise EntryStorageInvalid('document_integrity_failed')
        previous=row
    return rows,size


def _view(row):
    snapshot=_plain(row.snapshot)
    return dict(id=row.id,case_id=row.case_id,application_id=row.application_id,revision=row.revision,
        created_at=applications._utc(row.created_at),created_by=row.created_by,snapshot=snapshot,
        snapshot_hash=row.snapshot_hash,operation=_plain(row.command)['operation'],summary=summarize(snapshot))


async def record_document_operation(engine,*,actor,case_id,application_id,expected_revision,request_key,operation):
    _authorize(actor);_id(case_id);_id(application_id);_key(request_key)
    if type(expected_revision) is not int or not 0<=expected_revision<MAX_REVISIONS:
        raise EntryStorageInvalid('invalid_document_revision')
    operation=normalize(operation,cutoff=applications._today())
    command=_command(case_id=case_id,application_id=application_id,expected_revision=expected_revision,
                     operation=operation,actor=actor.manager_id)
    async def write(session):
        await applications._case(session,case_id)
        application=await applications._application(session,case_id,application_id,lock=True)
        events=await applications._events(session,application)
        rows,size=await _history(session,application)
        old=next((r for r in rows if r.request_key==request_key),None)
        if old:
            if old.request_hash!=_hash(command):raise EntryStorageConflict('request_key_reused')
            return _view(old)
        if len(rows)!=expected_revision:raise EntryStorageConflict('document_revision_changed')
        if events[-1].status in ('approved','refused','closed') or await session.scalar(
            select(EntryApplication.id).where(EntryApplication.previous_id==application.id)):
            raise EntryStorageInvalid('document_application_closed')
        definition=None
        if operation['action']=='initialize':
            product=operation['data']['product']
            if product not in PRODUCTS[application.procedure]:raise EntryStorageInvalid('document_product_mismatch')
            try:
                catalog=load_document_catalog()
                if catalog.digest!=operation['data']['catalog_digest']:raise EntryStorageConflict('document_catalog_changed')
                definition=dict(product=product,catalog_digest=catalog.digest,catalog_version=catalog.document()['version'],items=checklist(catalog,product))
            except DocumentChecklistError:raise EntryStorageInvalid('document_source_unavailable') from None
        snapshot=apply_operation(_plain(rows[-1].snapshot) if rows else None,operation,actor=actor.manager_id,definition=definition)
        if size+len(canonical(snapshot).encode())+len(canonical(command).encode())>MAX_HISTORY_BYTES:
            raise EntryStorageInvalid('document_history_limit')
        row=EntryDocumentRevision(case_id=case_id,application_id=application_id,revision=len(rows)+1,
            previous_id=rows[-1].id if rows else None,request_key=request_key,request_hash=_hash(command),
            command=command,snapshot=snapshot,created_by=actor.manager_id,created_at=_now())
        row.snapshot_hash=_hash(_payload(row));session.add(row);await session.flush()
        return _view(row)
    return await applications._run(engine,write)


async def read_document_inventory(engine,*,actor,case_id,application_id,revision=None):
    _authorize(actor);_id(case_id);_id(application_id)
    if revision is not None and (type(revision) is not int or not 1<=revision<=MAX_REVISIONS):
        raise EntryStorageInvalid('invalid_document_revision')
    async def read(session):
        await applications._case(session,case_id)
        application=await applications._application(session,case_id,application_id)
        events=await applications._events(session,application)
        rows,_=await _history(session,application)
        selected=next((r for r in rows if r.revision==revision),None) if revision else rows[-1] if rows else None
        if revision and selected is None:raise EntryStorageInvalid('document_revision_unavailable')
        return dict(application=applications._application_view(application),application_status=events[-1].status,
            current_revision=len(rows),selected=_view(selected) if selected else None,
            history=[dict(revision=r.revision,created_by=r.created_by,created_at=applications._utc(r.created_at),
                          action=r.command['operation']['action']) for r in reversed(rows)])
    return await applications._run(engine,read)
