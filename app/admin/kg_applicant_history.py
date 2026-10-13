"""Protected personal history forms with pinned base and recoverable requests."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends,HTTPException,Path,Query,Request
from fastapi.responses import HTMLResponse,RedirectResponse

import app.admin.router as ar
from app.admin import kg_entry as entry
from app.admin import kg_applicant_history_form as form
from app.admin.workday import _write_on
from app.domain import applicant_stay_history as service
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
UNAVAILABLE={'applicant_unavailable','application_case_unavailable','applicant_history_revision_unavailable'}


def _csrf(request):
    if not request.session.get('kg_applicant_history_csrf'):request.session['kg_applicant_history_csrf']=secrets.token_hex(32)
    return request.session['kg_applicant_history_csrf']


def _signature(request,actor,case_id,applicant_id,values):
    payload=json.dumps(['kg-applicant-history-form/1',actor.manager_id,case_id,applicant_id,_csrf(request),
        [values.get(key,'') for key in form.META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def _envelope(request,actor,case_id,applicant_id,action,data,item,today):
    values=dict(zip(form.META,(action,str(data['current_revision']),data['selected']['snapshot_hash'] if data['selected'] else '',
        str(data['latest_profile_id'] or 0),item or '',secrets.token_hex(24),secrets.token_hex(16),today)))
    return {**values,'_ah_csrf':_csrf(request),'_ah_signature':_signature(request,actor,case_id,applicant_id,values)}


async def _form(request,actor,case_id,applicant_id):
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'Use the history form.',headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>8192:raise HTTPException(413,headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=20,encoding='utf-8',errors='strict')
        if len({k for k,v in pairs})!=len(pairs) or any(len(v)>128 for k,v in pairs):raise ValueError
        values=dict(pairs);action=values.get('_ah_action')
        if action not in form.FIELDS or not values.keys()<=(set(form.META)|form.SECURITY|form.FIELDS[action]):raise ValueError
    except (ValueError,UnicodeError):raise HTTPException(422,headers=HEADERS) from None
    token=request.session.get('kg_applicant_history_csrf','')
    if (not token or not hmac.compare_digest(token.encode(),values.get('_ah_csrf','').encode()) or
        not re.fullmatch('[a-f0-9]{48}',values.get('_ah_key','')) or
        not hmac.compare_digest(_signature(request,actor,case_id,applicant_id,values).encode(),values.get('_ah_signature','').encode())):
        raise HTTPException(403,'Form changed or belongs to another session.',headers=HEADERS)
    return values


async def _read(actor,case_id,applicant_id,revision=None):
    return await service.read_history(entry._engine(),actor=actor,case_id=case_id,applicant_id=applicant_id,revision=revision)


def _case_unavailable(request,manager,case_id,applicant_id,retry=None):
    words,_,_=form.copy('ru')
    return ar.templates.TemplateResponse(request,'kg_applicant_history.html',dict(request=request,manager=manager,
        case=dict(id=case_id,title=''),applicant_id=applicant_id,language='ru',data=None,words=words,
        error=words['unavailable'],retry=retry,write_on=_write_on(request),
        url=f'/admin/case/{case_id}/kg-entry/applicants/{applicant_id}/history'),status_code=503,headers=HEADERS)


async def _render(request,manager,actor,case,applicant_id,*,revision=None,item=0,page=1,status=200,error='',echo=None,retry=None):
    data=None;forms={};base=None;selected_item=None;language='ru'
    url=f'/admin/case/{case["id"]}/kg-entry/applicants/{applicant_id}/history'
    try:
        data=await _read(actor,case['id'],applicant_id,revision);language=data['language']
        today=service.applications._local_day(service._now()).isoformat()
        base=form.state(data['selected'],today);visits=base['document']['intervals']
        if item>len(visits) or page>max(1,(len(visits)+24)//25):raise HTTPException(404,headers=HEADERS)
        selected_item=visits[item-1] if item else None
        if revision is None and data['latest_profile_id']:
            actions=[]
            if data['ordinary_writes_available']:
                actions=['summary']
                if item or len(visits)<1000:actions.append('visit')
                if item:actions.append('remove')
            if data['selected'] and data['selected']['action']=='save':actions.append('withdraw')
            for action in actions:
                item_ref=selected_item['ref'] if selected_item else 'visit-'+secrets.token_hex(12)
                forms[action]={**_envelope(request,actor,case['id'],applicant_id,action,data,item_ref,today),
                    **form.defaults(action,base,selected_item)}
            if echo and echo['_ah_action'] in forms and echo['_ah_revision']==str(data['current_revision']):
                forms[echo['_ah_action']]=echo
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        data=None;forms={};status=503;error='unavailable'
    except HTTPException:raise
    except Exception:data=None;forms={};status=503;error='unavailable'
    if retry:forms={}
    words,bases,evidence=form.copy(language)
    return ar.templates.TemplateResponse(request,'kg_applicant_history.html',dict(request=request,manager=manager,case=case,
        applicant_id=applicant_id,data=data,base=base,forms=forms,selected_item=selected_item,item_number=item,page=page,
        revision=revision,url=url,words=words,bases=bases,evidence=evidence,language=language,
        error=words.get(error,error),retry=retry,write_on=_write_on(request),
        meta=(*form.META,*sorted(form.SECURITY)),refs=form.passport_refs(base) if base else []),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applicants/{applicant_id}/history',response_class=HTMLResponse)
async def history_form(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
    revision:int|None=Query(None,ge=1,le=service.MAX_REVISIONS),item:int=Query(0,ge=0,le=1000),
    page:int=Query(1,ge=1,le=40),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager)
    pairs=list(request.query_params.multi_items())
    if len({k for k,v in pairs})!=len(pairs) or any(k not in ('revision','item','page') for k,v in pairs):raise HTTPException(422,headers=HEADERS)
    try:case=await entry._case(case_id,actor)
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except HTTPException:raise
    except Exception:return _case_unavailable(request,manager,case_id,applicant_id)
    return await _render(request,manager,actor,case,applicant_id,revision=revision,item=item,page=page)


@ar.router.post('/case/{case_id}/kg-entry/applicants/{applicant_id}/history',response_class=HTMLResponse)
async def history_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True)
    values=await _form(request,actor,case_id,applicant_id)
    try:case=await entry._case(case_id,actor)
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except HTTPException:raise
    except Exception:return _case_unavailable(request,manager,case_id,applicant_id,retry=values)
    item=0
    try:
        revision=int(values['_ah_revision'])
        # An exact retry rebuilds its original command from the signed OLD base.
        # Reading latest data here would change the request after an uncertain commit.
        data=await _read(actor,case_id,applicant_id,revision or None)
        selected=data['selected'] if revision else None
        if (selected['snapshot_hash'] if selected else '')!=values['_ah_hash']:raise EntryStorageConflict('history_base_changed')
        if selected and selected['action']=='save':
            item=next((i+1 for i,v in enumerate(selected['operation']['document']['intervals']) if v['ref']==values['_ah_item']),0)
        await service.record_history(entry._engine(),actor=actor,case_id=case_id,applicant_id=applicant_id,
            expected_revision=revision,request_key=values['_ah_key'],operation=form.operation(values,selected))
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,applicant_id,status=409,error='conflict')
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,applicant_id,item=item,status=422,error='invalid',echo=values)
    except Exception:
        return await _render(request,manager,actor,case,applicant_id,status=503,error='uncertain',retry=values)
    return RedirectResponse(f'/admin/case/{case_id}/kg-entry/applicants/{applicant_id}/history',status_code=303,
        headers={**HEADERS,'X-Action-Outcome':'applicant_history_saved'})
