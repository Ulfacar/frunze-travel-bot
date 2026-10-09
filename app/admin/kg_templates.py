"""Read-only synthetic appendix-A previews behind existing admin/KG gates."""
import hashlib
import hmac
import json
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends,HTTPException,Request
from fastapi.responses import HTMLResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.knowledge.template_preview import TemplatePreviewInvalid,load_catalog,preview,CATALOG_SHA256

URL='/kg-entry/templates'
HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
SECURITY={'_tpl_csrf','_tpl_signature','_tpl_catalog','_tpl_id'}


def _csrf(request):
    request.session.setdefault('kg_template_csrf',secrets.token_hex(32))
    return request.session['kg_template_csrf']


def _signature(request,actor,template_id,digest):
    payload=json.dumps(['kg-template-preview/1',actor.manager_id,_csrf(request),template_id,digest],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def _render(request,manager,actor,*,catalog=None,template_id='KG.TPL.A01',values=None,result=None,error='',status=200):
    data=catalog.document() if catalog else None
    template=next((u for u in data['templates'] if u['unit_id']==template_id),None) if data else None
    fields=dict(_tpl_csrf=_csrf(request),_tpl_id=template_id,_tpl_catalog=CATALOG_SHA256,
                _tpl_signature=_signature(request,actor,template_id,CATALOG_SHA256)) if template else {}
    return ar.templates.TemplateResponse(request,'kg_templates.html',dict(request=request,manager=manager,
        data=data,template=template,security=fields,values=values or {},result=result,error=error),
        status_code=status,headers=HEADERS)


@ar.router.get(URL,response_class=HTMLResponse)
async def template_form(request:Request,manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager)
    pairs=list(request.query_params.multi_items())
    if len(pairs)>1 or any(key!='template' or len(value)>32 for key,value in pairs):
        raise HTTPException(422,'Недопустимый выбор шаблона.',headers=HEADERS)
    template_id=request.query_params.get('template','KG.TPL.A01')
    try:
        catalog=load_catalog()
        result=preview(catalog,template_id=template_id,values={})
        return _render(request,manager,actor,catalog=catalog,template_id=template_id,result=result)
    except TemplatePreviewInvalid as exc:
        status=503 if str(exc).startswith('template_catalog_') else 422
        return _render(request,manager,actor,error='Шаблон недоступен. Проверьте источник и выбранный шаблон.',status=status)


@ar.router.post(URL,response_class=HTMLResponse)
async def template_preview(request:Request,manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager)
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'Используйте форму предварительного просмотра.',headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>16384:raise HTTPException(413,'Форма слишком большая.',headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=100,encoding='utf-8',errors='strict')
        if len(set(k for k,v in pairs))!=len(pairs) or any(len(v)>500 for k,v in pairs):raise ValueError
        values=dict(pairs)
    except (ValueError,UnicodeError):raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS) from None
    token=request.session.get('kg_template_csrf','')
    template_id=values.get('_tpl_id','');digest=values.get('_tpl_catalog','')
    if (not token or not hmac.compare_digest(token.encode(),values.get('_tpl_csrf','').encode()) or
        not hmac.compare_digest(_signature(request,actor,template_id,digest).encode(),values.get('_tpl_signature','').encode())):
        raise HTTPException(403,'Форма изменена или относится к другой сессии.',headers=HEADERS)
    if digest!=CATALOG_SHA256:
        return _render(request,manager,actor,error='Источник изменился. Откройте новую форму.',status=409)
    try:
        catalog=load_catalog()
        original=preview(catalog,template_id=template_id,values={})
        allowed=set(SECURITY)
        for field in original['fields']:
            if field['kind']!='unresolved_calculation':
                allowed.add(field['id'])
                if field['kind']=='money':allowed.add(field['id']+'_currency')
        if not values.keys()<=allowed:raise HTTPException(422,'Недопустимые поля шаблона.',headers=HEADERS)
        typed={}
        for field in original['fields']:
            key=field['id'];value=values.get(key,'')
            if not value:continue
            if field['kind']=='positive_integer':
                if not value.isascii() or not value.isdecimal():raise TemplatePreviewInvalid('invalid_integer')
                value=int(value)
            elif field['kind']=='money':value=dict(amount=value,currency=values.get(key+'_currency',''))
            typed[key]=value
        result=preview(catalog,template_id=template_id,values=typed)
        return _render(request,manager,actor,catalog=catalog,template_id=template_id,values=values,result=result)
    except TemplatePreviewInvalid as exc:
        unavailable=str(exc).startswith('template_catalog_')
        return _render(request,manager,actor,catalog=None if unavailable else catalog,template_id=template_id,values=values,
            error='Источник недоступен.' if unavailable else 'Проверьте даты, значения, валюту и варианты. Неподтверждённые расчёты не подставляются.',status=503 if unavailable else 422)
