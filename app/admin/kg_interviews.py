"""Native typed interview and acknowledged review; no channel sending."""
import hashlib
import hmac
import json
import secrets
from urllib.parse import parse_qsl
from pathlib import Path as FilePath

from fastapi import Depends,HTTPException,Path,Request
from fastapi.responses import HTMLResponse,RedirectResponse

import app.admin.router as ar
import app.admin.kg_entry as entry
from app.admin.workday import _write_on
from app.domain import entry_interviews as service
from app.domain.entry_interview_policy import policy_from_document,authorize,existing_full_admins
from app.domain.entry_storage import EntryStorageConflict,EntryStorageInvalid,EntryStorageUnavailable
from app.domain.service_authz import PermissionDenied

HEADERS={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'}
META=('_iv_action','_iv_target','_iv_revision','_iv_key','_iv_policy','_iv_paths','_iv_card','_iv_catalog')
SECURITY={'_iv_csrf','_iv_signature'}
SIMPLE={'start':{'owner','language','profile_id'},'language':{'language'},'pause':set(),'resume':set(),
        'refresh':set(),'interrupt':{'reason'},'handoff':set(),'ack':{'confirmed'},'remove':{'confirmed'}}
PHASES={'active':'Анкета открыта','paused':'Анкета на паузе','pending':'Ожидает принятия специалистом','acked':'Принято специалистом'}
INTERRUPTS={'manager_requested':'Нужен сотрудник','complaint':'Жалоба','refund':'Возврат оплаты',
    'legal_question':'Юридический вопрос','unsafe_request':'Небезопасный запрос','criminal_mention':'Упоминание уголовного вопроса: без подробностей',
    'conflicting_answers':'Противоречивые сведения','special_process':'Нужна специальная процедура',
    'calendar_needed':'Нужна проверка сроков','uncertain_answer':'Ответ требует проверки','consent_withdrawn':'Согласие отозвано'}
REASONS={'interview_revision_changed':'Анкета изменилась. Проверьте текущую версию.',
    'interview_questions_changed':'Набор вопросов изменился. Откройте анкету заново.',
    'interview_policy_changed':'Условия работы изменились. Новые ответы недоступны.',
    'interview_history_limit':'Достигнут предел сбора. Передайте карточку специалисту.',
    'consent_required':'Для этого поля необходимо подтверждённое согласие заявителя.',
    'interview_collection_blocked':'Сбор прекращён из-за отсутствия или отзыва согласия.',
    'interview_refresh_required':'Обстоятельства требуют повторной проверки даты. Обновите оценку анкеты.',
    'field_not_applicable':'Это поле не относится к текущим обстоятельствам.',
    'unproven_not_applicable':'Нельзя исключить поле, пока его условие не установлено.'}
UNAVAILABLE={'application_case_unavailable','applicant_unavailable','interview_unavailable','interview_profile_unavailable'}
COUNTRY_NAMES=json.loads((FilePath(__file__).resolve().parents[2]/'knowledge/kg_entry/source_v1_1/iso3166.json').read_text(encoding='utf-8'))
CHOICE_LABELS={
    'ru':'Русский','en':'English','applicant':'Заявитель','representative':'Представитель','individual':'Один заявитель',
    'family':'Семья','group':'Группа','company':'Компания','ordinary':'Обычный паспорт','diplomatic':'Дипломатический паспорт',
    'service':'Служебный паспорт','un_lp':'Пропуск ООН','stateless':'Документ лица без гражданства','refugee':'Документ беженца',
    'id_card':'ID-карта','internal':'Внутренний паспорт','other':'Другое','unrecognized':'Неизвестный тип',
    'abroad':'За пределами Кыргызстана','in_kg':'В Кыргызстане','tourism':'Туризм','private_visit':'Частный визит',
    'relatives_kg_citizen':'Родственники гражданина Кыргызстана','family_of_foreigner':'Семья иностранца',
    'business_meeting':'Деловые встречи','event':'Мероприятие','sport':'Спорт','medical':'Лечение','study':'Учёба',
    'work_hire':'Работа по найму','work_individual_employer':'Работа у индивидуального работодателя','entrepreneur':'Предпринимательство',
    'investor':'Инвестиции','it_remote':'IT / удалённая работа','journalism':'Журналистика','volunteer':'Волонтёрство',
    'equipment_installation':'Монтаж оборудования','transit':'Транзит','religious':'Религиозная деятельность','driver':'Водитель',
    'accompanying_gcc':'Сопровождение граждан стран Залива','official':'Официальная поездка','visa_free':'Безвизовый режим',
    'visa':'Виза','ep':'Единое разрешение','resident_card':'Резидент-карта','residence_permit':'ВНЖ','none':'Нет',
    'university':'Учебное заведение','clinic':'Клиника','relative':'Родственник','government':'Государственный орган',
    'employment':'Работа по найму','individual_business':'ИП','spouse':'Супруг(а)','child':'Ребёнок','parent':'Родитель',
    'citizen':'Гражданин Кыргызстана','self':'Сам заявитель','cash':'Наличные','card':'Карта','bank_transfer':'Банковский перевод',
    'hotel':'Отель','transfer':'Трансфер','tour':'Тур','tickets':'Билеты','insurance':'Страхование','registration':'Регистрация'}
GAP_LABELS={'missing':'нет ответа','unknown':'заявитель не знает','applicability_unknown':'сначала нужно уточнить условие',
    'stale':'нужно повторное подтверждение','invalid_not_applicable':'применимость требует проверки',
    'not_applicable':'не относится','answered':'ответ записан'}
CARD_REASONS=INTERRUPTS|{'manual_review_requested':'Сбор завершён для ручной проверки','incomplete_answers':'Остались пробелы в ответах',
    'intake_complete':'Применимые вопросы заполнены; требуется вывод специалиста','pinned_profile_requires_review':'Закреплённая квалификация требует проверки',
    'consent_not_granted':'Согласие на обработку данных не дано','special_document':'Особый тип документа',
    'work_specialist':'Рабочая цель требует специалиста','group_or_company':'Группа или компания требует специалиста',
    'current_basis_missing':'Не указано действующее основание пребывания','minor_without_both_parents':'Ребёнок едет без обоих родителей',
    'minor_applicant_without_both_parents':'Несовершеннолетний заявитель едет без обоих родителей',
    'passport_expiry_passed':'Срок паспорта истёк','current_until_passed':'Указанный срок пребывания истёк',
    'registration.until_passed':'Указанный срок регистрации истёк','hard_deadline.on_passed':'Жёсткая дата результата уже прошла',
    'reported_risk.overstay':'Сообщено о просрочке','reported_risk.fines':'Сообщено о штрафах',
    'reported_risk.deportation':'Сообщено о выдворении или депортации','reported_risk.entry_ban':'Сообщено о запрете въезда',
    'reported_previous_refusal':'Сообщено о прежнем отказе в визе','reported_residence_petition':'Подано ходатайство о ВНЖ или гражданстве'}
ACTION_LABELS={'start':'Начало анкеты','answer':'Ответы на вопросы','correct':'Явное исправление','remove':'Снятие текущего ответа',
    'language':'Смена языка','pause':'Пауза','resume':'Продолжение','interrupt':'Прерывание и передача','handoff':'Передача на проверку',
    'ack':'Принятие карточки','refresh':'Проверка текущих обстоятельств'}


def _url(case_id,applicant_id):return f'/admin/case/{case_id}/kg-entry/applicants/{applicant_id}/interview'


def _policy():
    try:return policy_from_document(ar.settings.kg_interview_policy) if ar.settings.kg_interview_policy else None
    except EntryStorageInvalid:return None


def _csrf(request):
    request.session.setdefault('kg_interview_csrf',secrets.token_hex(32))
    return request.session['kg_interview_csrf']


def _signature(request,actor,case_id,applicant_id,values):
    body=json.dumps(['kg-interview-form/1',actor.manager_id,case_id,applicant_id,_csrf(request),
        [values.get(k,'') for k in META]],separators=(',',':')).encode()
    return hmac.new(ar.settings.session_secret.encode(),body,hashlib.sha256).hexdigest()


def _envelope(request,actor,case_id,applicant_id,action,policy,current=None,paths=()):
    operational=action in service.OPERATIONAL
    values=dict(zip(META,(action,str(current['interview']['id'] if current else 0),str(current['revision'] if current else 0),
        secrets.token_hex(24),'' if operational else policy.digest if policy else '',json.dumps(list(paths),separators=(',',':')),
        current['state']['handoff']['hash'] if current and action=='ack' else '',
        current['interview']['catalog_hash'] if current else policy.catalog_hash if policy else '')))
    return values|{'_iv_csrf':_csrf(request),'_iv_signature':_signature(request,actor,case_id,applicant_id,values)}


def _typed_fields(paths,catalog_document=None):
    # Catalog templates resolve only canonical stable ordinal paths; applicability is recomputed by the domain.
    result=[]
    for path in paths:
        template=service.rules.template_path(path)
        source=service.catalog.document() if catalog_document is None else catalog_document
        base=next((f for f in source['fields'] if f['path']==template),None)
        if not base:raise ValueError
        item=dict(base);item['path']=path
        if '{i}' in template:
            index=path.split('.')[1]
            if not index.isdigit() or not 1<=int(index)<=100 or str(int(index))!=index:raise ValueError
            for key in ('ru','en'):item[key]=item[key].replace('{i}',index)
        result.append(item)
    return result


def _field_names(fields):
    names=set()
    for i,f in enumerate(fields):
        names.add(f'm{i}')
        if f['kind']=='countries':names.update(f'v{i}_{j}' for j in range(5))
        elif f['kind']=='choices':names.update(f'v{i}_{j}' for j in range(len(f['choices'])))
        else:names.add(f'v{i}')
    return names


def _changes(values,paths):
    changes={}
    for i,f in enumerate(_typed_fields(paths,service.catalog.by_digest(values['_iv_catalog']))):
        mode=values.get(f'm{i}');kind=f['kind']
        # Each widget has its own exact, bounded set; blank controls are not answers.
        keys=[f'v{i}_{j}' for j in range(5 if kind=='countries' else len(f['choices']))] if kind in ('countries','choices') else [f'v{i}']
        raw=[values.get(k,'') for k in keys]
        if mode in ('unknown','not_applicable'):
            if any(raw):raise ValueError
            value=mode
        elif mode=='value':
            if kind=='countries':value=[v for v in raw if v]
            elif kind=='choices':
                if any(v not in ('','yes') for v in raw):raise ValueError
                value=[option for option,v in zip(f['choices'],raw) if v=='yes']
            elif kind=='boolean':
                if raw[0] not in ('true','false'):raise ValueError
                value=raw[0]=='true'
            elif kind=='integer':
                value=int(raw[0])
                if str(value)!=raw[0]:raise ValueError
            else:value=raw[0]
        else:raise ValueError
        changes[f['path']]=service.rules.validate_value(f,value)
    return changes


async def _form(request,actor,case_id,applicant_id):
    if request.headers.get('content-type','').split(';',1)[0].strip()!='application/x-www-form-urlencoded':
        raise HTTPException(415,'Используйте форму.',headers=HEADERS)
    body=bytearray()
    async for chunk in request.stream():
        if len(body)+len(chunk)>32768:raise HTTPException(413,'Форма слишком большая.',headers=HEADERS)
        body.extend(chunk)
    try:
        pairs=parse_qsl(body.decode('utf-8'),keep_blank_values=True,max_num_fields=40,encoding='utf-8',errors='strict')
        if len({k for k,v in pairs})!=len(pairs) or any(len(k)>64 or len(v)>2048 for k,v in pairs):raise ValueError
        values=dict(pairs);action=values.get('_iv_action');paths=json.loads(values['_iv_paths'])
        if type(paths) is not list or len(paths)>3 or any(type(p) is not str or len(p)>100 for p in paths) or len(set(paths))!=len(paths):raise ValueError
        if action in ('answer','correct','remove'):
            if not paths or action in ('correct','remove') and len(paths)!=1:raise ValueError
        elif paths:raise ValueError
        fields=_typed_fields(paths,service.catalog.by_digest(values['_iv_catalog']))
        allowed=_field_names(fields) if action in ('answer','correct') else SIMPLE[action]
        if not set(META)|SECURITY<=values.keys() or not values.keys()<=set(META)|SECURITY|allowed:raise ValueError
        for key in ('_iv_target','_iv_revision'):
            number=int(values[key])
            if str(number)!=values[key] or not 0<=number<=2147483647:raise ValueError
        if (action=='start')!=(values['_iv_target']=='0') or (action=='start')!=(values['_iv_revision']=='0'):raise ValueError
    except (ValueError,UnicodeError,KeyError,TypeError):raise HTTPException(422,'Недопустимые поля формы.',headers=HEADERS) from None
    token=request.session.get('kg_interview_csrf','')
    if not token or not hmac.compare_digest(token.encode(),values['_iv_csrf'].encode()) or not hmac.compare_digest(
        _signature(request,actor,case_id,applicant_id,values).encode(),values['_iv_signature'].encode()):
        raise HTTPException(403,'Форма изменена или относится к другой сессии.',headers=HEADERS)
    return values,paths


async def _render(request,manager,actor,case,applicant_id,*,field=None,error='',status=200,retry=None):
    current=None;forms={};widgets=[];correction=None;fields={};policy=_policy();allowed=False;owners=[]
    try:
        current=await service.read_interview(entry._engine(),actor=actor,case_id=case['id'],applicant_id=applicant_id,policy=policy)
        try:
            authorize(actor,policy,on=service.applications._today());allowed=True
            owners=sorted(set(policy.operators)&existing_full_admins())
        except (EntryStorageInvalid,PermissionDenied):pass
        if current['interview']:
            document=service.catalog.by_digest(current['interview']['catalog_hash'])
            fields=service.rules.Answers(current['state']['answers'],catalog_document=document).fields
            if field:
                if field not in fields:raise HTTPException(422,'Неизвестный вопрос.',headers=HEADERS)
                correction=fields[field]
            widgets=_typed_fields([q['path'] for q in current['drafts']],document)
        if not retry:
            def envelope(action,paths=()):return _envelope(request,actor,case['id'],applicant_id,action,policy,current if current['interview'] else None,paths)
            if not current['interview'] and allowed and policy.catalog_hash==service.catalog.digest():forms['start']=envelope('start')
            elif current['interview']:
                phase=current['state']['phase']
                if current['can_collect']:
                    if widgets:forms['answer']=envelope('answer',[f['path'] for f in widgets])
                    if correction:
                        forms['correct']=envelope('correct',[field])
                        if field in current['state']['answers']:forms['remove']=envelope('remove',[field])
                if current['can_control']:
                    for action in ('language','refresh','pause' if phase=='active' else 'resume'):forms[action]=envelope(action)
                if current['can_handoff']:
                    for action in ('handoff','interrupt'):forms[action]=envelope(action)
                if current['can_ack']:forms['ack']=envelope('ack')
                if current['can_withdraw']:forms['withdraw']=envelope('interrupt')
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageInvalid as exc:
        if str(exc) in UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        current=None;forms={};error='История не прошла проверку. Изменения недоступны.';status=503
    except HTTPException:raise
    except Exception:
        current=None;forms={};error='Хранилище временно недоступно.';status=503
    return ar.templates.TemplateResponse(request,'kg_interviews.html',dict(request=request,manager=manager,case=case,
        applicant_id=applicant_id,current=current,forms=forms,widgets=widgets,correction=correction,fields=fields,
        policy=policy,allowed=allowed,owners=owners,error=error,retry=retry,url=_url(case['id'],applicant_id),
        phases=PHASES,interrupts={k:INTERRUPTS.get(k,k.replace('_',' ')) for k in sorted(service.rules.INTERRUPTS)},
        write_on=_write_on(request),countries=sorted(service.rules.COUNTRIES),country_names=COUNTRY_NAMES,
        choice_labels=CHOICE_LABELS,gap_labels=GAP_LABELS,card_reasons=CARD_REASONS,action_labels=ACTION_LABELS),status_code=status,headers=HEADERS)


@ar.router.get('/case/{case_id}/kg-entry/applicants/{applicant_id}/interview',response_class=HTMLResponse)
async def interview_form(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager);case=await entry._case(case_id,actor)
    pairs=list(request.query_params.multi_items())
    if len(pairs)>1 or any(k!='field' or len(v)>100 for k,v in pairs):raise HTTPException(422,'Недопустимый вопрос.',headers=HEADERS)
    return await _render(request,manager,actor,case,applicant_id,field=request.query_params.get('field'))


@ar.router.post('/case/{case_id}/kg-entry/applicants/{applicant_id}/interview',response_class=HTMLResponse)
async def interview_submit(request:Request,case_id:int=Path(ge=1,le=2147483647),applicant_id:int=Path(ge=1,le=2147483647),manager=Depends(ar.require_full_admin)):
    actor=entry._gate(request,manager,write=True);case=await entry._case(case_id,actor)
    values,paths=await _form(request,actor,case_id,applicant_id);policy=_policy();action=values['_iv_action']
    try:
        if action=='start':
            raw=values.get('profile_id','');profile_id=int(raw) if raw else None
            if raw and str(profile_id)!=raw:raise ValueError
            await service.start_interview(entry._engine(),actor=actor,case_id=case_id,applicant_id=applicant_id,
                owner_login=values.get('owner',''),language=values.get('language',''),profile_id=profile_id,
                request_key=values['_iv_key'],expected_policy_hash=values['_iv_policy'],policy=policy)
        else:
            operation={'action':action}
            if action in ('answer','correct'):operation.update(changes=_changes(values,paths),displayed=paths)
            elif action=='remove':
                if values.get('confirmed')!='yes':raise ValueError
                operation['paths']=paths
            elif action=='language':operation['language']=values.get('language','')
            elif action=='interrupt':operation['reason']=values.get('reason','')
            elif action=='ack':operation.update(card_hash=values['_iv_card'],confirmed=values.get('confirmed')=='yes')
            await service.record_action(entry._engine(),actor=actor,case_id=case_id,applicant_id=applicant_id,
                interview_id=int(values['_iv_target']),expected_revision=int(values['_iv_revision']),
                request_key=values['_iv_key'],operation=operation,policy=policy,expected_policy_hash=values['_iv_policy'] or None)
    except PermissionDenied:raise HTTPException(403,headers=HEADERS) from None
    except EntryStorageUnavailable:
        return await _render(request,manager,actor,case,applicant_id,status=503,retry=values,
            error='Сохранение не подтверждено. Повторите исходный запрос для проверки результата без дубля.')
    except EntryStorageConflict as exc:
        return await _render(request,manager,actor,case,applicant_id,status=409,error=REASONS.get(str(exc),'Сведения изменились. Проверьте текущую анкету.'))
    except (EntryStorageInvalid,ValueError) as exc:
        if str(exc) in UNAVAILABLE:raise HTTPException(404,headers=HEADERS) from None
        return await _render(request,manager,actor,case,applicant_id,field=paths[0] if action=='correct' else None,
            status=422,error=REASONS.get(str(exc),'Проверьте тип ответа и обязательные поля. Для «не знаю» оставьте значение пустым.'))
    except Exception:
        return await _render(request,manager,actor,case,applicant_id,status=503,retry=values,error='Результат сохранения неизвестен. Повторите исходный запрос.')
    return RedirectResponse(_url(case_id,applicant_id),status_code=303,headers=HEADERS)
