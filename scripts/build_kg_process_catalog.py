"""Reproducible draft translation of PDF14; never publishes a CRM workflow."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA = '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'

# Boolean facts are hypothetical manual confirmations, not CRM/payment evidence.
FACT_LABELS = {
    'conversation_started': 'Диалог начат или обращение взял менеджер',
    'profile_complete': 'Карточка квалификации заполнена',
    'manager_review_required': 'Нужна квалификация менеджером',
    'product_defined': 'Тип услуги и продукт определены',
    'visa_required': 'По проверенному сценарию нужна виза',
    'quote_sent': 'Предложение с составом услуг направлено',
    'offer_accepted': 'Оферта или договор принят',
    'consent_confirmed': 'Согласие на обработку данных подтверждено',
    'invoice_issued': 'Счёт выставлен',
    'service_payment_confirmed': 'Факт оплаты услуг подтверждён',
    'checklist_sent': 'Чек-лист документов передан',
    'documents_received': 'Комплект документов получен',
    'documents_accepted': 'Комплект принят после проверки',
    'documents_current': 'Принятие относится к актуальной версии документов и паспорта',
    'corrections_needed': 'Есть замечания к комплекту',
    'corrections_completed': 'Замечания устранены',
    'portal_draft_created': 'Черновик на портале создан',
    'email_verified': 'E-mail портала подтверждён',
    'portal_payment_confirmed': 'Факт оплаты на портале подтверждён',
    'submission_recorded': 'Фактическая отправка заявления подтверждена',
    'application_reference_recorded': 'Номер подачи записан и проверен',
    'issued_document_downloaded': 'Выданный документ получен для проверки',
    'issued_document_checked': 'Данные выданного документа проверены',
    'delivered_to_client': 'Документ и памятка переданы клиенту',
    'receipt_confirmed': 'Клиент подтвердил получение',
    'actual_entry_confirmed': 'Подтверждён фактический въезд, а не плановая дата',
    'followup_completed': 'Сопровождение выполнено и проверено',
    'actual_exit_or_end_confirmed': 'Подтверждён выезд или проверено основание завершения сопровождения',
    'employer_qualified': 'Квалификация работодателя выполнена',
    'employer_authorization_confirmed': 'Полномочия для работы с кабинетом работодателя подтверждены',
    'account_activated': 'Кабинет работодателя активирован',
    'quota_applied': 'Заявка на квоту подана',
    'quota_approved': 'Квота одобрена и её применимость проверена',
    'permit_issued': 'Единое разрешение выдано',
    'registration_confirmed': 'Требуемая регистрация подтверждена',
    'resident_package_received': 'Комплект на резидент-карту получен',
    'resident_issued_and_collected': 'Резидент-карта выдана, получение пластика подтверждено',
    'completion_reviewed': 'Основание завершения или продления проверено',
    'stay_basis_checked': 'Основание и срок регистрации проверены специалистом',
    'receiving_party_docs_accepted': 'Документы принимающей стороны приняты',
    'payment_code_received': 'Код оплаты регистрации получен',
    'registration_payment_confirmed': 'Оплата регистрации подтверждена',
    'registration_certificate_received': 'Талон регистрации получен и срок проверен',
    'overstay_assessed': 'Обстоятельства нарушения и допустимый путь проверены специалистом',
    'protocol_received': 'Протокол ОВД получен',
    'fine_payment_confirmed': 'Оплата штрафа подтверждена квитанцией',
    'police_letter_received': 'Письмо ОВД получено',
    'exit_visa_issued': 'Выездная виза L выдана и проверена',
    'departure_confirmed': 'Фактический выезд подтверждён',
}


def source_section(text, number):
    match = re.search(rf'^## {re.escape(number)}\. .*?\n(.*?)(?=^## |^# |\Z)', text, re.M | re.S)
    if not match: raise ValueError('source_section_missing')
    return match.group(0).strip()


def build():
    text = (ROOT / 'docs/kb-visa-inbound-v1.1-derived.md').read_text(encoding='utf-8')
    sections = {f'14.{n}': source_section(text, f'14.{n}') for n in range(2, 7)}
    stages = []
    for section in ('14.2', '14.3', '14.4'):
        for line in sections[section].splitlines():
            if not re.match(r'^\| (?:V\d\d|X\d\d|W\d\d|WX\d) \|', line): continue
            cells = [part.strip() for part in line.strip('|').split('|')]
            code = cells[0]
            page = (63 if int(code[1:]) <= 11 else 64) if code.startswith('V') else (
                (64 if int(code[1:]) <= 4 else 65) if code.startswith('X') else
                (65 if code.startswith('W') and not code.startswith('WX') and int(code[1:]) <= 18 else 66))
            stages.append(dict(code=code, name=cells[1], process='work' if code.startswith('W') else 'visa',
                kind='flag' if code in ('V11', 'X10', 'X12') else 'exception' if 'X' in code else 'stage',
                section=section, page=page, source_text=line))
    labels = {
        'R01': 'Запрос', 'R02': 'Проверка основания и дедлайна', 'R03': 'Документы принимающей стороны',
        'R04': 'Заявление подано, получен код оплаты', 'R05': 'Оплачено', 'R06': 'Талон получен',
        'R07': 'Сопровождение', 'R08': 'Завершено', 'RX1': 'Отказ', 'RX2': 'Просрочка регистрации',
        'U01': 'Обращение', 'U02': 'Оценка', 'U03': 'ОВД: протокол', 'U04': 'Штраф оплачен',
        'U05': 'Письмо ОВД', 'U06': 'L подано или регистрация до 30 дней', 'U07': 'L выдана',
        'U08': 'Выезд подтверждён', 'U09': 'Закрыто', 'UX1': 'Экстренная ситуация', 'UX2': 'Отказ в L',
    }
    for code, name in labels.items():
        section = '14.5' if code.startswith('R') else '14.6'
        # Retain the full source paragraph: short display labels are editorial.
        paragraph = next(line for line in sections[section].splitlines() if line.startswith(('R01 ', 'U01 ')))
        if code not in paragraph: raise ValueError('missing_source_code')
        stages.append(dict(code=code, name=name, process='stay' if code.startswith('R') else 'regularization',
            kind='exception' if 'X' in code else 'stage', section=section, page=66, source_text=paragraph))
    assert len(stages) == 87
    facts = {key: {'label': value, 'type': 'boolean'} for key, value in FACT_LABELS.items()}
    facts['decision'] = {'label': 'Результат рассмотрения', 'type': 'enum',
        'values': {'pending': 'Ещё рассматривается', 'approved': 'Одобрено', 'refused': 'Отказ', 'revision_requested': 'Доработка'}}
    facts['eligibility'] = {'label': 'Вывод специалиста о возможности выбранного продукта', 'type': 'enum',
        'values': {'eligible': 'Основания проверены, продукт возможен', 'ineligible': 'Выбранный продукт невозможен', 'needs_review': 'Решение ещё не принято'}}
    facts['regularization_route'] = {'label': 'Проверенный путь урегулирования', 'type': 'enum',
        'values': {'exit_visa': 'Выездная виза L', 'registration': 'Регистрация'}}
    edges = []
    def edge(a, b, required='', *, expected=None, basis='source_sequence', effect='same_process'):
        guards = {key: True for key in required.split()}; guards.update(expected or {})
        edges.append({'from': a, 'to': b, 'requires': guards, 'basis': basis, 'proposed_effect': effect})
    edge('V01','V02','conversation_started')
    edge('V02','V03','manager_review_required')
    edge('V02','V04','profile_complete product_defined', expected={'manager_review_required':False,'eligibility':'eligible'})
    edge('V03','V04','profile_complete product_defined',expected={'eligibility':'eligible'})
    edge('V03','X08', expected={'eligibility':'ineligible'})
    edge('V04','V05',expected={'visa_required':False,'eligibility':'eligible'})
    edge('V04','V06','quote_sent',expected={'visa_required':True,'eligibility':'eligible'})
    edge('V06','V07','offer_accepted consent_confirmed')
    edge('V07','V08','offer_accepted consent_confirmed invoice_issued')
    edge('V08','V09','service_payment_confirmed')
    edge('V09','V10','consent_confirmed service_payment_confirmed checklist_sent')
    edge('V10','V12','consent_confirmed documents_received')
    edge('V12','V13','corrections_needed')
    edge('V13','V12','corrections_completed documents_received')
    edge('V12','V14','documents_accepted documents_current',expected={'corrections_needed':False})
    edge('V14','V15','consent_confirmed documents_accepted documents_current portal_draft_created')
    edge('V15','V16','consent_confirmed documents_accepted documents_current email_verified portal_payment_confirmed submission_recorded application_reference_recorded')
    edge('V16','V17','submission_recorded application_reference_recorded')
    for dest, decision in [('V18','revision_requested'), ('V20','approved'), ('X01','refused')]:
        edge('V17',dest,expected={'decision':decision})
    edge('V18','V19','corrections_completed documents_accepted documents_current submission_recorded',effect='same_attempt_resubmission')
    edge('V19','V17','submission_recorded application_reference_recorded')
    edge('V20','V21','issued_document_downloaded')
    edge('V21','V22','issued_document_checked delivered_to_client')
    edge('V22','V23','receipt_confirmed')
    edge('V23','V24','actual_entry_confirmed')
    edge('V24','V25','followup_completed actual_exit_or_end_confirmed')
    work = [('W01','W02','profile_complete'), ('W02','W03','employer_qualified quote_sent offer_accepted'),
        ('W03','W04','service_payment_confirmed'), ('W04','W05','employer_authorization_confirmed'),
        ('W05','W06','account_activated'), ('W06','W07','quota_applied'), ('W07','W08','quota_approved'),
        ('W08','W09','quota_approved consent_confirmed checklist_sent'), ('W09','W10','documents_received'),
        ('W10','W11','consent_confirmed documents_accepted documents_current submission_recorded application_reference_recorded'),
        ('W11','W12','submission_recorded application_reference_recorded'),
        ('W14','W15','permit_issued actual_entry_confirmed registration_confirmed'),
        ('W16','W17','resident_package_received documents_accepted documents_current submission_recorded application_reference_recorded'),
        ('W17','W18','submission_recorded application_reference_recorded'),
        ('W19','W20','resident_issued_and_collected registration_confirmed'),
        ('W20','W21','registration_confirmed'), ('W21','W22','followup_completed completion_reviewed')]
    for a,b,g in work: edge(a,b,g,basis='draft_proposal',effect='separate_registration_application' if a=='W19' else 'same_process')
    edge('W12','W13',expected={'decision':'revision_requested'},basis='draft_proposal')
    edge('W13','W12','corrections_completed documents_accepted documents_current submission_recorded',basis='draft_proposal',effect='same_attempt_resubmission')
    edge('W12','W14','permit_issued',expected={'decision':'approved'},basis='draft_proposal')
    edge('W12','WX2',expected={'decision':'refused'},basis='draft_proposal')
    edge('W15','W16','permit_issued resident_package_received',basis='draft_proposal',effect='separate_resident_application')
    edge('W18','W19','resident_issued_and_collected',expected={'decision':'approved'},basis='draft_proposal')
    edge('W18','WX2',expected={'decision':'refused'},basis='draft_proposal')
    stay = [('R01','R02','profile_complete'), ('R02','R03','stay_basis_checked consent_confirmed'),
        ('R03','R04','receiving_party_docs_accepted documents_current submission_recorded payment_code_received'),
        ('R04','R05','registration_payment_confirmed'), ('R05','R06','registration_certificate_received'),
        ('R06','R07','registration_certificate_received'), ('R07','R08','followup_completed completion_reviewed')]
    for a,b,g in stay: edge(a,b,g)
    edge('R04','RX1',expected={'decision':'refused'},basis='draft_proposal')
    edge('R05','RX1',expected={'decision':'refused'},basis='draft_proposal')
    for a,b,g in [('U01','U02','profile_complete'),('U02','U03','overstay_assessed protocol_received'),
                  ('U03','U04','fine_payment_confirmed'),('U04','U05','police_letter_received')]: edge(a,b,g)
    edge('U05','U06','police_letter_received documents_accepted documents_current submission_recorded',expected={'regularization_route':'exit_visa'})
    edge('U05','U06','stay_basis_checked receiving_party_docs_accepted documents_current submission_recorded',expected={'regularization_route':'registration'},effect='separate_registration_application')
    edge('U06','U07','exit_visa_issued',expected={'regularization_route':'exit_visa','decision':'approved'})
    edge('U06','UX2',expected={'regularization_route':'exit_visa','decision':'refused'},basis='draft_proposal')
    edge('U07','U08','departure_confirmed')
    edge('U08','U09','departure_confirmed completion_reviewed')
    notices = {
        'X01':'После анализа отказа повтор оформляется новой связанной заявкой. Старую попытку нельзя переводить обратно на рассмотрение.',
        'WX2':'Отказ требует анализа; новая попытка и решения о деньгах оформляются отдельно.',
        'RX2':'Просрочка требует отдельной процедуры урегулирования; регистрация автоматически не становится визой L.',
        'U06':'При выборе регистрации продолжение относится к отдельной регистрационной заявке. U07 доступен только для пути L.',
        'V11':'Параллельный флаг/подстатус ожидания приглашающей стороны, не обязательный последовательный этап.',
        'X10':'Параллельный флаг риска срока; автоматическое вычисление и эскалация здесь не включены.',
        'X12':'Параллельный флаг задержки; автоматическое вычисление и задача здесь не включены.',
    }
    return {'format':'kg-entry-process-draft/1','version':'pdf-1.1-review-1','publication_approved':False,
        'source_sha256':SOURCE_SHA,'section_sha256':{key:hashlib.sha256(value.encode()).hexdigest() for key,value in sections.items()},
        'scope':'source_process_preview_only','decisions':['DEC-02','DEC-06','DEC-07','DEC-08','DEC-11','DEC-12'],
        'processes':{'visa':'Визы','work':'Работа','stay':'Пребывание','regularization':'Урегулирование'},
        'facts':facts,'stages':stages,'edges':edges,'notices':notices}


if __name__ == '__main__':
    target = ROOT / 'knowledge/kg_entry/processes_v1_1/catalog.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(build(), ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
    target.write_bytes(payload)
    print('Draft catalog:',len(build()['stages']),'codes;',len(build()['edges']),'edges; SHA256',hashlib.sha256(payload).hexdigest())
