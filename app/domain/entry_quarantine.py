"""Atomic binary quarantine and package receipt; no release or content endpoint."""
import hashlib
import re

from sqlalchemy import inspect, select, text

from app.domain import entry_applications as applications, entry_document_packages as packages
from app.domain.entry_package_rules import normalize
from app.domain.entry_quarantine_policy import authorize_upload, policy_from_document, validate_file
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _authorize, _hash, _id, _key
from app.domain.knowledge_review import _plain
from app.domain.models import EntryDocumentPackageEvent, EntryQuarantinedFile
from app.domain.permissions import Actor


async def lock_process_observation(session):
    """Order global quarantine writes with process evidence commits across cases.

    Both writers take this transaction lock before case/application locks. SQLite
    already serializes writers and the owned transaction retries stale snapshots.
    """
    if session.bind.dialect.name == 'postgresql':
        await session.execute(text('SELECT pg_advisory_xact_lock(721613002710)'))


def _payload(row):
    return dict(case_id=row.case_id,application_id=row.application_id,package_event_id=row.package_event_id,
        item_id=row.item_id,document_version=row.document_version,request_key=row.request_key,request_hash=row.request_hash,
        fingerprint=row.fingerprint,byte_size=row.byte_size,media_type=row.media_type,command=_plain(row.command),
        policy=_plain(row.policy),created_by=row.created_by,created_at=applications._utc(row.created_at))


def _view(row):
    return dict(id=row.id,item_id=row.item_id,document_version=row.document_version,
        package_event_id=row.package_event_id,fingerprint=row.fingerprint,byte_size=row.byte_size,
        media_type=row.media_type,created_by=row.created_by,created_at=applications._utc(row.created_at),
        status='quarantined',release_allowed=False)


def _operation(request):
    return dict(action='receive',data=dict(item=request['item_id'],fingerprint=request['fingerprint'],
        on=request['received_on'],source=request['source']),confirmed=True)


def _package_key(request_key):
    return 'quarantine.'+hashlib.sha256(request_key.encode()).hexdigest()[:48]


async def metadata(session,application_id,*,history):
    """Read metadata only; compatible with the database before migration0026."""
    events,states=history
    upload_receipts={row.id for row in events if row.request_key.startswith('quarantine.')}
    connection=await session.connection()
    if not await connection.run_sync(lambda c:inspect(c).has_table('entry_quarantined_files')):
        if upload_receipts: raise EntryStorageInvalid('quarantine_integrity_failed')
        return []
    receipts={event.id:(event,state) for event,state in zip(events,states)}
    rows=(await session.scalars(select(EntryQuarantinedFile)
        .where(EntryQuarantinedFile.application_id==application_id).order_by(EntryQuarantinedFile.id).limit(501))).all()
    if len(rows)>500: raise EntryStorageInvalid('quarantine_integrity_failed')
    if {row.package_event_id for row in rows}!=upload_receipts:
        raise EntryStorageInvalid('quarantine_integrity_failed')
    result=[]
    for row in rows:
        if row.package_event_id not in receipts: raise EntryStorageInvalid('quarantine_integrity_failed')
        receipt,state=receipts[row.package_event_id]
        item=state['items'].get(row.item_id)
        if (receipt.case_id!=row.case_id or receipt.application_id!=application_id or receipt.action!='receive' or
            not item or item['version']!=row.document_version or item['fingerprint']!=row.fingerprint or
            applications._utc(receipt.created_at)!=applications._utc(row.created_at)):
            raise EntryStorageInvalid('quarantine_integrity_failed')
        request=_plain(row.command); policy=policy_from_document(_plain(row.policy))
        expected_fields={'case_id','application_id','actor','expected_revision','expected_document_version',
            'item_id','received_on','source','fingerprint','byte_size','media_type','policy_hash'}
        if type(request) is not dict or request.keys()!=expected_fields:
            raise EntryStorageInvalid('quarantine_integrity_failed')
        authorize_upload(Actor(row.created_by,True),policy,day=applications._local_day(row.created_at))
        operation=normalize(_operation(request),cutoff=applications._local_day(row.created_at))
        expected_event=packages._command(row.case_id,row.application_id,request['expected_revision'],operation,row.created_by)
        if (row.application_id!=application_id or row.snapshot_hash!=_hash(_payload(row)) or row.request_hash!=_hash(request) or
            request!=dict(case_id=row.case_id,application_id=row.application_id,actor=row.created_by,
                expected_revision=receipt.revision-1,expected_document_version=row.document_version-1,item_id=row.item_id,
                received_on=request['received_on'],source=request['source'],fingerprint=row.fingerprint,
                byte_size=row.byte_size,media_type=row.media_type,policy_hash=policy.digest) or
            _plain(receipt.command)['request']!=expected_event or receipt.request_key!=_package_key(row.request_key) or
            row.media_type not in policy.allowed_types or not 8<=row.byte_size<=policy.max_file_bytes):
            raise EntryStorageInvalid('quarantine_integrity_failed')
        result.append(_view(row))
    return result


