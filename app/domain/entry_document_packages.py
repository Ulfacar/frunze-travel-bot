"""Bounded immutable full-package journal with explicit, policy-gated acceptance.

Only document metadata is recorded. No upload, portal submission or messages.
Definitions are stored once per explicitly selected, server-bundled version.
"""
from copy import deepcopy
import re

from sqlalchemy import inspect, select

from app.domain import entry_applications as applications, entry_documents as legacy_documents
from app.domain.entry_package_policy import PackagePolicy, authorize_acceptance, policy_from_document
from app.domain.entry_package_rules import MAX_BYTES, MAX_REVISIONS, PRODUCTS, apply_operation, normalize, summarize, assert_acceptable, _passports
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, _authorize, _hash, _id, _key
from app.domain.knowledge_review import _plain
from app.domain.models import EntryApplication, EntryDocumentPackageEvent, _now
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge.complete_document_checklist import load_definition, load_complete_document_catalog, KNOWN_CATALOGS
from app.knowledge.document_checklist import DocumentChecklistError
from app.knowledge.review import canonical

# Even a full journal must retain room to revoke acceptance and withdraw consent.
WITHDRAWAL_SLOTS = 2
WITHDRAWAL_BYTES = 8192


def _invalid(code='document_package_integrity_failed'):
    raise EntryStorageInvalid(code)


def _definition(digest, product):
    try:
        return load_definition(digest, product)
    except DocumentChecklistError:
        _invalid('document_package_source_unavailable')


def _policy_scope(policy):
    try:
        catalog=load_complete_document_catalog(KNOWN_CATALOGS[policy.catalog_digest])
        document=catalog.document()
        identifiers={r['id'] for r in document['clauses']} | {
            'matrix_'+r['id'] for rows in document['matrix'].values() for r in rows}
        if catalog.digest!=policy.catalog_digest or not set(policy.reviewed_source_items)<=identifiers:
            _invalid('invalid_package_policy_source_scope')
    except (KeyError, DocumentChecklistError):
        _invalid('document_package_source_unavailable')


def _command(case_id, application_id, expected_revision, operation, actor):
    return dict(case_id=case_id,application_id=application_id,expected_revision=expected_revision,
                operation=operation,actor=actor)


def _payload(row):
    return dict(case_id=row.case_id,application_id=row.application_id,revision=row.revision,action=row.action,
        previous_id=row.previous_id,legacy_inventory_id=row.legacy_inventory_id,legacy_inventory_hash=row.legacy_inventory_hash,
        definition=_plain(row.definition),request_key=row.request_key,request_hash=row.request_hash,
        state_hash=row.state_hash,command=_plain(row.command),created_by=row.created_by,created_at=applications._utc(row.created_at))


def _bytes(row):
    return len(canonical(_payload(row)).encode())


async def has_package(session, application_id):
    # Keep the legacy editor usable against a database before additive migration0025.
    connection=await session.connection()
    exists=await connection.run_sync(lambda c: inspect(c).has_table('entry_document_package_events'))
    return bool(exists and await session.scalar(select(EntryDocumentPackageEvent.id).where(
        EntryDocumentPackageEvent.application_id==application_id).limit(1)))


