"""Native scoped procedural forms; execution authority is absent by default."""
import hashlib
import hmac
import json
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.kg_document_ui import HEADERS, UNAVAILABLE
from app.admin.workday import _write_on
from app.domain import entry_processes as service
from app.domain.entry_process_policy import configured_policy, authorize, ROLES, ROOTS, AUTHORITATIVE, edge_id
from app.domain.entry_process_rules import catalog, fact_role, MAX_EVENTS
from app.domain.entry_package_policy import configured_policy as package_policy
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict, EntryStorageUnavailable
from app.domain.service_authz import PermissionDenied
from app.knowledge.process_preview import CATALOG_SHA256

META = ('_pj_action', '_pj_revision', '_pj_key', '_pj_role', '_pj_fact', '_pj_edge', '_pj_evidence',
    '_pj_active', '_pj_profile', '_pj_policy')
SECURITY = {'_pj_csrf', '_pj_signature'}
FIELDS = {'initialize':{'on','employer_reference','confirmed'}, 'link':{'on','application_id','confirmed'},
    'attest':{'on','valid_through','value','source','reference','proof','confirmed'},
    'withdraw':{'on','reference','proof','confirmed'}, 'transition':{'on','confirmed'}, 'stop':{'on','reference','proof','confirmed'}}
ACTIONS = {'initialize':'Начало журнала', 'link':'Связь с отдельной заявкой', 'attest':'Подтверждение факта',
    'withdraw':'Отзыв подтверждения', 'transition':'Переход этапа', 'stop':'Остановка процесса'}
ROLE_LABELS = {'visa':'Виза', 'permit':'Разрешение на работу', 'resident':'Резидент-карта',
    'registration':'Регистрация', 'protocol':'Протокол нарушения', 'exit_visa':'Выездная виза L'}
SOURCE_LABELS = {'operator_check':'Проверка сотрудником', 'official_document':'Официальный документ',
    'portal':'Запись портала', 'client_statement':'Подтверждение клиента', 'contract':'Договор', 'payment_receipt':'Платёжный документ'}
REASONS = {'current_evidence':'Подтверждения актуальны', 'process_not_initialized':'Журнал ещё не начат',
    'process_stopped':'Процесс остановлен', 'process_policy_changed':'Условия работы изменились',
    'process_prerequisites_changed':'Нужно обновить подтверждения', 'process_prerequisites_missing':'Не все условия подтверждены',
    'process_dependency_missing':'Сначала свяжите нужную отдельную заявку', 'process_branch_mismatch':'Эта ветка не относится к выбранной процедуре',
    'process_edge_not_authorized':'Переход не разрешён действующими условиями', 'process_application_terminal':'Попытка завершена отказом или закрыта',
    'process_policy_outdated':'Срок разрешения на ведение этапов истёк', 'process_history_limit':'Достигнут предел записей',
    'attestation_profile_changed':'Анкета изменилась после проверки', 'attestation_expired':'Срок подтверждения истёк',
    'process_evidence_limit':'Слишком много связанных подтверждений для одного перехода',
    'process_money_evidence_limit':'Платёжный журнал слишком большой для этой проверки',
    'document_in_quarantine':'Документ находится в карантине', 'package_not_approved':'Комплект ещё не принят'}


def _policies():
    try: policy = configured_policy(ar.settings)
    except EntryStorageInvalid: policy = None
    try: package = package_policy(ar.settings)
    except EntryStorageInvalid: package = None
    return policy, package


def _csrf(request):
    request.session.setdefault('kg_process_journal_csrf', secrets.token_hex(32))
    return request.session['kg_process_journal_csrf']


def _signature(request, actor, case_id, application_id, values):
    body = json.dumps(['kg-process-journal/1', actor.manager_id, case_id, application_id, _csrf(request),
        [values.get(key, '') for key in META]], separators=(',', ':')).encode()
    return hmac.new(ar.settings.session_secret.encode(), body, hashlib.sha256).hexdigest()


def _envelope(request, actor, case_id, application_id, action, history, policy, *, role='', fact='', edge=None):
    state = history['selected']['snapshot'] if history['selected'] else {}
    values = dict(zip(META, (action, str(history['current_revision']), secrets.token_hex(24), role, fact,
        edge['edge_id'] if edge else '', edge['evidence_digest'] or '' if edge else '',
        str(state.get('active_application_id', application_id)), str(history['profile_id'] or ''),
        policy.digest if policy and action not in ('stop','withdraw') else '')))
    return {**values, '_pj_csrf':_csrf(request), '_pj_signature':_signature(request, actor, case_id, application_id, values)}


