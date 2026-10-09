"""Native immutable inventory editor; existing full-admin and write gates only."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends,HTTPException,Path,Query,Request
from fastapi.responses import HTMLResponse,RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.domain import entry_documents as service
from app.domain.entry_document_rules import PRODUCTS,SOURCES,REASONS,MAX_REVISIONS
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict
from app.domain.service_authz import PermissionDenied
from app.knowledge.document_checklist import load_document_catalog,KINDS

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
META=('_di_action','_di_revision','_di_key','_di_item','_di_version','_di_fingerprint','_di_catalog')
SECURITY={'_di_csrf','_di_signature'}
FIELDS={'initialize':{'product','confirmed'},'receive':{'fingerprint','on','source','confirmed'},
        'review':{'on','outcome','reason','confirmed'},'withdraw':{'on','reason','confirmed'},
        'applicability':{'applicable','confirmed'},'passport_change':{'on','reason','confirmed'}}
STATES={'missing':'Нет документа','received':'Получен, ожидает проверки','checked':'Проверен',
        'correction':'Нужна доработка','withdrawn':'Отозван','recheck':'Нужна повторная проверка'}
UNAVAILABLE={'application_case_unavailable','application_unavailable','applicant_unavailable'}
ERRORS={'document_version_changed':'Версия документа изменилась. Откройте актуальную запись.',
        'document_content_unchanged':'Этот файл уже записан как текущая версия.',
        'document_source_unverified':'Требование источника ещё не подтверждено; отметка проверки недоступна.',
        'invalid_document_date':'Проверьте фактическую дату: она не может быть в будущем или раньше получения.',
        'document_confirmation_required':'Подтвердите операцию.',
        'document_application_closed':'Работа с комплектом этой попытки завершена. История доступна для просмотра.',
        'invalid_document_fingerprint':'Контрольная сумма SHA256: 64 строчные шестнадцатеричные цифры.',
        'document_history_limit':'Достигнут предел истории. Новая запись не добавлена.'}


def _csrf(request):
    if not request.session.get('kg_document_inventory_csrf'):request.session['kg_document_inventory_csrf']=secrets.token_hex(32)
    return request.session['kg_document_inventory_csrf']


def _signature(request,actor,case_id,application_id,values):
    data=json.dumps(['kg-document-inventory/1',actor.manager_id,case_id,application_id,_csrf(request),
                     [values.get(key,'') for key in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),data,hashlib.sha256).hexdigest()


def _envelope(request,actor,case_id,application_id,action,revision,item=None,catalog=''):
    values=dict(zip(META,(action,str(revision),secrets.token_hex(24),item['id'] if item else '',
                         str(item['version']) if item else '0',item['fingerprint'] or '' if item else '',catalog)))
    values.update(_di_csrf=_csrf(request),_di_signature=_signature(request,actor,case_id,application_id,values))
    return values


async def _form(request,actor,case_id,application_id):
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'Используйте форму документов.',headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>8192:raise HTTPException(413,'Форма слишком большая.',headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=22,encoding='utf-8',errors='strict')
        if len({k for k,v in pairs})!=len(pairs) or any(len(v)>128 for k,v in pairs):raise ValueError
        values=dict(pairs);action=values.get('_di_action')
        if action not in FIELDS or not values.keys()<=(set(META)|SECURITY|FIELDS[action]):raise ValueError
    except (ValueError,UnicodeError):raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS) from None
    token=request.session.get('kg_document_inventory_csrf','')
    if (not token or not hmac.compare_digest(token.encode(),values.get('_di_csrf','').encode())
        or not re.fullmatch('[a-f0-9]{48}',values.get('_di_key',''))
        or not hmac.compare_digest(_signature(request,actor,case_id,application_id,values).encode(),values.get('_di_signature','').encode())):
        raise HTTPException(403,'Форма изменена или относится к другой сессии. Откройте её заново.',headers=HEADERS)
    return values


def _operation(values):
    action=values['_di_action'];data={}
    if action=='initialize':data=dict(product=values.get('product',''),catalog_digest=values['_di_catalog'])
    if action in ('receive','review','withdraw','applicability'):data['item']=values['_di_item']
    if action in ('receive','review','withdraw','passport_change'):data['on']=values.get('on','')
    if action=='receive':data.update(fingerprint=values.get('fingerprint',''),source=values.get('source',''))
    if action in ('review','withdraw'):
        data.update(version=int(values['_di_version']),fingerprint=values['_di_fingerprint'],reason=values.get('reason') or None)
    if action=='review':data['outcome']=values.get('outcome','')
    if action=='applicability':
        value=values.get('applicable','')
        if value not in ('','true','false'):raise EntryStorageInvalid('invalid_document_operation')
        data['applicable']={'':None,'true':True,'false':False}[value]
    if action=='passport_change':data['reason']=values.get('reason','')
    return dict(action=action,data=data,confirmed=values.get('confirmed')=='yes')


async def _render(request,manager,actor,case,application_id,*,item_id='',revision=None,error='',status=200,echo=None,retry=None):
    inventory=None;selected_item=None;forms={};products={}
    url=f'/admin/case/{case["id"]}/kg-entry/applications/{application_id}/documents'
    try:
        inventory=await service.read_document_inventory(entry._engine(),actor=actor,case_id=case['id'],application_id=application_id,revision=revision)
        current=inventory['selected']
        if item_id and (not current or item_id not in current['snapshot']['items']):raise HTTPException(404,headers=HEADERS)
        if current:
            items=current['summary']['items']
            selected_item=next((r for r in items if r['id']==item_id),items[0])
        historical=bool(revision and revision!=inventory['current_revision'])
        mutable=(not historical and inventory['application_status'] not in ('approved','refused','closed') and inventory['current_revision']<MAX_REVISIONS)
        if mutable:
            if not current:
                catalog=load_document_catalog();products={k:v for k,v in catalog.document()['products'].items() if k in PRODUCTS[inventory['application']['procedure']]}
                if products:forms['initialize']=_envelope(request,actor,case['id'],application_id,'initialize',0,catalog=catalog.digest)
            else:
                actions=['receive','passport_change']
                if selected_item['version'] and selected_item['status']!='withdrawn':actions+=['review','withdraw']
                if selected_item['kind']=='conditional':actions+=['applicability']
                for action in actions:forms[action]=_envelope(request,actor,case['id'],application_id,action,inventory['current_revision'],selected_item)
        if echo and echo['_di_action'] in forms and echo['_di_revision']==str(inventory['current_revision']):forms[echo['_di_action']]=echo
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE or str(exc)=='document_revision_unavailable':raise HTTPException(404,headers=HEADERS) from None
        inventory=None;forms={};error='Не удалось проверить историю документов. Изменения недоступны.';status=503
    except HTTPException:raise
    except Exception:
        inventory=None;forms={};error='Хранилище документов временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_document_inventory.html',dict(request=request,manager=manager,case=case,
        application_id=application_id,inventory=inventory,item=selected_item,forms=forms,products=products,
        error=error,retry=retry,url=url,write_on=_write_on(request),meta=META,security=SECURITY,
        states=STATES,sources=SOURCES,reasons=REASONS,kinds=KINDS,today=ar._bishkek_today().isoformat()),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applications/{application_id}/documents',response_class=HTMLResponse)
async def inventory_form(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),item:str=Query('',max_length=8),revision:int|None=Query(None,ge=1,le=MAX_REVISIONS),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager)
    pairs=list(request.query_params.multi_items())
    if len({k for k,v in pairs})!=len(pairs) or any(k not in ('item','revision') for k,v in pairs):raise HTTPException(422,headers=HEADERS)
    case=await entry._case(case_id,actor)
    return await _render(request,manager,actor,case,application_id,item_id=item,revision=revision)


@ar.router.post('/case/{case_id}/kg-entry/applications/{application_id}/documents',response_class=HTMLResponse)
async def inventory_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True)
    case=await entry._case(case_id,actor);values=await _form(request,actor,case_id,application_id)
    item=values['_di_item']
    try:
        await service.record_document_operation(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,
            expected_revision=int(values['_di_revision']),request_key=values['_di_key'],operation=_operation(values))
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,application_id,item_id=item,status=409,
            error='Запись уже изменилась или запрос повторён с другими данными. Проверьте актуальную версию перед новой операцией.')
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,application_id,item_id=item,status=422,echo=values,
            error=ERRORS.get(str(exc),'Проверьте данные операции. Новая запись не добавлена.'))
    except Exception:
        return await _render(request,manager,actor,case,application_id,item_id=item,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос без изменений, чтобы получить его результат без дубля.')
    location=f'/admin/case/{case_id}/kg-entry/applications/{application_id}/documents'
    if item:location+='?item='+item
    return RedirectResponse(location,status_code=303,headers={**HEADERS,'X-Action-Outcome':'document_saved'})
