"""Signed, explicit management of conditional internal work-date reminders."""
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl

from fastapi import Depends,HTTPException,Path,Request
from fastapi.responses import HTMLResponse,RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.domain import work_review_tasks as service
from app.domain.work_review_policy import configured
from app.domain.entry_storage import EntryStorageInvalid,EntryStorageConflict
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','X-Robots-Tag':'noindex','Referrer-Policy':'no-referrer'}
ROUTE='/case/{case_id}/kg-entry/applicants/{applicant_id}/applications/{application_id}/work-review'
META=('_wr_action','_wr_revision','_wr_token','_wr_key','_wr_language')
SECURITY=('_wr_csrf','_wr_signature')
TEXT={
 'ru':dict(title='Проверка срока ЕР',back='К заявке',notice='Это внутреннее напоминание проверить расчёт. Дата подачи, право на работу и пребывание требуют отдельного подтверждения.',
    freshness='При изменении данных откройте карточку и выполните сверку. Просмотр сам по себе не изменяет задачу.',
    current='Текущие данные',date='Условная дата',owner='Ответственный',unknown='Не установлено',task='Задача',none='Задача ещё не создана.',history='Сохранённая история',
    stops='Проверки текущего пребывания',expired_stay='Срок пребывания истёк',working_day_margin='Малый запас рабочих дней',visa_free_headroom='Недостаток безвизовых дней',
    triggered='Выявлено — требуется специалист',not_triggered='Не выявлено',within='Условная дата ещё не прошла.',past='Условная дата подачи прошла. Требуется разбор специалиста.',
    refresh='Создать или сверить напоминание',restore='Применить расчёт вместо ручной даты',new_generation='Создать задачу по новому основанию',complete='Отметить проверку выполненной',cancel='Отменить задачу',
    confirm='Подтверждаю действие',retry='Повторить исходный запрос',off='Сохранение отключено. Доступен просмотр.',
    unknown_date='Актуальное основание расчёта не подтверждено.',missing_owner='У услуги не назначен ответственный.',claimed='Задача находится в обработке.',schedule_conflict='Дата изменена вручную. Для замены требуется отдельное подтверждение.',
    planned='Запланирована',rescheduled='Перенесена',completed='Выполнена',cancelled='Отменена',
    changed='Данные изменились. Сверьте текущее состояние.',invalid='Действие недоступно. Проверьте подтверждение и текущее состояние.',
    uncertain='Результат сохранения неизвестен. Повторите исходный запрос без изменений.',unavailable='Не удалось проверить данные. Изменения недоступны.'),
 'en':dict(title='Unified permit date review',back='Back to application',notice='This is an internal reminder to review a calculation. Filing, work and stay permissions require separate confirmation.',
    freshness='When evidence changes, open this page and reconcile the reminder. Viewing the page does not update the task.',
    current='Current evidence',date='Conditional date',owner='Owner',unknown='Not established',task='Task',none='No task has been created.',history='Saved history',
    stops='Current stay checks',expired_stay='Stay period expired',working_day_margin='Small working-day margin',visa_free_headroom='Insufficient visa-free days',
    triggered='Detected — specialist review required',not_triggered='Not detected',within='The conditional date has not passed.',past='The conditional filing date has passed. Specialist review required.',
    refresh='Create or reconcile reminder',restore='Replace manual date with current calculation',new_generation='Create task for new evidence',complete='Mark review completed',cancel='Cancel task',
    confirm='I confirm this action',retry='Retry the original request',off='Saving is disabled. Read only.',
    unknown_date='Current calculation evidence is not confirmed.',missing_owner='The case has no assigned owner.',claimed='The task is being processed.',schedule_conflict='The date was changed manually. Replacing it requires explicit confirmation.',
    planned='Planned',rescheduled='Rescheduled',completed='Completed',cancelled='Cancelled',
    changed='Evidence changed. Review the current state.',invalid='Action unavailable. Check confirmation and current state.',
    uncertain='The save outcome is unknown. Retry the original request unchanged.',unavailable='Evidence could not be verified. Changes are unavailable.')}


def _url(ids,language='ru'):return '/admin'+ROUTE.format(case_id=ids[0],applicant_id=ids[1],application_id=ids[2])+'?language='+language


def _language(request):
    pairs=list(request.query_params.multi_items())
    if not pairs:return 'ru'
    if len(pairs)!=1 or pairs[0][0]!='language' or pairs[0][1] not in TEXT:raise HTTPException(422,headers=HEADERS)
    return pairs[0][1]


def _authority(ids):
    try:return configured(ar.settings,ids[0],ids[1])
    except EntryStorageInvalid:return None


