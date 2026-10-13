"""Signed native forms for source-scoped, manually selected review tasks."""
from datetime import datetime
import hashlib
import hmac
import json
import re
import secrets
from urllib.parse import parse_qsl, urlencode

from fastapi import Depends, HTTPException, Path, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.domain import operator_sop_reviews as service, operator_sop_rules as rules, operator_sop_policy as policies
from app.domain import entry_deadline_tasks as tasks, entry_deadlines
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict, EntryStorageUnavailable, _hash
from app.domain.service_authz import PermissionDenied

ROUTE='/case/{case_id}/kg-entry/applicants/{applicant_id}/applications/{application_id}/sop-reviews'
HEADERS={'Cache-Control':'no-store','X-Robots-Tag':'noindex','Referrer-Policy':'no-referrer'}
TEXT={
 'ru':dict(title='Проверки по этапам',back='К заявлению',notice='Выберите дату внутренней проверки. Это задача менеджера; официальный срок документа хранится отдельно.',
    freshness='После изменения данных выполните сверку задачи. Смена этапа отменяет доступную задачу; принятую в работу или изменённую вручную задачу нужно разобрать отдельно.',
    duty='Что проверить',choose='Показать',stage='Текущий этап',source='Пункт PDF',schedule='Выбранное время',on='Дата',time='Время в Бишкеке · необязательно',
    reason='Причина',source_followup='Следующая проверка по процессу',verify_missing_facts='Получить недостающие сведения',review_changed_facts='Проверить изменившиеся сведения',
    reference='Номер подтверждения',proof='SHA-256 подтверждения выбора',confirmed='Подтверждаю выбор времени внутренней проверки',
    operator_review='Сохранить проверку',operator_review_clear='Отозвать проверку',reconcile='Создать или сверить задачу',
    unavailable='Данные проверки недоступны. Обновите страницу.',unknown='Для этого этапа проверка сейчас недоступна.',
    changed='Данные изменились. Обновите страницу и проверьте выбор.',invalid='Проверьте дату, время и подтверждение.',
    uncertain='Результат сохранения не подтверждён. Повторите ту же команду.',retry='Повторить команду',
    task='Задача',no_task='Задача ещё не создана.',owner='Ответственный',current='Актуальность',history='Последняя сохранённая проверка',
    current_operator_review='Актуальна',unknown_status='Требует сверки',cleared='Отозвана',superseded='Заменена',
    planned='Запланирована',rescheduled='Перенесена',completed='Выполнена',cancelled='Отменена',
    unknown_date='Текущие основания не подтверждены.',missing_owner='Назначьте ответственного по делу.',claimed='Задача принята в работу.',
    schedule_conflict='Время задачи изменено вручную.',generation_limit='Достигнут предел истории задач.',date_only='Без точного времени'),
 'en':dict(title='Stage reviews',back='Back to application',notice='Choose an internal review date. This is a manager task; an official document deadline is recorded separately.',
    freshness='Reconcile the task after evidence changes. A stage change cancels an eligible task; claimed or manually edited tasks need separate attention.',
    duty='Review purpose',choose='Show',stage='Current stage',source='PDF clause',schedule='Selected time',on='Date',time='Bishkek time · optional',
    reason='Reason',source_followup='Next process review',verify_missing_facts='Obtain missing facts',review_changed_facts='Review changed facts',
    reference='Selection evidence reference',proof='Selection evidence SHA-256',confirmed='I confirm the selected internal review time',
    operator_review='Save review',operator_review_clear='Withdraw review',reconcile='Create or reconcile task',
    unavailable='Review data is unavailable. Reload the page.',unknown='This review is currently unavailable for this stage.',
    changed='The evidence changed. Reload and check the selection.',invalid='Check the date, time and evidence.',
    uncertain='The save result is uncertain. Retry the same command.',retry='Retry command',task='Task',no_task='No task yet.',owner='Owner',current='Current relevance',history='Last saved review',
    current_operator_review='Current',unknown_status='Needs reconciliation',cleared='Withdrawn',superseded='Superseded',
    planned='Planned',rescheduled='Rescheduled',completed='Completed',cancelled='Cancelled',unknown_date='Current evidence is unconfirmed.',
    missing_owner='Assign a case owner.',claimed='The task is being processed.',schedule_conflict='The task time was changed manually.',
    generation_limit='Task history limit reached.',date_only='No exact time')}
META=('action','revision','evidence_hash','key','rule','language')
TEXT['ru'].update(case_label='Дело',person_label='Заявитель',application_label='Корневое заявление',active_label='Заявление текущего этапа',
    confirm_clear='Подтверждаю отзыв этой проверки',confirm_reconcile='Подтверждаю сверку задачи с текущими данными',
    unknown='Проверка сейчас недоступна. Сверьте основания и доступ.',
    authority_missing='Проверка не настроена для вашего доступа.',authority_changed='Разрешение на проверку изменилось или истекло.',
    stage_unavailable='Этот вид проверки не относится к текущему этапу.',collection_blocked='Сбор данных остановлен или согласие отозвано.',
    wait_satisfied='Ожидаемое действие уже выполнено. Сверьте задачу.',evidence_changed='Исходные сведения изменились. Сверьте задачу.')
