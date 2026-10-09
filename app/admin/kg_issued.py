"""Native post-issue metadata workflow; no file upload or external delivery."""
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
from app.domain import entry_issued as service
from app.domain.entry_issued_rules import CHECKS,CHANNELS,CAUSES,MAX_REVISIONS
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
META=('_is_action','_is_revision','_is_key','_is_version','_is_fingerprint','_is_passport')
SECURITY={'_is_csrf','_is_signature'}
FIELDS={
    'file':{'on','fingerprint','passport_fingerprint','confirmed'},
    'review':{'on','confirmed',*('check_'+key for key in CHECKS)},
    'correction':{'on','cause','proof','confirmed'},
    'delivery':{'on','channel','proof','pamphlet','confirmed'},
    'receipt':{'on','proof','identity_checked','confirmed'},
    'passport_change':{'on','passport_fingerprint','confirmed'},
    'travel':{'on','direction','proof','source','passport_fingerprint','confirmed'},
}
ACTIONS={'file':'Записать выданный файл','review':'Сверить выданный документ','correction':'Зафиксировать ошибку',
         'delivery':'Записать передачу','receipt':'Подтвердить получение клиентом','passport_change':'Установить смену паспорта',
         'travel':'Записать фактический въезд / выезд'}
NOT_FOUND={'application_case_unavailable','application_unavailable','applicant_unavailable','issued_revision_unavailable'}
ERRORS={
    'issued_review_required':'Сначала проверьте актуальный файл по текущему паспорту.',
    'issued_version_changed':'Версия файла изменилась. Откройте текущую запись.',
    'issued_passport_mismatch':'Паспорт не совпадает с выданным документом. Нужен исправленный файл.',
    'invalid_issued_date':'Проверьте фактическую дату и порядок операций. Будущие события не записываются как факты.',
    'issued_content_unchanged':'Этот файл уже записан как текущая версия.',
    'issued_delivery_missing':'Сначала запишите фактическую передачу клиенту.',
    'issued_approval_required':'Нужно подтверждённое одобрение визовой заявки с портала или официального документа.',
    'duplicate_actual_travel_fact':'Этот факт въезда или выезда уже записан.',
    'invalid_issued_fingerprint':'Контрольная сумма SHA256 должна содержать64 строчных шестнадцатеричных символа.',
    'issued_confirmation_required':'Подтвердите указанные факты.',
}


def _csrf(request):
    request.session.setdefault('kg_issued_csrf',secrets.token_hex(32))
    return request.session['kg_issued_csrf']


def _signature(request,actor,case_id,application_id,values):
    data=json.dumps(['kg-issued/1',actor.manager_id,case_id,application_id,_csrf(request),
                     [values.get(key,'') for key in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),data,hashlib.sha256).hexdigest()


def _envelope(request,actor,case_id,application_id,action,history):
    snapshot=history['selected']['snapshot'] if history['selected'] else {}
    values=dict(zip(META,(action,str(history['current_revision']),secrets.token_hex(24),str(snapshot.get('version',0)),
                         snapshot.get('fingerprint') or '',snapshot.get('current_passport') or '')))
    return {**values,'_is_csrf':_csrf(request),'_is_signature':_signature(request,actor,case_id,application_id,values)}


async def _form(request,actor,case_id,application_id):
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'Используйте форму.',headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>8192:raise HTTPException(413,'Форма слишком большая.',headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=30,encoding='utf-8',errors='strict')
        if len(set(k for k,v in pairs))!=len(pairs) or any(len(v)>128 for k,v in pairs):raise ValueError
        values=dict(pairs);action=values.get('_is_action')
        if action not in FIELDS or not values.keys()<=(set(META)|SECURITY|FIELDS[action]):raise ValueError
    except (ValueError,UnicodeError):raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS) from None
    token=request.session.get('kg_issued_csrf','')
    if (not token or not hmac.compare_digest(token.encode(),values.get('_is_csrf','').encode()) or
        not hmac.compare_digest(_signature(request,actor,case_id,application_id,values).encode(),values.get('_is_signature','').encode())):
        raise HTTPException(403,'Форма изменена или относится к другой сессии.',headers=HEADERS)
    return values


