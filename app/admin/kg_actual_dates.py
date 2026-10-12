"""Signed no-JS actual-document dates and conditional review commands."""
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
from app.domain import entry_anchors as anchors, entry_anchor_rules as anchor_rules, applicant_profiles as profiles
from app.domain import conditional_deadlines as deadlines, conditional_deadline_rules as rules, conditional_deadline_policy as policies
from app.domain import entry_deadline_tasks as tasks
from app.domain.entry_storage import EntryStorageInvalid, EntryStorageConflict, EntryStorageUnavailable, _plain
from app.domain.service_authz import PermissionDenied

ROUTE='/case/{case_id}/kg-entry/applicants/{applicant_id}/applications/{application_id}/actual-dates'
HEADERS={'Cache-Control':'no-store','X-Robots-Tag':'noindex','Referrer-Policy':'no-referrer'}
TEXT={
 'ru':dict(title='Даты документов и проверок', back='К заявлению', actual='Фактические даты', review='Внутренняя проверка',
    notice='Дата проверки рассчитывается по подтверждённым данным. Решение о подаче, работе или пребывании принимает специалист.',
    freshness='После изменения документов выполните сверку напоминания. Просмотр карточки не изменяет задачу.',
    unknown='Дата не установлена', past='Дата проверки прошла — требуется специалист.', record='Сохранить факт', withdraw='Отозвать факт',
    conditional_review='Сохранить дату проверки', conditional_clear='Отозвать дату проверки', reconcile='Создать или сверить напоминание',
    confirm='Подтверждаю действие', retry='Повторить исходный запрос', off='Сохранение отключено.', invalid='Проверьте поля и актуальные основания.',
    changed='Данные изменились. Обновите карточку.', uncertain='Результат сохранения неизвестен. Повторите исходный запрос без изменений.',
    unavailable='Данные недоступны для проверки.', history='Сохранённые факты', status='Состояние', selected='Правило проверки',
    anchor_key='Обозначение документа или изменения', on='Дата факта / подтверждения', reference='Ссылка на официальный документ',
    proof='SHA-256 подтверждения', valid_from='Начало действия', valid_until='Последний день действия', document_ref='SHA-256 документа',
    passport_ref='SHA-256 паспорта', basis_type='Основание регистрации', tax_status='Сведения о налогах', basis_proof='SHA-256 основания',
    before_ref='SHA-256 прежних сведений', after_ref='SHA-256 новых сведений', event_meaning='Дата кода', reason='Причина отзыва',
    no_authority='Полномочия для записи не настроены.', task='Напоминание', no_task='Напоминание не создано.',
    planned='Запланировано',rescheduled='Перенесено',completed='Выполнено',cancelled='Отменено',
    unknown_date='Текущее основание не подтверждено.',missing_owner='Назначьте ответственного в услуге.',claimed='Задача в обработке.',
    schedule_conflict='Дата задачи изменена вручную. Сначала разберите расхождение.',generation_limit='Достигнут предел истории задач.'),
 'en':dict(title='Document and review dates', back='Back to application',actual='Actual dates',review='Internal review',
    notice='The review date uses confirmed evidence. A specialist separately decides filing, work and stay matters.',
    freshness='Reconcile the reminder after documents change. Viewing this page does not update the task.',
    unknown='Date not established',past='The review date has passed — specialist review required.',record='Record evidence',withdraw='Withdraw evidence',
    conditional_review='Save review date',conditional_clear='Withdraw review date',reconcile='Create or reconcile reminder',
    confirm='I confirm this action',retry='Retry original request',off='Saving is disabled.',invalid='Check fields and current evidence.',
    changed='Evidence changed. Reload this page.',uncertain='The save outcome is unknown. Retry the original request unchanged.',
    unavailable='Evidence cannot be verified.',history='Recorded evidence',status='Status',selected='Review rule',
    anchor_key='Document or change identifier',on='Event / confirmation date',reference='Official document reference',proof='Evidence SHA-256',
    valid_from='Valid from',valid_until='Last valid day',document_ref='Document SHA-256',passport_ref='Passport SHA-256',
    basis_type='Registration basis',tax_status='Tax evidence',basis_proof='Basis SHA-256',before_ref='Previous evidence SHA-256',
    after_ref='New evidence SHA-256',event_meaning='Code date meaning',reason='Withdrawal reason',
    no_authority='Recording authority has not been configured.',task='Reminder',no_task='No reminder yet.',
    planned='Planned',rescheduled='Rescheduled',completed='Completed',cancelled='Cancelled',unknown_date='Current evidence is unconfirmed.',
    missing_owner='Assign a case owner.',claimed='The task is being processed.',schedule_conflict='The task date was changed manually. Review the conflict first.',
    generation_limit='Task history limit reached.')}
