"""Source-backed synthetic document checklist; never records actual documents."""
import hmac
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends,HTTPException,Request
from fastapi.responses import HTMLResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.knowledge.document_checklist import (DocumentChecklistError,KINDS,STATES,OUTCOMES,
    load_document_catalog,checklist,review_checklist)

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}


def _render(request,manager,*,catalog=None,product='TS',values=None,result=None,error='',status=200):
    context=dict(request=request,manager=manager,error=error,data=None)
    if catalog:
        request.session.setdefault('kg_document_csrf',secrets.token_hex(32))
        context.update(data=catalog.document(),product=product,items=checklist(catalog,product),
            values=values or {},result=result,csrf=request.session['kg_document_csrf'],
            digest=catalog.digest,kinds=KINDS,states=STATES,outcomes=OUTCOMES)
    return ar.templates.TemplateResponse(request,'kg_documents.html',context,status_code=status,headers=HEADERS)


def _error(request,manager,exc):
    code=str(exc)
    status=409 if code=='stale_document_catalog' else 503 if code.startswith('document_catalog_') else 422
    message='Версия источника изменилась. Откройте свежую форму.' if status==409 else 'Проверка недоступна. Проверьте выбор или откройте форму заново.'
    return _render(request,manager,error=message,status=status)


@ar.router.get('/kg-entry/documents',response_class=HTMLResponse)
async def documents_preview(request:Request,manager=Depends(ar.require_full_admin)):
    entry._gate(request,manager)
    try:
        pairs=list(request.query_params.multi_items())
        if len(pairs)>1 or any(k!='product' or len(v)>8 for k,v in pairs):
            raise DocumentChecklistError('invalid_document_product')
        return _render(request,manager,catalog=load_document_catalog(),product=request.query_params.get('product','TS'))
    except DocumentChecklistError as exc:return _error(request,manager,exc)


@ar.router.post('/kg-entry/documents',response_class=HTMLResponse)
async def documents_check(request:Request,manager=Depends(ar.require_full_admin)):
    entry._gate(request,manager)
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'Используйте форму.',headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>16384:raise HTTPException(413,'Форма слишком большая.',headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=80,encoding='utf-8',errors='strict')
        if len({k for k,v in pairs})!=len(pairs) or any(len(v)>128 for k,v in pairs):raise ValueError
        values=dict(pairs)
    except (ValueError,UnicodeError):raise HTTPException(422,'Некорректная форма.',headers=HEADERS) from None
    csrf=request.session.get('kg_document_csrf','')
    if not csrf or not hmac.compare_digest(csrf.encode(),values.get('csrf','').encode()):
        raise HTTPException(403,'Откройте форму заново.',headers=HEADERS)
    try:
        catalog=load_document_catalog();product=values.get('product','')
        items=checklist(catalog,product)
        editable={row['id'] for row in items if row['kind']!='not_listed'}
        conditional={row['id'] for row in items if row['kind']=='conditional'}
        allowed={'csrf','catalog_digest','product','current_version'}|{'state_'+key for key in editable}|{'applies_'+key for key in conditional}
        if not values.keys()<=allowed:raise DocumentChecklistError('invalid_document_answers')
        def tri(value):
            if value not in ('','true','false'):raise DocumentChecklistError('invalid_document_answers')
            return {'':None,'true':True,'false':False}[value]
        states={key:values.get('state_'+key,'unknown') for key in editable}
        conditions={key:tri(values.get('applies_'+key,'')) for key in conditional}
        result=review_checklist(catalog,product=product,states=states,conditions=conditions,
            current_version=tri(values.get('current_version','')),expected_digest=values.get('catalog_digest'))
        return _render(request,manager,catalog=catalog,product=product,values=values,result=result)
    except DocumentChecklistError as exc:return _error(request,manager,exc)