async def _history(session, application):
    rows=list((await session.scalars(select(EntryDocumentPackageEvent).where(
        EntryDocumentPackageEvent.application_id==application.id).order_by(EntryDocumentPackageEvent.revision)
        .limit(MAX_REVISIONS+1))).all())
    if len(rows)>MAX_REVISIONS: _invalid('document_package_history_limit')
    state=None; definition=None; previous=None; size=0; snapshots=[]; definitions=[]
    for i,row in enumerate(rows,1):
        command=_plain(row.command); stored_definition=_plain(row.definition)
        size+=_bytes(row)
        if size>MAX_BYTES: _invalid('document_package_history_limit')
        if (type(command) is not dict or command.keys() not in ({'request','policy'},{'request','policy','rules_version'}) or
            type(command['request']) is not dict or 'operation' not in command['request']): _invalid()
        rules_version=command.get('rules_version',1)
        if type(rules_version) is not int or rules_version not in (1,2): _invalid()
        operation=normalize(command['request']['operation'],cutoff=applications._local_day(row.created_at))
        request=_command(application.case_id,application.id,i-1,operation,row.created_by)
        if (row.case_id!=application.case_id or row.revision!=i or row.action!=operation['action'] or
            row.previous_id!=(previous.id if previous else None) or
            previous and (row.id<=previous.id or applications._utc(row.created_at)<applications._utc(previous.created_at)) or
            command['request']!=request or row.request_hash!=_hash(request) or row.snapshot_hash!=_hash(_payload(row)) or
            type(row.created_by) is not str or not re.fullmatch(r'[a-z0-9_.-]{1,64}',row.created_by) or row.created_by in ('system','bot')):
            _invalid()
        _key(row.request_key)
        action=operation['action']; data=operation['data']; legacy=None
        if action in ('initialize','upgrade_definition'):
            product=data['product'] if i==1 else state['product']
            if product not in PRODUCTS[application.procedure]: _invalid('document_product_mismatch')
            definition=_definition(data['catalog_digest'],product)
            if stored_definition!=definition: _invalid()
        elif stored_definition is not None: _invalid()
        if i==1:
            if action!='initialize': _invalid()
            old,_=await legacy_documents._history(session,application)
            if len(old)!=data['legacy_revision']: _invalid('package_legacy_history_changed')
            if old:
                if row.legacy_inventory_id!=old[-1].id or row.legacy_inventory_hash!=old[-1].snapshot_hash: _invalid()
                legacy=_plain(old[-1].snapshot)
            elif row.legacy_inventory_id is not None or row.legacy_inventory_hash is not None: _invalid()
        elif row.legacy_inventory_id is not None or row.legacy_inventory_hash is not None: _invalid()
        policy=None
        if action=='approve':
            policy=policy_from_document(command['policy']); _policy_scope(policy)
            authorize_acceptance(Actor(row.created_by,True),policy,catalog_digest=state['catalog_digest'],day=applications._local_day(row.created_at))
            if data['on']!=applications._local_day(row.created_at).isoformat(): _invalid('invalid_package_approval_date')
        elif command['policy'] is not None: _invalid()
        state=apply_operation(state,operation,actor=row.created_by,definition=definition,legacy=legacy,policy=policy,rules_version=rules_version)
        if row.state_hash!=_hash(state): _invalid()
        snapshots.append(deepcopy(state)); definitions.append(definition); previous=row
    return rows,snapshots,definitions,size


def _legacy_passport_gap(rows,states):
    """Keep old hashes readable, but never approve checks affected by the v1 bug."""
    gap=False
    for index,row in enumerate(rows):
        if row.action in ('initialize','upgrade_definition'): gap=False
        elif index and _plain(row.command).get('rules_version',1)==1:
            before,after=states[index-1],states[index]
            if _passports(before)!=_passports(after) and _passports(before,1)==_passports(after,1): gap=True
    return gap


async def quarantined_fingerprints(session,fingerprints):
    """Deny quarantined bytes across applications without exposing their owners.

    The durable receipt remains a denial even if the binary half is missing.
    Each caller supplies only the bounded fingerprints of its own document view.
    """
    values={value for value in fingerprints if value}
    if not values: return set()
    if len(values)>500: _invalid('invalid_quarantine_scope')
    connection=await session.connection()
    if not await connection.run_sync(lambda c:inspect(c).has_table('entry_document_package_events')): return set()
    fingerprint=EntryDocumentPackageEvent.command['request']['operation']['data']['fingerprint'].as_string()
    return set((await session.scalars(select(fingerprint).where(
        EntryDocumentPackageEvent.request_key.like('quarantine.%'),EntryDocumentPackageEvent.action=='receive',
        fingerprint.in_(values)).distinct())).all())


def _view(row,state,definition):
    return dict(id=row.id,case_id=row.case_id,application_id=row.application_id,revision=row.revision,
        created_by=row.created_by,created_at=applications._utc(row.created_at),snapshot=deepcopy(state),definition=deepcopy(definition),
        snapshot_hash=row.snapshot_hash,state_hash=row.state_hash,operation=_plain(row.command)['request']['operation'],
        summary=summarize(state,definition),approved_in_revision=state['approval'] is not None)


