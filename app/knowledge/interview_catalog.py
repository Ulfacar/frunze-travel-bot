"""Versioned atomic A–H questions from supplied PDF3.3; no approved legal rules.

This separate v3 catalog does not change historical qualification v1/v2 schemas.
Repeated family/history slots have stable ordinal identifiers; changing a parent
invalidates dependent answers rather than shifting one person's answers to another.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

VERSION = 'kg-interview-catalog/3.1'
SOURCE_SHA256 = '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'
FIELDS = []


def add(code, path, ru, en, kind='text', *, choices=(), when='always', depends=(), maximum=500):
    FIELDS.append(dict(code=code, path=path, ru=ru, en=en, kind=kind, choices=list(choices),
        when=when, depends=list(depends), maximum=maximum,
        page=26 if code[0]=='A' or code in ('B1','B2') else 27 if code[0] in 'BCD' else 28 if code[0] in 'EFG' else 29,
        rationale_ru='Это нужно сотруднику для проверки обстоятельств и риска отказа.' if code[0]=='D' else '',
        rationale_en='This helps the specialist check the circumstances and refusal risk.' if code[0]=='D' else ''))


def fields(code, prefix, rows, *, when='always', depends=()):
    for name, ru, en, kind in rows:
        add(code, prefix+name, ru, en, kind, when=when, depends=depends)


add('A1','contact_name','Как обращаться к этому заявителю?','How should we address this applicant?',maximum=120)
add('A2','language','На каком языке продолжить?','Which language should we use?','choice',choices=('ru','en'))
fields('A3','contact_', [('phone','Телефон заявителя или уполномоченного представителя','Applicant or authorized representative phone','text'),
    ('messenger','Удобный мессенджер','Preferred messenger','text')])
add('A3','contact_role','Контакт принадлежит заявителю или представителю?','Does this contact belong to the applicant or a representative?','choice',choices=('applicant','representative'))
add('A4','contact_email','Доступный адрес электронной почты','Email address you can access','text',maximum=254)
add('A5','party_type','Для кого обращение?','Who is this request for?','choice',choices=('individual','family','group','company'))
add('A5','applicants_count','Сколько всего заявителей?','How many applicants are there in total?','integer',maximum=200)
add('A6','consent.given','Получено согласие именно этого заявителя на обработку данных?','Has this applicant given consent to data processing?','boolean')
fields('A6','consent.', [('on','Дата согласия','Consent date','date'),
    ('evidence_ref','Номер подтверждения согласия','Consent evidence reference','opaque'),
    ('evidence_sha256','SHA256 подтверждения согласия','Consent evidence SHA256','proof')],when='consent_yes',depends=('consent.given',))
add('A6','terms.accepted','Приняты условия оферты отдельно от согласия на данные?','Have the offer terms been accepted separately from data consent?','boolean')
fields('A6','terms.', [('on','Дата принятия условий','Terms acceptance date','date'),
    ('evidence_ref','Номер подтверждения принятия условий','Terms acceptance evidence reference','opaque'),
    ('evidence_sha256','SHA256 подтверждения принятия условий','Terms acceptance evidence SHA256','proof')],when='terms_yes',depends=('terms.accepted',))
add('B1','citizenships','Все гражданства заявителя','All citizenships of the applicant','countries')
add('B2','passport_country','По паспорту какой страны планируется въезд?','Which country issued the passport to be used for entry?','country',when='multiple_citizenships',depends=('citizenships',))
add('B3','document_type','Тип документа для въезда','Document type for entry','choice',choices=('ordinary','diplomatic','service','un_lp','stateless','refugee','id_card','internal','other','unrecognized'))
add('B4','passport_expiry','До какой даты действует паспорт?','When does the passport expire?','date',depends=('document_type','passport_country'))
fields('B5','passport_', [('two_blank_pages','Есть две чистые страницы?','Are there two blank pages?','boolean'),
    ('undamaged','Паспорт без повреждений и посторонних отметок?','Is the passport free of damage and unofficial marks?','boolean')],depends=('document_type','passport_country'))
add('B6','residence_country','Страна постоянного проживания','Country of permanent residence','country')
add('B6','foreign_residence.exists','Есть вид на жительство или резидент-карта другой страны?','Do you hold another country’s residence permit or card?','boolean')
fields('B6','foreign_residence.', [('country','Страна резидентского документа','Residence document country','country'),
    ('until','Срок действия резидентского документа','Residence document expiry','date')],when='foreign_residence',depends=('foreign_residence.exists',))
add('B7','long_visa.exists','Есть виза США, Великобритании или Шенгена со сроком действия более трёх лет?','Do you have a US, UK or Schengen visa valid for more than three years?','boolean',when='china_india',depends=('citizenships',))
fields('B7','long_visa.', [('country','Страна долгосрочной визы','Long-term visa country','country'),
    ('from','Начало действия долгосрочной визы','Long-term visa valid from','date'),
    ('until','Конец действия долгосрочной визы','Long-term visa valid until','date')],when='long_visa',depends=('long_visa.exists',))
add('B8','location','Где сейчас заявитель?','Where is the applicant now?','choice',choices=('abroad','in_kg'))
add('B8','current_country','Текущая страна пребывания','Current country of stay','country',when='abroad',depends=('location',))
fields('B8','actual_entry.', [('on','Дата фактического въезда в Кыргызстан','Actual entry date into Kyrgyzstan','date'),
    ('point','Пункт фактического въезда','Actual entry crossing','text')],when='in_kg',depends=('location',))
add('C1','purpose','Фактическая цель поездки','Actual purpose of the trip','choice',choices=('tourism','private_visit','relatives_kg_citizen','family_of_foreigner','business_meeting','event','sport','medical','study','work_hire','work_individual_employer','entrepreneur','investor','it_remote','journalism','volunteer','equipment_installation','transit','religious','driver','accompanying_gcc','official','other'))
add('C2','purpose_detail','Что планируется делать: организация, занятие или родственная связь? Без диагнозов.','What is planned: organization, activity or family relationship? Do not include diagnoses.','text',when='detailed_purpose',depends=('purpose',),maximum=500)
add('C3','entry_on','Планируемая дата въезда','Planned entry date','date')
add('C4','exit_on','Планируемая дата выезда','Planned exit date','date')
add('C5','multiple_entries','Планируются выезды и возвращения в этой поездке?','Will this trip include departures and re-entries?','boolean')
add('C6','planned_entry_point','Планируемый аэропорт или наземный пункт въезда','Planned airport or land entry crossing','text')
add('C7','tickets_bought','Билеты уже куплены?','Have tickets already been purchased?','boolean')
add('C8','accommodation_address','Планируемое место проживания и адрес','Planned accommodation and address','text',maximum=500)
add('C9','hard_deadline.exists','Есть жёсткая дата получения результата?','Is there a fixed date by which the result is needed?','boolean')
add('C9','hard_deadline.on','Какая именно дата?','What is that date?','date',when='hard_deadline',depends=('hard_deadline.exists',))
add('C10','organized_group.exists','Поездка в организованной группе?','Is this an organized group trip?','boolean',when='tourism',depends=('purpose',))
fields('C10','organized_group.', [('size','Число участников организованной группы','Organized group size','integer'),
    ('operator','Организатор группы','Group operator','text')],when='organized_group',depends=('organized_group.exists',))
fields('C11','event.', [('from','Начало мероприятия или лечения','Event or treatment start date','date'),
    ('to','Окончание мероприятия или лечения','Event or treatment end date','date')],when='event',depends=('purpose',))
add('D1','previous_visits','Заявитель раньше бывал в Кыргызстане?','Has the applicant previously visited Kyrgyzstan?','boolean')
add('D1','history_count','Сколько интервалов пребывания нужно записать?','How many stay intervals need to be recorded?','integer',when='previous_visits',depends=('previous_visits',),maximum=100)
fields('D1','history.{i}.', [('entry','Дата въезда по этому интервалу','Entry date for this interval','date'),
    ('exit','Дата выезда по этому интервалу','Exit date for this interval','date'),
    ('passport_country','Страна паспорта этого въезда','Passport country used for this entry','country')],when='history_member',depends=('history_count',))
add('D2','reported_window','За какое окно заявитель сам сообщает число дней? Это не расчёт режима.','For which window does the applicant report days? This is not an eligibility calculation.','choice',choices=('60','120','180','360'),when='previous_visits',depends=('previous_visits',))
add('D2','reported_days','Сообщённое заявителем число дней в этом окне','Applicant-reported days in that window','integer',when='reported_window',depends=('reported_window',),maximum=360)
fields('D3','risk.', [('overstay','Были просрочки пребывания?','Have there been overstays?','boolean'),
    ('fines','Были штрафы в Кыргызстане?','Have there been fines in Kyrgyzstan?','boolean'),
    ('deportation','Было выдворение или депортация?','Has there been expulsion or deportation?','boolean'),
    ('entry_ban','Был запрет на въезд?','Has there been an entry ban?','boolean')])
add('D3','risk.ban_until','До какой даты действует известный запрет?','Until what date does the known ban apply?','date',when='entry_ban',depends=('risk.entry_ban',))
add('D4','previous_refusal','Были отказы в визе Кыргызстана?','Has a Kyrgyzstan visa been refused before?','boolean')
fields('D4','refusal.', [('on','Дата прежнего отказа','Previous refusal date','date'),
    ('type','Тип визы по прежнему отказу','Visa type of the previous refusal','text')],when='previous_refusal',depends=('previous_refusal',))
add('D5','previous_visa_count','Сколько прежних виз Кыргызстана нужно записать?','How many previous Kyrgyzstan visas need to be recorded?','integer',when='previous_visits',depends=('previous_visits',),maximum=20)
fields('D5','previous_visa.{i}.', [('type','Тип прежней визы','Previous visa type','text'),
    ('from','Начало действия прежней визы','Previous visa valid from','date'),
    ('until','Конец действия прежней визы','Previous visa valid until','date')],when='previous_visa_member',depends=('previous_visa_count',))
add('E1','current_basis','На каком основании заявитель сейчас в Кыргызстане?','What is the applicant’s current basis of stay in Kyrgyzstan?','choice',choices=('visa_free','visa','ep','resident_card','residence_permit','none'),when='in_kg',depends=('location',))
add('E1','current_visa_type','Тип текущей визы','Current visa type','text',when='current_visa',depends=('current_basis',))
add('E2','registration.exists','Есть действующая регистрация?','Is there a valid registration?','boolean',when='in_kg',depends=('location',))
fields('E2','registration.', [('until','До какой даты действует регистрация?','When does registration expire?','date'),
    ('address','Адрес регистрации','Registration address','text')],when='registered',depends=('registration.exists',))
add('E3','current_inviter','Кто оформлял текущую визу или приглашение?','Who arranged the current visa or invitation?','text',when='current_visa',depends=('current_basis',))
add('E4','current_until','До какой даты действует текущее основание пребывания?','When does the current basis of stay expire?','date',when='in_kg',depends=('location','current_basis'))
add('E5','residence_petition','Подано ходатайство о ВНЖ или гражданстве?','Has a residence or citizenship application been submitted?','boolean',when='in_kg',depends=('location',))
add('E6','declared_purpose','Какая цель была заявлена при въезде?','What purpose was declared on entry?','text',when='in_kg',depends=('location',))
add('F1','inviter.exists','Есть приглашающая сторона в Кыргызстане?','Is there an inviting party in Kyrgyzstan?','boolean',when='inviter_needed',depends=('purpose',))
add('F1','inviter.type','Тип приглашающей стороны','Type of inviting party','choice',choices=('company','university','clinic','relative','government','other'),when='inviter',depends=('inviter.exists',))
fields('F2','inviter.', [('name','Название приглашающей стороны','Inviting party name','text'),
    ('tax_id','ИНН приглашающей стороны','Inviting party tax identifier','text'),
    ('contact','Контактное лицо приглашающей стороны','Inviting party contact person','text'),
    ('phone','Телефон приглашающей стороны','Inviting party phone','text'),
    ('email','E-mail приглашающей стороны','Inviting party email','text')],when='inviter',depends=('inviter.exists',))
fields('F3','inviter.', [('letter','Готовы выдать письмо с подписью и печатью?','Can they issue a signed and stamped letter?','boolean'),
    ('constituent_documents','Готовы предоставить учредительные документы?','Can they provide incorporation documents?','boolean'),
    ('portal_account','Есть кабинет на портале?','Do they have a portal account?','boolean')],when='inviter',depends=('inviter.exists',))
fields('F4','inviter.', [('tax_debt_absent','Подтверждено отсутствие налогового долга?','Has absence of tax arrears been confirmed?','boolean'),
    ('social_debt_absent','Подтверждено отсутствие долга по соцвзносам?','Has absence of social contribution arrears been confirmed?','boolean')],when='employer_or_study',depends=('purpose','inviter.exists'))
fields('F5','employment.', [('position','Должность','Job title','text'),
    ('salary_kgs','Заявленная зарплата в сомах за месяц','Reported monthly salary in KGS','decimal'),
    ('contract_from','Начало трудового договора','Employment contract start','date'),
    ('contract_until','Конец трудового договора','Employment contract end','date'),
    ('workplace','Место работы','Workplace','text')],when='work',depends=('purpose',))
add('F5','employment.form','Найм или индивидуальное предпринимательство?','Employment or individual entrepreneurship?','choice',choices=('employment','individual_business'),when='work',depends=('purpose',))
fields('F6','employment.', [('prior_permits','Работодатель ранее оформлял ЕР?','Has the employer obtained unified permits before?','boolean'),
    ('quota','Есть одобренная квота?','Is there an approved quota?','boolean')],when='work',depends=('purpose',))
add('F7','employment.sector','Отрасль работодателя','Employer industry','text',when='work',depends=('purpose',))
add('F7','employment.garment','Работодатель занимается швейным производством?','Does the employer operate in garment manufacturing?','boolean',when='work',depends=('purpose',))
add('F7','employment.chamber_member','Работодатель состоит в ТПП?','Is the employer a chamber of commerce member?','boolean',when='garment',depends=('employment.garment',))
add('F8','permit.exists','Есть действующее ЕР или разрешение?','Is there an existing unified or work permit?','boolean',when='work_in_kg',depends=('purpose','location'))
fields('F8','permit.', [('number','Номер действующего разрешения','Existing permit number','text'),
    ('until','Срок действующего разрешения','Existing permit expiry','date')],when='permit',depends=('permit.exists',))
fields('F9','company.', [('exists','Есть собственная компания или ИП в Кыргызстане?','Do you own a company or individual business in Kyrgyzstan?','boolean'),
    ('planned','Планируется открыть компанию или ИП?','Do you plan to establish a company or individual business?','boolean')],when='business',depends=('purpose',))
add('F9','company.form','Компания или ИП?','Company or individual business?','choice',choices=('company','individual_business'),when='company',depends=('company.exists','company.planned'))
fields('F10','investment.', [('amount_kgs','Заявленная сумма инвестиций в сомах','Reported investment amount in KGS','decimal'),
    ('authority_letter','Есть письмо органа по инвестициям?','Is there a letter from the investment authority?','boolean')],when='investor',depends=('purpose',))
add('G1','family_count','Сколько членов семьи едет с заявителем? Ноль — никто.','How many family members will travel with the applicant? Zero means none.','integer',maximum=20)
add('G1','applicant.age','Возраст самого заявителя','Applicant’s own age','integer',maximum=150)
add('G1','applicant.family_relation','Кем заявитель приходится основному члену семьи в Кыргызстане?','How is the applicant related to the principal family member in Kyrgyzstan?','choice',choices=('spouse','child','parent','other'),when='family_purpose',depends=('purpose',))
add('G3','relationship_document.exists','Есть свидетельство о родстве самого заявителя?','Does the applicant have their own relationship certificate?','boolean',when='family_purpose',depends=('purpose','applicant.family_relation'))
fields('G3','relationship_document.', [('country','Страна выдачи документа о родстве заявителя','Country issuing the applicant’s relationship certificate','country'),
    ('apostille','Есть апостиль или легализация документа заявителя?','Is the applicant’s certificate apostilled or legalized?','boolean'),
    ('translation','Есть перевод документа заявителя?','Is the applicant’s certificate translated?','boolean')],when='own_family_document',depends=('purpose','applicant.family_relation','relationship_document.exists'))
add('G5','applicant.both_parents','Сам несовершеннолетний заявитель едет с обоими родителями?','Will the minor applicant travel with both parents?','boolean',when='own_minor',depends=('applicant.age',))
add('G6','applicant.born_in_kg','Сам несовершеннолетний заявитель родился в Кыргызстане?','Was the minor applicant born in Kyrgyzstan?','boolean',when='own_minor',depends=('applicant.age',))
fields('G6','applicant.', [('birth_on','Дата рождения самого заявителя','Applicant’s own date of birth','date'),
    ('passport_received','Сам заявитель получил паспорт?','Has the applicant received a passport?','boolean')],when='own_child_born_kg',depends=('applicant.age','applicant.born_in_kg'))
add('G7','applicant.dependent','Сам заявитель — родитель или совершеннолетний ребёнок на иждивении?','Is the applicant a dependent parent or adult child?','boolean',when='own_adult_child_or_parent',depends=('purpose','applicant.family_relation','applicant.age'))
add('G7','applicant.disability_basis','Для самого совершеннолетнего ребёнка заявлено основание инвалидности? Без диагноза.','Is disability claimed as a basis for the adult child applicant? Do not provide a diagnosis.','boolean',when='own_adult_child',depends=('purpose','applicant.family_relation','applicant.age'))
add('G1','family.{i}.relation','Родство члена семьи №{i}','Relationship of family member #{i}','choice',choices=('spouse','child','parent','other'),when='family_member',depends=('family_count',))
add('G1','family.{i}.age','Возраст ребёнка №{i}','Age of child #{i}','integer',when='child',depends=('family_count','family.{i}.relation'),maximum=2147483647)
fields('G2','family.{i}.', [('together','Член семьи №{i} въезжает вместе с заявителем?','Will family member #{i} enter with the applicant?','boolean'),
    ('later','Член семьи №{i} въезжает позже?','Will family member #{i} enter later?','boolean')],when='family_member',depends=('family_count',))
add('G3','family.{i}.relationship_document','Есть свидетельство о родстве для члена семьи №{i}?','Is there a relationship certificate for family member #{i}?','boolean',when='family_purpose_member',depends=('family_count','purpose','family.{i}.relation'))
fields('G3','family.{i}.', [('document_country','Страна выдачи документа о родстве №{i}','Country issuing relationship certificate #{i}','country'),
    ('apostille','Есть апостиль или легализация документа №{i}?','Is certificate #{i} apostilled or legalized?','boolean'),
    ('translation','Есть перевод документа №{i}?','Is there a translation of certificate #{i}?','boolean')],when='family_document',depends=('family_count','purpose','family.{i}.relation','family.{i}.relationship_document'))
add('G4','principal.status','Статус основного члена семьи в Кыргызстане','Principal family member’s status in Kyrgyzstan','choice',choices=('citizen','ep','resident_card','residence_permit','visa','none'),when='foreign_family_purpose',depends=('purpose',))
add('G4','principal.until','До какой даты действует документ основного члена семьи?','When does the principal family member’s document expire?','date',when='principal_document',depends=('principal.status',))
add('G5','family.{i}.both_parents','Ребёнок №{i} едет с обоими родителями?','Will child #{i} travel with both parents?','boolean',when='minor_child',depends=('family_count','family.{i}.relation','family.{i}.age'))
add('G6','family.{i}.born_in_kg','Ребёнок №{i} родился в Кыргызстане?','Was child #{i} born in Kyrgyzstan?','boolean',when='child',depends=('family_count','family.{i}.relation'))
fields('G6','family.{i}.', [('birth_on','Дата рождения ребёнка №{i}','Child #{i} date of birth','date'),
    ('passport_received','Ребёнок №{i} получил паспорт?','Has child #{i} received a passport?','boolean')],when='child_born_kg',depends=('family_count','family.{i}.born_in_kg'))
add('G7','family.{i}.dependent','Член семьи №{i} находится на иждивении?','Is family member #{i} a dependant?','boolean',when='adult_child_or_parent',depends=('family_count','family.{i}.relation','family.{i}.age'))
add('G7','family.{i}.disability_basis','Для совершеннолетнего ребёнка №{i} заявлено основание инвалидности? Без диагноза.','Is disability claimed as a basis for adult child #{i}? Do not provide a diagnosis.','boolean',when='adult_child',depends=('family_count','family.{i}.relation','family.{i}.age'))
add('H1','payer','Кто оплачивает услугу?','Who will pay for the service?','choice',choices=('self','company','other'))
fields('H1','commercial.', [('contract','Нужен договор?','Is a contract required?','boolean'),
    ('company_invoice','Нужен счёт на юридическое лицо?','Is a company invoice required?','boolean'),
    ('closing_documents','Нужны закрывающие документы?','Are completion/accounting documents required?','boolean')])
add('H2','payment_preference','Предпочтительный способ оплаты','Preferred payment method','choice',choices=('cash','card','bank_transfer','other'))
add('H3','extra_services','Какие дополнительные услуги интересуют?','Which additional services are of interest?','choices',choices=('hotel','transfer','tour','tickets','insurance','registration'))
add('H4','referral','Откуда узнали о компании?','How did you hear about the company?','text',maximum=200)

PRIMARY = ('citizenships','location','current_country','actual_entry.on','purpose','entry_on','exit_on','document_type',
           'inviter.exists','party_type','applicants_count')
REPEATS = {'family':'family_count','history':'history_count','previous_visa':'previous_visa_count'}


def document():
    return dict(version=VERSION,source_sha256=SOURCE_SHA256,section='3.3 A-H',fields=deepcopy(FIELDS),
                primary=list(PRIMARY),repeats=dict(REPEATS),legal_rules_approved=False,reducer_version='kg-interview-reducer/1')


def digest(value=None):
    return hashlib.sha256(json.dumps(document() if value is None else value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


# Retain these immutable version files when introducing a new active catalog.
# A changed active prompt cannot rewrite or invalidate an older stored interview.
_REGISTRY={}
for _filename in ('interview_catalog_v3_1.json',):
    _stored=json.loads((Path(__file__).resolve().parents[2]/'knowledge/kg_entry'/_filename).read_text(encoding='utf-8'))
    _REGISTRY[digest(_stored)]=_stored


def by_digest(value):
    if type(value) is not str or value not in _REGISTRY:raise ValueError('unsupported_interview_catalog')
    return deepcopy(_REGISTRY[value])


def expanded(counts,*,catalog_document=None):
    source=document() if catalog_document is None else catalog_document
    result=[]
    for field in source['fields']:
        if '{i}' not in field['path']:
            result.append(deepcopy(field));continue
        parent=source['repeats'][field['path'].split('.')[0]]
        count=counts.get(parent)
        if type(count) is not int:continue
        for i in range(1,count+1):
            item=deepcopy(field)
            for key in ('path','ru','en'):item[key]=item[key].replace('{i}',str(i))
            item['depends']=[p.replace('{i}',str(i)) for p in item['depends']]
            item['member']=i;result.append(item)
    return result
