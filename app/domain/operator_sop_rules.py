"""Closed source duties for explicitly selected internal review times.

The source cadence is context for a human choice, never a computed or official
deadline. Every duty requires separately pinned server authority.
"""
from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

from app.domain.entry_anchor_rules import day, shape, text
from app.domain.entry_storage import EntryStorageInvalid, _hash, _plain

FORMAT = 'kg-operator-sop-review/1'
PREFIX = 'KG.DL.INTERNAL_SOP_'
SOURCE_HASH = '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'
BISHKEK = ZoneInfo('Asia/Bishkek')
# key: explicit eligible stages, source section, printed page, original duty,
# human labels. Distinct reminders remain distinct per-application tracks.
DUTIES = {
 'LEAD_RESPONSE': (('V01',),'19.1',78,'Нет ответа 15 мин — алерт','Ответ на обращение','Respond to enquiry'),
 'QUALIFICATION_2H': (('V02','V03'),'19.1',78,'Клиенту — 2 ч','Проверка ответа на вопросы · 2 ч','Qualification response review · 2h'),
 'QUALIFICATION_24H': (('V02','V03'),'19.1',78,'Клиенту — 24 ч','Проверка ответа на вопросы · 24 ч','Qualification response review · 24h'),
 'QUALIFICATION_72H': (('V02','V03'),'19.1',78,'72 ч тишины → X07','Проверка длительного отсутствия ответа','Review prolonged silence'),
 'SPECIALIST_HANDOFF': (('V03',),'14.2',62,'Принять ≤ 2 р.ч.; решение ≤ 1 р.д.','Разбор специалистом','Specialist review'),
 'QUOTE_PREPARATION': (('V04',),'19.1',78,'КП ≤ 2 р.ч.','Подготовка предложения','Prepare quotation'),
 'QUOTE_24H': (('V06',),'19.1',78,'КП: 24 ч','Проверка решения по предложению · 24 ч','Quotation response review · 24h'),
 'QUOTE_72H': (('V06',),'19.1',78,'КП: 72 ч','Проверка решения по предложению · 72 ч','Quotation response review · 72h'),
 'CONTRACT_REVIEW': (('V06','V07'),'19.1',78,'Договор / оферта: в день КП','Проверка договора','Review contract'),
 'PAYMENT_24H': (('V08',),'19.1',78,'Оплата: 24 ч','Проверка оплаты · 24 ч','Payment review · 24h'),
 'PAYMENT_48H': (('V08',),'19.1',78,'Оплата: 48 ч','Проверка оплаты · 48 ч','Payment review · 48h'),
 'PAYMENT_URGENT': (('V08',),'19.1',78,'срочным — 4 ч','Проверка срочной оплаты','Urgent payment review'),
 'WORK_COMMERCIAL_24H': (('W03','W04'),'19.9',81,'КП, договор, оплата: 24/48 ч','Договор и оплата работодателя · 24 ч','Employer contract and payment review · 24h'),
 'WORK_COMMERCIAL_48H': (('W03','W04'),'19.9',81,'КП, договор, оплата: 24/48 ч','Договор и оплата работодателя · 48 ч','Employer contract and payment review · 48h'),
 'DOCUMENTS_D1': (('V10','V13','W09','W10'),'19.1',78,'Сбор документов: Д+1','Проверка документов · Д+1','Document follow-up · D+1'),
 'DOCUMENTS_D3': (('V10','V13','W09','W10'),'19.1',78,'Сбор документов: Д+3','Проверка документов · Д+3','Document follow-up · D+3'),
 'DOCUMENTS_D7': (('V10','V13','W09','W10'),'19.1',78,'Сбор документов: Д+7','Проверка документов · Д+7','Document follow-up · D+7'),
 'DOCUMENTS_D14': (('V10','V13'),'19.1',78,'Д+14 → X06','Разбор задержки документов','Review delayed documents'),
 'INVITER_FOLLOWUP': (('V11',),'14.2',62,'Напоминание стороне каждые 2 р.д.','Проверка ответа приглашающей стороны','Review inviting-party response'),
 'READY_SUBMISSION_REVIEW': (('V14',),'14.2',63,'В тот же р.д.; срочно ≤ 2 ч','Проверка готовой заявки','Review ready application'),
 'DOCUMENT_CHECK': (('V12',),'19.1',78,'Проверка ≤ 4 р.ч.','Проверка полученного комплекта','Check received packet'),
 'VERIFICATION_24H': (('V15',),'19.1',78,'Верификация: 24 ч от начала','Проверка верификации · 24 ч','Verification review · 24h'),
 'VERIFICATION_48H': (('V15',),'19.1',78,'Верификация: 48 ч от начала','Проверка верификации · 48 ч','Verification review · 48h'),
 'VERIFICATION_EXPIRY': (('V15',),'19.1',78,'верификация ≤ 72 ч','Проверка срока верификации','Review verification window'),
 'APPLICATION_STATUS': (('V17','W12'),'19.1',78,'Проверка статуса 10:00 и 16:00; срочные каждые 2–3 ч','Проверка статуса подачи','Check application status'),
 'CORRECTION_REVIEW': (('V18','W13'),'19.1',78,'Ежедневно до исправления','Проверка доработки','Review correction'),
 'DOWNLOAD_REVIEW': (('V20',),'19.1',79,'Скачивание e-Visa ≤ 1 р.ч.','Получение выданного документа','Obtain issued document'),
 'ISSUED_CHECK': (('V21',),'19.1',79,'Проверка и передача ≤ 1 р.ч.','Проверка выданного документа','Check issued document'),
 'RECEIPT_REVIEW': (('V22',),'19.1',79,'Нет подтверждения 24 ч → звонок','Проверка получения клиентом','Review client receipt'),
 'ENTRY_EVE_REVIEW': (('V23',),'14.2',63,'Накануне въезда — памятка','Подготовка к запланированному въезду','Review planned entry preparation'),
 'ENTRY_CONFIRMATION_REVIEW': (('V23',),'14.2',63,'на следующий день — «Вы въехали?»','Проверка фактического въезда','Review actual entry confirmation'),
 'FEEDBACK_REVIEW': (('V25',),'19.1',79,'Запрос отзыва','Проверка обратной связи','Review feedback'),
 'RETURN_TRIP_REVIEW': (('V25',),'19.1',79,'предложение повторной поездки','Обсуждение повторной поездки','Review a future trip'),
 'QUOTA_REVIEW': (('W08',),'19.9',81,'Дедлайн использования +3 мес.','Проверка использования квоты','Review quota use'),
 'RES_STATUS': (('W17','W18'),'19.9',82,'Проверка ежедневно','Проверка резидент-карты','Review resident card status'),
 'EMPLOYER_TAX': (('W21',),'19.9',82,'ежеквартально — налоги','Проверка сведений о налогах работодателя','Review employer tax evidence'),
 'STUDENT_ANNUAL': (('V24','V25'),'19.7',81,'ежегодно — продление регистрации и РК','Проверка документов студента за выбранный период','Review student documents for selected period'),
 'ENTRY_BAN_REVIEW': (('U09',),'14.6',65,'напоминание о дате окончания запрета въезда','Проверка сведений о запрете въезда','Review entry-ban evidence'),
 'EXEMPTION_REVIEW': (('V05','V24'),'14.2',63,'регистрация: за 5 дней до окончания освобождения','Проверка срока освобождения от регистрации','Review registration exemption'),
 'OTHER_AFTERCARE': (('V24','W21','R07','R08'),'19.1',79,'Сопровождение: регистрация, продление, выезд','Проверка дальнейших действий','Review follow-up actions'),
}
SOURCE_OVERRIDES = {
 ('APPLICATION_STATUS','W12'): ('19.9',82,'Проверка 2 раза в день'),
 ('CORRECTION_REVIEW','W13'): ('19.9',82,'Дедлайн 60 дн; ежедневно'),
 ('EXEMPTION_REVIEW','V05'): ('14.2',62,'Виза не требуется; памятка по регистрации'),
 ('OTHER_AFTERCARE','W21'): ('19.9',82,'РК −7 р.д. — новая ЕР; ежеквартально — налоги'),
 ('OTHER_AFTERCARE','R07'): ('19.12',83,'Продление / перерегистрация'),
 ('OTHER_AFTERCARE','R08'): ('19.12',83,'Продление / перерегистрация'),
}
for _duty in ('DOCUMENTS_D1','DOCUMENTS_D3','DOCUMENTS_D7'):
    for _stage in ('W09','W10'):
        SOURCE_OVERRIDES[(_duty,_stage)] = ('19.9',82,'Д+1/3/7')
