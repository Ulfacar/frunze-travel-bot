"""Application-scoped internal drafts, with separate preview and confirmation."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends,HTTPException,Path,Request
from fastapi.responses import HTMLResponse,RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.domain import entry_notifications as service
from app.domain.entry_notification_policy import policy_from_document
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid,EntryStorageUnavailable
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer','X-Robots-Tag':'noindex'}
META=('_n_action','_n_revision','_n_policy','_n_key','_n_preview','_n_renderer','_n_template','_n_values')
UNAVAILABLE={'application_case_unavailable','application_unavailable','applicant_unavailable'}
REASONS={'notification_application_changed':'После сохранения изменились сведения заявки',
    'notification_renderer_changed':'Текущая версия шаблонов изменилась',
    'notification_policy_changed':'Условия хранения изменились',
    'notification_catalog_changed':'Источник шаблонов изменился',
    'notification_policy_or_source_unavailable':'Нет действующих полномочий или текущий источник недоступен'}


def _url(case_id,application_id):return f'/admin/case/{case_id}/kg-entry/applications/{application_id}/notification-drafts'


def _policy():
    try:return policy_from_document(ar.settings.kg_notification_storage_policy) if ar.settings.kg_notification_storage_policy else None
    except EntryStorageInvalid:return None


def _csrf(request):
    request.session.setdefault('kg_notification_csrf',secrets.token_hex(32));return request.session['kg_notification_csrf']


def _signature(request,actor,case_id,application_id,values):
    body=json.dumps(['kg-notification-form/1',actor.manager_id,case_id,application_id,_csrf(request),
        [values.get(k,'') for k in META]],ensure_ascii=True,separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),body,hashlib.sha256).hexdigest()


def _envelope(request,actor,case_id,application_id,*,policy,current=None,template_id=None,preview=None,key=None):
    shown=preview['preview'] if preview else None
    data=dict(_n_action='save' if shown else 'preview',_n_revision=str(shown['expected_revision'] if shown else current['revision']),
        _n_policy=shown['policy_hash'] if shown else policy.digest,_n_key=key or secrets.token_hex(16),
        _n_preview=preview['preview_hash'] if shown else '',_n_renderer=shown['renderer_version'] if shown else service.rules.VERSION,
        _n_template=shown['parameters']['template_id'] if shown else template_id,
        _n_values=json.dumps(shown['parameters']['values'],ensure_ascii=False,separators=(',',':')) if shown else '')
    data['_n_csrf']=_csrf(request);data['_n_sig']=_signature(request,actor,case_id,application_id,data)
    return data


def _unique_object(pairs):
    result=dict(pairs)
    if len(result)!=len(pairs):raise ValueError
    return result


async def _form(request,actor,case_id,application_id):
    try:
        if request.headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded':raise ValueError
        length=request.headers.get('content-length')
        if length is not None and (not length.isascii() or not length.isdecimal() or int(length)>65536):raise ValueError
        raw=bytearray()
        async for chunk in request.stream():
            if len(raw)+len(chunk)>65536:raise ValueError
            raw.extend(chunk)
        decoded=raw.decode('utf-8')
        if re.search(r'%(?![0-9a-fA-F]{2})',decoded):raise ValueError
        pairs=parse_qsl(decoded,keep_blank_values=True,strict_parsing=True,max_num_fields=96,encoding='utf-8',errors='strict')
        values=dict(pairs);required=set(META+('_n_csrf','_n_sig'))
        if len(values)!=len(pairs) or not required<=set(values):raise ValueError
        if any(len(k)>40 or len(v)>(24576 if k=='_n_values' else 500) for k,v in pairs):raise ValueError
        if values['_n_action'] not in ('preview','save'):raise ValueError
        if any(not re.fullmatch('[a-f0-9]{64}',values[k]) for k in ('_n_csrf','_n_sig')):raise HTTPException(403,headers=HEADERS)
        if not hmac.compare_digest(values['_n_csrf'],_csrf(request)):raise HTTPException(403,headers=HEADERS)
        if not hmac.compare_digest(values['_n_sig'],_signature(request,actor,case_id,application_id,values)):raise HTTPException(403,headers=HEADERS)
        if str(int(values['_n_revision']))!=values['_n_revision'] or not 0<=int(values['_n_revision'])<=128:raise ValueError
        if values['_n_action']=='save':
            if set(values)!=required|{'_n_confirm'} or values['_n_confirm']!='1':raise ValueError
            typed=json.loads(values['_n_values'],object_pairs_hook=_unique_object,
                             parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
        else:
            if values['_n_values']:raise ValueError
            template=next((t for t in service.rules.catalog().document()['templates'] if t['unit_id']==values['_n_template']),None)
            if template is None:raise ValueError
            allowed=set(required);typed={}
            for field in template['fields']:
                if field['kind']=='unresolved_calculation':continue
                key=field['id'];allowed.add(key)
                if field['kind']=='money':allowed.add(key+'_currency')
                value=values.get(key,'')
                if not value:continue
                if field['kind']=='positive_integer':
                    if not value.isascii() or not value.isdecimal() or str(int(value))!=value:raise ValueError
                    value=int(value)
                elif field['kind']=='money':value=dict(amount=value,currency=values.get(key+'_currency',''))
                typed[key]=value
            if not set(values)<=allowed:raise ValueError
        parameters=service._request(dict(template_id=values['_n_template'],values=typed))
        return values,parameters
    except (ValueError,UnicodeError,TypeError,EntryStorageInvalid,service.rules.NotificationInvalid):
        raise HTTPException(422,'Проверьте поля черновика и подтверждение сохранения.',headers=HEADERS) from None


async def _render(request,manager,actor,case,application_id,*,template_id=None,selected_revision=None,
                  preview=None,save_form=None,retry=None,error=None,status=200):
    current=None;selected=None;template=None;form=None;policy=_policy()
    try:
        current=await service.read_drafts(entry._engine(),actor=actor,case_id=case['id'],application_id=application_id,policy=policy)
        if current['history']:
            selected=next((h for h in current['history'] if h['receipt']['revision']==selected_revision),None) if selected_revision else current['history'][0]
            if selected is None:raise HTTPException(404,headers=HEADERS)
        elif selected_revision:raise HTTPException(404,headers=HEADERS)
        if current['templates']:
            template=next((t for t in current['templates'] if t['unit_id']==template_id),None) if template_id else current['templates'][0]
            if template is None:raise HTTPException(422,'Недоступный шаблон.',headers=HEADERS)
        if not retry and template and current['can_save'] and _write_on(request):
            form=_envelope(request,actor,case['id'],application_id,policy=policy,current=current,template_id=template['unit_id'])
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        current=None;error='История черновиков не прошла проверку. Новая запись недоступна.';status=503
    except HTTPException:raise
    except Exception:current=None;error='Хранилище временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_notifications.html',dict(request=request,manager=manager,case=case,
        application_id=application_id,current=current,selected=selected,template=template,form=form,
        preview=preview,save_form=save_form,retry=retry,error=error,url=_url(case['id'],application_id),reasons=REASONS),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applications/{application_id}/notification-drafts',response_class=HTMLResponse)
async def notification_form(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);case=await entry._case(case_id,actor)
    pairs=list(request.query_params.multi_items());selected_revision=None;template_id=None
    try:
        if len(pairs)>1:raise ValueError
        if pairs:
            name,value=pairs[0]
            if name=='revision':
                selected_revision=int(value)
                if str(selected_revision)!=value or not 1<=selected_revision<=128:raise ValueError
            elif name=='template' and re.fullmatch(r'KG\.TPL\.A[0-9]{2}',value):template_id=value
            else:raise ValueError
    except ValueError:raise HTTPException(422,'Недопустимый выбор черновика.',headers=HEADERS) from None
    return await _render(request,manager,actor,case,application_id,template_id=template_id,selected_revision=selected_revision)


@ar.router.post('/case/{case_id}/kg-entry/applications/{application_id}/notification-drafts',response_class=HTMLResponse)
async def notification_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);case=await entry._case(case_id,actor)
    values,parameters=await _form(request,actor,case_id,application_id);policy=_policy()
    try:
        if values['_n_action']=='preview':
            if policy is None or values['_n_policy']!=policy.digest:raise EntryStorageConflict('notification_policy_changed')
            shown=await service.preview_draft(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,parameters=parameters,policy=policy)
            saved=_envelope(request,actor,case_id,application_id,policy=policy,preview=shown,key=values['_n_key'])
            return await _render(request,manager,actor,case,application_id,template_id=parameters['template_id'],preview=shown,save_form=saved)
        await service.save_draft(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,parameters=parameters,
            expected_revision=int(values['_n_revision']),request_key=values['_n_key'],expected_policy_hash=values['_n_policy'],
            expected_preview_hash=values['_n_preview'],policy=policy,renderer_version=values['_n_renderer'])
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,application_id,status=409,error='Заявка, источник или предварительный просмотр изменились. Проверьте новую версию.')
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,application_id,status=422,error='Проверьте типы полей, доступность шаблона и условия хранения.')
    except Exception:
        return await _render(request,manager,actor,case,application_id,retry=values if values['_n_action']=='save' else None,
            status=503,error='Сохранение не подтверждено. Повторите исходный запрос; повтор не создаст дубль.')
    return RedirectResponse(_url(case_id,application_id),status_code=303,headers=HEADERS)
