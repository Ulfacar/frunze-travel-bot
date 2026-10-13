"""Explicit visa case before contract; operations share the caller's transaction.

Opening grants no consent, classification, quotation, payment or signature.
Legacy sign_contract remains unchanged. New signature targets this exact case.
"""
from datetime import datetime,timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import settings
from app.domain import service_cases as cases,live_assign
from app.domain.entry_storage import _hash,_plain
from app.domain.models import DomainError,Product,ServiceCase,ServiceCaseOpening,ServiceEvent,WorkflowVersion
from app.domain.service_authz import can_open_case,can_view_case,require

OPEN='service-case-opening/1'
SIGN='existing-case-signature/1'


def positive(value):
    if type(value) is not int or not 1<=value<=2147483647:raise DomainError('invalid case operation identity')
    return value


def actor_id(actor):
    value=cases._required_text(actor.manager_id,'actor',64).lower()
    # Native actor_for already supplies this canonical trusted identity. Reject
    # an inconsistent domain caller before writing evidence through legacy APIs.
    if actor.manager_id!=value:raise DomainError('actor identity must be canonical')
    return value


def owner_id(actor,owner):
    owner=cases._required_text(owner,'owner_login',64).lower()
    require(actor.is_full_admin or owner==actor_id(actor),'open preliminary case for owner')
    known={str(m.login or '').strip().lower() for m in settings.manager_list()}
    if owner not in known:raise DomainError('owner manager is not configured')
    return owner


async def locked_case(session,case_id,actor):
    positive(case_id)
    observed=await session.get(ServiceCase,case_id)
    product=await session.get(Product,observed.product_id) if observed else None
    require(observed is not None and product is not None and product.direction=='visa' and
        can_view_case(actor,direction=product.direction,owner_login=observed.owner_login),'read preliminary case')
    await live_assign.lock_contact(session,observed.contact_id)
    case=await session.scalar(select(ServiceCase).where(ServiceCase.id==case_id).with_for_update().execution_options(populate_existing=True))
    require(can_view_case(actor,direction=product.direction,owner_login=case.owner_login),'change preliminary case')
    return case,product


def opening_payload(row):
    return dict(format=OPEN,case_id=row.case_id,request_key=row.request_key,
        created_at=cases._moment(row.created_at).isoformat(),document=_plain(row.document))


async def validate_opening(session,row,case):
    doc=_plain(row.document)
    if not isinstance(doc,dict) or set(doc)!={'command','result'}:raise DomainError('invalid preliminary opening evidence')
    command,result=doc['command'],doc['result']
    if (not isinstance(command,dict) or set(command)!={'format','contact_id','product_id','workflow_version_id','owner_login','actor','request_id'} or
        not isinstance(result,dict) or set(result)!={'case_id','event_id','revision','stage'} or not isinstance(row.created_at,datetime)):
        raise DomainError('invalid preliminary opening evidence')
    for k in ('contact_id','product_id','workflow_version_id'):positive(command[k])
    for k in ('case_id','event_id','revision'):positive(result[k])
    if command['request_id'] is not None:positive(command['request_id'])
    for value,label,limit in ((command['owner_login'],'owner',64),(command['actor'],'actor',64),
                             (result['stage'],'stage',64),(row.request_key,'request key',128)):
        if not isinstance(value,str) or cases._required_text(value,label,limit)!=value:
            raise DomainError('invalid preliminary opening evidence')
    if row.snapshot_hash!=_hash(opening_payload(row)):raise DomainError('invalid preliminary opening evidence')
    if (command.get('format')!=OPEN or result['revision']!=1 or result.get('case_id')!=case.id or row.case_id!=case.id or
        any(command[k]!=command[k].lower() for k in ('actor','owner_login')) or
        command.get('contact_id')!=case.contact_id or command.get('product_id')!=case.product_id or
        command.get('workflow_version_id')!=case.workflow_version_id or command.get('request_id')!=case.request_id):
        raise DomainError('preliminary opening subject mismatch')
    version=await session.get(WorkflowVersion,case.workflow_version_id)
    if (version is None or version.product_id!=case.product_id or version.published_at is None or
        not version.stages or result['stage']!=version.stages[0]['code']):
        raise DomainError('invalid preliminary opening workflow evidence')
    event=await session.get(ServiceEvent,result.get('event_id'))
    if (event is None or event.case_id!=case.id or event.event_type!='case_opened' or
        event.from_stage is not None or event.reason is not None or
        event.actor!=command.get('actor') or event.to_stage!=result.get('stage') or
        not isinstance(event.payload,dict) or event.payload.get('workflow_version_id')!=case.workflow_version_id or
        event.payload.get('revision')!=result.get('revision')):
        raise DomainError('preliminary opening event mismatch')
    return doc


