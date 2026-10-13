"""Unsigned visa cases and explicit recording of a signature on the same case."""
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime,timezone
from urllib.parse import quote

from fastapi import Depends,HTTPException,Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select,text
from sqlalchemy.exc import SQLAlchemyError

import app.admin.router as ar
from app.admin import contracts
from app.admin.workday import _require_workday,_write_on,_case_or_404
from app.core.live_authz import actor_for
from app.domain import precontract_cases as service
from app.domain.models import ServiceCaseOpening,DomainError
from app.domain.services import ContactService
from app.domain.service_authz import PermissionDenied

META=('request_key','expected_revision','original_owner')
FIELDS=set(META)|{'signature','csrf_token','product_choice','reference','signed_at','amount','currency','amount_unknown_reason','confirmed'}


def signature(request,manager,action,target,values):
    payload=json.dumps(['precontract-form/1',manager['login'],action,str(target),
        contracts._csrf(request),[values.get(k,'') for k in META]],ensure_ascii=False,separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def envelope(request,manager,action,target,*,revision='',owner=''):
    values=dict(request_key=secrets.token_hex(24),expected_revision=str(revision),original_owner=owner,
        product_choice='',reference='',signed_at=datetime.now(contracts.BISHKEK).strftime('%Y-%m-%dT%H:%M'),
        amount='',currency='',amount_unknown_reason='',confirmed='')
    values.update(csrf_token=contracts._csrf(request),signature=signature(request,manager,action,target,values))
    return values


async def submitted(request,manager,action,target):
    if len(await request.body())>16384:raise HTTPException(413)
    form=await request.form()
    if set(form)-FIELDS or any(len(form.getlist(k))!=1 for k in form):raise HTTPException(422)
    values={k:str(form.get(k,'')) for k in FIELDS}
    if any(len(v)>1024 for v in values.values()):raise HTTPException(422)
    expected=request.session.get('contract_csrf','')
    if (not expected or not secrets.compare_digest(expected.encode(),values['csrf_token'].encode()) or
        not re.fullmatch('[0-9a-f]{48}',values['request_key']) or not secrets.compare_digest(
            signature(request,manager,action,target,values).encode(),values['signature'].encode())):
        raise HTTPException(403,'Форма устарела. Откройте её заново.')
    return values


def render(request,manager,action,target,values,*,products=(),case=None,error='',status=200):
    url=(f'/admin/conversation/{quote(str(target),safe="")}/preliminary' if action=='open' else f'/admin/case/{target}/contract')
    return ar.templates.TemplateResponse(request,'precontract.html',dict(manager=manager,action=action,
        target=target,values=values,products=products,case=case,error=error,form_url=url,write_on=_write_on(request)),
        status_code=status,headers={'Cache-Control':'no-store','X-Action-Outcome':'failed' if status==503 else 'invalid' if error else 'form'})


def failure(exc):
    message=str(exc)
    if any(v in message for v in ('conflict','changed','revision','first stage')):
        return 'Карточка изменилась или эта операция уже сохранена с другими данными. Проверьте карточку; повтор исходной формы не создаст вторую услугу.',409
    if isinstance(exc,SQLAlchemyError):return 'Реестр временно недоступен. Повторите эту же форму, чтобы проверить исходное сохранение.',503
    if 'archived' in message:return 'Услуга архивирована. Новую подпись сохранить нельзя.',409
    return 'Проверьте поля и состояние карточки. Запись не сохранена.',422


async def conversation(user_id,manager):
    conv,actor,direction=await contracts._conversation(user_id,manager)
    if direction!='visa':raise HTTPException(404)
    return conv,actor,direction


@ar.router.get('/conversation/{user_id}/preliminary')
async def preliminary_form(user_id:str,request:Request,manager:dict=Depends(ar.require_admin)):
    _require_workday(request);conv,actor,direction=await conversation(user_id,manager)
    try:
        async with ar._domain_sessionmaker()() as s:
            contact=await contracts._find_contact(s,contracts._identity(conv))
            owner=await contracts._owner(s,conv,actor,direction,contact)
            products=await contracts._products(s,direction)
        return render(request,manager,'open',user_id,envelope(request,manager,'open',user_id,owner=owner),products=products)
    except (SQLAlchemyError,DomainError) as exc:
        error,status=failure(exc)
        return render(request,manager,'open',user_id,envelope(request,manager,'open',user_id),error=error,status=status)


@ar.router.post('/conversation/{user_id}/preliminary')
async def preliminary_submit(user_id:str,request:Request,manager:dict=Depends(ar.require_admin)):
    _require_workday(request);conv,actor,direction=await conversation(user_id,manager)
    values=await submitted(request,manager,'open',user_id)
    if not _write_on(request):return render(request,manager,'open',user_id,values,error='Запись услуг выключена.',status=409)
    try:
        if not re.fullmatch('[1-9][0-9]*:[1-9][0-9]*',values['product_choice']):raise DomainError('choose product')
        product_id,version_id=map(int,values['product_choice'].split(':'))
        async with ar._domain_sessionmaker()() as s:
            async with s.begin():
                if s.bind.dialect.name=='sqlite':await s.execute(text('BEGIN'))
                identity=contracts._identity(conv);contact=await contracts._find_contact(s,identity)
                old=await s.scalar(select(ServiceCaseOpening.id).where(ServiceCaseOpening.request_key==values['request_key']))
                if old is not None and contact is None:raise DomainError('opening subject changed')
                if old is None:
                    owner=await contracts._owner(s,conv,actor,direction,contact,lock=True)
                    if owner!=values['original_owner']:raise DomainError('owner changed')
                if contact is None:
                    kind,value=identity
                    contact=await ContactService.find_or_create_by_identity(s,kind,'+'+value if kind=='phone' else value)
                    owner=await contracts._owner(s,conv,actor,direction,contact,lock=True)
                    if owner!=values['original_owner']:raise DomainError('owner changed')
                result=await service.open_preliminary(s,contact_id=contact.id,product_id=product_id,
                    workflow_version_id=version_id,owner_login=values['original_owner'],by=actor,request_key=values['request_key'])
        return RedirectResponse(f"/admin/case/{result['case_id']}",303,headers={'X-Action-Outcome':'preliminary_opened','Cache-Control':'no-store'})
    except PermissionDenied:raise HTTPException(404) from None
    except (DomainError,SQLAlchemyError) as exc:
        error,status=failure(exc);return render(request,manager,'open',user_id,values,error=error,status=status)


@ar.router.get('/case/{case_id}/contract')
async def signature_form(case_id:int,request:Request,manager:dict=Depends(ar.require_admin)):
    _require_workday(request);actor=actor_for(manager)
    try:
        async with ar._domain_sessionmaker()() as s:
            case,product=await _case_or_404(s,case_id,actor)
            if product.direction!='visa':raise HTTPException(404)
            receipt=await s.scalar(select(ServiceCaseOpening).where(ServiceCaseOpening.case_id==case_id))
            if receipt is None:raise HTTPException(409,'Для этой карточки нет записи предварительного открытия.')
            await service.validate_opening(s,receipt,case)
    except (DomainError,SQLAlchemyError) as exc:
        error,status=failure(exc)
        return render(request,manager,'sign',case_id,envelope(request,manager,'sign',case_id),error=error,status=status)
    return render(request,manager,'sign',case_id,envelope(request,manager,'sign',case_id,revision=case.revision),case=case,
        error='Договор уже записан в карточке.' if case.signed_at else '',status=409 if case.signed_at else 200)


@ar.router.post('/case/{case_id}/contract')
async def signature_submit(case_id:int,request:Request,manager:dict=Depends(ar.require_admin)):
    _require_workday(request);actor=actor_for(manager)
    values=await submitted(request,manager,'sign',case_id)
    if not _write_on(request):return render(request,manager,'sign',case_id,values,error='Запись услуг выключена.',status=409)
    try:
        if values['confirmed']!='yes':raise DomainError('signature confirmation required')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}',values['signed_at']):raise DomainError('invalid signed_at')
        try:
            signed_at=datetime.fromisoformat(values['signed_at']).replace(tzinfo=contracts.BISHKEK).astimezone(timezone.utc)
            revision=int(values['expected_revision'])
        except ValueError:raise DomainError('invalid signature fields') from None
        async with ar._domain_sessionmaker()() as s:
            async with s.begin():
                if s.bind.dialect.name=='sqlite':await s.execute(text('BEGIN'))
                result=await service.record_signed_contract(s,case_id=case_id,expected_revision=revision,by=actor,
                    reference=values['reference'],signed_at=signed_at,amount=values['amount'].strip() or None,
                    currency=values['currency'],amount_unknown_reason=values['amount_unknown_reason'],request_key=values['request_key'])
        return RedirectResponse(f"/admin/case/{result['case_id']}",303,headers={'X-Action-Outcome':'contract_recorded','Cache-Control':'no-store'})
    except PermissionDenied:raise HTTPException(404) from None
    except (DomainError,SQLAlchemyError) as exc:
        error,status=failure(exc);return render(request,manager,'sign',case_id,values,error=error,status=status)
