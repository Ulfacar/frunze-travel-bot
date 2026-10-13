"""Bounded operations on a server-read personal snapshot; no full-history POST."""
from copy import deepcopy

from app.domain.entry_storage import EntryStorageInvalid

META=('_ah_action','_ah_revision','_ah_hash','_ah_profile','_ah_item','_ah_key','_ah_new_passport','_ah_today')
SECURITY={'_ah_csrf','_ah_signature'}
FIELDS={'summary':{'as_of','history_complete','passport','confirmed'},
    'visit':{'entry_date','exit_date','basis','country','passport','evidence','verified','confirmed'},
    'remove':{'confirmed'},'withdraw':{'reason','confirmed'}}


def state(selected,today):
    if selected and selected['action']=='save':return deepcopy(selected['operation'])
    return dict(passport_ref=None,document=dict(format='kg-stay-history/1',as_of=today,history_complete=None,intervals=[]))


def passport_refs(base):
    # Tokens are only choices in this person's pinned snapshot. Labels are local
    # conveniences, never identity assertions across people or versions.
    return list(dict.fromkeys(ref for ref in [base['passport_ref'],
        *(item['passport_ref'] for item in base['document']['intervals'])] if ref))


def choice(ref,refs):return str(refs.index(ref)) if ref in refs else ''


def passport(value,base,values):
    if not value:return None
    if value=='new':return values['_ah_new_passport']
    refs=passport_refs(base)
    if value not in {str(i) for i in range(len(refs))}:raise EntryStorageInvalid('invalid_passport_reference')
    return refs[int(value)]


def operation(values,selected):
    if values.get('confirmed')!='yes':raise EntryStorageInvalid('applicant_history_confirmation_required')
    action=values['_ah_action']
    if action=='withdraw':return dict(action='withdraw',confirmed=True,reason=values.get('reason',''))
    base=state(selected,values['_ah_today']);doc=base['document']
    if action=='summary':
        complete=values.get('history_complete','')
        if complete not in ('','true','false'):raise EntryStorageInvalid('invalid_history_complete')
        doc.update(as_of=values.get('as_of',''),history_complete={'':None,'true':True,'false':False}[complete])
        base['passport_ref']=passport(values.get('passport',''),base,values)
    elif action in ('visit','remove'):
        ref=values['_ah_item'];old=next((i for i in doc['intervals'] if i['ref']==ref),None)
        if action=='remove':
            if old is None:raise EntryStorageInvalid('history_visit_unavailable')
            doc['intervals'].remove(old)
        else:
            if values.get('verified','') not in ('','yes'):raise EntryStorageInvalid('invalid_history_confirmation')
            item=dict(ref=ref,entry_date=values.get('entry_date',''),exit_date=values.get('exit_date') or None,
                basis=values.get('basis','unknown'),passport_country=values.get('country') or None,
                passport_ref=passport(values.get('passport',''),base,values),
                evidence=values.get('evidence','client_statement'),confirmed=values.get('verified')=='yes')
            if old is None:doc['intervals'].append(item)
            else:doc['intervals'][doc['intervals'].index(old)]=item
        # Changing visits invalidates the previous statement of completeness.
        doc['history_complete']=None
    else:raise EntryStorageInvalid('invalid_applicant_history_operation')
    return dict(action='save',confirmed=True,profile_id=int(values['_ah_profile']),
        passport_ref=base['passport_ref'],document=doc)


def defaults(action,base,item):
    refs=passport_refs(base)
    if action=='summary':return dict(as_of=base['document']['as_of'],
        history_complete={None:'',True:'true',False:'false'}[base['document']['history_complete']],
        passport=choice(base['passport_ref'],refs))
    if action=='visit':
        item=item or {}
        return dict(entry_date=item.get('entry_date',''),exit_date=item.get('exit_date') or '',basis=item.get('basis','unknown'),
            country=item.get('passport_country') or '',passport=choice(item.get('passport_ref'),refs),
            evidence=item.get('evidence','client_statement'),verified='yes' if item.get('confirmed') else '')
    return {}


