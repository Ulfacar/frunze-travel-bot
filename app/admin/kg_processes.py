"""No-storage review screen for draft source processes; never advances a case."""
import hmac
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.knowledge.process_preview import EFFECTS, RESULTS, ProcessPreviewError, evaluate_transition, load_process_catalog

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}


def _csrf(request):
    if not request.session.get('kg_process_preview_csrf'):
        request.session['kg_process_preview_csrf']=secrets.token_hex(32)
    return request.session['kg_process_preview_csrf']


def _context(request, catalog, process, stage, *, values=None, result=None, error=''):
    data=catalog.document() if catalog else None
    if data is None:
        return {'request':request,'data':None,'error':error}
    if process not in data['processes']: raise ProcessPreviewError('invalid_process')
    stages=[row for row in data['stages'] if row['process']==process]
    current=next((row for row in stages if row['code']==stage), None) if stage else stages[0]
    if current is None: raise ProcessPreviewError('invalid_process_stage')
    edges=[row for row in data['edges'] if row['from']==current['code']]
    targets=[row for row in stages if any(edge['to']==row['code'] for edge in edges)]
    fact_keys=sorted({key for edge in edges for key in edge['requires']})
    return {'request':request,'data':data,'catalog_digest':catalog.digest,'process':process,'stages':stages,
        'current':current,'targets':targets,'fact_keys':fact_keys,'values':values or {},'result':result,
        'error':error,'csrf':_csrf(request),'results':RESULTS,'effects':EFFECTS}


def _render(request, manager, context, status=200):
    return ar.templates.TemplateResponse(request,'kg_processes.html',{'manager':manager,**context},status_code=status,headers=HEADERS)


@ar.router.get('/kg-entry/processes',response_class=HTMLResponse)
async def process_preview(request:Request,manager=Depends(ar.require_full_admin)):
    entry._gate(request,manager)
    try:
        pairs=list(request.query_params.multi_items())
        if len(pairs)>2 or len({key for key,_ in pairs})!=len(pairs) or any(key not in ('process','stage') or len(value)>24 for key,value in pairs):
            raise ProcessPreviewError('invalid_process_selection')
        catalog=load_process_catalog()
        context=_context(request,catalog,request.query_params.get('process','visa'),request.query_params.get('stage',''))
        return _render(request,manager,context)
    except ProcessPreviewError as exc:
        status=503 if str(exc) in ('process_catalog_unavailable','process_catalog_integrity_failed','invalid_process_catalog') else 422
        return _render(request,manager,_context(request,None,None,None,error='Не удалось открыть черновик. Проверьте выбор процесса или повторите позже.'),status)


@ar.router.post('/kg-entry/processes',response_class=HTMLResponse)
async def process_preview_check(request:Request,manager=Depends(ar.require_full_admin)):
    entry._gate(request,manager)  # read-only preview also works with writes disabled
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'Используйте форму проверки.',headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>8192: raise HTTPException(413,'Форма слишком большая.',headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=80,encoding='utf-8',errors='strict')
        if len({key for key,_ in pairs})!=len(pairs) or any(len(value)>128 for _,value in pairs): raise ValueError
        values=dict(pairs)
    except (ValueError,UnicodeError): raise HTTPException(422,'Некорректная форма.',headers=HEADERS) from None
    csrf=request.session.get('kg_process_preview_csrf','')
    if not csrf or not hmac.compare_digest(csrf.encode(),values.get('csrf','').encode()):
        raise HTTPException(403,'Откройте форму проверки заново.',headers=HEADERS)
    catalog=None
    try:
        catalog=load_process_catalog()
        context=_context(request,catalog,values.get('process',''),values.get('current',''))
        allowed={'csrf','catalog_digest','process','current','target'} | {f'fact_{key}' for key in context['fact_keys']}
        if not set(values)<=allowed: raise ProcessPreviewError('invalid_process_facts')
        facts={}
        for key in context['fact_keys']:
            value=values.get('fact_'+key,'')
            spec=context['data']['facts'][key]
            if value=='': facts[key]=None
            elif spec['type']=='boolean' and value in ('true','false'): facts[key]=value=='true'
            elif spec['type']=='enum' and value in spec['values']: facts[key]=value
            else: raise ProcessPreviewError('invalid_process_facts')
        result=evaluate_transition(catalog,process=values.get('process'),current=values.get('current'),target=values.get('target'),
                                   facts=facts,expected_digest=values.get('catalog_digest'))
        return _render(request,manager,_context(request,catalog,values['process'],values['current'],values=values,result=result))
    except ProcessPreviewError as exc:
        code=str(exc)
        status=409 if code=='stale_process_catalog' else 503 if code in ('process_catalog_unavailable','process_catalog_integrity_failed','invalid_process_catalog') else 422
        message=('Версия черновика изменилась. Откройте свежую форму и заново задайте сценарий.' if status==409 else
                 'Проверка не выполнена. Проверьте поля или откройте черновик заново.')
        # Do not reflect malformed input or preserve a stale approval-looking result.
        return _render(request,manager,_context(request,None,None,None,error=message),status)
