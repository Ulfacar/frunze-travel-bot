"""Explicit internal quotation preview/save; never payment or customer sending."""
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
from app.domain import entry_quotes as service
from app.domain.entry_quote_policy import policy_from_document
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid,EntryStorageUnavailable
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','X-Robots-Tag':'noindex'}
META=('_q_action','_q_revision','_q_policy','_q_key','_q_preview','_q_calculator')
PARAMS=('recipe_id','additional_blocks','urgent')
COMPONENTS={'service':'Наш сервисный сбор','government':'Государственные платежи','bank':'Банк','partner':'Партнёры'}
REASONS={'quote_price_unknown':'Цена этой позиции неизвестна','quote_urgent_price_unknown':'Срочная стоимость не подтверждена',
    'quote_recipe_expired_or_future':'Прайс не действует на текущую дату','quote_rounding_policy_required':'Нужен утверждённый порядок округления',
    'quote_total_limit':'Превышен допустимый размер расчёта','quote_no_priced_line':'Нет ни одной денежной позиции',
    'quote_superseded':'Есть более новая версия расчёта','quote_application_changed':'Данные заявки изменились после расчёта',
    'quote_application_terminal':'Эта попытка подачи завершена','quote_incomplete':'Полная цена не определена',
    'quote_policy_changed':'Условия расчёта изменились','quote_calculator_changed':'Алгоритм расчёта обновлён',
    'quote_policy_unavailable':'Нет действующих полномочий для использования цены'}
UNAVAILABLE={'application_case_unavailable','application_unavailable','applicant_unavailable'}


def _url(case_id,application_id):return f'/admin/case/{case_id}/kg-entry/applications/{application_id}/quotes'


def _policy():
    try:return policy_from_document(ar.settings.kg_quote_policy) if ar.settings.kg_quote_policy else None
    except EntryStorageInvalid:return None


def _csrf(request):
    request.session.setdefault('kg_quote_csrf',secrets.token_hex(32));return request.session['kg_quote_csrf']


def _signature(request,actor,case_id,application_id,values):
    names=META+(PARAMS if values.get('_q_action')=='save' else ())
    body=json.dumps(['kg-quote-form/1',actor.manager_id,case_id,application_id,_csrf(request),
        [values.get(k,'') for k in names]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),body,hashlib.sha256).hexdigest()


def _envelope(request,actor,case_id,application_id,*,policy,current=None,preview=None,key=None):
    data=dict(_q_action='save' if preview else 'preview',_q_revision=str(preview['preview']['expected_revision'] if preview else current['revision']),
        _q_policy=preview['preview']['policy_hash'] if preview else policy.digest,_q_key=key or secrets.token_hex(16),
        _q_preview=preview['preview_hash'] if preview else '',_q_calculator=preview['preview']['calculator_version'] if preview else service.rules.VERSION)
    if preview:
        p=preview['preview']['parameters'];data.update(recipe_id=p['recipe_id'],additional_blocks=str(p['additional_blocks']),urgent='1' if p['urgent'] else '0')
    data['_q_csrf']=_csrf(request);data['_q_sig']=_signature(request,actor,case_id,application_id,data)
    return data


async def _form(request,actor,case_id,application_id):
    try:
        if request.headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded':raise ValueError
        length=request.headers.get('content-length')
        if length is not None and (not length.isascii() or not length.isdecimal() or int(length)>16384):raise ValueError
        raw=bytearray()
        async for chunk in request.stream():
            if len(raw)+len(chunk)>16384:raise ValueError
            raw.extend(chunk)
        pairs=parse_qsl(raw.decode('utf-8'),keep_blank_values=True,strict_parsing=True,max_num_fields=16)
        values=dict(pairs)
        if len(values)!=len(pairs) or set(values)!=set(META+PARAMS+('_q_csrf','_q_sig')):raise ValueError
        if any(len(k)>40 or len(v)>100 for k,v in pairs):raise ValueError
        if values['_q_action'] not in ('preview','save'):raise ValueError
        if any(len(values[k])!=64 or any(c not in '0123456789abcdef' for c in values[k]) for k in ('_q_csrf','_q_sig')):
            raise HTTPException(403,headers=HEADERS)
        if not hmac.compare_digest(values['_q_csrf'],_csrf(request)):raise HTTPException(403,headers=HEADERS)
        if not hmac.compare_digest(values['_q_sig'],_signature(request,actor,case_id,application_id,values)):raise HTTPException(403,headers=HEADERS)
        for key in ('_q_revision','additional_blocks'):
            if str(int(values[key]))!=values[key] or not 0<=int(values[key])<=128:raise ValueError
        if values['urgent'] not in ('0','1'):raise ValueError
        return values
    except (ValueError,UnicodeDecodeError):raise HTTPException(422,'Проверьте поля расчёта.',headers=HEADERS) from None


