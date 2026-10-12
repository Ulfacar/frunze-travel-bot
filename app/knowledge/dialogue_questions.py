"""Bounded client questions and exact labelled answers; no collection authority.

The caller must prove current consent, a provider-accepted prompt and matching
interview head. A successful parse alone grants neither collection nor sending.
Historical prompts use this retained renderer, never arbitrary stored wording.
"""
from dataclasses import asdict
import re
import unicodedata

from . import interview_catalog as catalog, interview_rules as rules
from .dialogue_interrupts import MAX_TEXT, triage

VERSION = 'kg-dialogue-questions/1'
CATALOG_HASH = 'aa5aafeb14cf76b920eb86b16121c0e2da81ddf0631f878074ae519791c83744'

# Explicitly reviewed client wording. Operator evidence/consent/terms fields,
# free prose and repeated-person questions are deliberately not admitted.
QUESTIONS = {
    'citizenships': ('Какие у вас гражданства?', 'What citizenships do you hold?'),
    'passport_country': ('Какая страна выдала паспорт для этой поездки?', 'Which country issued the passport for this trip?'),
    'document_type': ('Какой документ вы используете для въезда?', 'Which document will you use for entry?'),
    'passport_expiry': ('До какой даты действует ваш паспорт?', 'When does your passport expire?'),
    'passport_two_blank_pages': ('В паспорте есть две чистые страницы?', 'Does your passport have two blank pages?'),
    'passport_undamaged': ('Паспорт без повреждений и посторонних отметок?', 'Is your passport free of damage and unofficial marks?'),
    'residence_country': ('В какой стране вы постоянно проживаете?', 'In which country do you permanently live?'),
    'foreign_residence.exists': ('У вас есть вид на жительство или резидент-карта другой страны?', 'Do you hold another country’s residence permit or card?'),
    'long_visa.exists': ('Есть виза США, Великобритании или Шенгена со сроком действия более трёх лет?', 'Do you have a US, UK or Schengen visa valid for more than three years?'),
    'location': ('Где вы сейчас находитесь?', 'Where are you now?'),
    'current_country': ('В какой стране вы сейчас находитесь?', 'Which country are you in now?'),
    'actual_entry.on': ('Когда вы фактически въехали в Кыргызстан?', 'When did you actually enter Kyrgyzstan?'),
    'entry_on': ('Когда вы планируете въехать в Кыргызстан?', 'When do you plan to enter Kyrgyzstan?'),
    'exit_on': ('Когда вы планируете выехать из Кыргызстана?', 'When do you plan to leave Kyrgyzstan?'),
    'multiple_entries': ('Планируете выезжать и возвращаться в этой поездке?', 'Do you plan to leave and re-enter during this trip?'),
    'tickets_bought': ('Билеты уже куплены?', 'Have you already bought tickets?'),
    'hard_deadline.exists': ('Есть точная дата, к которой нужен результат?', 'Is there a fixed date by which you need the result?'),
    'hard_deadline.on': ('К какой дате нужен результат?', 'By which date do you need the result?'),
    'organized_group.exists': ('Вы едете в организованной группе?', 'Are you travelling in an organized group?'),
    'previous_visits': ('Вы раньше бывали в Кыргызстане?', 'Have you visited Kyrgyzstan before?'),
    'risk.overstay': ('У вас были просрочки пребывания в Кыргызстане?', 'Have you overstayed in Kyrgyzstan before?'),
    'risk.fines': ('У вас были штрафы в Кыргызстане?', 'Have you had fines in Kyrgyzstan?'),
    'risk.deportation': ('У вас было выдворение или депортация?', 'Have you been expelled or deported?'),
    'risk.entry_ban': ('У вас был запрет на въезд?', 'Have you had an entry ban?'),
    'previous_refusal': ('Вам раньше отказывали в визе Кыргызстана?', 'Have you been refused a Kyrgyzstan visa before?'),
    'current_basis': ('На каком основании вы сейчас находитесь в Кыргызстане?', 'What is your current basis of stay in Kyrgyzstan?'),
    'current_until': ('До какой даты вам разрешено текущее пребывание в Кыргызстане?', 'Until which date is your current stay in Kyrgyzstan permitted?'),
    'registration.exists': ('У вас есть действующая регистрация?', 'Do you have a valid registration?'),
    'registration.until': ('До какой даты действует регистрация?', 'When does your registration expire?'),
    'residence_petition': ('Вы подали ходатайство о ВНЖ или гражданстве?', 'Have you submitted a residence or citizenship application?'),
    'inviter.exists': ('У вас есть приглашающая сторона в Кыргызстане?', 'Do you have an inviting party in Kyrgyzstan?'),
    'party_type': ('Для кого это обращение?', 'Who is this request for?'),
    'applicants_count': ('Сколько всего заявителей?', 'How many applicants are there in total?'),
    'applicant.age': ('Сколько вам полных лет?', 'How old are you in completed years?'),
    'family_count': ('Сколько членов семьи едет с вами?', 'How many family members will travel with you?'),
}
OPTIONS = {
    'document_type': (
        ('ordinary', 'Обычный паспорт', 'Ordinary passport'),
        ('diplomatic', 'Дипломатический паспорт', 'Diplomatic passport'),
        ('service', 'Служебный паспорт', 'Service passport'),
        ('un_lp', 'Документ ООН', 'UN laissez-passer'),
        ('stateless', 'Документ лица без гражданства', 'Stateless person document'),
        ('refugee', 'Документ беженца', 'Refugee document'),
        ('id_card', 'ID-карта', 'ID card'),
        ('internal', 'Внутренний паспорт', 'Internal passport'),
        ('other', 'Другой документ', 'Other document'),
        ('unrecognized', 'Непризнанный документ', 'Unrecognized document')),
    'location': (('abroad', 'За пределами Кыргызстана', 'Outside Kyrgyzstan'), ('in_kg', 'В Кыргызстане', 'In Kyrgyzstan')),
    'current_basis': (
        ('visa_free', 'Безвизовое пребывание', 'Visa-free stay'), ('visa', 'Виза', 'Visa'),
        ('ep', 'Единое разрешение', 'Unified permit'), ('resident_card', 'Резидент-карта', 'Resident card'),
        ('residence_permit', 'Вид на жительство', 'Residence permit'), ('none', 'Нет основания', 'No basis')),
    'party_type': (('individual', 'Один заявитель', 'One applicant'), ('family', 'Семья', 'Family'),
                   ('group', 'Группа', 'Group'), ('company', 'Компания', 'Company')),
}
HINTS = {
    'boolean': ('Ответ: да или нет.', 'Answer: yes or no.'),
    'date': ('Дата: ГГГГ-ММ-ДД.', 'Date: YYYY-MM-DD.'),
    'integer': ('Ответ: целое число.', 'Answer: a whole number.'),
    'country': ('Ответ: трёхбуквенный код страны, например RUS.', 'Answer: a three-letter country code, for example RUS.'),
    'countries': ('Ответ: трёхбуквенные коды через запятую, например RUS, KAZ.', 'Answer: three-letter codes separated by commas, for example RUS, KAZ.'),
}
MAP_HASH = rules.digest(dict(version=VERSION, catalog=CATALOG_HASH, questions=QUESTIONS, options=OPTIONS, hints=HINTS))