async def open_preliminary(session,*,contact_id,product_id,workflow_version_id,owner_login,by,
                           request_key,request_id=None):
    require(can_open_case(by,direction='visa'),'open preliminary case')
    actor=actor_id(by);key=cases._required_text(request_key,'opening request key',128)
    command=dict(format=OPEN,contact_id=positive(contact_id),product_id=positive(product_id),
        workflow_version_id=positive(workflow_version_id),owner_login=cases._required_text(owner_login,'owner_login',64).lower(),
        actor=actor,request_id=positive(request_id) if request_id is not None else None)
    async def repeated(row):
        case,_=await locked_case(session,row.case_id,by)
        saved=await validate_opening(session,row,case)
        if saved['command']!=command:raise DomainError('opening idempotency conflict')
        return saved['result']|dict(opening_id=row.id,snapshot_hash=row.snapshot_hash,duplicate=True)
    old=await session.scalar(select(ServiceCaseOpening).where(ServiceCaseOpening.request_key==key))
    if old is not None:return await repeated(old)
    owner=owner_id(by,owner_login)
    await live_assign.lock_contact(session,contact_id)
    product=await cases._product(session,product_id)
    require(product.direction=='visa','open preliminary case')
    if product.current_version_id!=workflow_version_id:raise DomainError('preliminary workflow changed; reload')
    try:
        async with session.begin_nested():
            case=await cases.open_case(session,contact_id=contact_id,product_id=product_id,
                owner_login=owner,by=by,request_id=request_id)
            event=await session.scalar(select(ServiceEvent).where(ServiceEvent.case_id==case.id,ServiceEvent.event_type=='case_opened'))
            result=dict(case_id=case.id,event_id=event.id,revision=case.revision,stage=case.stage)
            row=ServiceCaseOpening(case_id=case.id,request_key=key,created_at=datetime.now(timezone.utc),
                document=dict(command=command,result=result))
            row.snapshot_hash=_hash(opening_payload(row));session.add(row);await session.flush()
    except IntegrityError:
        old=await session.scalar(select(ServiceCaseOpening).where(ServiceCaseOpening.request_key==key))
        if old is None:raise DomainError('preliminary opening conflict; retry') from None
        return await repeated(old)
    return result|dict(opening_id=row.id,snapshot_hash=row.snapshot_hash,duplicate=False)