for _duty in ('DOCUMENTS_D1','DOCUMENTS_D3','DOCUMENTS_D7','DOCUMENTS_D14'):
    SOURCE_OVERRIDES[(_duty,'V13')] = ('14.2',63,'Как V10 (сроки V10: печатная стр.62)')
TERMINAL_DUTIES = frozenset(('STUDENT_ANNUAL','FEEDBACK_REVIEW','RETURN_TRIP_REVIEW','ENTRY_BAN_REVIEW','OTHER_AFTERCARE'))


def fail(code='invalid_operator_sop_review'):
    raise EntryStorageInvalid(code)


def definition(rule_id):
    if type(rule_id) is not str or not rule_id.startswith(PREFIX):
        fail('operator_sop_duty_unsupported')
    key=rule_id.removeprefix(PREFIX)
    if key not in DUTIES: fail('operator_sop_duty_unsupported')
    stages,section,page,clause,ru,en=DUTIES[key]
    references = []
    for stage in stages:
        actual_section,actual_page,actual_clause=SOURCE_OVERRIDES.get((key,stage),(section,page,clause))
        references.append(dict(stage=stage,section=actual_section,printed_page=str(actual_page),clause=actual_clause))
    return dict(rule_id=rule_id, stages=list(stages), source_refs=references,
        source_hash=SOURCE_HASH, scope='operator_selected_internal_review_only',
        calculation='not_performed', labels={'ru':ru,'en':en})


