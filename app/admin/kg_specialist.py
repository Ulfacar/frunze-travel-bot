"""Native, explicit specialist review and linked internal quotations."""
import hashlib
import hmac
import json
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends,HTTPException,Path,Request
from fastapi.responses import HTMLResponse,RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin import kg_interviews,kg_quotes
from app.admin.workday import _write_on
from app.domain import specialist_decisions as service,specialist_facts as facts
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict,EntryStorageUnavailable,_hash
from app.domain.knowledge_publication_rules import configured_policy as publication_policy
from app.domain.specialist_policy import configured_policy
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','X-Robots-Tag':'noindex','Referrer-Policy':'no-referrer'}
ROUTE='/case/{case_id}/kg-entry/applicants/{applicant_id}/applications/{application_id}/specialist'
META=('_sp_action','_sp_revision','_sp_key','_sp_payload','_sp_language')
SECURITY=('_sp_csrf','_sp_sig')
EVIDENCE=('alternatives','host','nonemployment','purpose')
REASON=('reason_code','reason_reference','reason_proof','reason_on')
RECORD=('disposition','meeting_nonprofit','local_work','host_legal_entity_in_kg','reviewed_on')+tuple(
    f'{fact}_{field}' for fact in EVIDENCE for field in ('reference','proof','on'))+REASON
EXTRA={'record':RECORD,'withdraw':REASON,'preview':('recipe_id','urgent'),'save':()}
# An accepted journal event contains the whole operation. Percent encoding can
# expand each UTF-8 byte threefold; allow that bounded operation plus metadata.
PAYLOAD_LIMIT=service.MAX_EVENT_BYTES
BODY_LIMIT=3*PAYLOAD_LIMIT+16384


def _url(case_id,applicant_id,application_id,language='ru'):
    return '/admin'+ROUTE.format(case_id=case_id,applicant_id=applicant_id,application_id=application_id)+'?language='+language


def _policies():
    try:policy=configured_policy(ar.settings)
    except EntryStorageInvalid:policy=None
    try:publication=publication_policy(ar.settings)
    except EntryStorageInvalid:publication=None
    return dict(policy=policy,interview_policy=kg_interviews._policy(),publication_policy=publication)


def _csrf(request):
    return request.session.setdefault('kg_specialist_csrf',secrets.token_hex(32))


def _signature(request,actor,ids,values):
    body=json.dumps(['kg-specialist-form/1',actor.manager_id,*ids,_csrf(request),
        [values.get(k,'') for k in META]],ensure_ascii=False,separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),body,hashlib.sha256).hexdigest()


def _envelope(request,actor,ids,language,action,revision,payload,*,key=None):
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':'))
    if len(encoded.encode('utf8'))>PAYLOAD_LIMIT:raise EntryStorageInvalid('specialist_form_size_limit')
    values=dict(_sp_action=action,_sp_revision=str(revision),_sp_key=key or secrets.token_hex(24),
        _sp_payload=encoded,_sp_language=language)
    return values|{'_sp_csrf':_csrf(request),'_sp_sig':_signature(request,actor,ids,values)}


def _language(request):
    pairs=list(request.query_params.multi_items())
    if not pairs:return 'ru'
    if len(pairs)!=1 or pairs[0][0]!='language' or pairs[0][1] not in ('ru','en'):
        raise HTTPException(422,headers=HEADERS)
    return pairs[0][1]


async def _form(request,actor,ids,language):
    try:
        if request.headers.get('content-type','').split(';')[0]!='application/x-www-form-urlencoded':raise ValueError
        length=request.headers.get('content-length')
        if length is not None and (not length.isascii() or not length.isdecimal() or int(length)>BODY_LIMIT):raise ValueError
        raw=bytearray()
        async for chunk in request.stream():
            if len(raw)+len(chunk)>BODY_LIMIT:raise ValueError
            raw.extend(chunk)
        pairs=parse_qsl(raw.decode('utf-8'),keep_blank_values=True,strict_parsing=True,encoding='utf-8',errors='strict',max_num_fields=40)
        values=dict(pairs);action=values.get('_sp_action')
        if action not in EXTRA or len(values)!=len(pairs) or set(values)!=set(META+SECURITY+EXTRA[action]):raise ValueError
        if any(len(k)>50 or (len(v.encode('utf8'))>PAYLOAD_LIMIT if k=='_sp_payload' else len(v)>150) for k,v in pairs):raise ValueError
        for key in SECURITY:
            if len(values[key])!=64 or any(c not in '0123456789abcdef' for c in values[key]):
                raise HTTPException(403,headers=HEADERS)
        if (values['_sp_language']!=language or not hmac.compare_digest(values['_sp_csrf'],_csrf(request)) or
            not hmac.compare_digest(values['_sp_sig'],_signature(request,actor,ids,values))):
            raise HTTPException(403,headers=HEADERS)
        if str(int(values['_sp_revision']))!=values['_sp_revision'] or not 0<=int(values['_sp_revision'])<64:raise ValueError
        return values
    except (ValueError,UnicodeError):raise HTTPException(422,headers=HEADERS) from None


