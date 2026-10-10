"""Native receipt/correlation/confirmation forms; no external inbox or sending."""
import hashlib
import hmac
import json
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.domain import entry_portal as service
from app.domain.entry_portal_policy import configured_policy, authorize
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.service_authz import PermissionDenied

HEADERS = {'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer'}
META = ('_pn_action', '_pn_target', '_pn_revision', '_pn_key', '_pn_policy', '_pn_namespace', '_pn_channel', '_pn_binding')
SECURITY = {'_pn_csrf', '_pn_signature'}
FIELDS = {'receive': {'transport_id','archive_reference','archive_proof','text','reference','kind','occurred_on'},
    'correlate': {'confirmed'}, 'confirm': {'confirmed','cycle_verified','on','source','verification_reference','verification_proof'},
    'dismiss': {'confirmed','reason'}}
KINDS = {'verification':'Проверка электронной почты', 'payment':'Сведения об оплате', 'correction':'Возврат на доработку',
         'approval':'Сведения об одобрении', 'refusal':'Сведения об отказе'}
SOURCES = {'paste':'Текст уведомления', 'portal':'Проверка портала вручную', 'official_document':'Официальный документ'}
STATES = {'pending':'Ожидает сопоставления', 'correlated':'Сопоставлено с подачей', 'checked':'Сведения проверены',
          'applied':'Подтверждение записано в заявку', 'dismissed':'Проверка закрыта'}
REASONS = {'portal_content_already_applied':'Это содержимое уже использовано. Закройте повтор как дубликат.',
    'portal_application_changed':'Заявка или цикл подачи изменились. Повторно проверьте и сопоставьте уведомление.',
    'portal_independent_verification_required':'Подтвердите проверку текущей подачи по порталу или официальному документу.',
    'portal_application_not_submitted':'Текущее состояние заявки не допускает это решение.',
    'portal_observed_date_conflict':'Дата проверки события должна совпадать с датой, указанной в уведомлении.',
    'invalid_portal_date':'Проверьте фактическую дату события: она не может быть в будущем или раньше подачи.',
    'portal_correlation_required':'Сначала сопоставьте сведения с конкретной подачей.',
    'portal_transport_conflict':'Этот идентификатор сообщения уже связан с другими сведениями.',
    'portal_action_limit':'Достигнут предел проверок. Доступно закрытие этой записи.'}
UNAVAILABLE = {'application_case_unavailable','portal_receipt_unavailable','application_unavailable','applicant_unavailable'}


def _policy():
    try: return configured_policy(ar.settings)
    except EntryStorageInvalid: return None


def _csrf(request):
    request.session.setdefault('kg_portal_csrf', secrets.token_hex(32))
    return request.session['kg_portal_csrf']


def _signature(request, actor, case_id, values):
    body = json.dumps(['kg-portal/1',actor.manager_id,case_id,_csrf(request),[values.get(k,'') for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),body,hashlib.sha256).hexdigest()


def _envelope(request, actor, case_id, action, policy, selected=None, channel=''):
    values = dict(zip(META,(action,str(selected['receipt']['id'] if selected else 0),str(selected['revision'] if selected else 0),
        secrets.token_hex(24),policy.digest if policy else '',policy.source_namespace if policy else '',channel,
        json.dumps(selected['candidate'],separators=(',',':')) if selected and action=='correlate' else '')))
    return values | {'_pn_csrf':_csrf(request),'_pn_signature':_signature(request,actor,case_id,values)}


async def _form(request, actor, case_id):
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'Используйте форму.',headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>65536: raise HTTPException(413,'Форма слишком большая.',headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=30,encoding='utf-8',errors='strict')
        if len({k for k,v in pairs})!=len(pairs) or any(len(k)>64 or len(v)>(16384 if k=='text' else 2048 if k=='_pn_binding' else 512) for k,v in pairs): raise ValueError
        values=dict(pairs);action=values.get('_pn_action')
        if action not in FIELDS or not values.keys()<=set(META)|SECURITY|FIELDS[action]: raise ValueError
        if action=='receive':
            channel_fields={'text'} if values.get('_pn_channel')=='paste' else {'reference','kind','occurred_on'}
            if not values.keys()<=set(META)|SECURITY|{'transport_id','archive_reference','archive_proof'}|channel_fields: raise ValueError
        for field in ('_pn_target','_pn_revision'):
            n=int(values[field])
            if str(n)!=values[field] or not 0<=n<=2147483647: raise ValueError
        if (action=='receive')!=(values['_pn_target']=='0'): raise ValueError
    except (ValueError,UnicodeError,KeyError): raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS) from None
    token=request.session.get('kg_portal_csrf','')
    if (not token or not hmac.compare_digest(token.encode(),values.get('_pn_csrf','').encode()) or
        not hmac.compare_digest(_signature(request,actor,case_id,values).encode(),values.get('_pn_signature','').encode())):
        raise HTTPException(403,'Форма изменена или относится к другой сессии.',headers=HEADERS)
    return values