KINDS={
 'visa_period':('Срок визы','Visa validity'), 'permit_period':('Срок ЕР','Unified permit validity'),
 'resident_period':('Срок карты резидента','Resident card validity'),'registration_period':('Срок регистрации','Registration validity'),
 'registration_payment_code':('Код оплаты регистрации','Registration payment code'),'address_change':('Изменение адреса','Address change'),
 'passport_change':('Смена паспорта','Passport change'),'purpose_change':('Изменение цели','Purpose change'),
 'employment_ended':('Прекращение трудовых отношений','Employment ended'),'permit_terminated':('Прекращение действия ЕР','Permit terminated')}
KINDS['visa_renewal_context']=('Основания продления или смены визы','Visa renewal or change premises')
for language,labels in {
 'ru':dict(period_anchor_id='Номер записи срока визы',period_anchor_hash='SHA-256 записи срока визы',intent='Действие',current_type='Текущий тип визы',target_type='Запрашиваемый тип визы',current_purpose='Прежняя цель',target_purpose='Новая или сохраняемая цель',current_inviter_ref='SHA-256 сведений о прежней приглашающей стороне',target_inviter_ref='SHA-256 сведений о новой приглашающей стороне',premise_proof='SHA-256 подтверждения оснований'),
 'en':dict(period_anchor_id='Visa period record ID',period_anchor_hash='Visa period record SHA-256',intent='Intent',current_type='Current visa type',target_type='Requested visa type',current_purpose='Previous purpose',target_purpose='Requested purpose',current_inviter_ref='Current inviter identity SHA-256',target_inviter_ref='Requested inviter identity SHA-256',premise_proof='Premise evidence SHA-256')}.items():TEXT[language].update(labels)
RULES={
 'KG.DL.INTERNAL_TS_EXIT_REVIEW':('TS: проверка выезда за 5 календарных дней','TS: exit review 5 calendar days before expiry'),
 'KG.DL.INTERNAL_B_RENEWAL_PREPARATION':('B: подготовка заявленного продления за 15 рабочих дней','B: declared renewal preparation 15 working days before expiry'),
 'KG.DL.INTERNAL_RL_RES_PREPARATION':('RL → карта резидента: подготовка за 15 рабочих дней','RL → resident card: preparation 15 working days before expiry'),
 'KG.DL.INTERNAL_RL_RES_REVIEW':('RL → карта резидента: проверка за 10 рабочих дней','RL → resident card: review 10 working days before expiry'),
 'KG.DL.INTERNAL_S_RES_REVIEW':('S → карта резидента: проверка за 10 рабочих дней','S → resident card: review 10 working days before expiry'),
 'KG.DL.VISA_EXTENSION':('Продление визы: −5 рабочих дней','Visa renewal: −5 working days'),
 'KG.DL.RC_BEFORE_EP_END':('Карта резидента: −10 рабочих дней до окончания ЕР','Resident card: −10 working days before permit expiry'),
 'KG.DL.EP_BEFORE_RC_END':('ЕР: −7 рабочих дней до окончания карты','Permit: −7 working days before card expiry'),
 'KG.DL.REGISTRATION_CODE_PAYMENT':('Оплата кода: +3 рабочих дня','Code payment: +3 working days'),
 'KG.DL.REGISTRATION_EXTENSION':('Последний день регистрации','Last registration day'),
 'KG.DL.REREGISTRATION':('Изменение сведений: +10 рабочих дней','Changed details: +10 working days'),
 'KG.DL.DISMISSAL_NOTIFICATION':('Уведомление об увольнении: +3 дня','Dismissal notice: +3 days'),
 'KG.DL.EXIT_AFTER_EP_END':('Прекращение ЕР: план выезда +30 дней','Permit termination: exit review +30 days'),
 'KG.DL.INTERNAL_DISMISSAL_EXIT_PLAN':('Увольнение: план выезда +30 дней','Dismissal: exit review +30 days'),
 'KG.DL.INTERNAL_RES_PREPARATION':('Подготовка карты: −15 рабочих дней','Card preparation: −15 working days'),
 'KG.DL.INTERNAL_EAEU_REG_REVIEW':('ЕАЭС: −10 рабочих дней до конца 60-дневной регистрации','EAEU: −10 working days before 60-day registration ends'),
 'KG.DL.INTERNAL_ABSENCE_REG_REVIEW':('Возвращение после отсутствия 30+ дней','Return after 30+ days away')}