TEXT['en'].update(case_label='Case',person_label='Applicant',application_label='Root application',active_label='Current stage application',
    confirm_clear='I confirm withdrawal of this review',confirm_reconcile='I confirm task reconciliation with current evidence',
    unknown='This review is unavailable. Check the evidence and access.',
    authority_missing='This review has not been configured for your access.',authority_changed='Review authority changed or expired.',
    stage_unavailable='This review does not apply to the current stage.',collection_blocked='Data collection is stopped or consent was withdrawn.',
    wait_satisfied='The awaited action is complete. Reconcile the task.',evidence_changed='Source evidence changed. Reconcile the task.')


def reason_text(code,language):
    keys={'operator_sop_authority_missing':'authority_missing','operator_sop_operator_unavailable':'authority_missing',
        'operator_sop_authority_expired':'authority_changed','operator_sop_authority_changed':'authority_changed','operator_sop_authority_unavailable':'authority_missing',
        'operator_sop_process_authority_expired':'authority_changed',
        'operator_sop_stage_unavailable':'stage_unavailable','operator_sop_collection_blocked':'collection_blocked',
        'conditional_deadline_collection_or_dialogue_blocked':'collection_blocked','operator_sop_wait_satisfied':'wait_satisfied',
        'operator_sop_evidence_changed':'evidence_changed','operator_sop_process_prerequisites_changed':'evidence_changed'}
    return TEXT[language][keys.get(code,'unknown')]


def current_authority(rule):
    try:return policies.configured(ar.settings,rule),False
    except (EntryStorageInvalid,EntryStorageUnavailable,TypeError,ValueError):return None,True


def query(request):
    pairs=list(request.query_params.multi_items());values=dict(pairs)
    if len(values)!=len(pairs) or set(values)-{'language','rule'} or values.get('language','ru') not in TEXT:
        raise HTTPException(422,headers=HEADERS)
    rule=values.get('rule',rules.PREFIX+'LEAD_RESPONSE')
    try:rules.definition(rule)
    except EntryStorageInvalid:raise HTTPException(422,headers=HEADERS) from None
    return values.get('language','ru'),rule


def url(ids,language,rule):
    return '/admin'+ROUTE.format(case_id=ids[0],applicant_id=ids[1],application_id=ids[2])+'?'+urlencode(dict(language=language,rule=rule))


