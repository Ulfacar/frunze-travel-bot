"""Native policy-gated file intake; bytes stay in quarantine and are never served."""
import hashlib
import hmac
import json
import secrets

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
import app.admin.kg_document_packages as package_ui
from app.admin.kg_document_ui import HEADERS
from app.admin.kg_quarantine_multipart import parse_upload, UploadFormInvalid, UploadTooLarge
from app.admin.workday import _write_on
from app.domain import entry_document_packages as packages, entry_quarantine as service
from app.domain.entry_quarantine_policy import configured_policy, authorize_upload
from app.domain.entry_document_rules import SOURCES
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid
from app.domain.service_authz import PermissionDenied

META=('_q_key','_q_revision','_q_version','_q_item','_q_policy')
FIELDS=set(META)|{'_q_csrf','_q_signature','_q_sha256','received_on','source','confirmed'}
ERRORS={
    'quarantine_file_type_invalid':'Выберите PDF или JPEG с соответствующим содержимым и расширением.',
    'quarantine_file_size_invalid':'Файл пустой или превышает разрешённый размер.',
    'quarantine_checksum_mismatch':'Содержимое изменилось. Для повтора выберите тот же файл.',
    'quarantine_quota_reached':'Достигнут лимит хранения файлов этой заявки. Новый файл не сохранён.',
    'document_application_closed':'Эта попытка завершена. Новые файлы не принимаются.',
    'document_content_unchanged':'Такое содержимое уже записано как текущая версия.',
    'document_package_history_limit':'Достигнут предел истории комплекта. Новый файл не сохранён.',
    'invalid_document_package_date':'Проверьте дату получения: она не может быть будущей или раньше предыдущей версии.',
}


def _policy():
    try: return configured_policy(ar.settings),False
    except (EntryStorageInvalid,TypeError,ValueError): return None,True


def _csrf(request):
    if not request.session.get('kg_quarantine_csrf'): request.session['kg_quarantine_csrf']=secrets.token_hex(32)
    return request.session['kg_quarantine_csrf']


def _signature(request,actor,case_id,application_id,values):
    message=json.dumps(['kg-quarantine/1',actor.manager_id,case_id,application_id,_csrf(request),
        [values.get(k,'') for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),message,hashlib.sha256).hexdigest()


def _verify(request,actor,case_id,application_id,values):
    token=request.session.get('kg_quarantine_csrf','')
    required=set(META)|{'_q_csrf','_q_signature'}
    if not values.keys()<=FIELDS or not required<=values.keys():
        raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS)
    if (not token or not hmac.compare_digest(token.encode(),values['_q_csrf'].encode()) or
        not hmac.compare_digest(_signature(request,actor,case_id,application_id,values).encode(),values['_q_signature'].encode())):
        raise HTTPException(403,'Откройте форму заново: она относится к другой сессии или была изменена.',headers=HEADERS)
    if values.get('confirmed')!='yes': raise HTTPException(422,'Подтвердите загрузку в карантин.',headers=HEADERS)


