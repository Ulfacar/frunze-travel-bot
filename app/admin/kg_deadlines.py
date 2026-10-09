"""Application deadline review and manual evidence under existing pilot gates."""
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
from app.domain import entry_deadlines as service
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict, EntryStorageUnavailable
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
META=('_dl_action','_dl_rule','_dl_revision','_dl_key')
SECURITY={'_dl_csrf','_dl_signature'}
FIELDS={
    'recalculate':{'knowledge_version_id','calendar_id','anchor','policy','count_anchor_day','month_end','hours_mode','confirmed'},
    'manual':{'due_on','evidence_on','proof','source','reason','confirmed'},
    'clear':{'reason','confirmed'},
}
NOT_FOUND={'application_case_unavailable','application_unavailable','applicant_unavailable','deadline_revision_unavailable'}
BLOCKERS={'actual_anchor_missing':'Не записано фактическое событие для отсчёта',
    'actual_anchor_superseded':'Появилось более позднее событие: нужен пересчёт',
    'rule_value_missing':'В источнике нет проверенного значения для расчёта',
    'source_anchor_not_supported':'Событие не соответствует основанию отсчёта в источнике',
    'counting_policy_missing':'Не выбрано правило отсчёта',
    'calendar_year_missing':'Нет календаря на нужный год',
    'calendar_provisional':'Календарь ещё не полон',
    'aware_anchor_required':'Для часового срока требуется точное время события'}


def _url(case_id,application_id):
    return f'/admin/case/{case_id}/kg-entry/applications/{application_id}/deadlines'


def _csrf(request):
    request.session.setdefault('kg_deadline_csrf',secrets.token_hex(32))
    return request.session['kg_deadline_csrf']


