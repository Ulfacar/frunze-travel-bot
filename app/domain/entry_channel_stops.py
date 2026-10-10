"""Permanent exact-route handoff latches. No provider calls in writer retries.

Activated senders validate the bounded entire registry, including negative lookups.
Hashes detect inconsistent stored records, not replacement of every DB trust anchor.
"""
import asyncio
from dataclasses import dataclass
import hashlib

from sqlalchemy import select,text,cast,Text,func

from app.domain import entry_applications as applications,entry_interviews as interviews
from app.domain import entry_channel_policy as rules
from app.domain.entry_storage import EntryStorageConflict,_hash,_id,_key,_transaction
from app.domain.knowledge_import import _sessions
from app.domain.knowledge_review import _plain
from app.domain.models import Dialog,EntryChannelStop,EntryInterview,EntryInterviewEvent,_now
from app.domain.service_authz import PermissionDenied
from app.knowledge.review import canonical

MAX_STOPS=128
MAX_ROW_BYTES=65536
MAX_REGISTRY_BYTES=4*1048576
LOCK_TIMEOUT_MS=2000
PROVIDER_TIMEOUT=25


def _exact(value,keys):
    if type(value) is not dict or set(value)!=set(keys):rules.fail('channel_stop_integrity_failed')


def _same(a,b):return canonical(a)==canonical(b)


def _lock_key(value):
    return int.from_bytes(hashlib.sha256(('kg-channel-stop/1:'+value).encode()).digest()[:8],'big',signed=True)


async def _lock(session,descriptor,*,writer=False):
    dialect=session.bind.dialect.name
    if dialect=='sqlite':
        await session.execute(text('PRAGMA busy_timeout=2000'))
        await session.execute(text('BEGIN IMMEDIATE'))
    elif dialect=='postgresql':
        await session.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT_MS}ms'"))
        function='pg_advisory_xact_lock' if writer else 'pg_advisory_xact_lock_shared'
        await session.execute(text(f'SELECT {function}(:key)'),{'key':_lock_key(_hash(descriptor))})
        if writer:await session.execute(text('SELECT pg_advisory_xact_lock(:key)'),{'key':_lock_key('registry-capacity')})
    else:rules.fail('unsupported_channel_guard_database')


def _payload(row):
    return dict(format='kg-channel-stop/1',case_id=row.case_id,applicant_id=row.applicant_id,
        interview_id=row.interview_id,handoff_event_id=row.handoff_event_id,contact_id=row.contact_id,
        dialog_id=row.dialog_id,transport_key=row.transport_key,card_hash=row.card_hash,
        request_key=row.request_key,request_hash=row.request_hash,command=_plain(row.command),
        policy=_plain(row.policy),route=_plain(row.route),source_pin=_plain(row.source_pin),
        authority=_plain(row.authority),created_by=row.created_by,created_at=applications._utc(row.created_at))


def _receipt(row):
    return dict(id=row.id,case_id=row.case_id,applicant_id=row.applicant_id,interview_id=row.interview_id,
        dialog_id=row.dialog_id,card_hash=row.card_hash,route=_plain(row.route),snapshot_hash=row.snapshot_hash,
        created_by=row.created_by,created_at=applications._utc(row.created_at),permanent=True)


def _command(actor,case_id,applicant_id,interview_id,dialog_id,expected_revision,expected_policy_hash,expected_preview_hash):
    return dict(format='kg-channel-bind/1',actor=actor,case_id=case_id,applicant_id=applicant_id,
        interview_id=interview_id,dialog_id=dialog_id,expected_revision=expected_revision,
        policy_hash=expected_policy_hash,preview_hash=expected_preview_hash,confirmed=True)


def _json_size(model,names):
    return sum(func.length(cast(getattr(model,name),Text)) for name in names)


async def _anchor(session,model,identifier,names,limit):
    size=await session.scalar(select(_json_size(model,names)).where(model.id==identifier))
    if size is None or size>limit:rules.fail('channel_stop_anchor_limit')
    return await session.get(model,identifier)