async def record_upload(engine,*,actor,case_id,application_id,expected_revision,expected_document_version,
                        item_id,request_key,received_on,source,data,filename,media_type,policy,expected_sha256=None):
    _authorize(actor); _id(case_id); _id(application_id); _key(request_key)
    authorize_upload(actor,policy,day=applications._today())
    fingerprint=validate_file(data,filename=filename,media_type=media_type,policy=policy,expected_sha256=expected_sha256)
    if (type(expected_revision) is not int or not 1<=expected_revision<500 or
        type(expected_document_version) is not int or not 0<=expected_document_version<500 or
        type(item_id) is not str or not re.fullmatch('[a-z][a-z0-9_]{1,40}',item_id)):
        raise EntryStorageInvalid('invalid_quarantine_request')
    request=dict(case_id=case_id,application_id=application_id,actor=actor.manager_id,
        expected_revision=expected_revision,expected_document_version=expected_document_version,item_id=item_id,
        received_on=received_on,source=source,fingerprint=fingerprint,byte_size=len(data),media_type=media_type,policy_hash=policy.digest)
    operation=normalize(_operation(request),cutoff=applications._today())
    request_hash=_hash(request)

    async def write(session):
        await lock_process_observation(session)
        await applications._case(session,case_id,lock=True)
        application=await applications._application(session,case_id,application_id,lock=True)
        # Validate the existing full history before relying on its receipt links.
        rows,states,_,_=await packages._history(session,application)
        retained=await metadata(session,application_id,history=(rows,states))
        prior=await session.scalar(select(EntryQuarantinedFile).where(
            EntryQuarantinedFile.application_id==application_id,EntryQuarantinedFile.request_key==request_key))
        if prior:
            if prior.request_hash!=request_hash: raise EntryStorageConflict('request_key_reused')
            stored=await session.scalar(select(EntryQuarantinedFile.content).where(EntryQuarantinedFile.id==prior.id))
            if stored!=data: raise EntryStorageInvalid('quarantine_integrity_failed')
            return _view(prior)
        if len(rows)!=expected_revision: raise EntryStorageConflict('document_package_revision_changed')
        state=states[-1] if states else None
        item=state['items'].get(item_id) if state else None
        if not item or item['version']!=expected_document_version:
            raise EntryStorageConflict('document_version_changed')
        if len(retained)>=policy.max_application_files or sum(r['byte_size'] for r in retained)+len(data)>policy.max_application_bytes:
            raise EntryStorageInvalid('quarantine_quota_reached')
        key=_package_key(request_key)
        if any(row.request_key==key for row in rows): raise EntryStorageConflict('quarantine_receipt_key_reused')
        receipt=await packages._record_package_operation(session,actor=actor,case_id=case_id,application_id=application_id,
            expected_revision=expected_revision,request_key=key,operation=operation)
        stamp=await session.scalar(select(EntryDocumentPackageEvent.created_at).where(EntryDocumentPackageEvent.id==receipt['id']))
        authorize_upload(actor,policy,day=applications._local_day(stamp))
        row=EntryQuarantinedFile(case_id=case_id,application_id=application_id,package_event_id=receipt['id'],item_id=item_id,
            document_version=receipt['snapshot']['items'][item_id]['version'],request_key=request_key,request_hash=request_hash,
            fingerprint=fingerprint,byte_size=len(data),media_type=media_type,command=request,policy=policy.document(),
            created_by=actor.manager_id,created_at=stamp,content=data)
        row.snapshot_hash=_hash(_payload(row)); session.add(row); await session.flush()
        return _view(row)
    return await applications._run(engine,write)


async def verify_file(engine,*,actor,case_id,application_id,file_id):
    """Internal integrity verification returning metadata, never the file bytes."""
    _authorize(actor); _id(case_id); _id(application_id); _id(file_id)
    async def read(session):
        await applications._case(session,case_id)
        application=await applications._application(session,case_id,application_id)
        events,states,_,_=await packages._history(session,application)
        rows=await metadata(session,application_id,history=(events,states))
        row=next((r for r in rows if r['id']==file_id),None)
        if row is None: raise EntryStorageInvalid('quarantine_file_unavailable')
        content=await session.scalar(select(EntryQuarantinedFile.content).where(EntryQuarantinedFile.id==file_id))
        if len(content)!=row['byte_size'] or hashlib.sha256(content).hexdigest()!=row['fingerprint']:
            raise EntryStorageInvalid('quarantine_integrity_failed')
        return row
    return await applications._run(engine,read)
