"""Read-only full-admin answers from the current approved knowledge publication."""
from fastapi import Depends, Request
from fastapi.responses import HTMLResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.domain import knowledge_answers as service
from app.domain.entry_storage import EntryStorageInvalid
from app.domain.knowledge_publication_rules import configured_policy

URL = '/admin/kg-entry/answers'
HEADERS = {'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer'}


@ar.router.get('/kg-entry/answers', response_class=HTMLResponse)
async def knowledge_answers(request: Request, manager=Depends(ar.require_full_admin)):
    actor = entry._gate(request, manager)
    report = None
    error = ''
    status = 200
    language = 'ru'
    units = ''
    try:
        pairs = list(request.query_params.multi_items())
        params = dict(pairs)
        if (len(params) != len(pairs) or set(params) - {'units', 'language'} or
                params.get('language', 'ru') not in service.COPY or len(params.get('units', '')) > 362):
            raise EntryStorageInvalid('invalid_answer_query')
        language = params.get('language', 'ru')
        units = params.get('units', '')
        if units:
            ids = service.publication._identifiers([item.strip() for item in units.split(',')], maximum=3)
            try:
                policy = configured_policy(ar.settings)
            except EntryStorageInvalid:
                error = 'Не удалось проверить настройки утверждения источников. Требуется проверка специалиста.'
                status = 503
            else:
                report = await service.answer_knowledge(entry._engine(), actor=actor, policy=policy,
                                                        unit_ids=ids, language=language)
    except EntryStorageInvalid:
        error = 'Проверьте коды правил и язык. Можно выбрать до трёх разных правил.'
        status = 422
    return ar.templates.TemplateResponse(request, 'kg_answers.html', dict(manager=manager, report=report,
        error=error, units=units, language=language, copy=service.COPY[language], url=URL),
        status_code=status, headers=HEADERS)