async def _render(request,manager,actor,case,*,receipt_id=None,before=None,error='',status=200,retry=None):
    listing={'receipts':[],'next_before':None};selected=None;forms={};policy=_policy();allowed=False
    url=f'/admin/case/{case["id"]}/kg-entry/portal'
    try:
        listing=await service.list_receipts(entry._engine(),actor=actor,case_id=case['id'],before=before)
        if receipt_id:
            selected=await service.read_receipt(entry._engine(),actor=actor,case_id=case['id'],receipt_id=receipt_id,policy=policy)
        try: authorize(actor,policy,on=service.applications._today());allowed=True
        except (EntryStorageInvalid,PermissionDenied): pass
        if not retry:
            if selected:
                for action,flag in [('correlate','can_correlate'),('confirm','can_confirm'),('dismiss','can_dismiss')]:
                    if selected[flag]: forms[action]=_envelope(request,actor,case['id'],action,policy if selected['policy_enabled'] else None,selected)
            elif allowed:
                for channel in (['paste'] if policy.allow_paste else [])+list(policy.manual_sources):
                    forms['receive-'+channel]=_envelope(request,actor,case['id'],'receive',policy,channel=channel)
    except PermissionDenied: raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE: raise HTTPException(404,headers=HEADERS) from None
        listing=None;selected=None;forms={};error='История не прошла проверку. Изменения недоступны.';status=503
    except Exception:
        listing=None;selected=None;forms={};error='Хранилище временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_portal.html',dict(request=request,manager=manager,case=case,
        listing=listing,selected=selected,forms=forms,policy=policy,allowed=allowed,error=error,retry=retry,url=url,
        kinds=KINDS,sources=SOURCES,states=STATES,write_on=_write_on(request),meta=META,security=SECURITY,
        today=service.applications._today().isoformat()),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/portal',response_class=HTMLResponse)
async def portal_form(request:Request,case_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);case=await entry._case(case_id,actor)
    try:
        pairs=list(request.query_params.multi_items())
        if len(pairs)>1 or any(k not in ('receipt_id','before') for k,v in pairs): raise ValueError
        params={}
        for k,v in pairs:
            n=int(v)
            if str(n)!=v or not 1<=n<=2147483647: raise ValueError
            params[k]=n
    except ValueError: raise HTTPException(422,'Недопустимый номер записи.',headers=HEADERS) from None
    return await _render(request,manager,actor,case,**params)


@ar.router.post('/case/{case_id}/kg-entry/portal',response_class=HTMLResponse)
async def portal_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);case=await entry._case(case_id,actor)
    values=await _form(request,actor,case_id);receipt_id=int(values['_pn_target']) or None;policy=_policy()
    try:
        if values['_pn_action']=='receive':
            channel=values['_pn_channel']
            receipt=await service.receive(entry._engine(),actor=actor,case_id=case_id,channel=channel,
                source_namespace=values['_pn_namespace'],transport_id=values.get('transport_id',''),
                archive_reference=values.get('archive_reference',''),archive_proof=values.get('archive_proof',''),
                request_key=values['_pn_key'],expected_policy_hash=values['_pn_policy'],policy=policy,
                text=values.get('text','') if channel=='paste' else None,
                manual=None if channel=='paste' else dict(reference=values.get('reference',''),kind=values.get('kind',''),occurred_on=values.get('occurred_on','')))
            receipt_id=receipt['id']
        else:
            action=values['_pn_action'];operation={'action':action,'confirmed':values.get('confirmed')=='yes'}
            if action=='correlate': operation['binding']=json.loads(values['_pn_binding'])
            elif action=='dismiss': operation['reason']=values.get('reason','')
            else: operation.update(on=values.get('on',''),source=values.get('source',''),
                verification_reference=values.get('verification_reference',''),verification_proof=values.get('verification_proof',''),
                cycle_verified=values.get('cycle_verified')=='yes')
            await service.record_action(entry._engine(),actor=actor,case_id=case_id,receipt_id=receipt_id,
                expected_revision=int(values['_pn_revision']),request_key=values['_pn_key'],operation=operation,
                policy=policy,expected_policy_hash=values['_pn_policy'] or None)
    except PermissionDenied: raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageUnavailable:
        return await _render(request,manager,actor,case,receipt_id=receipt_id,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос, чтобы проверить результат без дубля.')
    except EntryStorageConflict as exc:
        return await _render(request,manager,actor,case,receipt_id=receipt_id,status=409,
            error=REASONS.get(str(exc),'Сведения или заявка изменились. Проверьте текущую запись.'))
    except (EntryStorageInvalid,ValueError) as exc:
        if str(exc) in UNAVAILABLE: raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,receipt_id=receipt_id,status=422,
            error=REASONS.get(str(exc),'Проверьте обязательные поля, источник и подтверждения.'))
    except Exception:
        return await _render(request,manager,actor,case,receipt_id=receipt_id,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос для проверки результата.')
    return RedirectResponse(f'/admin/case/{case_id}/kg-entry/portal?receipt_id={receipt_id}',status_code=303,headers=HEADERS)