def effective_acceptance(state,definition,policy,*,day):
    approval=state['approval']
    if not approval: return dict(accepted=False,reason=state['last_invalidation'] or 'package_not_approved')
    if not isinstance(policy,PackagePolicy) or approval['policy_hash']!=policy.digest:
        return dict(accepted=False,reason='package_policy_changed')
    try:
        _policy_scope(policy)
        authorize_acceptance(Actor(approval['actor'],True),policy,catalog_digest=state['catalog_digest'],day=day)
        if approval['basis_hash']!=_hash({k:v for k,v in state.items() if k not in ('approval','last_invalidation')}): _invalid()
        assert_acceptable(state,definition,policy)
    except (EntryStorageInvalid,PermissionDenied) as exc:
        return dict(accepted=False,reason=str(exc))
    return dict(accepted=True,reason='approved_current_metadata')


async def _record_package_operation(session,*,actor,case_id,application_id,expected_revision,request_key,operation,policy=None):
    _authorize(actor); _id(case_id); _id(application_id); _key(request_key)
    if type(expected_revision) is not int or not 0<=expected_revision<MAX_REVISIONS: _invalid('invalid_document_package_revision')
    operation=normalize(operation,cutoff=applications._today())
    request=_command(case_id,application_id,expected_revision,operation,actor.manager_id)
    await applications._case(session,case_id,lock=True)
    application=await applications._application(session,case_id,application_id,lock=True)
    events=await applications._events(session,application)
    rows,states,definitions,size=await _history(session,application)
    for index,row in enumerate(rows):
        if row.request_key==request_key:
            if row.request_hash!=_hash(request): raise EntryStorageConflict('request_key_reused')
            return _view(row,states[index],definitions[index])
    if len(rows)!=expected_revision: raise EntryStorageConflict('document_package_revision_changed')
    closed=events[-1].status in ('approved','refused','closed') or await session.scalar(select(EntryApplication.id).where(EntryApplication.previous_id==application.id))
    withdrawal=operation['action']=='revoke' or operation['action']=='consent' and operation['data']['status']=='withdrawn'
    if closed and not withdrawal:
        _invalid('document_application_closed')
    occurred_at=_now(); day=applications._local_day(occurred_at)
    if rows and applications._utc(occurred_at)<applications._utc(rows[-1].created_at): _invalid('document_package_clock_reversed')
    normalize(operation,cutoff=day)
    state=states[-1] if states else None; definition=definitions[-1] if definitions else None
    reserved_only = len(rows) >= MAX_REVISIONS-WITHDRAWAL_SLOTS or size >= MAX_BYTES-WITHDRAWAL_BYTES
    if reserved_only:
        meaningful = state and (operation['action']=='revoke' and state['approval'] or
            operation['action']=='consent' and operation['data']['status']=='withdrawn' and
            state['consent'] and state['consent']['status']=='granted')
        if not meaningful: _invalid('document_package_history_limit')
    action=operation['action']; data=operation['data']; old=[]; legacy=None; approval_policy=None
    if action=='initialize':
        if data['product'] not in PRODUCTS[application.procedure]: _invalid('document_product_mismatch')
        definition=_definition(data['catalog_digest'],data['product'])
        old,_=await legacy_documents._history(session,application)
        if len(old)!=data['legacy_revision']: raise EntryStorageConflict('package_legacy_revision_changed')
        legacy=_plain(old[-1].snapshot) if old else None
    elif action=='upgrade_definition':
        if state is None: _invalid('document_package_missing')
        definition=_definition(data['catalog_digest'],state['product'])
    if action=='approve':
        if state is None: _invalid('document_package_missing')
        if _legacy_passport_gap(rows,states): _invalid('package_passport_recheck_required')
        authorize_acceptance(actor,policy,catalog_digest=state['catalog_digest'],day=day); _policy_scope(policy)
        if data['on']!=day.isoformat(): _invalid('invalid_package_approval_date')
        approval_policy=policy
    if action in ('review','approve'):
        # Imported lazily to keep the metadata journal usable before migration0026.
        from app.domain.entry_quarantine import metadata
        await metadata(session,application_id,history=(rows,states))
        fingerprints={data['fingerprint']} if action=='review' else {
            item['fingerprint'] for item in state['items'].values() if item['status']!='withdrawn'}
        if await quarantined_fingerprints(session,fingerprints): _invalid('document_in_quarantine')
    next_state=apply_operation(state,operation,actor=actor.manager_id,definition=definition,legacy=legacy,policy=approval_policy)
    row=EntryDocumentPackageEvent(case_id=case_id,application_id=application_id,revision=len(rows)+1,action=action,
        previous_id=rows[-1].id if rows else None,legacy_inventory_id=old[-1].id if old else None,
        legacy_inventory_hash=old[-1].snapshot_hash if old else None,
        definition=definition if action in ('initialize','upgrade_definition') else None,
        request_key=request_key,request_hash=_hash(request),state_hash=_hash(next_state),
        command=dict(request=request,policy=approval_policy.document() if approval_policy else None,rules_version=2),created_by=actor.manager_id,created_at=occurred_at)
    row.snapshot_hash=_hash(_payload(row))
    byte_limit=MAX_BYTES if withdrawal else MAX_BYTES-WITHDRAWAL_BYTES
    if size+_bytes(row)>byte_limit: _invalid('document_package_history_limit')
    session.add(row); await session.flush()
    return _view(row,next_state,definition)


