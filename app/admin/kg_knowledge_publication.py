"""Explicit publication preview and authenticated lifecycle commands."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl, urlencode

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.domain import knowledge_decisions, knowledge_publication as service
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid, EntryStorageUnavailable
from app.domain.knowledge_publication_rules import authorize_publisher, configured_policy
from app.domain.service_authz import PermissionDenied

URL = '/admin/kg-entry/publication'
HEADERS = {'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer'}
META = ('_kp_version', '_kp_units', '_kp_revision', '_kp_action', '_kp_manifest', '_kp_policy', '_kp_key')
SECURITY = {'_kp_csrf', '_kp_signature'}
LABELS = {'review':'Передать на проверку', 'approve':'Утвердить выбранные правила', 'activate':'Активировать версию',
          'rollback':'Вернуть эту версию', 'withdraw':'Отозвать активную версию'}
REASONS = {'source_not_confirmed':'Источник не подтверждён', 'source_label_requires_specialist':'Пометка требует специалиста',
    'source_value_missing':'Значение отсутствует', 'source_evidence_unresolved':'Основание не согласовано',
    'source_conflict':'Есть противоречие', 'effective_date_unknown':'Не указана дата начала действия',
    'not_yet_effective':'Правило ещё не вступило в силу', 'no_longer_effective':'Действие правила завершилось',
    'source_verifier_missing':'Не указан проверивший источник', 'source_verification_in_future':'Дата сверки в будущем',
    'source_verification_date_unknown':'Не указано время сверки', 'source_review_expired':'Источник требует повторной проверки',
    'source_review_date_unknown':'Не указан срок проверки', 'source_owner_unknown':'Не назначен ответственный за источник',
    'review_evidence_missing':'Нет записи о проверке', 'review_not_confirmed':'Проверка не подтверждена',
    'official_source_review_required':'Нужна сверка с официальным источником', 'review_in_future':'Дата проверки в будущем',
    'review_expired':'Срок проверки прошёл', 'review_changed_since_approval':'Решение изменилось после утверждения'}


def _ids(raw):
    return service._identifiers(raw.split(','), maximum=100)


def _signature(request, actor, fields):
    csrf = request.session.setdefault('kg_publication_csrf', secrets.token_hex(32))
    payload = json.dumps(['kg-publication/1', actor.manager_id, csrf, [fields.get(k,'') for k in META]], separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(), payload, hashlib.sha256).hexdigest()


def _envelope(request, actor, report, action, policy):
    manifest = report['lifecycle_manifest'] if action == 'withdraw' else report['manifest']
    fields = dict(zip(META, (str(report['version']['id']), ','.join(u['unit_id'] for u in manifest['units']),
        str(report['current_revision']), action, service._hash(manifest), service._hash(service._policy(policy)), secrets.token_hex(24))))
    fields['_kp_signature'] = _signature(request, actor, fields)
    fields['_kp_csrf'] = request.session['kg_publication_csrf']
    return fields


async def _form(request, actor):
    if request.query_params: raise HTTPException(422, headers=HEADERS)
    if request.headers.get('content-type','').split(';',1)[0].strip() != 'application/x-www-form-urlencoded':
        raise HTTPException(415, headers=HEADERS)
    body = bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk) > 24000: raise HTTPException(413, headers=HEADERS)
        body.extend(chunk)
    try:
        pairs = parse_qsl(body.decode('utf-8'), keep_blank_values=True, max_num_fields=10, encoding='utf-8', errors='strict')
        values = dict(pairs)
        if (len(pairs) != len(values) or values.keys() != set(META)|SECURITY|{'confirmed'} or
            any(len(v) > (12100 if k == '_kp_units' else 128) for k,v in pairs) or
            values['_kp_action'] not in LABELS): raise ValueError
    except (ValueError, UnicodeError): raise HTTPException(422, headers=HEADERS) from None
    token = request.session.get('kg_publication_csrf','')
    if (not token or not hmac.compare_digest(token.encode(), values['_kp_csrf'].encode()) or
        not re.fullmatch('[a-f0-9]{48}', values['_kp_key']) or
        not hmac.compare_digest(_signature(request, actor, values).encode(), values['_kp_signature'].encode())):
        raise HTTPException(403, 'Форма устарела или изменена.', headers=HEADERS)
    return values


async def _render(request, manager, actor, *, version=None, units='', status=200, error='', retry=None):
    catalog = None; report = None; forms = {}; authority = False
    try:
        policy = configured_policy(ar.settings)
        try: authorize_publisher(actor, policy); authority = True
        except PermissionDenied: pass
        if version and units:
            report = await service.publication_preview(entry._engine(), actor=actor, version_id=version, unit_ids=_ids(units))
            state = report['version']['status']
            actions = ['withdraw'] if state == 'active' else ['review']
            if not any(item['reasons'] for item in report['availability']) and report['manifest'] == report['lifecycle_manifest']:
                actions += {'review':['approve'], 'approved':['activate'], 'retired':['rollback']}.get(state, [])
            if authority and retry is None and report['current_revision'] < service.MAX_REVISIONS:
                forms = {action:_envelope(request, actor, report, action, policy) for action in actions}
        else:
            catalog = await knowledge_decisions.review_catalog(entry._engine(), actor=actor, version_id=version)
            version = catalog['version_id']
    except PermissionDenied: raise HTTPException(403, headers=HEADERS) from None
    except Exception:
        catalog = None; report = None; forms = {}
        error = 'Не удалось проверить источник, полномочия или журнал публикации. Изменения недоступны.'; status = 503
    return ar.templates.TemplateResponse(request, 'kg_knowledge_publication.html', dict(manager=manager, url=URL,
        version=version, units=units, catalog=catalog, report=report, forms=forms, authority=authority,
        write_on=_write_on(request), labels=LABELS, reasons=REASONS, error=error, retry=retry), status_code=status, headers=HEADERS)


@ar.router.get('/kg-entry/publication', response_class=HTMLResponse)
async def publication_form(request:Request, version:int|None=Query(None,ge=1,le=2147483647),
    units:str=Query('',max_length=12100), manager=Depends(ar.require_full_admin)):
    actor = entry._gate(request, manager)
    pairs = request.query_params.multi_items()
    if len(dict(pairs)) != len(pairs) or any(k not in ('version','units') for k,v in pairs) or units and not version:
        raise HTTPException(422, headers=HEADERS)
    if units:
        try: _ids(units)
        except EntryStorageInvalid: raise HTTPException(422, headers=HEADERS) from None
    return await _render(request, manager, actor, version=version, units=units)


@ar.router.post('/kg-entry/publication', response_class=HTMLResponse)
async def publication_submit(request:Request, manager=Depends(ar.require_full_admin)):
    actor = entry._gate(request, manager, write=True)
    try: policy = configured_policy(ar.settings); authorize_publisher(actor, policy)
    except (PermissionDenied, EntryStorageInvalid): raise HTTPException(403, 'Полномочия публикации не настроены.', headers=HEADERS) from None
    values = await _form(request, actor)
    if values['_kp_policy'] != service._hash(service._policy(policy)):
        raise HTTPException(409, 'Полномочия изменились. Откройте предпросмотр заново.', headers=HEADERS)
    version = int(values['_kp_version']); units = values['_kp_units']
    try:
        if values['confirmed'] != 'yes': raise EntryStorageInvalid('confirmation_required')
        await service.publish_knowledge(entry._engine(), actor=actor, policy=policy, version_id=version,
            action=values['_kp_action'], expected_revision=int(values['_kp_revision']), request_key=values['_kp_key'],
            unit_ids=_ids(units), manifest_hash=values['_kp_manifest'])
    except PermissionDenied: raise HTTPException(403, headers=HEADERS) from None
    except EntryStorageConflict:
        return await _render(request, manager, actor, version=version, units=units, status=409,
                             error='Версия, решение или состав правил изменились. Проверьте новый предпросмотр.')
    except EntryStorageInvalid:
        return await _render(request, manager, actor, version=version, units=units, status=422,
                             error='Публикация не выполнена. Проверьте основания, сроки и подтверждение действия.')
    except Exception:
        return await _render(request, manager, actor, version=version, units=units, status=503, retry=values,
                             error='Результат сохранения неизвестен. Повторите исходный запрос без изменений.')
    return RedirectResponse(URL+'?'+urlencode(dict(version=version, units=units)), status_code=303, headers=HEADERS)
