"""Literal approved source answers. No LLM, personal eligibility or delivery."""
import json

from app.domain import knowledge_publication as publication
from app.domain.entry_storage import EntryStorageInvalid, _authorize
from app.domain.models import DomainError
from app.domain.service_authz import PermissionDenied
from app.knowledge.bundle_schema import VALUE_SCHEMAS

FORMAT = 'kg-approved-answer/1'
MAX_ANSWER_BYTES = 32000
COPY = {
    'ru': {
        'intro': 'В действующей утверждённой базе указано:',
        'scope': 'Это сведения из источника. Применимость к конкретному человеку, итоговая стоимость и даты требуют отдельной проверки.',
        'fallback': 'По этой части запроса подтверждённый ответ недоступен. Требуется проверка специалиста.',
        'empty': 'Выберите от одного до трёх правил из журнала проверки.',
        'yes': 'да', 'no': 'нет', 'empty_list': 'пустой список',
    },
    'en': {
        'intro': 'The current approved knowledge source states:',
        'scope': 'These are source facts. Applicability to an individual, total cost and exact dates require a separate review.',
        'fallback': 'A confirmed answer is unavailable for this part of the request. Specialist review is required.',
        'empty': 'Select one to three rules from the review register.',
        'yes': 'yes', 'no': 'no', 'empty_list': 'empty list',
    },
}
KINDS = {
    'visa_free_regime': ('Безвизовый режим', 'Visa-free regime'),
    'registration_exemption': ('Освобождение от регистрации', 'Registration exemption'),
    'registration_default': ('Общее правило регистрации', 'Default registration rule'),
    'registration_term': ('Срок регистрации', 'Registration term'),
    'special_regime': ('Специальный режим', 'Special regime'),
    'visa_required_regime': ('Визовый режим', 'Visa-required regime'),
    'rule_param': ('Параметр правила', 'Rule parameter'),
    'deadline': ('Срок действия', 'Action deadline'),
    'processing_time': ('Срок рассмотрения', 'Processing time'),
    'tariff': ('Отдельный компонент стоимости', 'Individual fee component'),
    'template': ('Утверждённая формулировка', 'Approved wording'),
    'escalation_trigger': ('Условие передачи специалисту', 'Specialist escalation trigger'),
}
# Every structured value is retained. Unknown field semantics fail closed.
LABELS = {
    'days': ('Дни', 'Days'), 'window_days': ('Окно учёта, дни', 'Counting window, days'),
    'work_needs_unified_permit': ('Для работы требуется единое разрешение', 'Work requires a unified permit'),
    'countries': ('Страны (ISO)', 'Countries (ISO)'),
    'deadline_working_days_from_border': ('Рабочие дни от пересечения границы', 'Working days from border crossing'),
    'not_in_list': ('Страны вне списка освобождений (ISO)', 'Countries outside the exemption list (ISO)'),
    'reentry_after_days': ('Повторный въезд через, дни', 'Re-entry after, days'),
    'visa_inside_kg': ('Виза внутри Кыргызстана', 'Visa inside Kyrgyzstan'),
    'requires': ('Требование', 'Requirement'), 'applies_to': ('Область действия', 'Applies to'),
    'document_type': ('Тип документа', 'Document type'), 'condition': ('Условие', 'Condition'),
    'procedure': ('Порядок', 'Procedure'), 'scope': ('Охват', 'Scope'),
    'gknb_approval': ('Согласование ГКНБ', 'GKNB approval'),
    'value': ('Значение', 'Value'), 'unit': ('Единица измерения', 'Unit'),
    'anchor': ('Событие отсчёта', 'Counting anchor'), 'inclusive': ('Включая границу', 'Inclusive boundary'),
    'direction': ('Направление отсчёта', 'Counting direction'), 'timezone': ('Часовой пояс', 'Time zone'),
    'boundary_inclusive': ('Включая граничную дату', 'Boundary date included'),
    'shift_from_nonworking': ('Перенос с нерабочего дня', 'Non-working day adjustment'),
    'standard_wd': ('Стандартный срок, рабочие дни', 'Standard time, working days'),
    'urgent_wd': ('Срочный срок, рабочие дни', 'Urgent time, working days'),
    'urgent_multiplier': ('Множитель срочности', 'Urgency multiplier'),
    'amount': ('Сумма компонента', 'Component amount'), 'currency': ('Валюта', 'Currency'),
    'per': ('За единицу', 'Per'), 'component': ('Компонент стоимости', 'Fee component'),
    'lang': ('Язык источника', 'Source language'), 'text': ('Текст', 'Text'),
    'placeholders': ('Переменные', 'Placeholders'), 'action': ('Действие', 'Action'),
}
ENUMS = {
    'unit': {'days': ('дни', 'days'), 'working_days': ('рабочие дни', 'working days'),
             'calendar_days': ('календарные дни', 'calendar days'), 'hours': ('часы', 'hours'),
             'months': ('месяцы', 'months'), 'bool': ('да/нет', 'yes/no'), 'list': ('список', 'list')},
    'direction': {'before': ('до', 'before'), 'after': ('после', 'after')},
    'shift_from_nonworking': {'none': ('без переноса', 'no adjustment'),
        'next_working': ('на следующий рабочий день', 'next working day'),
        'previous_working': ('на предыдущий рабочий день', 'previous working day')},
    'procedure': {'simplified': ('упрощённый', 'simplified'), 'general': ('общий', 'general')},
    'scope': {'all_types': ('все типы', 'all types'), 'business_tourist': ('деловая / туристическая', 'business / tourist'),
              'tourist_gcc_resident': ('туристическая для резидентов GCC', 'tourist for GCC residents')},
    'per': {'person': ('человек', 'person'), 'application': ('заявление', 'application')},
    'component': {'service': ('услуги', 'service'), 'government': ('государственный сбор', 'government fee'),
                   'bank': ('банк', 'bank'), 'partner': ('партнёр', 'partner')},
    'anchor': {'full_package': ('полный комплект документов', 'full document package')},
}


