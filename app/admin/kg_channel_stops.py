"""Explicit permanent autonomous-stop preview and signed confirmation."""
import hashlib
import hmac
import json
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends,HTTPException,Path,Request
from fastapi.responses import HTMLResponse,RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.core.kg_channel_guard import resolve_dialog
from app.domain import entry_channel_stops as service,entry_channel_policy as rules
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid,EntryStorageUnavailable
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex'}
META=('_cs_action','_cs_revision','_cs_policy','_cs_key','_cs_preview')
ROUTE='/case/{case_id}/kg-entry/applicants/{applicant_id}/interview/{interview_id}/channel-stop'


def _url(case_id,applicant_id,interview_id):return '/admin'+ROUTE.format(case_id=case_id,applicant_id=applicant_id,interview_id=interview_id)


def _policy():
    try:return rules.policy_from_document(ar.settings.kg_channel_stop_policy) if ar.settings.kg_channel_stop_policy else None
    except EntryStorageInvalid:return None


def _csrf(request):
    request.session.setdefault('kg_channel_stop_csrf',secrets.token_hex(32));return request.session['kg_channel_stop_csrf']


def _signature(request,actor,ids,values):
    names=META+(('dialog_id',) if values.get('_cs_action')=='save' else ())
    body=json.dumps(['kg-channel-stop-form/1',actor.manager_id,*ids,_csrf(request),[values.get(k,'') for k in names]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),body,hashlib.sha256).hexdigest()


def _envelope(request,actor,ids,policy,*,preview=None,key=None):
    p=preview['preview'] if preview else None
    values=dict(_cs_action='save' if p else 'preview',_cs_revision=str(p['revision']) if p else '0',
        _cs_policy=p['policy_hash'] if p else policy.digest,_cs_key=key or secrets.token_hex(16),
        _cs_preview=preview['preview_hash'] if p else '')
    if p:values['dialog_id']=str(p['dialog']['id'])
    values['_cs_csrf']=_csrf(request);values['_cs_sig']=_signature(request,actor,ids,values)
    return values


async def _form(request,actor,ids):
    try:
        if request.headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded':raise ValueError
        length=request.headers.get('content-length')
        if length is not None and (not length.isascii() or not length.isdecimal() or int(length)>16384):raise ValueError
        body=bytearray()
        async for chunk in request.stream():
            if len(body)+len(chunk)>16384:raise ValueError
            body.extend(chunk)
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,strict_parsing=True,max_num_fields=12,errors='strict')
        values=dict(pairs)
        required=set(META+('_cs_csrf','_cs_sig','dialog_id'))
        if len(values)!=len(pairs) or not required<=values.keys() or not values.keys()<=required|{'confirmed'}:raise ValueError
        if any(len(k)>40 or len(v)>100 for k,v in pairs):raise ValueError
        if values['_cs_action'] not in ('preview','save'):raise ValueError
        if any(len(values[k])!=64 or any(c not in '0123456789abcdef' for c in values[k]) for k in ('_cs_csrf','_cs_sig')):
            raise HTTPException(403,headers=HEADERS)
        if not hmac.compare_digest(values['_cs_csrf'],_csrf(request)) or not hmac.compare_digest(values['_cs_sig'],_signature(request,actor,ids,values)):
            raise HTTPException(403,headers=HEADERS)
        for key,low,high in (('dialog_id',1,2147483647),('_cs_revision',0,256)):
            if str(int(values[key]))!=values[key] or not low<=int(values[key])<=high:raise ValueError
        if values['_cs_action']=='save' and values.get('confirmed')!='yes':raise ValueError
        if values['_cs_action']=='preview' and 'confirmed' in values:raise ValueError
        return values
    except (ValueError,UnicodeError):raise HTTPException(422,'Проверьте поля и подтверждение.',headers=HEADERS) from None


async def _render(request,manager,actor,case,applicant_id,interview_id,*,preview=None,save_form=None,retry=None,error=None,status=200):
    current=None;form=None;policy=_policy();ids=(case['id'],applicant_id,interview_id)
    try:
        current=await service.list_stops(entry._engine(),actor=actor,case_id=case['id'],applicant_id=applicant_id,interview_id=interview_id)
        if policy and _write_on(request) and current['dialogs'] and not retry:form=_envelope(request,actor,ids,policy)
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ('application_case_unavailable','applicant_unavailable','interview_unavailable'):raise HTTPException(404,headers=HEADERS) from None
        error='История остановок не прошла проверку. Новые записи недоступны.';status=503
    except HTTPException:raise
    except Exception:error='Хранилище временно недоступно.';status=503
    from app.admin.kg_interviews import INTERRUPTS
    cause_labels=dict(INTERRUPTS)
    cause_labels['consent_withdrawn']='Запрос на остановку сбора данных'
    return ar.templates.TemplateResponse(request,'kg_channel_stops.html',dict(request=request,manager=manager,case=case,
        applicant_id=applicant_id,interview_id=interview_id,current=current,form=form,preview=preview,save_form=save_form,
        retry=retry,error=error,url=_url(*ids),cause_labels=cause_labels),status_code=status,headers=HEADERS)


@ar.router.get(ROUTE,response_class=HTMLResponse)
async def stop_form(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                    interview_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);case=await entry._case(case_id,actor)
    if request.query_params:raise HTTPException(422,headers=HEADERS)
    return await _render(request,manager,actor,case,applicant_id,interview_id)


@ar.router.post(ROUTE,response_class=HTMLResponse)
async def stop_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                      interview_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);case=await entry._case(case_id,actor);ids=(case_id,applicant_id,interview_id)
    values=await _form(request,actor,ids);policy=_policy()
    target=dict(actor=actor,case_id=case_id,applicant_id=applicant_id,interview_id=interview_id,dialog_id=int(values['dialog_id']),resolver=resolve_dialog,policy=policy)
    try:
        if values['_cs_action']=='preview':
            if policy is None or policy.digest!=values['_cs_policy']:raise EntryStorageConflict('channel_policy_changed')
            shown=await service.preview_stop(entry._engine(),**target)
            save_form=None if shown['existing'] else _envelope(request,actor,ids,policy,preview=shown,key=values['_cs_key'])
            return await _render(request,manager,actor,case,applicant_id,interview_id,preview=shown,save_form=save_form)
        await service.bind_stop(entry._engine(),**target,expected_revision=int(values['_cs_revision']),expected_policy_hash=values['_cs_policy'],
            expected_preview_hash=values['_cs_preview'],request_key=values['_cs_key'],confirmed=values.get('confirmed')=='yes')
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,applicant_id,interview_id,status=409,error='Данные изменились или диалог уже остановлен. Проверьте текущую карточку и предварительный просмотр.')
    except EntryStorageInvalid:
        return await _render(request,manager,actor,case,applicant_id,interview_id,status=422,error='Не удалось подтвердить выбранный диалог, условия или карточку. Остановка не сохранена.')
    except Exception:
        return await _render(request,manager,actor,case,applicant_id,interview_id,status=503,
            retry=values if values['_cs_action']=='save' else None,error='Результат сохранения неизвестен. Повторите исходный запрос для проверки без дубля.')
    return RedirectResponse(_url(*ids),status_code=303,headers=HEADERS)
