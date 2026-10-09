"""Native full-admin register over case-scoped application operations."""
import hashlib
import hmac
import json
import logging
import re
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.admin.kg_entry as entry
import app.admin.router as ar
from app.admin.workday import _write_on
from app.domain import entry_applications as service
from app.domain.entry_application_rules import PROCEDURES, PROCESSES, RETRYABLE, ROLES, SOURCES, STATUSES, TRANSITIONS
from app.domain.entry_storage import EntryStorageConflict, EntryStorageInvalid
from app.domain.service_authz import PermissionDenied

log = logging.getLogger('admin.kg_applications')
META = ('_ea_action', '_ea_target', '_ea_revision', '_ea_key')
SECURITY = ('_ea_csrf', '_ea_signature')
FIELDS = {'applicant': {'role'}, 'application': {'applicant_id', 'procedure'}, 'retry': set(),
          'event': {'status', 'occurred_on', 'source', 'reference', 'confirmed'}}
HEADERS = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
ERRORS = {'operator_confirmation_required': 'Подтвердите, что вы проверили событие по выбранному источнику.',
          'invalid_application_date': 'Укажите фактическую дату: не в будущем и не раньше предыдущего события.',
          'invalid_application_transition': 'Такое событие не подходит к текущему состоянию заявки.',
          'invalid_application_source': 'Для этого события требуется портал или официальный документ.',
          'invalid_portal_reference': 'Reference портала: восемь заглавных латинских букв или цифр.',
          'portal_reference_required': 'Для события портала укажите reference number.',
          'portal_reference_is_immutable': 'Reference уже закреплён за этой попыткой и не может быть заменён.',
          'portal_reference_requires_submission': 'Новый reference записывается при подтверждении подачи на портал.',
          'previous_application_not_retryable': 'Связанная повторная попытка доступна после отказа или закрытия.',
          'application_subject_mismatch': 'Повторная попытка должна относиться к тому же заявителю и документу.',
          'applicant_limit_reached': 'Достигнут предел числа заявителей в этой услуге.'}
UNAVAILABLE = {'application_case_unavailable', 'applicant_unavailable', 'application_unavailable'}


def _csrf(request):
    if not request.session.get('kg_applications_csrf'):
        request.session['kg_applications_csrf'] = secrets.token_hex(32)
    return request.session['kg_applications_csrf']


def _signature(request, actor, case_id, values):
    payload = json.dumps(['kg-applications/1', actor.manager_id, case_id, _csrf(request),
                          [values.get(key, '') for key in META]], separators=(',', ':')).encode()
    return hmac.new(ar.settings.session_secret.encode(), payload, hashlib.sha256).hexdigest()


def _envelope(request, actor, case_id, action, target=0, revision=0):
    values = dict(zip(META, (action, str(target), str(revision), secrets.token_hex(24))))
    values.update(_ea_csrf=_csrf(request), _ea_signature=_signature(request, actor, case_id, values))
    return values


async def _form(request):
    if request.headers.get('content-type', '').split(';', 1)[0].strip() != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Используйте форму реестра.')
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > 8192: raise HTTPException(413, 'Форма слишком большая.')
        body.extend(chunk)
    try:
        pairs = parse_qsl(body.decode('utf-8'), keep_blank_values=True, max_num_fields=20, encoding='utf-8', errors='strict')
    except (ValueError, UnicodeError):
        raise HTTPException(422, 'Не удалось прочитать форму.') from None
    values = {}
    for key, value in pairs:
        if key in values or len(value) > 128:
            raise HTTPException(422, 'Недопустимые или повторяющиеся поля.')
        values[key] = value
    action = values.get('_ea_action')
    if action not in FIELDS or not set(values) <= FIELDS[action] | set(META) | set(SECURITY):
        raise HTTPException(422, 'Недопустимые поля формы.')
    return values


def _verify(request, actor, case_id, values):
    token = request.session.get('kg_applications_csrf', '')
    if (not token or not secrets.compare_digest(token.encode(), values.get('_ea_csrf', '').encode())
            or not re.fullmatch('[a-f0-9]{48}', values.get('_ea_key', ''))
            or not secrets.compare_digest(_signature(request, actor, case_id, values).encode(), values.get('_ea_signature', '').encode())):
        raise HTTPException(403, 'Форма устарела или изменена. Откройте реестр заново.')


def _number(value):
    if not isinstance(value, str) or not re.fullmatch('[1-9][0-9]{0,9}', value) or int(value) > 2147483647:
        raise EntryStorageInvalid('invalid_identifier')
    return int(value)