async def record_package_operation(engine,*,actor,case_id,application_id,expected_revision,request_key,operation,policy=None):
    # Reserved receipt keys identify the atomic binary pair during recovery.
    _key(request_key)
    if request_key.startswith('quarantine.'): _invalid('reserved_quarantine_request_key')
    async def write(session):
        return await _record_package_operation(session,actor=actor,case_id=case_id,application_id=application_id,
            expected_revision=expected_revision,request_key=request_key,operation=operation,policy=policy)
    return await applications._run(engine,write)


async def read_document_package(engine,*,actor,case_id,application_id,revision=None,policy=None):
    _authorize(actor); _id(case_id); _id(application_id)
    if revision is not None and (type(revision) is not int or not 1<=revision<=MAX_REVISIONS): _invalid('invalid_document_package_revision')
    async def read(session):
        await applications._case(session,case_id)
        application=await applications._application(session,case_id,application_id)
        events=await applications._events(session,application)
        rows,states,definitions,size=await _history(session,application)
        from app.domain.entry_quarantine import metadata
        quarantine=await metadata(session,application_id,history=(rows,states))
        if revision and revision>len(rows): _invalid('document_package_revision_unavailable')
        index=revision-1 if revision else len(rows)-1
        selected=_view(rows[index],states[index],definitions[index]) if rows else None
        fingerprints={item['fingerprint'] for state in ([states[-1],states[index]] if rows else []) for item in state['items'].values()}
        quarantined=await quarantined_fingerprints(session,fingerprints)
        acceptance=effective_acceptance(states[-1],definitions[-1],policy,day=applications._today()) if rows else dict(accepted=False,reason='package_not_initialized')
        if _legacy_passport_gap(rows,states): acceptance=dict(accepted=False,reason='package_passport_recheck_required')
        if rows and any(item['fingerprint'] in quarantined and item['status']!='withdrawn' for item in states[-1]['items'].values()):
            acceptance=dict(accepted=False,reason='document_in_quarantine')
        if selected:
            for item in selected['summary']['rows']:
                item['quarantined']=item['fingerprint'] in quarantined and item['status']!='withdrawn'
                if item['quarantined']:
                    if item['effective_status']=='checked' and item['applicable']:
                        bucket='practice_pending' if item['kind']=='practice' else 'recommended_pending' if item['kind']=='recommended' else 'required_pending'
                        selected['summary']['counts'][bucket]+=1
                    item['effective_status']='quarantined'
            selected['summary']['quarantined_count']=sum(item['quarantined'] for item in selected['summary']['rows'])
        if selected and index==len(rows)-1: selected['summary']['package_accepted']=acceptance['accepted']
        old,_=await legacy_documents._history(session,application)
        return dict(application=applications._application_view(application),application_status=events[-1].status,
            quarantine=quarantine,
            ordinary_writes_available=len(rows)<MAX_REVISIONS-WITHDRAWAL_SLOTS and size<MAX_BYTES-WITHDRAWAL_BYTES,
            current_revision=len(rows),legacy_revision=len(old),legacy_product=old[-1].snapshot['definition']['product'] if old else None,
            selected=selected,current_acceptance=acceptance,
            history=[dict(revision=r.revision,action=r.action,created_by=r.created_by,created_at=applications._utc(r.created_at)) for r in reversed(rows)])
    return await applications._run(engine,read)