async def _registry(session):
    # Check raw JSON sizes in SQL before decoding or fetching corrupt large blobs.
    sizes=list((await session.execute(select(EntryChannelStop.id,_json_size(EntryChannelStop,
        ('command','policy','route','source_pin','authority'))).order_by(EntryChannelStop.id).limit(MAX_STOPS+1))).all())
    if len(sizes)>MAX_STOPS or any(s is None or s>MAX_ROW_BYTES for _,s in sizes) or sum(s for _,s in sizes)>MAX_REGISTRY_BYTES:
        rules.fail('channel_stop_registry_limit')
    rows=list((await session.scalars(select(EntryChannelStop).order_by(EntryChannelStop.id).limit(MAX_STOPS+1))).all())
    if len(rows)>MAX_STOPS:rules.fail('channel_stop_registry_limit')
    total=0;routes=set();requests=set()
    for row in rows:
        payload=_payload(row);amount=len(canonical(payload).encode());total+=amount
        if amount>MAX_ROW_BYTES or total>MAX_REGISTRY_BYTES:rules.fail('channel_stop_registry_limit')
        descriptor=rules.validate_route(_plain(row.route));policy=rules.policy_from_document(_plain(row.policy))
        doc=policy.document();command=_plain(row.command);pin=_plain(row.source_pin);authority=_plain(row.authority)
        _exact(pin,('dialog','observed_event_id','observed_revision','observed_hash','handoff_revision','handoff_hash','header_hash','preview'))
        _exact(pin['dialog'],('id','contact_id','channel','bot_id','channel_key'))
        _exact(authority,('full_admins',));admins=authority['full_admins']
        for value in (row.id,row.case_id,row.applicant_id,row.interview_id,row.contact_id,row.dialog_id,row.handoff_event_id,
                      pin['observed_event_id'],pin['observed_revision'],pin['handoff_revision']):_id(value)
        for value in (pin['observed_hash'],pin['handoff_hash'],pin['header_hash']):rules.proof(value)
        _key(row.request_key)
        if (type(admins) is not list or not 1<=len(admins)<=100 or any(type(a) is not str for a in admins)
            or admins!=sorted(set(admins)) or row.created_by not in admins or row.created_by not in doc['operators']
            or not rules.day(doc['valid_from'])<=applications._local_day(row.created_at)<=rules.day(doc['review_due_on'])
            or rules.route_scope(descriptor) not in doc['scopes'] or row.transport_key!=_hash(descriptor)
            or row.snapshot_hash!=_hash(payload) or row.request_hash!=_hash(command)
            or row.transport_key in routes or (row.case_id,row.request_key) in requests):rules.fail('channel_stop_integrity_failed')
        expected=_command(row.created_by,row.case_id,row.applicant_id,row.interview_id,row.dialog_id,
            pin['observed_revision'],policy.digest,_hash(pin['preview']))
        if not _same(command,expected):rules.fail('channel_stop_integrity_failed')
        dialog=pin['dialog']
        if (type(dialog['bot_id']) is not str or not dialog['bot_id'] or len(dialog['bot_id'])>64
            or not _same([dialog['id'],dialog['contact_id'],dialog['channel']],[row.dialog_id,row.contact_id,'whatsapp'])
            or rules.recipient(dialog['channel_key'])!=descriptor['recipient']):rules.fail('channel_stop_integrity_failed')
        header=await _anchor(session,EntryInterview,row.interview_id,('command','policy','catalog','source_pin','authority'),1048576)
        event=await _anchor(session,EntryInterviewEvent,row.handoff_event_id,('command','snapshot'),interviews.MAX_EVENT_BYTES)
        observed=await _anchor(session,EntryInterviewEvent,pin['observed_event_id'],('command','snapshot'),interviews.MAX_EVENT_BYTES)
        if header is None or event is None or observed is None:rules.fail('channel_stop_integrity_failed')
        for anchor in (header,event,observed):
            if anchor.case_id!=row.case_id or anchor.applicant_id!=row.applicant_id:rules.fail('channel_stop_integrity_failed')
        if (header.snapshot_hash!=pin['header_hash'] or header.snapshot_hash!=_hash(interviews._header_payload(header))
            or event.interview_id!=row.interview_id or observed.interview_id!=row.interview_id
            or event.revision!=pin['handoff_revision'] or observed.revision!=pin['observed_revision']
            or event.snapshot_hash!=pin['handoff_hash'] or observed.snapshot_hash!=pin['observed_hash']
            or event.snapshot_hash!=_hash(interviews._event_payload(event))
            or observed.snapshot_hash!=_hash(interviews._event_payload(observed))
            or applications._utc(row.created_at)<applications._utc(observed.created_at)
            or applications._utc(row.created_at)<applications._utc(event.created_at)):rules.fail('channel_stop_integrity_failed')
        pinned=interviews.policy_from_document(_plain(header.policy))
        if not _same(_plain(header.catalog),interviews.catalog.by_digest(pinned.catalog_hash)):rules.fail('channel_stop_integrity_failed')
        prior=None
        if event.previous_id is not None:
            prior=await _anchor(session,EntryInterviewEvent,event.previous_id,('command','snapshot'),interviews.MAX_EVENT_BYTES)
            if (prior.interview_id!=header.id or prior.case_id!=row.case_id or prior.applicant_id!=row.applicant_id
                or prior.revision!=event.revision-1 or prior.id>=event.id
                or prior.snapshot_hash!=_hash(interviews._event_payload(prior))
                or prior.snapshot.get('handoff') is not None
                or applications._utc(prior.created_at)>applications._utc(event.created_at)):rules.fail('channel_stop_integrity_failed')
        elif event.revision!=1:rules.fail('channel_stop_integrity_failed')
        operation=interviews._operation(_plain(event.command)['operation'],start=event.revision==1)
        expected_command=interviews._command(header,event.revision-1,event.created_by,operation,event.command['policy_hash'])
        if (not _same(_plain(event.command),expected_command) or event.request_hash!=_hash(expected_command)
            or event.action!=operation['action'] or event.created_by not in pinned.operators
            or event.created_by not in header.authority['full_admins']):rules.fail('channel_stop_integrity_failed')
        reconstructed=interviews._reduce(header,pinned,_plain(prior.snapshot) if prior else interviews._initial(header),operation,
            revision=event.revision,on=applications._local_day(event.created_at).isoformat(),actor=event.created_by)
        if not _same(reconstructed,_plain(event.snapshot)):rules.fail('channel_stop_integrity_failed')
        handoff=_plain(event.snapshot).get('handoff')
        if (type(handoff) is not dict or set(handoff)!= {'card','hash'} or handoff['hash']!=row.card_hash
            or _hash(handoff['card'])!=row.card_hash or not _same(
                [handoff['card'].get(k) for k in ('interview_id','case_id','applicant_id','revision','owner_login')],
                [row.interview_id,row.case_id,row.applicant_id,event.revision,header.owner_login])):rules.fail('channel_stop_integrity_failed')
        preview=pin['preview']
        if not _same(preview,_preview_payload(header,observed,dialog,descriptor,policy,preview.get('on') if type(preview) is dict else None)):
            rules.fail('channel_stop_integrity_failed')
        if preview['on']!=applications._local_day(row.created_at).isoformat():rules.fail('channel_stop_integrity_failed')
        before=_plain(observed.snapshot)
        if before['phase'] in ('active','paused'):
            if (event.revision!=observed.revision+1 or event.previous_id!=observed.id or event.action!='handoff'
                or event.created_by!=row.created_by or applications._utc(event.created_at)!=applications._utc(row.created_at)):
                rules.fail('channel_stop_integrity_failed')
        elif before['phase'] in ('pending','acked'):
            if event.revision>observed.revision or not _same(before['handoff'],handoff):rules.fail('channel_stop_integrity_failed')
        else:rules.fail('channel_stop_integrity_failed')
        routes.add(row.transport_key);requests.add((row.case_id,row.request_key))
    return rows,total