async def _render(request, manager, actor, case, *, application_id=None, page=1, echo=None, error='', status=200):
    forms, selected, register = {}, None, {'applicants': [], 'applications': [], 'page': page, 'total': 0, 'has_next': False}
    try:
        register = await service.read_application_register(entry._engine(), actor=actor, case_id=case['id'], page=page)
        if application_id:
            selected = await service.read_application(entry._engine(), actor=actor, case_id=case['id'], application_id=application_id)
        forms['applicant'] = {**_envelope(request, actor, case['id'], 'applicant'), 'role': 'unknown'}
        forms['application'] = {**_envelope(request, actor, case['id'], 'application'), 'applicant_id': '', 'procedure': 'visa'}
        if selected:
            current = selected['current']
            if TRANSITIONS[current['status']] and current['revision'] < service.MAX_EVENTS:
                forms['event'] = {**_envelope(request, actor, case['id'], 'event', selected['id'], current['revision']),
                    'status': '', 'occurred_on': '', 'source': '', 'reference': current['reference'] or '', 'confirmed': ''}
            if current['status'] in RETRYABLE and not selected['successor_id'] and selected['attempt'] < service.MAX_ATTEMPTS:
                forms['retry'] = _envelope(request, actor, case['id'], 'retry', selected['id'], current['revision'])
    except PermissionDenied:
        raise HTTPException(403) from None
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE: raise HTTPException(404) from None
        log.warning('KG applications: invalid register')
        status, error = 503, error or 'Реестр заявок временно недоступен. Попробуйте позже.'
    except Exception:
        log.warning('KG applications: storage unavailable')
        status, error = 503, error or 'Реестр заявок временно недоступен. Попробуйте позже.'
    if status == 503: forms = {}
    if echo is not None: forms[echo['_ea_action']] = echo
    return ar.templates.TemplateResponse(request, 'kg_applications.html', {
        'manager': manager, 'case': case, 'register': register, 'selected': selected, 'forms': forms,
        'roles': ROLES, 'procedures': PROCEDURES, 'processes': PROCESSES, 'statuses': STATUSES, 'sources': SOURCES,
        'transitions': TRANSITIONS, 'meta': (*META, *SECURITY), 'error': error, 'write_on': _write_on(request),
        'today': ar._bishkek_today().isoformat(), 'form_url': f"/admin/case/{case['id']}/kg-entry/applications",
    }, status_code=status, headers={**HEADERS, 'X-Action-Outcome': 'failed' if status == 503 else 'invalid' if error else 'form'})


async def _case(case_id, actor):
    try: return await entry._case(case_id, actor)
    except HTTPException: raise
    except Exception: raise HTTPException(503, 'Реестр услуг временно недоступен.', headers=HEADERS) from None


@ar.router.get('/case/{case_id}/kg-entry/applications', response_class=HTMLResponse)
async def applications_form(case_id: int, request: Request, application_id: int | None = Query(None, ge=1, le=2147483647),
                            page: int = Query(1, ge=1, le=100000), manager=Depends(ar.require_full_admin)):
    actor = entry._gate(request, manager)
    case = await _case(case_id, actor)
    return await _render(request, manager, actor, case, application_id=application_id, page=page)


@ar.router.post('/case/{case_id}/kg-entry/applications', response_class=HTMLResponse)
async def applications_submit(case_id: int, request: Request, manager=Depends(ar.require_full_admin)):
    actor = entry._gate(request, manager, write=True)
    case = await _case(case_id, actor)
    values = await _form(request)
    _verify(request, actor, case_id, values)
    action, target = values['_ea_action'], int(values['_ea_target'])
    application_id = target or None
    try:
        args = dict(actor=actor, case_id=case_id, request_key=values['_ea_key'])
        if action == 'applicant':
            await service.add_applicant(entry._engine(), role=values.get('role', ''), **args)
        elif action == 'application':
            row = await service.open_application(entry._engine(), applicant_id=_number(values.get('applicant_id')),
                procedure=values.get('procedure', ''), **args)
            application_id = row['id']
        elif action == 'retry':
            old = await service.read_application(entry._engine(), actor=actor, case_id=case_id, application_id=target)
            if old['current']['revision'] != int(values['_ea_revision']): raise EntryStorageConflict('application_revision_changed')
            row = await service.open_application(entry._engine(), applicant_id=old['applicant_id'], procedure=old['procedure'], previous_id=target, **args)
            application_id = row['id']
        else:
            await service.record_application_event(entry._engine(), application_id=target, expected_revision=int(values['_ea_revision']),
                status=values.get('status', ''), occurred_on=values.get('occurred_on', ''), source=values.get('source', ''),
                reference=values.get('reference') or None, confirmed=values.get('confirmed') == 'yes', **args)
    except PermissionDenied:
        raise HTTPException(403) from None
    except EntryStorageConflict as exc:
        message = 'Заявка уже изменена или операция повторена с другими данными. Ответы оставлены; откройте актуальную заявку и сверьте их.'
        if str(exc) == 'portal_reference_already_recorded': message = 'Этот reference уже зарегистрирован. Проверьте номер; новая запись не создана.'
        return await _render(request, manager, actor, case, application_id=target or None, echo=values, error=message, status=409)
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE: raise HTTPException(404) from None
        return await _render(request, manager, actor, case, application_id=target or None, echo=values,
                             error=ERRORS.get(str(exc), 'Проверьте заявителя, документ и факты события.'), status=422)
    except Exception:
        log.warning('KG applications: save outcome unavailable')
        return await _render(request, manager, actor, case, application_id=target or None, echo=values, status=503,
                             error='Сохранение не подтверждено. Повторите эту же форму без изменений, чтобы проверить результат.')
    location = f'/admin/case/{case_id}/kg-entry/applications'
    if application_id: location += f'?application_id={application_id}'
    return RedirectResponse(location, status_code=303, headers={**HEADERS, 'X-Action-Outcome': 'application_saved'})
