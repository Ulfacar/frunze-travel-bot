"""Review evidence for imported source units, under existing administrator gates."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl, urlencode

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.domain import knowledge_decisions as service
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.service_authz import PermissionDenied

URL='/admin/kg-entry/reviews'
HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
META=('_kd_version','_kd_unit','_kd_revision','_kd_verdict','_kd_key')
SECURITY={'_kd_csrf','_kd_signature'}
FIELDS={'reason','evidence_kind','evidence_ref','proof','verified_on','review_due_on','confirmed'}
LABELS={'confirmed':'Подтверждение проверки','rejected':'Отклонение','needs_changes':'Запрос исправлений'}
REASONS={'source_matches':'Сверено с основанием','source_conflict':'Противоречие источников','insufficient_evidence':'Недостаточно подтверждений','outdated':'Сведения устарели','withdrawn':'Прежнее заключение отозвано'}


def _signature(request,actor,values):
    csrf=request.session.setdefault('kg_knowledge_decision_csrf',secrets.token_hex(32))
    payload=json.dumps(['kg-knowledge-review/1',actor.manager_id,csrf,[values.get(k,'') for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def _envelope(request,actor,version,unit,revision,verdict):
    values=dict(zip(META,(str(version),unit,str(revision),verdict,secrets.token_hex(24))))
    values['_kd_signature']=_signature(request,actor,values);values['_kd_csrf']=request.session['kg_knowledge_decision_csrf']
    return values


async def _form(request,actor):
    if request.query_params:raise HTTPException(422,headers=HEADERS)
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':raise HTTPException(415,headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>4096:raise HTTPException(413,headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=16,encoding='utf-8',errors='strict');values=dict(pairs)
        if len(pairs)!=len(values) or any(len(v)>128 for k,v in pairs):raise ValueError
        if not (set(META)|SECURITY)<=values.keys() or not values.keys()<=(set(META)|SECURITY|FIELDS):raise ValueError
        if values['_kd_verdict'] not in LABELS:raise ValueError
    except (ValueError,UnicodeError):raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS) from None
    token=request.session.get('kg_knowledge_decision_csrf','')
    if (not token or not hmac.compare_digest(token.encode(),values['_kd_csrf'].encode()) or
        not re.fullmatch('[a-f0-9]{48}',values['_kd_key']) or
        not hmac.compare_digest(_signature(request,actor,values).encode(),values['_kd_signature'].encode())):
        raise HTTPException(403,'Форма устарела или изменена. Откройте её заново.',headers=HEADERS)
    return values


async def _render(request,manager,actor,*,version=None,unit='',revision=None,page=1,query='',error='',status=200,echo=None,retry=None):
    catalog=None;report=None;forms={}
    try:
        if unit:
            report=await service.read_knowledge_decisions(entry._engine(),actor=actor,version_id=version,unit_id=unit,revision=revision)
            historical=revision is not None and revision!=report['current_revision']
            if not historical and report['current_revision']<service.MAX_REVISIONS and retry is None:
                forms={verdict:_envelope(request,actor,version,unit,report['current_revision'],verdict) for verdict in LABELS}
            if echo and echo['_kd_verdict'] in forms and echo['_kd_revision']==str(report['current_revision']):forms[echo['_kd_verdict']]=echo
        else:
            catalog=await service.review_catalog(entry._engine(),actor=actor,version_id=version,page=page,query=query)
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ('knowledge_version_unavailable','knowledge_unit_unavailable','knowledge_decision_unavailable'):
            raise HTTPException(404,headers=HEADERS) from None
        catalog=None;report=None;forms={};error='Не удалось проверить источник или историю решений. Изменения недоступны.';status=503
    except Exception:
        catalog=None;report=None;forms={};error='Хранилище базы знаний временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_knowledge_decisions.html',dict(manager=manager,url=URL,catalog=catalog,
        report=report,forms=forms,revision=revision,error=error,retry=retry,echo=echo or {},write_on=_write_on(request),labels=LABELS,reasons=REASONS),
        status_code=status,headers=HEADERS)


@ar.router.get('/kg-entry/reviews',response_class=HTMLResponse)
async def review_form(request:Request,version:int|None=Query(None,ge=1,le=2147483647),unit:str=Query('',max_length=120),
    revision:int|None=Query(None,ge=1,le=250),page:int=Query(1,ge=1,le=250),q:str=Query('',max_length=80),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager)
    pairs=request.query_params.multi_items()
    if len(dict(pairs))!=len(pairs) or any(k not in ('version','unit','revision','page','q') for k,v in pairs):raise HTTPException(422)
    if unit and not version or revision and not unit or unit and (q or page!=1) or any(ord(c)<32 for c in q):raise HTTPException(422)
    if unit:
        try:service._unit_id(unit)
        except EntryStorageInvalid:raise HTTPException(422) from None
    return await _render(request,manager,actor,version=version,unit=unit,revision=revision,page=page,query=q)


@ar.router.post('/kg-entry/reviews',response_class=HTMLResponse)
async def review_submit(request:Request,manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);values=await _form(request,actor)
    try:version=int(values['_kd_version'])
    except ValueError:raise HTTPException(422,headers=HEADERS) from None
    unit=values['_kd_unit']
    try:
        decision={k:values.get(k,'') for k in FIELDS}
        decision.update(verdict=values['_kd_verdict'],confirmed=values.get('confirmed')=='yes',review_due_on=values.get('review_due_on') or None)
        await service.record_knowledge_decision(entry._engine(),actor=actor,version_id=version,unit_id=unit,
            expected_revision=int(values['_kd_revision']),request_key=values['_kd_key'],decision=decision)
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,version=version,unit=unit,status=409,error='Решение уже изменилось. Сверьте последнюю запись.')
    except EntryStorageUnavailable:
        return await _render(request,manager,actor,version=version,unit=unit,status=503,retry=values,error='Результат сохранения неизвестен. Повторите исходный запрос без изменений.')
    except (EntryStorageInvalid,ValueError,KeyError):
        return await _render(request,manager,actor,version=version,unit=unit,status=422,echo=values,error='Проверьте дату, основание, контрольную сумму и подтверждение. Срок повторной проверки задаётся явно.')
    except Exception:
        return await _render(request,manager,actor,version=version,unit=unit,status=503,retry=values,error='Результат сохранения неизвестен. Повторите исходный запрос без изменений.')
    return RedirectResponse(URL+'?'+urlencode(dict(version=version,unit=unit)),status_code=303,headers=HEADERS)