class _Unrenderable(ValueError):
    pass


def _facts(value, language, prefix=''):
    result = []
    index = 0 if language == 'ru' else 1
    for key, raw in value.items():
        if key not in LABELS or raw is None:
            raise _Unrenderable('answer_value_incomplete_or_unsupported')
        label = prefix + LABELS[key][index]
        if type(raw) is dict:
            if not raw:
                raise _Unrenderable('answer_value_incomplete_or_unsupported')
            result.extend(_facts(raw, language, label + ' / '))
            continue
        if type(raw) is bool:
            rendered = COPY[language]['yes' if raw else 'no']
        elif type(raw) is list:
            if any(type(item) is not str for item in raw):
                raise _Unrenderable('answer_value_incomplete_or_unsupported')
            # JSON quoting preserves item boundaries, including commas in a name.
            rendered = json.dumps(raw, ensure_ascii=False) if raw else COPY[language]['empty_list']
        elif type(raw) in (str, int, float):
            rendered = ENUMS.get(key, {}).get(raw, (str(raw), str(raw)))[index]
        else:
            raise _Unrenderable('answer_value_incomplete_or_unsupported')
        result.append(dict(label=label, value=rendered))
    return result


def _answer(unit, language):
    if unit['kind'] not in VALUE_SCHEMAS:
        raise _Unrenderable('unsupported_answer_kind')
    if unit['condition_rule'] is not None:
        # Condition catalogs are still draft. Publication of a unit is not
        # approval of its extra machine predicates or personal applicability.
        raise _Unrenderable('condition_catalog_requires_specialist')
    value = unit['value']
    if unit['kind'] == 'visa_required_regime' and value['countries'] == 'all_others':
        raise _Unrenderable('catchall_scope_requires_specialist')
    if (unit['kind'] == 'rule_param' and value['unit'] in ('days', 'working_days', 'calendar_days')
            and not {'anchor', 'inclusive'} <= value.keys()):
        raise _Unrenderable('counting_basis_requires_specialist')
    if unit['kind'] == 'template':
        if value['placeholders']:
            raise _Unrenderable('template_requires_personal_facts')
        if value['lang'] != language:
            raise _Unrenderable('approved_translation_unavailable')
    facts = _facts(value, language)
    source = {key: unit[key] for key in ('unit_id', 'version_id', 'version_number', 'version_label',
        'source_document', 'source_hash', 'source_ref', 'page', 'section', 'unit_hash', 'bundle_hash',
        'manifest_hash', 'effective_from', 'effective_to', 'checked_at')}
    paragraphs = [COPY[language]['intro'], unit['title'], KINDS[unit['kind']][0 if language == 'ru' else 1]]
    if unit['kind'] in ('registration_exemption', 'registration_term'):
        paragraphs.append(('Страна (ISO): ' if language == 'ru' else 'Country (ISO): ') + unit['unit_id'].rsplit('.', 1)[1])
    paragraphs.extend(f"{fact['label']}: {fact['value']}" for fact in facts)
    if unit['source_text']:
        paragraphs.append(('Исходный фрагмент: ' if language == 'ru' else 'Original source excerpt: ') + unit['source_text'])
    paragraphs.extend([COPY[language]['scope'],
        f"{source['source_document']} · {source['source_ref']} · {source['section']} · {source['page']}",
        f"{source['unit_id']} · v{source['version_number']} ({source['version_label']})"])
    result = dict(unit_id=unit['unit_id'], kind=unit['kind'], title=unit['title'], facts=facts, source_text=unit['source_text'],
                  source=source, text='\n'.join(paragraphs), applicability='not_evaluated')
    if len(json.dumps(result, ensure_ascii=False).encode('utf-8')) > MAX_ANSWER_BYTES:
        raise _Unrenderable('answer_size_limit')
    return result


async def answer_knowledge(engine, *, actor, policy, unit_ids, language='ru'):
    """Recheck exact source IDs on every call; unavailable values never leave this API."""
    _authorize(actor)
    if type(language) is not str or language not in COPY:
        raise EntryStorageInvalid('invalid_answer_language')
    ids = publication._identifiers(unit_ids, maximum=3)
    try:
        runtime = await publication.runtime_knowledge(engine, actor=actor, policy=policy, unit_ids=ids)
    except PermissionDenied:
        raise
    except DomainError:
        runtime = dict(version_id=None, available=[], unavailable=[
            dict(unit_id=identifier, reasons=['knowledge_unavailable']) for identifier in ids])
    answers = []
    unavailable = list(runtime['unavailable'])
    for unit in runtime['available']:
        try:
            answers.append(_answer(unit, language))
        except _Unrenderable as exc:
            unavailable.append(dict(unit_id=unit['unit_id'], reasons=[str(exc)]))
    unavailable.sort(key=lambda item: item['unit_id'])
    return dict(format=FORMAT, language=language, version_id=runtime['version_id'], answers=answers,
        unavailable=unavailable, status='partial' if answers and unavailable else 'answered' if answers else 'specialist_required',
        requires_specialist=bool(unavailable), fallback=COPY[language]['fallback'] if unavailable else None,
        scope=COPY[language]['scope'], personal_eligibility='not_evaluated', delivery='not_sent')