def _preview_payload(header,event,dialog,descriptor,policy,on):
    return dict(format='kg-channel-preview/1',case_id=header.case_id,applicant_id=header.applicant_id,
        interview_id=header.id,header_hash=header.snapshot_hash,revision=event.revision,event_hash=event.snapshot_hash,
        phase=event.snapshot['phase'],card_hash=event.snapshot['handoff']['hash'] if event.snapshot['handoff'] else None,
        owner_login=header.owner_login,dialog=dialog,route=descriptor,policy_hash=policy.digest,on=on)


async def _context(session,actor,case_id,applicant_id,interview_id,dialog_id,resolver,policy,*,lock=False):
    case=await applications._case(session,case_id,lock=lock)
    person=await applications._applicant(session,case_id,applicant_id)
    header,pinned=await interviews._header(session,case,person,interview_id)
    events,state,_=await interviews._history(session,header,pinned)
    query=select(Dialog).where(Dialog.id==dialog_id)
    dialog=await session.scalar(query.with_for_update() if lock else query)
    if dialog is None or dialog.contact_id!=case.contact_id or dialog.channel!='whatsapp':rules.fail('channel_dialog_unavailable')
    if actor.manager_id not in header.authority['full_admins'] or actor.manager_id not in pinned.operators:
        raise PermissionDenied('interview_operator_denied')
    descriptor=rules.validate_route(resolver(dialog.channel,dialog.bot_id,dialog.channel_key))
    if descriptor['recipient']!=rules.recipient(dialog.channel_key):rules.fail('channel_dialog_identity_changed')
    # Case/Dialog waits may cross a policy boundary or the preview's local day.
    at=_now()
    rules.authorize(actor,policy,descriptor,on=applications._local_day(at))
    identity=dict(id=dialog.id,contact_id=dialog.contact_id,channel=dialog.channel,bot_id=dialog.bot_id,channel_key=dialog.channel_key)
    return header,events,state,identity,descriptor,_preview_payload(header,events[-1],identity,descriptor,policy,applications._local_day(at).isoformat()),at