def _reason(values):
    return {key:values['reason_'+key] for key in ('code','reference','proof','on')}


def _bool(value):
    if value not in ('yes','no'):raise EntryStorageInvalid('specialist_review_confirmation_required')
    return value=='yes'


def _operation(values):
    payload=json.loads(values['_sp_payload']);action=values['_sp_action']
    if action=='save':return service._operation(payload)
    if action=='withdraw':return service._operation(payload|dict(reason=_reason(values),confirmed=True))
    disposition=values['disposition'];findings=None;reason=None
    if disposition=='manual_internal_plan':
        findings=dict(reviewed_on=values['reviewed_on'],
            **{k:_bool(values[k]) for k in ('meeting_nonprofit','local_work','host_legal_entity_in_kg')},
            host_identity_hash=payload.pop('host_identity_hash'),purpose_detail_hash=payload.pop('purpose_detail_hash'),
            evidence=[dict(fact=fact,**{k:values[fact+'_'+k] for k in ('reference','proof','on')}) for fact in EVIDENCE])
    else:
        payload.pop('host_identity_hash');payload.pop('purpose_detail_hash');reason=_reason(values)
    return service._operation(payload|dict(disposition=disposition,findings=findings,reason=reason))


async def _scope(actor,ids):
    value=await service.apps.read_application(entry._engine(),actor=actor,case_id=ids[0],application_id=ids[2])
    if value['applicant_id']!=ids[1] or value['procedure']!='visa':raise HTTPException(404,headers=HEADERS)
    return value


def _unavailable(request,manager,ids,language,*,retry=None):
    # The case lookup itself failed: do not attempt an unverified scope/history
    # read just to render the error. A signed original form can still be retried.
    return ar.templates.TemplateResponse(request,'kg_specialist.html',dict(request=request,manager=manager,
        case={'id':ids[0]},ids=ids,language=language,current=None,context=None,forms={},recipes=[],plan=None,
        error='uncertain' if retry else 'read_unavailable',retry=retry,confirmation=None,proposal=None,preview=None,
        url=_url(*ids,language),alternate_url=_url(*ids,'en' if language=='ru' else 'ru'),evidence=EVIDENCE),
        status_code=503,headers=HEADERS)