def _signature(request,actor,case_id,application_id,values):
    payload=json.dumps(['kg-deadline-form/1',actor.manager_id,case_id,application_id,_csrf(request),
                        [values.get(k,'') for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def _envelope(request,actor,case_id,application_id,rule,revision,action):
    values=dict(zip(META,(action,rule,str(revision),secrets.token_hex(24))))
    values.update(_dl_csrf=_csrf(request),_dl_signature=_signature(request,actor,case_id,application_id,values))
    return values


async def _form(request,actor,case_id,application_id):
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>8192:raise HTTPException(413,headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=36,encoding='utf-8',errors='strict')
        values={};calendars=[]
        for name,value in pairs:
            if len(value)>128:raise ValueError
            if name=='calendar_id':
                calendars.append(value)
                if len(calendars)>10:raise ValueError
            else:
                if name in values:raise ValueError
                values[name]=value
        action=values.get('_dl_action')
        if action not in FIELDS or not set(values)<=(set(META)|SECURITY|FIELDS[action]):raise ValueError
        if calendars:
            if action!='recalculate':raise ValueError
            values['calendar_id']=calendars
    except (ValueError,UnicodeError):raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS) from None
    token=request.session.get('kg_deadline_csrf','')
    if (not token or not hmac.compare_digest(token.encode(),values.get('_dl_csrf','').encode()) or
        not re.fullmatch('[a-f0-9]{48}',values.get('_dl_key','')) or
        not hmac.compare_digest(_signature(request,actor,case_id,application_id,values).encode(),values.get('_dl_signature','').encode())):
        raise HTTPException(403,'Форма устарела или изменена. Откройте её заново.',headers=HEADERS)
    return values


def _operation(values):
    action=values['_dl_action']
    if action=='recalculate':
        selected=values.get('anchor','')
        anchor=None
        if selected:
            kind,identifier=selected.split(':',1)
            anchor=dict(kind=kind,id=int(identifier))
        if values.get('policy') not in ('','proposed'):raise ValueError
        policy=None
        if values.get('policy')=='proposed':
            count={'':None,'true':True,'false':False}[values.get('count_anchor_day','')]
            policy=dict(status='proposed',timezone='Asia/Bishkek',count_anchor_day=count,
                        month_end=values.get('month_end') or None,hours_mode=values.get('hours_mode') or None)
        data=dict(knowledge_version_id=int(values.get('knowledge_version_id','')),
            calendar_ids=[int(v) for v in values.get('calendar_id',[]) if v],anchor=anchor,policy=policy)
    else:
        data={k:values.get(k,'') for k in FIELDS[action]-{'confirmed'}}
    return dict(action=action,data=data,confirmed=values.get('confirmed')=='yes')


async def _render(request,manager,actor,case,application_id,*,rule='',revision=None,version=None,error='',status=200,echo=None,retry=None):
    options=None;history=None;forms={};selected_rule=None;values={}
    try:
        if rule:
            history=await service.read_deadline_history(entry._engine(),actor=actor,case_id=case['id'],
                application_id=application_id,rule_unit_id=rule,revision=revision)
        current=history['selected'] if history else None
        if version is None and current:version=current['snapshot']['selection']['knowledge_version_id']
        options=await service.read_deadline_options(entry._engine(),actor=actor,case_id=case['id'],
            application_id=application_id,knowledge_version_id=version,
            pinned_calendar_ids=current['snapshot']['selection']['calendar_ids'] if current else None)
        if options['rules']:
            if not rule:rule=options['rules'][0]['unit_id']
            selected_rule=next((r for r in options['rules'] if r['unit_id']==rule),None)
            if selected_rule is None:raise HTTPException(404,headers=HEADERS)
            if history is None:
                history=await service.read_deadline_history(entry._engine(),actor=actor,case_id=case['id'],
                    application_id=application_id,rule_unit_id=rule,revision=revision)
            current=history['selected']
            if current:
                data=current['snapshot']['selection'];anchor=data['anchor'];policy=data['policy'] or {}
                values=dict(knowledge_version_id=str(options['knowledge_version_id']),calendar_id=[str(v) for v in data['calendar_ids']],
                    anchor=f"{anchor['kind']}:{anchor['id']}" if anchor else '',policy='proposed' if policy else '',
                    count_anchor_day='true' if policy.get('count_anchor_day') is True else 'false' if policy.get('count_anchor_day') is False else '',
                    month_end=policy.get('month_end') or '',hours_mode=policy.get('hours_mode') or '')
            else:values=dict(knowledge_version_id=str(options['knowledge_version_id']),calendar_id=[])
            historical=revision is not None and revision!=history['current_revision']
            if not historical and history['current_revision']<service.MAX_REVISIONS and retry is None:
                actions=['recalculate']+(['manual'] if current else [])+(['clear'] if current and current['snapshot']['manual'] else [])
                forms={action:_envelope(request,actor,case['id'],application_id,rule,history['current_revision'],action) for action in actions}
            if echo and echo['_dl_action'] in forms and echo['_dl_revision']==str(history['current_revision']):
                forms[echo['_dl_action']]=echo
                values={**values,**echo}
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in NOT_FOUND:raise HTTPException(404,headers=HEADERS) from None
        options=None;history=None;forms={};error='Не удалось проверить сроки или источники. Изменения недоступны.';status=503
    except HTTPException:raise
    except Exception:
        options=None;history=None;forms={};error='Хранилище сроков временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_deadlines.html',dict(manager=manager,case=case,application_id=application_id,
        url=_url(case['id'],application_id),options=options,history=history,rule=selected_rule,forms=forms,values=values,
        error=error,retry=retry,write_on=_write_on(request),meta=META,security=SECURITY,blockers=BLOCKERS),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applications/{application_id}/deadlines',response_class=HTMLResponse)
async def deadline_form(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),
    rule:str=Query('',max_length=80),revision:int|None=Query(None,ge=1,le=service.MAX_REVISIONS),
    version:int|None=Query(None,ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager)
    pairs=list(request.query_params.multi_items())
    if len({k for k,v in pairs})!=len(pairs) or any(k not in ('rule','revision','version') for k,v in pairs):raise HTTPException(422)
    if rule and not re.fullmatch(r'KG\.DL\.[A-Z0-9_]{1,64}',rule) or revision and not rule or revision and version:
        raise HTTPException(422)
    try:case=await entry._case(case_id,actor)
    except HTTPException:raise
    except Exception:return HTMLResponse('Реестр услуг временно недоступен.',status_code=503,headers=HEADERS)
    return await _render(request,manager,actor,case,application_id,rule=rule,revision=revision,version=version)


@ar.router.post('/case/{case_id}/kg-entry/applications/{application_id}/deadlines',response_class=HTMLResponse)
async def deadline_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True)
    try:case=await entry._case(case_id,actor)
    except HTTPException:raise
    except Exception:return HTMLResponse('Реестр услуг временно недоступен. Сохранение не выполнено.',status_code=503,headers=HEADERS)
    values=await _form(request,actor,case_id,application_id)
    rule=values['_dl_rule']
    try:
        await service.record_deadline_operation(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,
            rule_unit_id=rule,expected_revision=int(values['_dl_revision']),request_key=values['_dl_key'],operation=_operation(values))
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,application_id,rule=rule,status=409,
            error='Запись уже изменилась. Сверьте последнюю версию перед новой операцией.')
    except EntryStorageUnavailable:
        return await _render(request,manager,actor,case,application_id,rule=rule,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос без изменений.')
    except (EntryStorageInvalid,ValueError,KeyError) as exc:
        if str(exc) in NOT_FOUND:raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,application_id,rule=rule,status=422,echo=values,
            error='Проверьте дату, подтверждение и основание. При новом событии сначала пересчитайте срок; старая ручная дата будет снята.')
    except Exception:
        return await _render(request,manager,actor,case,application_id,rule=rule,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос без изменений.')
    return RedirectResponse(_url(case_id,application_id)+'?'+urlencode(dict(rule=rule)),status_code=303,headers=HEADERS)