def _boolean(value,*,optional_not_present=False):
    choices={'':None,'true':True,'false':False}
    if optional_not_present:choices['not_present']='not_present'
    if value not in choices:raise EntryStorageInvalid('invalid_issued_checks')
    return choices[value]


def _operation(values):
    action=values['_is_action'];data={'on':values.get('on','')}
    for key in FIELDS[action]-{'on','confirmed','identity_checked'}:
        if not key.startswith('check_'):data[key]=values.get(key,'')
    if action in ('review','correction','delivery','receipt'):
        data.update(version=int(values['_is_version']),fingerprint=values['_is_fingerprint'])
    if action=='review':
        data.update(passport_fingerprint=values['_is_passport'],checks={key:_boolean(values.get('check_'+key,''),
            optional_not_present=key=='passport_dates') for key in CHECKS})
    if action=='receipt':data['identity_checked']=_boolean(values.get('identity_checked',''))
    return dict(action=action,data=data,confirmed=values.get('confirmed')=='yes')


async def _render(request,manager,actor,case,application_id,*,revision=None,error='',status=200,echo=None,retry=None):
    history=None;forms={}
    url=f'/admin/case/{case["id"]}/kg-entry/applications/{application_id}/issued'
    try:
        history=await service.read_issued_history(entry._engine(),actor=actor,case_id=case['id'],application_id=application_id,revision=revision)
        current=history['selected'];snapshot=current['snapshot'] if current else None
        if history['approval_available'] and (revision is None or revision==history['current_revision']) and history['current_revision']<MAX_REVISIONS:
            actions=['file','travel']
            if snapshot and snapshot['version']:actions+=['review','correction','delivery','receipt','passport_change']
            for action in actions:forms[action]=_envelope(request,actor,case['id'],application_id,action,history)
        if echo and echo['_is_action'] in forms and echo['_is_revision']==str(history['current_revision']):forms[echo['_is_action']]=echo
        if retry:forms={}
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in NOT_FOUND:raise HTTPException(404,headers=HEADERS) from None
        history=None;forms={};error='История не прошла проверку. Изменения недоступны.';status=503
    except Exception:
        history=None;forms={};error='Хранилище временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_issued.html',dict(request=request,manager=manager,case=case,
        application_id=application_id,history=history,forms=forms,actions=ACTIONS,checks=CHECKS,channels=CHANNELS,causes=CAUSES,
        error=error,retry=retry,url=url,write_on=_write_on(request),meta=META,security=SECURITY,
        today=ar._bishkek_today().isoformat()),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applications/{application_id}/issued',response_class=HTMLResponse)
async def issued_form(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);pairs=list(request.query_params.multi_items())
    try:
        if len(pairs)>1 or any(key!='revision' for key,value in pairs):raise ValueError
        value=request.query_params.get('revision')
        if value is not None and len(value)>3:raise ValueError
        revision=int(value) if value is not None else None
        if value is not None and (str(revision)!=value or not 1<=revision<=MAX_REVISIONS):raise ValueError
    except ValueError:raise HTTPException(422,'Недопустимая версия истории.',headers=HEADERS) from None
    case=await entry._case(case_id,actor)
    return await _render(request,manager,actor,case,application_id,revision=revision)


@ar.router.post('/case/{case_id}/kg-entry/applications/{application_id}/issued',response_class=HTMLResponse)
async def issued_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);case=await entry._case(case_id,actor)
    values=await _form(request,actor,case_id,application_id)
    try:
        await service.record_issued_operation(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,
            expected_revision=int(values['_is_revision']),request_key=values['_is_key'],operation=_operation(values))
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,application_id,status=409,error='История изменилась. Проверьте текущую версию перед новой операцией.')
    except EntryStorageInvalid as exc:
        if str(exc) in NOT_FOUND:raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,application_id,status=422,echo=values,
            error=ERRORS.get(str(exc),'Проверьте факты и версию документа. Новая запись не добавлена.'))
    except Exception:
        return await _render(request,manager,actor,case,application_id,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос без изменений для проверки результата без дубля.')
    return RedirectResponse(f'/admin/case/{case_id}/kg-entry/applications/{application_id}/issued',status_code=303,headers=HEADERS)