async def _form(request, actor, case_id, application_id):
    if request.headers.get('content-type', '').split(';', 1)[0].strip() != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Используйте форму.', headers=HEADERS)
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 8192: raise HTTPException(413, 'Форма слишком большая.', headers=HEADERS)
        body.extend(chunk)
    try:
        pairs = parse_qsl(body.decode('utf-8'), keep_blank_values=True, max_num_fields=30, encoding='utf-8', errors='strict')
        if len({k for k,v in pairs}) != len(pairs) or any(len(k)>64 or len(v)>128 for k,v in pairs): raise ValueError
        values = dict(pairs); action = values.get('_pj_action')
        if action not in FIELDS or not values.keys() <= set(META)|SECURITY|FIELDS[action]: raise ValueError
    except (ValueError, UnicodeError): raise HTTPException(422, 'Недопустимые поля формы.', headers=HEADERS) from None
    token = request.session.get('kg_process_journal_csrf', '')
    if (not token or not hmac.compare_digest(token.encode(), values.get('_pj_csrf','').encode()) or
        not hmac.compare_digest(_signature(request,actor,case_id,application_id,values).encode(), values.get('_pj_signature','').encode())):
        raise HTTPException(403, 'Форма изменена или относится к другой сессии.', headers=HEADERS)
    return values


def _operation(values):
    action = values['_pj_action']; data = dict(on=values.get('on',''))
    if action == 'initialize': data.update(catalog_digest=CATALOG_SHA256, employer_reference=values.get('employer_reference') or None)
    elif action == 'link': data.update(role=values['_pj_role'], application_id=int(values.get('application_id','')))
    elif action == 'transition': data.update(edge_id=values['_pj_edge'], evidence_digest=values['_pj_evidence'])
    elif action in ('attest', 'withdraw', 'stop'):
        data.update(reference=values.get('reference',''), proof=values.get('proof',''))
        if action != 'stop': data.update(role=values['_pj_role'], fact=values['_pj_fact'])
        if action == 'attest':
            spec = catalog()['facts'].get(data['fact'], {'type':'boolean'})
            raw = values.get('value','')
            if spec['type'] == 'boolean':
                if raw not in ('', 'true', 'false'): raise EntryStorageInvalid('invalid_process_operation')
                value = {'':None,'true':True,'false':False}[raw]
            else: value = raw or None
            profile_bound = data['fact'] in ('profile_review_complete', 'eligibility', 'visa_required')
            data.update(value=value, source=values.get('source',''), valid_through=values.get('valid_through',''),
                profile_id=int(values['_pj_profile']) if profile_bound and values['_pj_profile'] else None)
    return dict(action=action, data=data, confirmed=values.get('confirmed')=='yes')


