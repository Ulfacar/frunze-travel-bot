"""Native full-package forms; trusted policy is server-owned and absent by default."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Path, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.admin.kg_document_inventory import HEADERS, STATES, UNAVAILABLE
from app.domain import entry_document_packages as service
from app.domain.entry_package_rules import PRODUCTS, MAX_REVISIONS
from app.domain.entry_package_policy import configured_policy, authorize_acceptance
from app.domain.entry_document_rules import SOURCES, REASONS
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict
from app.domain.service_authz import PermissionDenied
from app.knowledge.complete_document_checklist import CATALOG_SHA256, load_complete_document_catalog, load_definition, _evaluate

META=('_dp_action','_dp_revision','_dp_key','_dp_item','_dp_version','_dp_fingerprint','_dp_catalog',
      '_dp_product','_dp_state','_dp_policy','_dp_legacy')
SECURITY={'_dp_csrf','_dp_signature'}
FIELDS={'initialize':{'product','confirmed'},'facts':{'confirmed'},'receive':{'fingerprint','on','source','confirmed'},
        'review':{'on','outcome','reason','alternative','confirmed'},'withdraw_document':{'on','reason','confirmed'},
        'passport_change':{'on','reason','confirmed'},'consent':{'status','on','reference','proof','confirmed'},
        'approve':{'on','reference','proof','confirmed'},'revoke':{'on','reason','confirmed'},'upgrade_definition':{'confirmed'}}
KINDS={'required':'Обязательно','conditional':'По условию','recommended':'Рекомендуется','practice':'Практическая проверка','policy':'Политика'}
SOURCES={**SOURCES,'manager_check':'Подтверждение проверки менеджером'}
ACTIONS={'initialize':'Создан полный комплект','facts':'Условия заявки','receive':'Получение версии','review':'Проверка',
         'withdraw_document':'Отзыв документа','passport_change':'Изменение паспорта','consent':'Согласие',
         'approve':'Приёмка комплекта','revoke':'Отзыв приёмки','upgrade_definition':'Обновление требований'}
ERRORS={'document_package_incomplete':'Остались непроверенные требования или неизвестные условия.',
        'package_passport_recheck_required':'Старая проверка не учитывала замену одной из копий паспорта. Обновите требования и проверьте комплект заново.',
        'document_package_invitation_conflict':'Выбрано письмо турорганизации. Подтвердите дополнительное основание для письма в условиях заявки и проверьте его содержание.',
        'package_alternative_required':'Укажите, каким из допустимых документов подтверждено требование.',
        'document_package_practice_pending':'Не завершены практические проверки, указанные в политике.',
        'document_package_source_unverified':'Есть требования, для которых не подтверждён источник.',
        'document_package_consent_required':'Для приёмки требуется действующее подтверждение согласия.',
        'document_version_changed':'Версия документа изменилась. Откройте актуальную запись.',
        'document_content_unchanged':'Это содержимое уже записано как текущая версия.',
        'invalid_document_package_date':'Проверьте дату: она не может быть в будущем или раньше предыдущего факта.',
        'invalid_package_approval_date':'Приёмка фиксируется сегодняшней датой.',
        'document_application_closed':'Эта попытка завершена. Доступна история.',
        'package_policy_changed':'Политика приёмки изменилась. Откройте форму заново.',
        'package_facts_unchanged':'Условия не изменились.',
        'document_package_history_limit':'Достигнут предел истории; новая запись не добавлена.'}


def _csrf(request):
    if not request.session.get('kg_package_csrf'): request.session['kg_package_csrf']=secrets.token_hex(32)
    return request.session['kg_package_csrf']


def _policy():
    # A broken acceptance policy must not prevent reading history or revocation.
    try: return configured_policy(ar.settings),False
    except EntryStorageInvalid: return None,True


def _signature(request,actor,case_id,application_id,values):
    payload=json.dumps(['kg-document-package/1',actor.manager_id,case_id,application_id,_csrf(request),
        [values.get(k,'') for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def _envelope(request,actor,case_id,application_id,action,inventory,item,policy):
    current=inventory['selected']; state=current['snapshot'] if current else {}
    values=dict(zip(META,(action,str(inventory['current_revision']),secrets.token_hex(24),item['id'] if item else '',
        str(item['version']) if item else '0',item['fingerprint'] or '' if item else '',
        CATALOG_SHA256 if action in ('initialize','upgrade_definition') else state.get('catalog_digest',''),
        state.get('product',''),current['state_hash'] if current else '',policy.digest if policy else '',str(inventory['legacy_revision']))))
    values.update(_dp_csrf=_csrf(request),_dp_signature=_signature(request,actor,case_id,application_id,values))
    return values


async def _form(request,actor,case_id,application_id):
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'Используйте форму комплекта.',headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>16384: raise HTTPException(413,'Форма слишком большая.',headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=160,encoding='utf-8',errors='strict')
        if len({k for k,v in pairs})!=len(pairs) or any(len(k)>100 or len(v)>128 for k,v in pairs): raise ValueError
        values=dict(pairs); action=values.get('_dp_action')
        if action not in FIELDS: raise ValueError
    except (ValueError,UnicodeError): raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS) from None
    token=request.session.get('kg_package_csrf','')
    if (not token or not hmac.compare_digest(token.encode(),values.get('_dp_csrf','').encode()) or
        not re.fullmatch('[a-f0-9]{48}',values.get('_dp_key','')) or
        not hmac.compare_digest(_signature(request,actor,case_id,application_id,values).encode(),values.get('_dp_signature','').encode())):
        raise HTTPException(403,'Форма изменена или относится к другой сессии. Откройте её заново.',headers=HEADERS)
    allowed=set(META)|SECURITY|FIELDS[action]
    if action=='facts':
        try: definition=load_definition(values['_dp_catalog'],values['_dp_product'])
        except Exception: raise HTTPException(503,'Требования этой версии недоступны.',headers=HEADERS) from None
        allowed|={'fact_'+k for k in definition['facts']}
    if not values.keys()<=allowed: raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS)
    return values


def _operation(values):
    action=values['_dp_action']; data={}
    if action=='initialize': data=dict(product=values.get('product',''),catalog_digest=values['_dp_catalog'],legacy_revision=int(values['_dp_legacy']))
    if action=='upgrade_definition': data=dict(catalog_digest=values['_dp_catalog'])
    if action in ('receive','review','withdraw_document'): data['item']=values['_dp_item']
    if action in ('receive','review','withdraw_document','passport_change','consent','approve','revoke'): data['on']=values.get('on','')
    if action=='receive': data.update(fingerprint=values.get('fingerprint',''),source=values.get('source',''))
    if action in ('review','withdraw_document'): data.update(version=int(values['_dp_version']),fingerprint=values['_dp_fingerprint'],reason=values.get('reason') or None)
    if action=='review': data.update(outcome=values.get('outcome',''),alternative=values.get('alternative') or None)
    if action in ('passport_change','revoke'): data['reason']=values.get('reason','')
    if action in ('consent','approve'): data.update(reference=values.get('reference',''),proof=values.get('proof',''))
    if action=='consent': data['status']=values.get('status','')
    if action=='approve': data.update(expected_state_hash=values['_dp_state'],expected_policy_hash=values['_dp_policy'])
    if action=='facts':
        definition=load_definition(values['_dp_catalog'],values['_dp_product']); facts={}
        for key,spec in definition['facts'].items():
            field='fact_'+key
            if field not in values: continue
            options={json.dumps(v):v for v in spec['values']}; options['']=None
            if values[field] not in options: raise EntryStorageInvalid('invalid_document_package_fact')
            facts[key]=options[values[field]]
        data['values']=facts
    return dict(action=action,data=data,confirmed=values.get('confirmed')=='yes')


async def _render(request,manager,actor,case,application_id,*,item_id='',revision=None,error='',status=200,echo=None,retry=None):
    inventory=None; item=None; forms={}; products={}; policy=None; policy_ready=False; facts=[];policy_invalid=False
    url=f'/admin/case/{case["id"]}/kg-entry/applications/{application_id}/document-package'
    try:
        policy,policy_invalid=_policy()
        inventory=await service.read_document_package(entry._engine(),actor=actor,case_id=case['id'],application_id=application_id,revision=revision,policy=policy)
        current=inventory['selected']
        if item_id and (not current or item_id not in current['snapshot']['items']): raise HTTPException(404,headers=HEADERS)
        if current:
            rows=current['summary']['rows']; item=next((r for r in rows if r['id']==item_id),rows[0])
            relevant={name for row in current['definition']['rows'] for name in _evaluate(row['when'],{},current['snapshot']['product'])[1]}
            facts=[dict(name=k,label=v['label'],options=[(json.dumps(x),'Да' if x is True else 'Нет' if x is False else x) for x in v['values']],
                selected=json.dumps(current['snapshot']['facts'][k]) if current['snapshot']['facts'][k] is not None else '')
                for k,v in current['definition']['facts'].items() if k in relevant]
            if policy:
                try:
                    authorize_acceptance(actor,policy,catalog_digest=current['snapshot']['catalog_digest'],day=ar._bishkek_today())
                    service._policy_scope(policy); policy_ready=True
                except (EntryStorageInvalid,PermissionDenied): pass
        historical=bool(revision and revision!=inventory['current_revision'])
        mutable=not historical and inventory['application_status'] not in ('approved','refused','closed') and inventory['ordinary_writes_available']
        if mutable:
            if not current:
                catalog=load_complete_document_catalog(); products={k:v for k,v in catalog.document()['products'].items() if k in PRODUCTS[inventory['application']['procedure']]}
                if inventory['legacy_product']: products={k:v for k,v in products.items() if k==inventory['legacy_product']}
                actions=['initialize'] if products else []
            else:
                actions=['facts','receive','passport_change','consent']
                if item['version'] and item['status']!='withdrawn': actions+=['review','withdraw_document']
                if policy_ready: actions+=['approve']
                if current['snapshot']['approval']: actions+=['revoke']
                if current['snapshot']['catalog_digest']!=CATALOG_SHA256: actions+=['upgrade_definition']
            for action in actions: forms[action]=_envelope(request,actor,case['id'],application_id,action,inventory,item,policy)
        elif current and not historical and inventory['current_revision']<MAX_REVISIONS:
            actions=['consent'] if current['snapshot']['consent'] and current['snapshot']['consent']['status']=='granted' else []
            if current['snapshot']['approval']:actions+=['revoke']
            for action in actions:forms[action]=_envelope(request,actor,case['id'],application_id,action,inventory,item,policy)
        if echo and echo['_dp_action'] in forms and echo['_dp_revision']==str(inventory['current_revision']): forms[echo['_dp_action']]=echo
    except PermissionDenied: raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE or str(exc)=='document_package_revision_unavailable': raise HTTPException(404,headers=HEADERS) from None
        inventory=None;forms={};error='Не удалось проверить историю комплекта. Изменения недоступны.';status=503
    except HTTPException: raise
    except Exception:
        inventory=None;forms={};error='Хранилище комплекта временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_document_package.html',dict(request=request,manager=manager,case=case,
        application_id=application_id,inventory=inventory,item=item,forms=forms,products=products,facts=facts,policy_ready=policy_ready,
        policy=policy,policy_invalid=policy_invalid,error=error,retry=retry,url=url,write_on=_write_on(request),meta=META,security=SECURITY,
        states=STATES,sources=SOURCES,reasons=REASONS,kinds=KINDS,actions=ACTIONS,today=ar._bishkek_today().isoformat()),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applications/{application_id}/document-package',response_class=HTMLResponse)
async def package_form(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),item:str=Query('',max_length=41),revision:int|None=Query(None,ge=1,le=MAX_REVISIONS),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager)
    pairs=list(request.query_params.multi_items())
    if len({k for k,v in pairs})!=len(pairs) or any(k not in ('item','revision') for k,v in pairs): raise HTTPException(422,headers=HEADERS)
    case=await entry._case(case_id,actor)
    return await _render(request,manager,actor,case,application_id,item_id=item,revision=revision)


@ar.router.post('/case/{case_id}/kg-entry/applications/{application_id}/document-package',response_class=HTMLResponse)
async def package_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True)
    case=await entry._case(case_id,actor); values=await _form(request,actor,case_id,application_id); item=values['_dp_item']
    try:
        await service.record_package_operation(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,
            expected_revision=int(values['_dp_revision']),request_key=values['_dp_key'],operation=_operation(values),
            policy=_policy()[0])
    except PermissionDenied: raise HTTPException(403,'Приёмка не разрешена действующей политикой.',headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,application_id,item_id=item,status=409,error='Запись уже изменилась. Откройте актуальную версию перед новой операцией.')
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE: raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,application_id,item_id=item,status=422,echo=values,error=ERRORS.get(str(exc),'Проверьте данные. Новая запись не добавлена.'))
    except Exception:
        return await _render(request,manager,actor,case,application_id,item_id=item,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос без изменений, чтобы получить его результат без дубля.')
    return RedirectResponse(f'/admin/case/{case_id}/kg-entry/applications/{application_id}/document-package'+('?item='+item if item else ''),
        status_code=303,headers={**HEADERS,'X-Action-Outcome':'document_package_saved'})