class QuestionInvalid(ValueError):
    pass


def _catalog(document):
    if type(document) is not dict or catalog.digest(document) != CATALOG_HASH:
        raise QuestionInvalid('unsupported_client_question_catalog')
    return {f['path']: f for f in document['fields']}


def render(*, batch, paths, language, catalog_document):
    """Render all exact caller-selected drafts. This does not mark them as sent."""
    fields = _catalog(catalog_document)
    if (type(batch) is not int or not 1 <= batch <= 1000 or language not in ('ru', 'en') or
            type(paths) is not list or not 1 <= len(paths) <= 3 or
            any(type(p) is not str or p not in QUESTIONS or p not in fields for p in paths) or
            len(set(paths)) != len(paths)):
        raise QuestionInvalid('unsupported_client_question_batch')
    lang = 0 if language == 'ru' else 1
    displayed = []; blocks = []
    for i, path in enumerate(paths, 1):
        field = fields[path]; kind = field['kind']; label = f'{batch}.{i}'
        options = OPTIONS.get(path, ())
        if kind == 'choice':
            if [o[0] for o in options] != field['choices']:
                raise QuestionInvalid('unsupported_client_question_options')
            hint = '; '.join(f'{n}: {o[lang+1]}' for n, o in enumerate(options, 1))
        elif kind in HINTS:
            hint = HINTS[kind][lang]
        else:
            raise QuestionInvalid('unsupported_client_question_kind')
        displayed.append(dict(label=label, path=path, kind=kind, options=[o[0] for o in options]))
        blocks.append(f'{label}. {QUESTIONS[path][lang]}\n{hint}')
    intro = ('Ответьте на один вопрос, сохранив его номер. Например: ' if lang == 0 else
             'Answer one question and keep its number. For example: ')
    first = fields[paths[0]]['kind']
    example = {'boolean': ('да', 'yes')[lang], 'date': '2030-12-31', 'country': 'RUS',
               'countries': 'RUS', 'integer': '1', 'choice': '1'}[first]
    body = '\n\n'.join(blocks) + '\n\n' + intro + f'{batch}.1: {example}'
    return dict(format=VERSION, map_hash=MAP_HASH, catalog_hash=CATALOG_HASH, batch=batch,
                language=language, displayed=displayed, body=body, body_hash=rules.digest(body))


