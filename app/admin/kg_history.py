"""Full-admin CRM editor over existing immutable actual-stay snapshots."""
import hashlib
import hmac
import json
import logging
import re
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.kg_history_form import (BASES, EVIDENCE, LIMIT, ROW_FIELDS, FormInvalid,
                                      countries, document_from_values, history_overlaps, row_values, values_from_history)
from app.admin.workday import _write_on
from app.domain.entry_storage import (EntryStorageConflict, EntryStorageInvalid,
                                      read_stay_history, save_stay_history)
from app.domain.models import StayHistory
from app.domain.service_authz import PermissionDenied

log = logging.getLogger('admin.kg_history')
META = ('_sh_key', '_sh_contact', '_sh_base', '_sh_revision', '_sh_asof')
SECURITY = ('_sh_csrf', '_sh_signature')
FIELDS = {'rows_count', 'history_complete', 'no_trips', 'history_action'}
HEADERS = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}
BODY_LIMIT = 1_048_576


def _csrf(request):
    if not request.session.get('kg_history_csrf'):
        request.session['kg_history_csrf'] = secrets.token_hex(32)
    return request.session['kg_history_csrf']


def _signature(request, actor, case_id, values):
    payload = json.dumps(['kg-stay-form/1', actor.manager_id, case_id, _csrf(request),
                          [values.get(k, '') for k in META]], separators=(',', ':')).encode()
    return hmac.new(ar.settings.session_secret.encode(), payload, hashlib.sha256).hexdigest()


def _envelope(request, actor, case, saved):
    values = dict(zip(META, (secrets.token_hex(24), str(case['contact_id']),
        str(saved['history_id'] if saved else 0), str(saved['revision'] if saved else 0), ar._bishkek_today().isoformat())))
    values.update(_sh_csrf=_csrf(request), _sh_signature=_signature(request, actor, case['id'], values))
    return values


def _verify(request, actor, case, values):
    token = request.session.get('kg_history_csrf', '')
    if (not token or not secrets.compare_digest(token.encode(), values.get('_sh_csrf', '').encode())
            or not re.fullmatch('[a-f0-9]{48}', values.get('_sh_key', ''))
            or not secrets.compare_digest(_signature(request, actor, case['id'], values).encode(),
                                           values.get('_sh_signature', '').encode())
            or values.get('_sh_contact') != str(case['contact_id'])):
        raise HTTPException(403, 'Форма устарела или изменена. Откройте историю заново.')


async def _form(request):
    if request.headers.get('content-type', '').split(';', 1)[0].strip() != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Используйте форму истории.')
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > BODY_LIMIT:
            raise HTTPException(413, 'Форма слишком большая.')
        body.extend(chunk)
    try:
        pairs = parse_qsl(body.decode('utf-8'), keep_blank_values=True, max_num_fields=LIMIT * len(ROW_FIELDS) + 20,
                          encoding='utf-8', errors='strict')
    except (ValueError, UnicodeError):
        raise HTTPException(422, 'Не удалось прочитать форму.') from None
    result = {}
    for key, value in pairs:
        match = re.fullmatch(r'trip\.(0|[1-9][0-9]{0,2})\.([a-z_]+)', key)
        valid_row = match and int(match[1]) < LIMIT and match[2] in ROW_FIELDS
        if key in result or len(value) > 128 or key not in FIELDS | set(META) | set(SECURITY) and not valid_row:
            raise HTTPException(422, 'Недопустимые или повторяющиеся поля истории.')
        if (key.endswith(('.remove', '.clear_passport')) or key == 'no_trips') and value not in ('', 'yes'):
            raise HTTPException(422, 'Недопустимый ответ истории.')
        result[key] = value
    try:
        rows = row_values(result)
    except FormInvalid as exc:
        raise HTTPException(422, str(exc)) from None
    if any(key.startswith('trip.') and int(key.split('.')[1]) >= len(rows) for key in result):
        raise HTTPException(422, 'Число поездок не соответствует форме.')
    return result


async def _read(actor, contact_id, history_id):
    try:
        return await read_stay_history(entry._engine(), actor=actor, contact_id=contact_id, history_id=history_id)
    except EntryStorageInvalid as exc:
        if str(exc) == 'history_unavailable':
            raise HTTPException(404) from None
        raise


async def _context(request, actor, case, history_id=None):
    async with ar._domain_sessionmaker()() as session:
        latest = (await session.execute(select(StayHistory.id, StayHistory.revision).where(
            StayHistory.contact_id == case['contact_id']).order_by(StayHistory.revision.desc()).limit(1))).first()
        selected_id = history_id if history_id is not None else latest.id if latest else None
        previous = (await session.scalar(select(StayHistory.previous_id).where(
            StayHistory.id == selected_id, StayHistory.contact_id == case['contact_id']))) if selected_id else None
    saved = await _read(actor, case['contact_id'], selected_id) if selected_id else None
    return {'saved': saved, 'previous_id': previous, 'latest_id': latest.id if latest else None,
            'history_overlaps': history_overlaps(saved['document']) if saved else False,
            'editable': saved is None or latest is not None and saved['history_id'] == latest.id,
            'values': values_from_history(saved['document'] if saved else {}),
            'envelope': _envelope(request, actor, case, saved)}