def _signature(request,actor,ids,values):
    token=request.session.setdefault('kg_work_review_csrf',secrets.token_hex(32))
    payload=json.dumps(['kg-work-review-form/1',actor.manager_id,*ids,token,[values[k] for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def _envelope(request,actor,ids,language,current,action):
    values=dict(zip(META,(action,str(current['revision']),current['token'],secrets.token_hex(24),language)))
    values['_wr_signature']=_signature(request,actor,ids,values);values['_wr_csrf']=request.session['kg_work_review_csrf']
    return values


async def _form(request,actor,ids,language):
    if request.headers.get('content-type','').split(';')[0].strip()!='application/x-www-form-urlencoded':raise HTTPException(415,headers=HEADERS)
    raw=bytearray()
    async for chunk in request.stream():
        if len(raw)+len(chunk)>4096:raise HTTPException(413,headers=HEADERS)
        raw.extend(chunk)
    try:
        pairs=parse_qsl(raw.decode('utf-8'),keep_blank_values=True,strict_parsing=True,encoding='utf-8',errors='strict',max_num_fields=9)
        values=dict(pairs)
        if len(pairs)!=len(values) or values.keys()!=set(META+SECURITY+('confirmed',)) or any(len(v)>128 for v in values.values()):raise ValueError
        if (values['_wr_action'] not in service.ACTIONS or values['_wr_language']!=language or
            not re.fullmatch('[a-f0-9]{48}',values['_wr_key']) or not re.fullmatch('[a-f0-9]{64}',values['_wr_token']) or
            str(int(values['_wr_revision']))!=values['_wr_revision'] or not 0<=int(values['_wr_revision'])<=service.MAX_REVISIONS):raise ValueError
        if any(not re.fullmatch('[a-f0-9]{64}',values[k]) for k in SECURITY):raise HTTPException(403,headers=HEADERS)
        if (not hmac.compare_digest(values['_wr_csrf'],request.session.get('kg_work_review_csrf','')) or
            not hmac.compare_digest(values['_wr_signature'],_signature(request,actor,ids,values))):raise HTTPException(403,headers=HEADERS)
        return values
    except (ValueError,UnicodeError):raise HTTPException(422,headers=HEADERS) from None


def _args(actor,ids):return dict(actor=actor,case_id=ids[0],applicant_id=ids[1],application_id=ids[2],authority=_authority(ids))


async def _render(request,manager,actor,ids,language,*,status=200,error=None,retry=None):
    state=None;forms={}
    try:
        state=await service.read(entry._engine(),**_args(actor,ids));c=state['current'];rows=state['history'];task=c['task']
        old=rows[0]['snapshot'] if rows else None
        authority=_authority(ids);operators=authority.review.document['operators'] if authority and c['eligible'] else old['operators'] if old else []
        if _write_on(request) and actor.manager_id in operators and not retry and not(task and task['claimed']):
            actions=[]
            if c['revision']<service.MAX_REVISIONS:
                if not task or task['status'] in service.ACTIVE:
                    if c['eligible'] or rows:actions.append('restore' if c['eligible'] and c['attention']=='schedule_conflict' else 'refresh')
                elif c['eligible'] and c['semantic']!=old['semantic']:actions.append('new_generation')
                if task and task['status'] in service.ACTIVE and c['eligible'] and actor.manager_id in old['operators']:actions.append('complete')
            if task and task['status'] in service.ACTIVE and c['revision']<=service.MAX_REVISIONS and actor.manager_id in old['operators']:actions.append('cancel')
            forms={a:_envelope(request,actor,ids,language,c,a) for a in actions}
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ('application_case_unavailable','application_unavailable','applicant_unavailable','work_review_scope'):raise HTTPException(404,headers=HEADERS) from None
        state=None;forms={};status=503;error='uncertain' if retry else 'unavailable'
    except Exception:state=None;forms={};status=503;error='uncertain' if retry else 'unavailable'
    return ar.templates.TemplateResponse(request,'kg_work_review.html',dict(manager=manager,case={'id':ids[0]},ids=ids,language=language,
        state=state,forms=forms,text=TEXT[language],url=_url(ids,language),alternate=_url(ids,'en' if language=='ru' else 'ru'),
        error=error,retry=retry,write_on=_write_on(request)),status_code=status,headers=HEADERS)


@ar.router.get(ROUTE,response_class=HTMLResponse)
async def work_review_form(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                           application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);ids=(case_id,applicant_id,application_id);language=_language(request)
    return await _render(request,manager,actor,ids,language)


@ar.router.post(ROUTE,response_class=HTMLResponse)
async def work_review_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                             application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);ids=(case_id,applicant_id,application_id);language=_language(request)
    values=await _form(request,actor,ids,language)
    try:
        if values['confirmed']!='yes':raise EntryStorageInvalid('confirmation_required')
        await service.record(entry._engine(),**_args(actor,ids),expected_revision=int(values['_wr_revision']),request_key=values['_wr_key'],
            operation=dict(action=values['_wr_action'],token=values['_wr_token'],confirmed=True))
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:return await _render(request,manager,actor,ids,language,status=409,error='changed')
    except EntryStorageInvalid:return await _render(request,manager,actor,ids,language,status=422,error='invalid')
    except Exception:return await _render(request,manager,actor,ids,language,status=503,error='uncertain',retry=values)
    return RedirectResponse(_url(ids,language),status_code=303,headers=HEADERS)