async def record_signed_contract(session,*,case_id,expected_revision,by,reference,signed_at,
                                  amount,currency,amount_unknown_reason='',request_key):
    case,product=await locked_case(session,case_id,by)
    actor=actor_id(by);positive(expected_revision)
    key=cases._required_text(request_key,'signature request key',128)
    reference=cases._required_text(reference,'contract reference',128)
    currency_code=str(currency or '').strip().upper() or None
    import re
    if currency_code is not None and not re.fullmatch('[A-Z]{3}',currency_code):raise DomainError('invalid contract currency')
    unknown=cases._optional_text(amount_unknown_reason,'amount_unknown_reason',255)
    value=cases._contract_amount(amount,currency_code,unknown)
    if not isinstance(signed_at,datetime) or signed_at.tzinfo is None:raise DomainError('signed_at must be timezone-aware')
    moment=cases._moment(signed_at)
    command=dict(format=SIGN,case_id=case.id,actor=actor,expected_revision=expected_revision,reference=reference,
        signed_at=moment.isoformat(),amount=str(value) if value is not None else None,currency=currency_code,
        amount_unknown_reason=unknown,request_key=key)
    opening=await session.scalar(select(ServiceCaseOpening).where(ServiceCaseOpening.case_id==case.id))
    if opening is None:raise DomainError('preliminary opening receipt required')
    opening_document=await validate_opening(session,opening,case)
    signed=list((await session.scalars(select(ServiceEvent).where(ServiceEvent.case_id==case.id,
        ServiceEvent.event_type=='contract_signed').order_by(ServiceEvent.id).limit(2))).all())
    if signed:
        event=signed[0];payload=_plain(event.payload)
        if not isinstance(payload,dict) or set(payload)!={'reference','amount','currency','revision','operation'}:
            raise DomainError('invalid retained signature evidence')
        retained=payload.get('operation')
        if (len(signed)!=1 or not isinstance(retained,dict) or set(retained)!={'command','result','snapshot_hash'} or
            _hash(retained.get('command'))!=_hash(command)):
            raise DomainError('existing contract signature conflict')
        core=dict(command=retained['command'],result=retained.get('result'))
        if retained.get('snapshot_hash')!=_hash(core):raise DomainError('invalid retained signature evidence')
        result=core['result']
        if not isinstance(result,dict) or set(result)!={'case_id','revision','workflow_version_id','owner_login','opening_hash'}:
            raise DomainError('invalid retained signature evidence')
        for k in ('case_id','revision','workflow_version_id'):positive(result[k])
        retained_owner=result['owner_login']
        if (not isinstance(retained_owner,str) or cases._required_text(retained_owner,'retained owner',64).lower()!=retained_owner or
            result['revision']!=expected_revision+1):
            raise DomainError('invalid retained signature evidence')
        if (event.actor!=actor or event.from_stage is not None or event.to_stage!=opening_document['result']['stage'] or
            event.reason!=unknown or result.get('case_id')!=case.id or result.get('revision')!=event.payload.get('revision') or
            any(event.payload.get(k)!=command[k] for k in ('reference','amount','currency')) or case.idempotency_key!=key or
            result.get('opening_hash')!=opening.snapshot_hash or result.get('workflow_version_id')!=case.workflow_version_id or
            case.contract_reference!=reference or case.signed_by!=actor or cases._moment(case.signed_at)!=moment):
            raise DomainError('invalid retained signature evidence')
        return result|dict(event_id=event.id,duplicate=True)
    if case.revision!=expected_revision:raise DomainError('preliminary case revision changed; reload')
    if any(getattr(case,k) is not None for k in ('signed_at','signed_by','contract_reference','idempotency_key','agreed_amount','currency','amount_unknown_reason')):
        raise DomainError('preliminary contract facts require review')
    product=await cases._product(session,case.product_id)
    if not product.active:raise DomainError('cannot sign archived product')
    version=await session.get(WorkflowVersion,case.workflow_version_id)
    if (version is None or version.published_at is None or version.product_id!=case.product_id or
        case.stage!=version.stages[0]['code'] or case.outcome is not None):
        raise DomainError('preliminary case must remain at original first stage')
    collision=await session.scalar(select(ServiceCase.id).where(ServiceCase.idempotency_key==key))
    if collision is not None:raise DomainError('signature idempotency conflict')
    try:
        async with session.begin_nested():
            case.contract_reference=reference;case.signed_at=moment;case.signed_by=actor
            object.__setattr__(case,'_money_correction_in_progress',True)
            try:case.agreed_amount=value;case.currency=currency_code
            finally:object.__setattr__(case,'_money_correction_in_progress',False)
            case.amount_unknown_reason=unknown or None;case.idempotency_key=key
            await session.flush()
            result=dict(case_id=case.id,revision=case.revision,workflow_version_id=case.workflow_version_id,
                owner_login=case.owner_login,opening_hash=opening.snapshot_hash)
            retained=dict(command=command,result=result);retained['snapshot_hash']=_hash(retained)
            event=ServiceEvent(case_id=case.id,event_type='contract_signed',actor=actor,to_stage=case.stage,
                reason=unknown,payload=dict(reference=reference,amount=command['amount'],currency=currency_code,
                    revision=case.revision,operation=retained))
            session.add(event)
            await cases._create_initial_tasks(session,case,version,direction=product.direction,by=by)
            await session.flush()
    except IntegrityError as exc:raise DomainError('signature idempotency conflict') from exc
    return result|dict(event_id=event.id,duplicate=False)
