"""Native internal deadline-task control under the existing full-admin pilot gate."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl, urlencode

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.domain import entry_deadline_tasks as service
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
META=('_dt_action','_dt_rule','_dt_binding','_dt_token','_dt_key','_dt_cursor')
SECURITY={'_dt_csrf','_dt_signature'}
ACTIONS=('sync','restore','complete','cancel','escalate','sweep')
ATTENTION={'unknown_date':'Подтверждённая дата пока не установлена.', 'missing_owner':'У услуги нет ответственного.',
    'claimed':'Задачу уже обрабатывают. Сначала выясните результат обработки.',
    'schedule_conflict':'Дата задачи изменена вручную. Сверьте её перед применением текущего срока.',
    'generation_limit':'Достигнут предел истории задач. Требуется разбор специалистом.'}
STATUSES={'planned':'Запланирована','rescheduled':'Перенесена','completed':'Выполнена','cancelled':'Отменена'}


def _url(case_id,application_id):
    return f'/admin/case/{case_id}/kg-entry/applications/{application_id}/deadline-tasks'


def _signature(request,actor,case_id,application_id,values):
    token=request.session.setdefault('kg_deadline_task_csrf',secrets.token_hex(32))
    payload=json.dumps(['kg-deadline-task/1',actor.manager_id,case_id,application_id,token,
        [values.get(k,'') for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def _envelope(request,actor,case_id,application_id,rule,current,action,cursor=0):
    values=dict(zip(META,(action,rule,str(current['binding_id'] or ''),current['token'] or '',secrets.token_hex(24),str(cursor))))
    values['_dt_signature']=_signature(request,actor,case_id,application_id,values)
    values['_dt_csrf']=request.session['kg_deadline_task_csrf']
    return values


async def _form(request,actor,case_id,application_id):
    if request.query_params:raise HTTPException(422,headers=HEADERS)
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>4096:raise HTTPException(413,headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=12,encoding='utf-8',errors='strict')
        values=dict(pairs)
        if len(values)!=len(pairs) or any(len(v)>128 for k,v in pairs):raise ValueError
        if not (set(META)|SECURITY)<=values.keys() or not values.keys()<=(set(META)|SECURITY|{'confirmed','reason'}):raise ValueError
        if values['_dt_action'] not in ACTIONS or values['_dt_action']!='escalate' and 'reason' in values:raise ValueError
    except (ValueError,UnicodeError):raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS) from None
    token=request.session.get('kg_deadline_task_csrf','')
    if (not token or not hmac.compare_digest(token.encode(),values.get('_dt_csrf','').encode()) or
        not re.fullmatch('[a-f0-9]{48}',values['_dt_key']) or
        not hmac.compare_digest(_signature(request,actor,case_id,application_id,values).encode(),values['_dt_signature'].encode())):
        raise HTTPException(403,'Форма устарела или изменена. Откройте её заново.',headers=HEADERS)
    return values


async def _render(request,manager,actor,case,application_id,rule,*,error='',status=200,retry=None,batch=None):
    state=None;forms={}
    try:
        state=await service.read_deadline_task(entry._engine(),actor=actor,case_id=case['id'],application_id=application_id,rule_unit_id=rule)
        current=state['current']
        if retry is None:
            actions=['sync','sweep']
            task=current['task']
            if task and task['status'] in service.ACTIVE and not task['claimed']:
                if current['attention']=='schedule_conflict':actions.append('restore')
                elif not current['pending']:actions+=['complete','cancel','escalate']
            forms={action:_envelope(request,actor,case['id'],application_id,rule,current,action,
                batch.get('next_cursor') or 0 if action=='sweep' and batch else 0) for action in actions}
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ('application_case_unavailable','application_unavailable','deadline_task_source_required'):
            raise HTTPException(404,headers=HEADERS) from None
        error='Не удалось проверить задачу и источник срока. Изменения недоступны.';status=503
    except Exception:
        error='Хранилище задач временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_deadline_tasks.html',dict(manager=manager,case=case,application_id=application_id,
        url=_url(case['id'],application_id),rule=rule,state=state,forms=forms,error=error,retry=retry,batch=batch,
        write_on=_write_on(request),attention=ATTENTION,statuses=STATUSES),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applications/{application_id}/deadline-tasks',response_class=HTMLResponse)
async def task_form(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),
    rule:str=Query(...,pattern=r'^KG\.DL\.[A-Z0-9_]{1,64}$',max_length=80),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager)
    if list(request.query_params.keys())!=['rule'] or len(request.query_params.multi_items())!=1:raise HTTPException(422)
    try:case=await entry._case(case_id,actor)
    except HTTPException:raise
    except Exception:return HTMLResponse('Реестр услуг временно недоступен.',status_code=503,headers=HEADERS)
    return await _render(request,manager,actor,case,application_id,rule)


@ar.router.post('/case/{case_id}/kg-entry/applications/{application_id}/deadline-tasks',response_class=HTMLResponse)
async def task_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True)
    try:case=await entry._case(case_id,actor)
    except HTTPException:raise
    except Exception:return HTMLResponse('Реестр услуг временно недоступен.',status_code=503,headers=HEADERS)
    values=await _form(request,actor,case_id,application_id);rule=values['_dt_rule'];action=values['_dt_action']
    args=dict(actor=actor,case_id=case_id,application_id=application_id,rule_unit_id=rule)
    try:
        if values.get('confirmed')!='yes':raise EntryStorageInvalid('confirmation_required')
        if action=='sweep':
            batch=await service.reconcile_case_deadline_tasks(entry._engine(),actor=actor,case_id=case_id,after_binding_id=int(values['_dt_cursor']))
            return await _render(request,manager,actor,case,application_id,rule,batch=batch)
        if action in ('sync','restore'):
            await service.reconcile_deadline_task(entry._engine(),**args,enable=True,restore=action=='restore',expected_token=values['_dt_token'])
        else:
            await service.act_on_deadline_task(entry._engine(),**args,binding_id=int(values['_dt_binding']),expected_token=values['_dt_token'],
                request_key=values['_dt_key'],action=action,reason=values.get('reason'))
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,application_id,rule,status=409,error='Задача или срок изменились. Сверьте текущее состояние.')
    except EntryStorageUnavailable:
        return await _render(request,manager,actor,case,application_id,rule,status=503,retry=values,error='Результат сохранения неизвестен. Повторите исходный запрос без изменений.')
    except (EntryStorageInvalid,ValueError,KeyError):
        return await _render(request,manager,actor,case,application_id,rule,status=422,error='Проверьте подтверждение, причину и текущее состояние задачи.')
    except Exception:
        return await _render(request,manager,actor,case,application_id,rule,status=503,retry=values,error='Результат сохранения неизвестен. Повторите исходный запрос без изменений.')
    return RedirectResponse(_url(case_id,application_id)+'?'+urlencode(dict(rule=rule)),status_code=303,headers=HEADERS)