OPTIONS={
 'basis_type':{'employment':('Трудовой договор','Employment'),'self_employed':('Самозанятость','Self-employed'),'appointment':('Назначение','Appointment'),
    'family':('Семья работника','Worker family'),'visa':('Виза','Visa'),'permit':('ЕР','Permit'),'resident_card':('Карта резидента','Resident card'),'other':('Иное — требуется разбор','Other — review needed')},
 'tax_status':{'pending':('Ожидаются','Pending'),'confirmed':('Подтверждены','Confirmed'),'not_applicable':('Не применимо','Not applicable'),'unknown':('Неизвестно','Unknown')},
 'event_meaning':{'official_code_received_on':('Фактически получен','Actually received'),'official_code_issued_on':('Официально сформирован','Officially issued')},
 'reason':{'wrong_document':('Неверный документ','Wrong document'),'superseded':('Заменён','Superseded'),'no_longer_confirmed':('Больше не подтверждено','No longer confirmed')}}
OPTIONS['intent']={'same_product_renewal':('Продление с прежней целью и типом','Same purpose and product renewal'),'change_status':('Смена цели или типа','Change of purpose or product')}
from app.knowledge.qualification_schema import REQUEST_SCHEMA
OPTIONS['current_type']=OPTIONS['target_type']={v:(v,v) for v in REQUEST_SCHEMA['$defs']['visa_type']['enum']}
OPTIONS['current_purpose']=OPTIONS['target_purpose']={k:(ru,en) for k,ru,en in (
 ('tourism','Туризм','Tourism'),('private_visit','Частный визит','Private visit'),('relatives_kg_citizen','Родственники гражданина КР','Relatives of a Kyrgyz citizen'),
 ('family_of_foreigner','Семья иностранца','Foreigner family'),('business_meeting','Деловая встреча','Business meeting'),('event','Мероприятие','Event'),
 ('sport','Спорт','Sport'),('medical','Лечение','Medical treatment'),('study','Учёба','Study'),('work_hire','Работа по найму','Employment'),
 ('work_individual_employer','Работа у физлица','Individual employer'),('entrepreneur','Предпринимательство','Entrepreneurship'),('investor','Инвестиции','Investment'),
 ('it_remote','Удалённая работа в ИТ','Remote IT work'),('journalism','Журналистика','Journalism'),('volunteer','Волонтёрство','Volunteering'),
 ('equipment_installation','Монтаж оборудования','Equipment installation'),('transit','Транзит','Transit'),('religious','Религиозная деятельность','Religious activity'),
 ('driver','Водитель','Driver'),('accompanying_gcc','Сопровождение гражданина ССАГПЗ','Accompanying a GCC citizen'),('official','Официальный визит','Official visit'))}
META=('action','kind','anchor_key','revision','profile_id','profile_hash','event_id','evidence_hash','key','rule','language')


def query(request):
    pairs=list(request.query_params.multi_items()); values=dict(pairs)
    if len(values)!=len(pairs) or set(values)-{'language','rule'} or values.get('language','ru') not in TEXT or values.get('rule','KG.DL.REGISTRATION_EXTENSION') not in RULES:
        raise HTTPException(422,headers=HEADERS)
    return values.get('language','ru'),values.get('rule','KG.DL.REGISTRATION_EXTENSION')


def url(ids,language,rule): return '/admin'+ROUTE.format(case_id=ids[0],applicant_id=ids[1],application_id=ids[2])+'?'+urlencode(dict(language=language,rule=rule))