TEXT={
 'title':('История пребывания','Stay history'), 'person':('Заявитель','Applicant'),
 'profile':('Анкета заявителя','Applicant profile'), 'current':('Актуальная версия','Latest version'),
 'historic':('Историческая версия: только просмотр. Статус ниже относится к текущим сведениям.','Historical version: read only. The status below describes the current evidence.'),
 'intro':('Поездки только этого заявителя. Сведения не подтверждают право на въезд или срок пребывания.','This applicant’s visits only. Recorded facts do not establish entry eligibility or an allowed stay.'),
 'missing':('История ещё не заполнена. Это не означает отсутствие поездок.','No history recorded. This does not mean there were no visits.'),
 'withdrawn':('Сведения сняты с использования. Прежние версии сохранены.','Evidence withdrawn from use. Earlier versions are retained.'),
 'review_required':('Требуется уточнение сведений','Evidence needs clarification'),
 'recorded_inputs':('Сведения записаны; правовая оценка не выполнена','Inputs recorded; legal eligibility has not been assessed'),
 'profile_needed':('Сначала сохраните анкету этого заявителя.','Save this applicant’s profile first.'),
 'write_off':('Запись отключена','Saving is disabled'),
 'capacity':('Предел изменений достигнут. Доступны просмотр и снятие сведений с использования.','Editing capacity reached. Reading and withdrawal remain available.'),
 'summary':('Подтвердить полноту истории и текущий паспорт','Confirm history completeness and current passport'),
 'as_of':('По состоянию на дату','History as of'), 'complete':('Все поездки до этой даты учтены?','Are all visits up to this date included?'),
 'unknown':('Неизвестно','Unknown'), 'yes':('Да, история полная','Yes, the history is complete'), 'no':('Нет, сведения неполные','No, some information is missing'),
 'empty':('Если поездок не было, явно подтвердите полную историю без поездок.','If there were no visits, explicitly confirm a complete history with no visits.'),
 'passport':('Паспорт','Passport'), 'new_passport':('Другой / впервые указанный паспорт','Different / newly recorded passport'),
 'passport_note':('Метки паспортов относятся только к этой версии истории. Сверьте документ; номера паспортов здесь не вводятся. Смена текущего паспорта не меняет паспорт прежних поездок.','Passport labels apply only to this history version. Check the document; do not enter passport numbers here. Changing the current passport does not change earlier visits.'),
 'visit':('Записать поездку','Record a visit'), 'visits':('Поездки в этой версии','Visits in this version'),
 'add':('Добавить поездку','Add visit'), 'edit':('Уточнить','Edit'), 'entry':('Дата въезда','Entry date'),
 'exit':('Дата выезда, если выезд уже состоялся','Exit date, if already departed'), 'open':('Выезд не указан','No exit recorded'),
 'basis':('Основание пребывания','Stay basis'), 'country':('Страна паспорта · код ISO из трёх букв, например RUS','Passport country · three-letter ISO code, e.g. RUS'),
 'evidence':('Источник сведений','Evidence source'), 'verified':('Сведения этой поездки проверены по указанному источнику','This visit was checked against the selected source'),
 'evidence_note':('Рассказ клиента нельзя отметить как проверенный документ. После изменения поездок полноту истории нужно подтвердить заново.','A client statement cannot be marked as verified documentary evidence. After editing visits, confirm history completeness again.'),
 'remove':('Убрать ошибочную поездку из новой версии','Remove an incorrect visit from the next version'),
 'remove_note':('Прежняя запись останется в истории версий.','The earlier record remains in version history.'),
 'withdraw':('Снять сведения с использования','Withdraw evidence from use'), 'reason':('Причина','Reason'),
 'confirmed':('Подтверждаю эту операцию','I confirm this operation'), 'save':('Сохранить','Save'),
 'versions':('История версий','Version history'), 'version':('Версия','Version'),
 'next':('Следующая страница','Next page'), 'previous':('Предыдущая страница','Previous page'),
 'total':('Всего поездок','Total visits'), 'retry':('Повторить исходный запрос','Retry the original request'),
 'page':('Страница','Page'), 'per_page':('Показано до 25 поездок на странице, в том числе при печати.','Up to 25 visits are shown per page, including print.'),
 'pinned_profile':('Анкета этой версии','Profile pinned to this version'),
 'unavailable':('Не удалось проверить историю. Изменения недоступны.','History could not be verified. Editing is unavailable.'),
 'invalid':('Проверьте даты, основание и подтверждение. Новая запись не добавлена.','Check dates, basis and confirmation. No new record was added.'),
 'conflict':('Сведения изменились. Проверьте актуальную версию перед новой операцией.','Evidence changed. Check the latest version before a new operation.'),
 'uncertain':('Сохранение не подтверждено. Повторите исходный запрос без изменений, чтобы получить результат без дубля.','Save outcome is uncertain. Retry the original request unchanged to recover its result without a duplicate.'),
 'profile_changed':('Анкета изменилась: нужна повторная проверка истории.','Profile changed: review the history again.'),
 'clock_uncertain':('Дата записи требует проверки.','Record time needs verification.'),
 'history_needs_current_confirmation':('Нужно подтвердить историю на текущую дату.','Confirm the history as of today.'),
 'history_incomplete':('Полнота истории не подтверждена.','History completeness is not confirmed.'),
 'current_passport_unknown':('Текущий паспорт не указан.','Current passport is unknown.'),
 'history_unconfirmed':('Есть непроверенные поездки.','Some visits are unverified.'),
 'stay_basis_unknown':('Есть поездки с неизвестным основанием.','Some stay bases are unknown.'),
 'passport_continuity_requires_review':('Паспорт менялся или связь поездок с паспортом не установлена.','Passport changed or continuity is unknown.'),
 'passport_country_unknown':('Страна паспорта указана не для всех поездок.','Passport country is missing for some visits.'),
 'uncertain_history':('Есть сомнения в истории поездок','History is uncertain'),
 'passport_changed':('Паспорт изменился','Passport changed'), 'correction_required':('Нужно исправить сведения','Evidence needs correction'),
}
BASE_LABELS={'unknown':('Неизвестно','Unknown'),'visa_free':('Безвизовое пребывание','Visa-free stay'),
    'visa':('Виза','Visa'),'ep':('Единое разрешение','Unified permit'),
    'resident_card':('Карта резидента','Resident card'),'residence_permit':('ВНЖ','Residence permit'),
    'registration_contract':('Регистрация по договору','Registration under contract')}
EVIDENCE_LABELS={'esuvm':('ЕСУВМ','ESUVM'),'passport_stamp':('Отметки в паспорте','Passport stamps'),
    'boarding_pass':('Посадочный талон','Boarding pass'),'visa_document':('Визовый документ','Visa document'),
    'client_statement':('Со слов клиента','Client statement'),'crm_record':('Запись CRM','CRM record')}


def copy(language):
    index=1 if language=='en' else 0
    return ({key:labels[index] for key,labels in TEXT.items()},
        {key:labels[index] for key,labels in BASE_LABELS.items()},
        {key:labels[index] for key,labels in EVIDENCE_LABELS.items()})