async def _render(request, manager, actor, case, application_id, *, revision=None, error='', status=200, retry=None):
    history = None; forms = {}; policy, package = _policies(); allowed = False
    url = f'/admin/case/{case["id"]}/kg-entry/applications/{application_id}/process-journal'
    try:
        history = await service.read_process_history(entry._engine(), actor=actor, case_id=case['id'], application_id=application_id,
            revision=revision, policy=policy, package_policy=package)
        try: authorize(actor, policy, day=service.applications._today()); allowed=True
        except (PermissionDenied, EntryStorageInvalid): pass
        selected = history['selected']; state = selected['snapshot'] if selected else None
        current = revision is None or revision == history['current_revision']
        def add(name, action, **kwargs):
            forms[name] = _envelope(request, actor, case['id'], application_id, action, history, policy, **kwargs)
        if current and not retry:
            if state and not state['stopped']:
                add('stop', 'stop')
                for key in state['attestations']:
                    role, fact = key.split('.',1); add('withdraw-'+key, 'withdraw', role=role, fact=fact)
            if allowed and history['current_revision'] < MAX_EVENTS-1:
                if state is None and history['application']['procedure'] in policy.initial_procedures:
                    add('initialize','initialize')
                elif state and not state['stopped']:
                    for role in ROLES:
                        if role not in state['used_roles']: add('link-'+role, 'link', role=role)
                    needed = set(state['attestations'])
                    for key in state['retained']:
                        role,fact=key.split('.',1)
                        needed.add(role+'.'+('profile_review_complete' if fact=='profile_complete' else fact))
                    for item in history['readiness']['transitions']:
                        if item['edge_id'] not in policy.allowed_edges: continue
                        if item['ready']: add('transition-'+item['edge']['to'], 'transition', edge=item)
                        for fact in item['edge']['requires']:
                            try: role = fact_role(state, item['edge'], fact)
                            except EntryStorageInvalid: continue
                            needed.add(role+'.'+('profile_review_complete' if fact=='profile_complete' else fact))
                    for key in sorted(needed):
                        role, fact = key.split('.',1)
                        if role in state['links'] and fact in dict(policy.manual_sources):
                            add('attest-'+key, 'attest', role=role, fact=fact)
    except PermissionDenied: raise HTTPException(403, headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE|{'process_revision_unavailable'}: raise HTTPException(404,headers=HEADERS) from None
        history=None; forms={}; error='История не прошла проверку. Изменения недоступны.'; status=503
    except Exception:
        history=None; forms={}; error='Хранилище временно недоступно.'; status=503
    document = catalog()
    facts = {**document['facts'], 'profile_review_complete':{'label':'Полнота индивидуальной анкеты проверена', 'type':'boolean'}}
    return ar.templates.TemplateResponse(request, 'kg_process_journal.html', dict(request=request, manager=manager, case=case,
        application_id=application_id, history=history, forms=forms, actions=ACTIONS, roles=ROLE_LABELS, role_procedures=ROLES,
        reasons=REASONS, facts=facts, stages={s['code']:s for s in document['stages']}, sources=SOURCE_LABELS,
        allowed_sources=dict(policy.manual_sources) if policy else {}, allowed=allowed, error=error, retry=retry, url=url,
        write_on=_write_on(request), meta=META, security=SECURITY, today=service.applications._today().isoformat()),
        status_code=status, headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applications/{application_id}/process-journal', response_class=HTMLResponse)
async def process_form(request:Request, case_id:int=Path(ge=1,le=2147483647),
                       application_id:int=Path(ge=1,le=2147483647), manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager)
    try:
        pairs=list(request.query_params.multi_items())
        if len(pairs)>1 or any(k!='revision' for k,v in pairs): raise ValueError
        raw=request.query_params.get('revision'); revision=int(raw) if raw is not None else None
        if raw is not None and (str(revision)!=raw or not 1<=revision<=MAX_EVENTS): raise ValueError
    except ValueError: raise HTTPException(422,'Недопустимая версия.',headers=HEADERS) from None
    case=await entry._case(case_id,actor)
    return await _render(request,manager,actor,case,application_id,revision=revision)


@ar.router.post('/case/{case_id}/kg-entry/applications/{application_id}/process-journal', response_class=HTMLResponse)
async def process_submit(request:Request, case_id:int=Path(ge=1,le=2147483647),
                         application_id:int=Path(ge=1,le=2147483647), manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True); case=await entry._case(case_id,actor)
    values=await _form(request,actor,case_id,application_id); policy,package=_policies()
    try:
        await service.record_process_operation(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,
            expected_revision=int(values['_pj_revision']),request_key=values['_pj_key'],operation=_operation(values),
            policy=policy,package_policy=package,expected_policy_hash=values['_pj_policy'] or None)
    except PermissionDenied: raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request,manager,actor,case,application_id,status=409,
            error='Заявка, подтверждения или условия работы изменились. Проверьте текущую версию.')
    except EntryStorageUnavailable:
        return await _render(request,manager,actor,case,application_id,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос для проверки результата без дубля.')
    except (EntryStorageInvalid, ValueError) as exc:
        if str(exc) in UNAVAILABLE: raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,application_id,status=422,
            error=REASONS.get(str(exc),'Проверьте данные и подтверждения. Новая запись не добавлена.'))
    except Exception:
        return await _render(request,manager,actor,case,application_id,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос для проверки результата без дубля.')
    return RedirectResponse(f'/admin/case/{case_id}/kg-entry/applications/{application_id}/process-journal',status_code=303,headers=HEADERS)