def signature(request,actor,ids,values):
    csrf=request.session.setdefault('kg_sop_review_csrf',secrets.token_hex(32))
    payload=json.dumps(['kg-sop-review/1',actor.manager_id,*ids,csrf,[values[k] for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def envelope(request,actor,ids,language,rule,action,revision,evidence_hash=''):
    value=dict(action=action,revision=str(revision),evidence_hash=evidence_hash,key=secrets.token_hex(24),rule=rule,language=language)
    value['signature']=signature(request,actor,ids,value);value['csrf']=request.session['kg_sop_review_csrf']
    return value


async def render(request,manager,actor,ids,language,rule,*,status=200,error=None,retry=None):
    review=None;task=None;current=None;forms=[]
    try:
        authority,authority_unavailable=current_authority(rule)
        review=await service.preview(entry._engine(),actor=actor,case_id=ids[0],applicant_id=ids[1],application_id=ids[2],rule_unit_id=rule,authority=authority)
        saved=review['selected'];available=review['report']['status']=='available'
        if saved:
            ta=dict(actor=actor,case_id=ids[0],application_id=ids[2],rule_unit_id=rule)
            task=await tasks.read_deadline_task(entry._engine(),**ta)
            current=(await entry_deadlines.read_deadline_history(entry._engine(),**ta))['operator_current']
        if _write_on(request) and not retry:
            if available and authority and actor.manager_id in authority.policy.document['operators']:
                forms.append(envelope(request,actor,ids,language,rule,'operator_review',review['revision'],review['report']['evidence_hash']))
            if saved and actor.manager_id in saved['snapshot']['authority']['policy']['operators']:
                if not saved['snapshot']['cleared']:
                    forms.append(envelope(request,actor,ids,language,rule,'operator_review_clear',review['revision'],saved['snapshot_hash']))
                forms.append(envelope(request,actor,ids,language,rule,'reconcile',review['revision']))
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ('application_case_unavailable','application_unavailable','applicant_unavailable','operator_sop_subject_mismatch'):
            raise HTTPException(404,headers=HEADERS) from None
        review=None;task=None;forms=[];status=503;error='uncertain' if retry else 'unavailable'
    except Exception:
        review=None;task=None;forms=[];status=503;error='uncertain' if retry else 'unavailable'
    return ar.templates.TemplateResponse(request,'kg_sop_reviews.html',dict(manager=manager,case={'id':ids[0]},ids=ids,language=language,rule=rule,
        text=TEXT[language],duties={rules.PREFIX+k:rules.definition(rules.PREFIX+k) for k in rules.DUTIES},
        url=url(ids,language,rule),alternate=url(ids,'en' if language=='ru' else 'ru',rule),review=review,task=task,current=current,
        task_local_time=datetime.fromisoformat(task['current']['task']['at']).astimezone(rules.BISHKEK).strftime('%H:%M') if task and task['current']['task'] and task['current']['task']['at'] else None,
        unavailable_reason=reason_text(review['report']['reason'],language) if review else None,
        current_reason=reason_text(current['reason'],language) if current else None,
        forms=forms,error=error,retry=retry),status_code=status,headers=HEADERS)


async def form(request,actor,ids,language,rule):
    if request.headers.get('content-type','').split(';')[0].strip()!='application/x-www-form-urlencoded':raise HTTPException(415,headers=HEADERS)
    raw=bytearray()
    async for chunk in request.stream():
        if len(raw)+len(chunk)>8192:raise HTTPException(413,headers=HEADERS)
        raw.extend(chunk)
    try:
        pairs=parse_qsl(raw.decode('utf-8'),keep_blank_values=True,strict_parsing=True,encoding='utf-8',errors='strict',max_num_fields=20)
        values=dict(pairs);required=set((*META,'signature','csrf','confirmed'))
        if len(values)!=len(pairs) or not required<=values.keys() or any(len(v)>128 for v in values.values()):raise ValueError
        if values['language']!=language or values['rule']!=rule:raise ValueError
        if any(not re.fullmatch('[a-f0-9]{64}',values[k]) for k in ('csrf','signature')):raise HTTPException(403,headers=HEADERS)
        if not hmac.compare_digest(values['csrf'],request.session.get('kg_sop_review_csrf','')) or not hmac.compare_digest(values['signature'],signature(request,actor,ids,values)):
            raise HTTPException(403,headers=HEADERS)
        if values['action']=='operator_review':required.update(('on','time','reason'))
        elif values['action'] not in ('operator_review_clear','reconcile'):raise ValueError
        if values.keys()!=required or values['confirmed']!='yes':raise ValueError
        return values
    except (ValueError,UnicodeError):raise HTTPException(422,headers=HEADERS) from None


@ar.router.get(ROUTE,response_class=HTMLResponse)
async def sop_reviews_form(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                            application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);ids=(case_id,applicant_id,application_id);language,rule=query(request)
    return await render(request,manager,actor,ids,language,rule)


@ar.router.post(ROUTE,response_class=HTMLResponse)
async def sop_reviews_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                              application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);ids=(case_id,applicant_id,application_id);language,rule=query(request)
    values=await form(request,actor,ids,language,rule);action=values['action']
    authority_unavailable=False
    try:
        authority,authority_unavailable=current_authority(rule)
        if action=='reconcile':
            await tasks.reconcile_deadline_task(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,
                rule_unit_id=rule,enable=authority is not None,minimum_revision=int(values['revision']))
        else:
            operation=dict(action=action,confirmed=True,evidence_hash=values['evidence_hash'])
            if action=='operator_review':
                operation['schedule']={k:values[k] for k in ('on','time','reason')}
                operation['schedule']['time']=values['time'] or None
                # Evidence of this operator's selected schedule, not an external
                # document proof. Exact retries derive the same reference/hash.
                operation['schedule'].update(reference='OPERATOR-'+values['key'].upper(),
                    proof=_hash(dict(format='operator-confirmed-selection/1',actor=actor.manager_id,
                        case_id=case_id,applicant_id=applicant_id,application_id=application_id,
                        rule=rule,key=values['key'],evidence_hash=values['evidence_hash'],
                        selected=dict(operation['schedule']))))
            await service.record(entry._engine(),actor=actor,case_id=case_id,applicant_id=applicant_id,application_id=application_id,
                rule_unit_id=rule,authority=authority,expected_revision=int(values['revision']),request_key=values['key'],operation=operation)
    except PermissionDenied:
        if authority_unavailable:return await render(request,manager,actor,ids,language,rule,status=503,error='unavailable',retry=values)
        raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:return await render(request,manager,actor,ids,language,rule,status=409,error='changed')
    except EntryStorageUnavailable:return await render(request,manager,actor,ids,language,rule,status=503,error='uncertain',retry=values)
    except (EntryStorageInvalid,ValueError):return await render(request,manager,actor,ids,language,rule,status=422,error='invalid')
    except Exception:return await render(request,manager,actor,ids,language,rule,status=503,error='uncertain',retry=values)
    return RedirectResponse(url(ids,language,rule),status_code=303,headers=HEADERS)