def signature(request,actor,ids,values):
    csrf=request.session.setdefault('kg_actual_dates_csrf',secrets.token_hex(32))
    payload=json.dumps(['kg-actual-dates/1',actor.manager_id,*ids,csrf,[values[k] for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),payload,hashlib.sha256).hexdigest()


def envelope(request,actor,ids,language,rule,action,**values):
    data={k:'' for k in META};data.update(action=action,key=secrets.token_hex(24),language=language,rule=rule)
    data.update({k:str(v) for k,v in values.items()});data['signature']=signature(request,actor,ids,data)
    data['csrf']=request.session['kg_actual_dates_csrf'];return data


def fields(kind,action):
    if action=='withdraw': return ('on','reason','proof')
    result=('on','reference','proof')
    if kind in anchor_rules.PERIODS: result+=('valid_from','valid_until','document_ref','passport_ref')
    if kind=='registration_period': result+=('basis_type','tax_status','basis_proof')
    if kind in anchor_rules.CHANGES: result+=('before_ref','after_ref')
    if kind=='registration_payment_code': result+=('event_meaning',)
    if kind=='visa_renewal_context':result+=('period_anchor_id','period_anchor_hash','intent','current_type','target_type','current_purpose','target_purpose','current_inviter_ref','target_inviter_ref','premise_proof')
    return result


async def render(request,manager,actor,ids,language,rule,*,status=200,error=None,retry=None):
    state=None;forms=[];review=None;review_forms=[];task=None
    try:
        policy=anchor_rules.configured(ar.settings);authority=policies.configured(ar.settings,rule)
        async def read(session):
            case,person,application=await anchors.scope(session,*ids)
            current=await anchors.current(session,case,person,application,policy=policy)
            profiles_rows=(await profiles._history(session,case,person))[0];events=await anchors.apps._events(session,application)
            return current,application.procedure,profiles_rows[-1] if profiles_rows else None,events[-1]
        state,procedure,profile,event=await anchors.apps._run(entry._engine(),read)
        if _write_on(request) and not retry:
            if policy and actor.manager_id in policy.document['operators'] and profile and state['revision']<anchor_rules.MAX_REVISIONS:
                for kind in policy.document['kinds']:
                    if anchor_rules.KINDS[kind]!=procedure:continue
                    forms.append(dict(kind=kind,title=KINDS[kind][language=='en'],action='record',fields=fields(kind,'record'),
                        data=envelope(request,actor,ids,language,rule,'record',kind=kind,revision=state['revision'],
                            profile_id=profile.id,profile_hash=profile.snapshot_hash,event_id=event.id)))
            for item in state['observations']:
                receipt=item['receipt']
                if receipt['operation']['action']=='record' and actor.manager_id in receipt['snapshot']['operators']:
                    forms.append(dict(kind=receipt['kind'],title=KINDS[receipt['kind']][language=='en']+' · '+receipt['anchor_key'],action='withdraw',fields=fields(receipt['kind'],'withdraw'),
                        data=envelope(request,actor,ids,language,rule,'withdraw',kind=receipt['kind'],anchor_key=receipt['anchor_key'],revision=state['revision'])))
        args=dict(actor=actor,case_id=ids[0],applicant_id=ids[1],application_id=ids[2],rule_unit_id=rule,authority=authority)
        review=await deadlines.preview(entry._engine(),**args)
        if review['selected']:
            task=await tasks.read_deadline_task(entry._engine(),actor=actor,case_id=ids[0],application_id=ids[2],rule_unit_id=rule)
        if _write_on(request) and not retry:
            if review['report']['review_due_on'] and authority and actor.manager_id in authority.policy.document['operators']:
                review_forms.append(envelope(request,actor,ids,language,rule,'conditional_review',revision=review['revision'],evidence_hash=review['report']['evidence_hash']))
            saved=review['selected']
            if saved and not saved['snapshot']['cleared'] and actor.manager_id in saved['snapshot']['authority']['policy']['operators']:
                review_forms.append(envelope(request,actor,ids,language,rule,'conditional_clear',revision=review['revision'],evidence_hash=saved['snapshot_hash']))
            if saved and authority and actor.manager_id in authority.policy.document['operators']:
                review_forms.append(envelope(request,actor,ids,language,rule,'reconcile',revision=review['revision']))
    except PermissionDenied: raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in ('application_case_unavailable','application_unavailable','applicant_unavailable','actual_anchor_subject_mismatch'):
            raise HTTPException(404,headers=HEADERS) from None
        state=None;forms=[];review=None;review_forms=[];status=503;error='uncertain' if retry else 'unavailable'
    except Exception: state=None;forms=[];review=None;review_forms=[];status=503;error='uncertain' if retry else 'unavailable'
    return ar.templates.TemplateResponse(request,'kg_actual_dates.html',dict(manager=manager,case={'id':ids[0]},ids=ids,language=language,rule=rule,
        text=TEXT[language],kinds=KINDS,rules=RULES,options=OPTIONS,url=url(ids,language,rule),alternate=url(ids,'en' if language=='ru' else 'ru',rule),
        state=state,forms=forms,review=review,review_forms=review_forms,task=task,error=error,retry=retry,write_on=_write_on(request)),status_code=status,headers=HEADERS)


async def form(request,actor,ids,language,rule):
    if request.headers.get('content-type','').split(';')[0].strip()!='application/x-www-form-urlencoded':raise HTTPException(415,headers=HEADERS)
    raw=bytearray()
    async for chunk in request.stream():
        if len(raw)+len(chunk)>16384:raise HTTPException(413,headers=HEADERS)
        raw.extend(chunk)
    try:
        pairs=parse_qsl(raw.decode('utf-8'),keep_blank_values=True,strict_parsing=True,encoding='utf-8',errors='strict',max_num_fields=30)
        values=dict(pairs)
        if len(values)!=len(pairs) or any(k not in values for k in (*META,'signature','csrf','confirmed')) or any(len(v)>128 for v in values.values()):raise ValueError
        if values['language']!=language or values['rule']!=rule:raise ValueError
        if any(not re.fullmatch('[a-f0-9]{64}',values[key]) for key in ('csrf','signature')):
            raise HTTPException(403,headers=HEADERS)
        if not hmac.compare_digest(values['csrf'],request.session.get('kg_actual_dates_csrf','')) or not hmac.compare_digest(values['signature'],signature(request,actor,ids,values)):
            raise HTTPException(403,headers=HEADERS)
        action=values['action'];allowed=set((*META,'signature','csrf','confirmed'))
        if action in ('record','withdraw'):
            if values['kind'] not in KINDS:raise ValueError
            allowed.update(fields(values['kind'],action))
            if action=='record':allowed.add('record_key')
        elif action not in ('conditional_review','conditional_clear','reconcile'):raise ValueError
        if values.keys()!=allowed or values['confirmed']!='yes':raise ValueError
        return values
    except (ValueError,UnicodeError):raise HTTPException(422,headers=HEADERS) from None


@ar.router.get(ROUTE,response_class=HTMLResponse)
async def actual_dates_form(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                            application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);ids=(case_id,applicant_id,application_id);language,rule=query(request)
    return await render(request,manager,actor,ids,language,rule)


@ar.router.post(ROUTE,response_class=HTMLResponse)
async def actual_dates_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),
                              application_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);ids=(case_id,applicant_id,application_id);language,rule=query(request)
    values=await form(request,actor,ids,language,rule);action=values['action']
    try:
        args=dict(actor=actor,case_id=case_id,applicant_id=applicant_id,application_id=application_id)
        if action in ('record','withdraw'):
            kind=values['kind'];data={k:values[k] for k in fields(kind,action)}
            if action=='record':
                value={k:data.pop(k) for k in fields(kind,action) if k not in ('on','reference','proof')}
                if kind=='visa_renewal_context':value['period_anchor_id']=int(value['period_anchor_id'])
                data.update(profile_id=int(values['profile_id']),profile_hash=values['profile_hash'],application_event_id=int(values['event_id']),source='official_document',value=value)
            await anchors.record(entry._engine(),**args,kind=kind,anchor_key=values['record_key'] if action=='record' else values['anchor_key'],
                expected_revision=int(values['revision']),request_key=values['key'],operation=dict(action=action,data=data,confirmed=True),policy=anchor_rules.configured(ar.settings))
        elif action=='reconcile':
            await tasks.reconcile_deadline_task(entry._engine(),actor=actor,case_id=case_id,application_id=application_id,rule_unit_id=rule,enable=True,minimum_revision=int(values['revision']))
        else:
            await deadlines.record(entry._engine(),**args,rule_unit_id=rule,expected_revision=int(values['revision']),request_key=values['key'],
                operation=dict(action=action,confirmed=True,evidence_hash=values['evidence_hash']),authority=policies.configured(ar.settings,rule))
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageConflict:return await render(request,manager,actor,ids,language,rule,status=409,error='changed')
    except EntryStorageUnavailable:return await render(request,manager,actor,ids,language,rule,status=503,error='uncertain',retry=values)
    except (EntryStorageInvalid,ValueError):return await render(request,manager,actor,ids,language,rule,status=422,error='invalid')
    except Exception:return await render(request,manager,actor,ids,language,rule,status=503,error='uncertain',retry=values)
    return RedirectResponse(url(ids,language,rule),status_code=303,headers=HEADERS)