def _input(actor,case_id,applicant_id,interview_id,dialog_id):
    rules.access(actor)
    for value in (case_id,applicant_id,interview_id,dialog_id):_id(value)


async def preview_stop(engine,*,actor,case_id,applicant_id,interview_id,dialog_id,resolver,policy):
    _input(actor,case_id,applicant_id,interview_id,dialog_id)
    async def read(session):
        _,_,_,_,descriptor,preview,_=await _context(session,actor,case_id,applicant_id,interview_id,dialog_id,resolver,policy)
        rows,_=await _registry(session)
        existing=next((r for r in rows if r.transport_key==_hash(descriptor)),None)
        return dict(preview=preview,preview_hash=_hash(preview),existing=_receipt(existing) if existing else None)
    return await applications._run(engine,read)


async def list_stops(engine,*,actor,case_id,applicant_id,interview_id):
    rules.access(actor)
    for value in (case_id,applicant_id,interview_id):_id(value)
    async def read(session):
        case=await applications._case(session,case_id);person=await applications._applicant(session,case_id,applicant_id)
        await interviews._header(session,case,person,interview_id)
        rows,_=await _registry(session)
        dialogs=list((await session.scalars(select(Dialog).where(Dialog.contact_id==case.contact_id,Dialog.channel=='whatsapp').order_by(Dialog.id).limit(101))).all())
        if len(dialogs)>100:rules.fail('channel_dialog_limit')
        try:
            active=rules.deployment_scopes()
            activation={r.id:'active' if rules.route_scope(_plain(r.route)) in active else 'disabled' for r in rows}
        except Exception:activation={r.id:'invalid_fail_closed' for r in rows}
        return dict(stops=[_receipt(r) for r in rows if r.interview_id==interview_id],activation=activation,
            dialogs=[dict(id=d.id,bot_id=d.bot_id,channel_key=d.channel_key) for d in dialogs])
    return await applications._run(engine,read)