async def _render(request,manager,actor,case,application_id,*,preview=None,save_form=None,error=None,status=200,retry=None,selected_revision=None):
    current=None;selected=None;form=None;policy=_policy()
    try:
        current=await service.read_quotes(entry._engine(),actor=actor,case_id=case['id'],application_id=application_id,policy=policy)
        if current['history']:
            selected=next((h for h in current['history'] if h['receipt']['revision']==selected_revision),None) if selected_revision else current['history'][0]
            if selected is None:raise HTTPException(404,headers=HEADERS)
        elif selected_revision:raise HTTPException(404,headers=HEADERS)
        if not retry and current['can_calculate'] and _write_on(request):
            form=_envelope(request,actor,case['id'],application_id,policy=policy,current=current)
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        current=None;error='История расчётов не прошла проверку. Новые записи недоступны.';status=503
    except HTTPException:raise
    except Exception:current=None;error='Хранилище временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_quotes.html',dict(request=request,manager=manager,case=case,
        application_id=application_id,current=current,selected=selected,form=form,preview=preview,save_form=save_form,
        retry=retry,error=error,url=_url(case['id'],application_id),components=COMPONENTS,reasons=REASONS),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applications/{application_id}/quotes',response_class=HTMLResponse)
async def quote_form(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);case=await entry._case(case_id,actor)
    pairs=list(request.query_params.multi_items());revision=None
    if pairs:
        try:
            if len(pairs)!=1 or pairs[0][0]!='revision':raise ValueError
            revision=int(pairs[0][1])
            if str(revision)!=pairs[0][1] or not 1<=revision<=128:raise ValueError
        except ValueError:raise HTTPException(422,'Недопустимая версия.',headers=HEADERS) from None
    return await _render(request,manager,actor,case,application_id,selected_revision=revision)


@ar.router.post('/case/{case_id}/kg-entry/applications/{application_id}/quotes',response_class=HTMLResponse)
async def quote_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);case=await entry._case(case_id,actor)
    values=await _form(request,actor,case_id,application_id);policy=_policy()
    parameters=dict(recipe_id=values['recipe_id'],additional_blocks=int(values['additional_blocks']),urgent=values['urgent']=='1')
    try:
        if values['_q_action']=='preview':
            if policy is None or values['_q_policy']!=policy.digest:raise EntryStorageConflict('quote_policy_changed')
            shown=await service.preview_quote(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,parameters=parameters,policy=policy)
            saved=_envelope(request,actor,case_id,application_id,policy=policy,preview=shown,key=values['_q_key'])
            return await _render(request,manager,actor,case,application_id,preview=shown,save_form=saved)
        await service.save_quote(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,parameters=parameters,
            expected_revision=int(values['_q_revision']),request_key=values['_q_key'],expected_policy_hash=values['_q_policy'],
            expected_preview_hash=values['_q_preview'],policy=policy,calculator_version=values['_q_calculator'])
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageUnavailable:
        return await _render(request,manager,actor,case,application_id,retry=values if values['_q_action']=='save' else None,
            status=503,error='Сохранение не подтверждено. Повторите исходный запрос; дубль не создаётся.')
    except EntryStorageConflict as exc:
        return await _render(request,manager,actor,case,application_id,status=409,error=REASONS.get(str(exc),'Расчёт или заявка изменились. Сначала заново проверьте предварительный расчёт.'))
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,application_id,status=422,error=REASONS.get(str(exc),'Проверьте параметры, соответствие прайса процедуре и доступность расчёта.'))
    except Exception:
        return await _render(request,manager,actor,case,application_id,retry=values if values['_q_action']=='save' else None,
            status=503,error='Результат операции неизвестен. Повторите исходный запрос для проверки.')
    return RedirectResponse(_url(case_id,application_id),status_code=303,headers=HEADERS)