async def _render(request, manager, actor, case, *, history_id=None, echo=None, error='', status=200):
    try:
        context = await _context(request, actor, case, history_id)
        catalog = countries()
    except (PermissionDenied, HTTPException):
        raise
    except Exception:
        log.warning('KG history: source or registry unavailable')
        context, catalog, status = {'editable': echo is not None, 'values': values_from_history({})}, {}, 503
        error = error or 'История поездок временно недоступна. Попробуйте позже.'
    if echo is not None:
        context.update(values=echo, envelope={k: echo.get(k, '') for k in (*META, *SECURITY)})
    rows = row_values(context['values'])
    # Keep old/echoed country visible even if a catalog update no longer includes it.
    for row in rows:
        if row['passport_country']:
            catalog.setdefault(row['passport_country'], row['passport_country'])
    return ar.templates.TemplateResponse(request, 'kg_history.html', {
        **context, 'rows': rows, 'countries': sorted(catalog.items(), key=lambda item: item[1]),
        'manager': manager, 'case': case, 'error': error, 'write_on': _write_on(request),
        'bases': BASES, 'evidence': EVIDENCE, 'limit': LIMIT,
        'form_url': f"/admin/case/{case['id']}/kg-entry/history",
    }, status_code=status, headers={**HEADERS, 'X-Action-Outcome': 'failed' if status == 503 else 'invalid' if error else 'form'})


@ar.router.get('/case/{case_id}/kg-entry/history', response_class=HTMLResponse)
async def history_form(case_id: int, request: Request, history_id: int | None = Query(None, ge=1, le=2147483647),
                       manager=Depends(ar.require_full_admin)):
    actor = entry._gate(request, manager)
    try:
        case = await entry._case(case_id, actor)
    except HTTPException:
        raise
    except Exception:
        return HTMLResponse('Реестр услуг временно недоступен.', status_code=503, headers=HEADERS)
    return await _render(request, manager, actor, case, history_id=history_id)


@ar.router.post('/case/{case_id}/kg-entry/history', response_class=HTMLResponse)
async def history_submit(case_id: int, request: Request, manager=Depends(ar.require_full_admin)):
    actor = entry._gate(request, manager, write=True)
    try:
        case = await entry._case(case_id, actor)
    except HTTPException:
        raise
    except Exception:
        return HTMLResponse('Реестр услуг временно недоступен. Сохранение не выполнено.', status_code=503, headers=HEADERS)
    values = await _form(request)
    _verify(request, actor, case, values)
    try:
        base_id = int(values['_sh_base'])
        base = await _read(actor, case['contact_id'], base_id) if base_id else None
        if (base['revision'] if base else 0) != int(values['_sh_revision']):
            raise FormInvalid('Версия истории изменилась. Откройте последнюю историю.')
        action = values.get('history_action', '')
        if action == 'add':
            count = len(row_values(values))
            if count >= LIMIT:
                raise FormInvalid('Достигнут предел числа поездок.')
            values['rows_count'] = str(count + 1)
            return await _render(request, manager, actor, case, echo=values)
        if action != 'save':
            raise FormInvalid('Выберите действие формы.')
        document = document_from_values(values, base=base['document'] if base else {},
            as_of=values['_sh_asof'], request_key=values['_sh_key'], country_codes=countries())
        result = await save_stay_history(entry._engine(), actor=actor, contact_id=case['contact_id'],
            expected_revision=int(values['_sh_revision']), request_key=values['_sh_key'], document=document)
    except (PermissionDenied, HTTPException):
        raise
    except FormInvalid as exc:
        return await _render(request, manager, actor, case, echo=values, error=str(exc), status=422)
    except EntryStorageConflict:
        return await _render(request, manager, actor, case, echo=values, status=409,
            error='История уже сохранена или изменена в другой вкладке. Ответы оставлены в форме; откройте последнюю версию и сверьте их.')
    except EntryStorageInvalid:
        return await _render(request, manager, actor, case, echo=values, status=422,
            error='Проверьте фактические даты, порядок поездок и источник подтверждения. Будущие даты, два незавершённых въезда и подтверждение только со слов клиента недопустимы.')
    except Exception:
        log.warning('KG history: save outcome unavailable')
        return await _render(request, manager, actor, case, echo=values, status=503,
            error='Сохранение не подтверждено. Повторите эту же форму без изменений, чтобы проверить результат.')
    return RedirectResponse(f"/admin/case/{case_id}/kg-entry/history?history_id={result['history_id']}",
                            status_code=303, headers={**HEADERS, 'X-Action-Outcome': 'history_saved'})