async def _render(request,manager,actor,case,ids,language,*,status=200,error=None,retry=None,confirmation=None,preview=None):
    current=None;context=None;forms={};recipes=[];policies=_policies();plan=None
    try:
        await _scope(actor,ids)
        current=await service.read_decisions(entry._engine(),actor=actor,case_id=ids[0],applicant_id=ids[1],**policies)
        plan=next((r for r in current['history'] if r['id']==current['current']['decision_id']),None)
        if _write_on(request) and not retry and not confirmation:
            if current['can_withdraw'] and plan and plan['application_id']==ids[2]:
                forms['withdraw']=_envelope(request,actor,ids,language,'withdraw',current['revision'],
                    dict(action='withdraw',decision_id=plan['id'],decision_hash=plan['snapshot_hash']))
            try:
                context=await service.review_context(entry._engine(),actor=actor,case_id=ids[0],applicant_id=ids[1],
                    application_id=ids[2],**policies)
            except PermissionDenied:pass
            if context and current['can_record']:
                observed=context['context'];state=observed['state'];profile=(observed['request'] or {}).get('profile',{})
                answers=state['answers'] if state else {}
                host={k:answers.get(k,{}).get('value') for k in ('inviter.name','inviter.tax_id','inviter.contact','inviter.phone','inviter.email')}
                forms['record']=_envelope(request,actor,ids,language,'record',context['revision'],dict(action='record',
                    application_id=ids[2],capability_id=facts.CAPABILITY,expected_policy_hash=context['policy_hash'],
                    expected_context_hash=observed['context_hash'],host_identity_hash=_hash(host),purpose_detail_hash=_hash(profile.get('purpose_details'))))
            if context and plan and plan['application_id']==ids[2] and current['current']['usable_for_internal_quote']:
                recipes=policies['policy'].capability(facts.CAPABILITY)['recipes']
                forms['preview']=_envelope(request,actor,ids,language,'preview',current['revision'],
                    dict(decision_id=plan['id'],decision_hash=plan['snapshot_hash']))
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in kg_quotes.UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        current=None;context=None;forms={};error='integrity';status=503
    except HTTPException:raise
    except Exception:current=None;context=None;forms={};error='uncertain' if retry else 'read_unavailable';status=503
    return ar.templates.TemplateResponse(request,'kg_specialist.html',dict(request=request,manager=manager,case=case,
        ids=ids,language=language,current=current,context=context,forms=forms,recipes=recipes,plan=plan,
        error=error,retry=retry,confirmation=confirmation,preview=preview,url=_url(*ids,language),
        proposal=json.loads(confirmation['_sp_payload']) if confirmation else None,
        alternate_url=_url(*ids,'en' if language=='ru' else 'ru'),evidence=EVIDENCE),status_code=status,headers=HEADERS)


@ar.router.get(ROUTE,response_class=HTMLResponse)
async def specialist_form(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                          application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);ids=(case_id,applicant_id,application_id);language=_language(request)
    try:case=await entry._case(case_id,actor)
    except HTTPException:raise
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except Exception:return _unavailable(request,manager,ids,language)
    return await _render(request,manager,actor,case,ids,language)


@ar.router.post(ROUTE,response_class=HTMLResponse)
async def specialist_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                            application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True)
    ids=(case_id,applicant_id,application_id);language=_language(request)
    values=await _form(request,actor,ids,language);policies=_policies()
    try:case=await entry._case(case_id,actor)
    except HTTPException:raise
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except Exception:return _unavailable(request,manager,ids,language,retry=values)
    try:
        await _scope(actor,ids)
        if values['_sp_action']=='preview':
            if values['urgent'] not in ('0','1'):raise EntryStorageInvalid('invalid_specialist_urgency')
            target=json.loads(values['_sp_payload'])
            shown=await service.preview_decision_quote(entry._engine(),actor=actor,case_id=case_id,applicant_id=applicant_id,
                **target,parameters=dict(recipe_id=values['recipe_id'],additional_blocks=0,urgent=values['urgent']=='1'),
                **policies,quote_policy=kg_quotes._policy())
            operation=dict(action='quote',**target,preview=shown['preview'],preview_hash=shown['preview_hash'])
            confirmation=_envelope(request,actor,ids,language,'save',shown['revision'],operation,key=values['_sp_key'])
            return await _render(request,manager,actor,case,ids,language,confirmation=confirmation,preview=shown['preview']['quote']['result'])
        operation=_operation(values)
        if values['_sp_action']!='save':
            confirmation=_envelope(request,actor,ids,language,'save',int(values['_sp_revision']),operation,key=values['_sp_key'])
            return await _render(request,manager,actor,case,ids,language,confirmation=confirmation)
        await service.record_decision(entry._engine(),actor=actor,case_id=case_id,applicant_id=applicant_id,
            expected_revision=int(values['_sp_revision']),request_key=values['_sp_key'],operation=operation,
            **policies,quote_policy=kg_quotes._policy())
    except HTTPException:raise
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,ids,language,status=409,error='changed',retry=values)
    except EntryStorageUnavailable:
        return await _render(request,manager,actor,case,ids,language,status=503,error='uncertain',retry=values)
    except (EntryStorageInvalid,ValueError,KeyError,TypeError):
        return await _render(request,manager,actor,case,ids,language,status=422,error='invalid',retry=values)
    except Exception:
        return await _render(request,manager,actor,case,ids,language,status=503,error='uncertain',retry=values)
    return RedirectResponse(_url(*ids,language),status_code=303,headers=HEADERS)