def selected_schedule(value):
    shape(value,('on','time','reason','reference','proof'))
    on=day(value['on']).isoformat()
    if value['reason'] not in ('source_followup','verify_missing_facts','review_changed_facts'):
        fail('operator_sop_schedule_reason_invalid')
    text(value['reference'],r'[A-Z][A-Z0-9._/-]{0,79}')
    text(value['proof'],r'[a-f0-9]{64}')
    selected_time=value['time'];instant=None
    if selected_time is not None:
        if type(selected_time) is not str or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]',selected_time):
            fail('operator_sop_time_invalid')
        try:
            wall=datetime.fromisoformat(on+'T'+selected_time)
            local=wall.replace(tzinfo=BISHKEK,fold=0)
            converted=local.astimezone(timezone.utc)
            coherent=(local.utcoffset()==wall.replace(tzinfo=BISHKEK,fold=1).utcoffset() and
                converted.astimezone(BISHKEK).replace(tzinfo=None)==wall)
            instant=converted.isoformat()
        except (OverflowError,ValueError):
            fail('operator_sop_time_out_of_range')
        if not coherent: fail('operator_sop_time_ambiguous_or_missing')
    return _plain(value)|dict(at=instant,timezone='Asia/Bishkek',origin='operator_selected',official=False,calculated=False)


def operation(value):
    if type(value) is not dict: fail()
    if value.get('action')=='operator_review':
        shape(value,('action','confirmed','evidence_hash','schedule'))
        selected_schedule(value['schedule'])
    elif value.get('action')=='operator_review_clear':
        shape(value,('action','confirmed','evidence_hash'))
    else: fail()
    if value['confirmed'] is not True: fail()
    text(value['evidence_hash'],r'[a-f0-9]{64}')
    return _plain(value)