async def bind_stop(engine,*,actor,case_id,applicant_id,interview_id,dialog_id,resolver,policy,expected_revision,
                    expected_policy_hash,expected_preview_hash,request_key,confirmed):
    _input(actor,case_id,applicant_id,interview_id,dialog_id);_key(request_key)
    if confirmed is not True or type(expected_revision) is not int or not 1<=expected_revision<=interviews.MAX_EVENTS:rules.fail('channel_confirmation_required')
    rules.proof(expected_policy_hash);rules.proof(expected_preview_hash)
    command=_command(actor.manager_id,case_id,applicant_id,interview_id,dialog_id,expected_revision,expected_policy_hash,expected_preview_hash)
    # Preliminary lookup only determines a lock. No admission or writes before it.
    async with _sessions(engine)() as session:
        prior=await session.scalar(select(EntryChannelStop).where(EntryChannelStop.case_id==case_id,EntryChannelStop.request_key==request_key))
        if prior:descriptor=rules.validate_route(_plain(prior.route))
        else:
            _,_,_,_,descriptor,_,_=await _context(session,actor,case_id,applicant_id,interview_id,dialog_id,resolver,policy)
    async def write(session):
        await _lock(session,descriptor,writer=True)
        rows,total=await _registry(session)
        prior=next((r for r in rows if r.case_id==case_id and r.request_key==request_key),None)
        if prior:
            if prior.request_hash!=_hash(command):raise EntryStorageConflict('channel_request_conflict')
            if prior.transport_key!=_hash(descriptor):raise EntryStorageConflict('channel_dialog_identity_changed')
            return _receipt(prior)
        if any(r.transport_key==_hash(descriptor) for r in rows):raise EntryStorageConflict('channel_already_stopped')
        if len(rows)>=MAX_STOPS:rules.fail('channel_stop_registry_limit')
        header,events,state,identity,current,preview,at=await _context(session,actor,case_id,applicant_id,interview_id,dialog_id,resolver,policy,lock=True)
        if not _same(current,descriptor):raise EntryStorageConflict('channel_dialog_identity_changed')
        if policy.digest!=expected_policy_hash or len(events)!=expected_revision or _hash(preview)!=expected_preview_hash:
            raise EntryStorageConflict('channel_preview_changed')
        observed=events[-1]
        if state['phase'] in ('active','paused'):
            await interviews._record_action_in_session(session,actor=actor,case_id=case_id,applicant_id=applicant_id,
                interview_id=interview_id,expected_revision=expected_revision,request_key='guard-'+_hash(command)[:58],
                operation={'action':'handoff'},at=at)
            events,state,_=await interviews._history(session,header,interviews.policy_from_document(_plain(header.policy)))
        handoff=state.get('handoff')
        if not handoff or state['phase'] not in ('pending','acked'):rules.fail('channel_handoff_required')
        event=next(e for e in events if e.revision==handoff['card']['revision'])
        row=EntryChannelStop(case_id=case_id,applicant_id=applicant_id,interview_id=interview_id,
            handoff_event_id=event.id,contact_id=identity['contact_id'],dialog_id=dialog_id,transport_key=_hash(descriptor),
            card_hash=handoff['hash'],request_key=request_key,request_hash=_hash(command),command=command,
            policy=policy.document(),route=descriptor,source_pin=dict(dialog=identity,observed_event_id=observed.id,
                observed_revision=observed.revision,observed_hash=observed.snapshot_hash,handoff_revision=event.revision,
                handoff_hash=event.snapshot_hash,header_hash=header.snapshot_hash,preview=preview),
            authority={'full_admins':sorted(rules.existing_full_admins())},created_by=actor.manager_id,created_at=at)
        row.snapshot_hash=_hash(_payload(row))
        amount=len(canonical(_payload(row)).encode())
        if amount>MAX_ROW_BYTES or total+amount>MAX_REGISTRY_BYTES:rules.fail('channel_stop_registry_limit')
        session.add(row);await session.flush();await _registry(session)
        return _receipt(row)
    return await _transaction(engine,write)


@dataclass(frozen=True)
class SendResult:
    invoked:bool
    value:object=None


async def guarded_send(engine,descriptor,callback):
    """Exactly one local callback invocation at most; remote delivery may be unknown.

Intentionally NO retry helper and NO commit. Hold admission until callback ends,
then rollback the read/lock transaction; cleanup failure cannot re-invoke it.
"""
    descriptor=rules.validate_route(descriptor)
    async with _sessions(engine)() as session:
        try:
            await _lock(session,descriptor)
            rows,_=await _registry(session)
            if any(r.transport_key==_hash(descriptor) for r in rows):return SendResult(False)
            async with asyncio.timeout(PROVIDER_TIMEOUT):value=await callback()
            return SendResult(True,value)
        finally:
            await session.rollback()