def validate_prompt(prompt, *, catalog_document):
    if type(prompt) is not dict:
        raise QuestionInvalid('invalid_client_prompt')
    try:
        expected = render(batch=prompt['batch'], paths=[p['path'] for p in prompt['displayed']],
                          language=prompt['language'], catalog_document=catalog_document)
    except (KeyError, TypeError, ValueError):
        raise QuestionInvalid('invalid_client_prompt') from None
    if prompt != expected:
        raise QuestionInvalid('client_prompt_changed')
    return expected


def parse(prompt, text, *, catalog_document, kind='text', voice=False):
    """Triage full raw input first; parse exactly one labelled literal value."""
    decision = triage(text, kind=kind, voice=voice)
    if decision.reason not in (None, 'uncertain_answer'):
        return dict(action='interrupt', triage=asdict(decision))
    if (type(text) is not str or not text or len(text) > MAX_TEXT or kind != 'text' or
            type(voice) is not bool or voice or any(unicodedata.category(c).startswith('C') for c in text)):
        return dict(action='interrupt', triage=asdict(triage('', kind='unsupported')))
    prompt = validate_prompt(prompt, catalog_document=catalog_document)
    if decision.reason is None:
        return dict(action='acknowledgement')
    match = re.fullmatch(r'([1-9][0-9]{0,3})\.([1-3]):[ ]*([^\r\n]+)', text)
    if not match or int(match[1]) != prompt['batch']:
        return dict(action='interrupt', triage=asdict(decision))
    item = next((p for p in prompt['displayed'] if p['label'] == match[1]+'.'+match[2]), None)
    if item is None:
        return dict(action='interrupt', triage=asdict(decision))
    raw = match[3]; value = raw; kind = item['kind']
    if kind == 'boolean':
        literals = {'да': True, 'нет': False, 'yes': True, 'no': False}
        value = literals.get(raw.casefold())
    elif kind == 'choice':
        value = item['options'][int(raw)-1] if re.fullmatch(r'[1-9][0-9]?', raw) and int(raw) <= len(item['options']) else None
    elif kind == 'integer':
        value = int(raw) if re.fullmatch(r'0|[1-9][0-9]{0,3}', raw) else None
    elif kind == 'countries':
        value = raw.split(', ') if re.fullmatch(r'[A-Z]{3}(, [A-Z]{3}){0,4}', raw) else None
    if value in ('unknown', 'not_applicable'):
        value = None
    try:
        value = rules.validate_value(_catalog(catalog_document)[item['path']], value)
    except rules.InterviewInvalid:
        return dict(action='interrupt', triage=asdict(decision))
    return dict(action='answer', changes={item['path']: value}, displayed=[p['path'] for p in prompt['displayed']],
                batch=prompt['batch'], prompt_hash=rules.digest(prompt))