async def _render(request,manager,actor,case,application_id,*,item_id='',values=None,status=200,error='',saved=False,retry_values=None):
    inventory=None; item=None; policy,invalid=_policy(); enabled=False
    url=f'/admin/case/{case["id"]}/kg-entry/applications/{application_id}/quarantine'
    try:
        inventory=await packages.read_document_package(entry._engine(),actor=actor,case_id=case['id'],application_id=application_id,policy=package_ui._policy()[0])
        current=inventory['selected']
        if current:
            rows=current['summary']['rows']; item=next((r for r in rows if r['id']==item_id),None) if item_id else rows[0]
            if item is None: raise HTTPException(404,headers=HEADERS)
            try:
                authorize_upload(actor,policy,day=service.applications._today())
                enabled=inventory['ordinary_writes_available'] and inventory['application_status'] not in ('approved','refused','closed')
            except (EntryStorageInvalid,PermissionDenied): pass
            if enabled and values is None:
                values=dict(zip(META,(secrets.token_hex(24),str(inventory['current_revision']),str(item['version']),item['id'],policy.digest)))
                values.update(_q_csrf=_csrf(request),_q_signature=_signature(request,actor,case['id'],application_id,values))
    except HTTPException: raise
    except PermissionDenied: raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ('application_case_unavailable','application_unavailable'): raise HTTPException(404,headers=HEADERS) from None
        enabled=False; error='Не удалось проверить историю файлов. Новая загрузка недоступна.'; status=503
        values=values or retry_values
    except Exception:
        enabled=False; error=error or 'Хранилище временно недоступно. Сохраните исходную форму для повтора.'; status=503
        values=values or retry_values
    return ar.templates.TemplateResponse(request,'kg_document_quarantine.html',dict(request=request,manager=manager,case=case,
        application_id=application_id,inventory=inventory,item=item,policy=policy,policy_invalid=invalid,enabled=enabled,
        values=values or {},url=url,write_on=_write_on(request),error=error,saved=saved and status==200,sources=SOURCES,
        today=service.applications._today().isoformat(),meta=META),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applications/{application_id}/quarantine',response_class=HTMLResponse)
async def quarantine_form(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),
                          item:str=Query('',max_length=41),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager); case=await entry._case(case_id,actor)
    if len(request.query_params)!=len(request.query_params.multi_items()) or any(k!='item' for k in request.query_params):
        raise HTTPException(422,headers=HEADERS)
    return await _render(request,manager,actor,case,application_id,item_id=item)


@ar.router.post('/case/{case_id}/kg-entry/applications/{application_id}/quarantine',response_class=HTMLResponse)
async def quarantine_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),
                            manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True); case=await entry._case(case_id,actor)
    policy,_=_policy()
    try: authorize_upload(actor,policy,day=service.applications._today())
    except (EntryStorageInvalid,PermissionDenied): raise HTTPException(403,'Загрузка не разрешена действующей политикой.',headers=HEADERS) from None
    if request.headers.get('content-type','').split(';',1)[0].strip()!='multipart/form-data':
        raise HTTPException(415,'Используйте форму загрузки.',headers=HEADERS)
    try: upload=await parse_upload(request,max_file_bytes=policy.max_file_bytes)
    except UploadTooLarge:
        return await _render(request,manager,actor,case,application_id,status=413,
            error='Файл или форма превышает разрешённый размер. Выберите документ и файл заново.')
    except UploadFormInvalid:
        return await _render(request,manager,actor,case,application_id,status=422,
            error='Форма загрузки повреждена или содержит лишние поля. Выберите документ и файл заново.')
    values=upload.fields; _verify(request,actor,case_id,application_id,values)
    if values['_q_policy']!=policy.digest: raise HTTPException(422,'Правила загрузки изменились. Откройте форму заново.',headers=HEADERS)
    error=''; status=200
    try:
        await service.record_upload(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,
            expected_revision=int(values['_q_revision']),expected_document_version=int(values['_q_version']),
            item_id=values['_q_item'],request_key=values['_q_key'],received_on=values.get('received_on',''),source=values.get('source',''),
            data=upload.data,filename=upload.filename,media_type=upload.media_type,policy=policy,expected_sha256=values.get('_q_sha256') or None)
    except PermissionDenied: raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        error='Запись уже изменилась или этот запрос относится к другому файлу. Откройте актуальную форму.'; status=409
    except EntryStorageInvalid as exc:
        error=ERRORS.get(str(exc),'Файл не сохранён. Проверьте выбранный документ и поля формы.'); status=422
    except Exception:
        error='Результат сохранения пока неизвестен. Выберите тот же файл и повторите исходный запрос: дубль не будет создан.'; status=503
        values['_q_sha256']=hashlib.sha256(upload.data).hexdigest()
    retry_values={**values,'_q_sha256':hashlib.sha256(upload.data).hexdigest()}
    return await _render(request,manager,actor,case,application_id,item_id=values['_q_item'],
        values=values if status!=200 else None,status=status,error=error,saved=status==200,retry_values=retry_values)
