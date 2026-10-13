"""Native stay-history form adapter. Dates are facts, not visa calculations."""
from datetime import date
import json
from pathlib import Path
import re

from app.admin.kg_entry_form import FormInvalid

LIMIT = 1000  # Existing storage schema limit, never silently truncate a saved history.
BASES = {'unknown': 'Не установлено', 'visa_free': 'Без визы', 'visa': 'Виза',
         'ep': 'Единое разрешение', 'resident_card': 'Резидент-карта',
         'residence_permit': 'Вид на жительство', 'registration_contract': 'Регистрация / договор'}
EVIDENCE = {'client_statement': 'Со слов клиента', 'passport_stamp': 'Отметка в паспорте',
            'esuvm': 'Сведения ЕСУВМ', 'boarding_pass': 'Посадочный талон',
            'visa_document': 'Визовый документ', 'crm_record': 'Запись CRM'}
ROW_FIELDS = ('entry_date', 'exit_state', 'exit_date', 'basis', 'passport_country',
              'evidence', 'confirmed', 'remove', 'clear_passport')
DEFAULTS = dict(entry_date='', exit_state='', exit_date='', basis='unknown',
                passport_country='', evidence='client_statement', confirmed='false')


def countries():
    source = Path(__file__).resolve().parents[2] / 'knowledge/kg_entry/source_v1_1/iso3166.json'
    result = json.loads(source.read_text(encoding='utf-8'))
    if (type(result) is not dict or not 200 <= len(result) <= 300 or
            any(not re.fullmatch('[A-Z]{3}', k) or not isinstance(v, str) or not 1 <= len(v) <= 100
                for k, v in result.items())):
        raise ValueError('country_catalog_unavailable')
    return result


def values_from_history(document):
    rows = document.get('intervals', [])
    values = {'rows_count': str(min(LIMIT, len(rows) + 1)),
              'history_complete': {True: 'true', False: 'false', None: 'unknown'}[document.get('history_complete')],
              'no_trips': 'yes' if not rows and document.get('history_complete') is True else ''}
    for i, row in enumerate(rows):
        for key in DEFAULTS:
            value = row.get(key)
            if key == 'confirmed': value = 'true' if value else 'false'
            if key == 'exit_state': value = 'date' if row['exit_date'] else 'ongoing'
            values[f'trip.{i}.{key}'] = value or ''
    return values


def row_values(values):
    try:
        count = int(values.get('rows_count', '1'))
        if str(count) != values.get('rows_count', '1') or not 1 <= count <= LIMIT:
            raise ValueError
    except ValueError:
        raise FormInvalid('Недопустимое число строк истории.') from None
    return [{key: values.get(f'trip.{i}.{key}', DEFAULTS.get(key, '')) for key in ROW_FIELDS} for i in range(count)]


def history_overlaps(document):
    """A review hint only; legitimate same-day crossings are not discarded."""
    ends = None
    for row in sorted(document.get('intervals', []), key=lambda r: r['entry_date']):
        if ends is not None and row['entry_date'] <= ends:
            return True
        ends = max(ends or '', row['exit_date'] or document['as_of'])
    return False


def document_from_values(values, *, base, as_of, request_key, country_codes):
    rows = row_values(values)
    old = base.get('intervals', [])
    if len(rows) < len(old):
        raise FormInvalid('Форма неполная. Откройте последнюю историю; поездки нельзя пропускать молча.')
    state = values.get('history_complete')
    if state not in ('true', 'false', 'unknown'):
        raise FormInvalid('Укажите, полностью ли восстановлена история.')
    result = []
    for i, row in enumerate(rows):
        previous = old[i] if i < len(old) else None
        if row['remove'] == 'yes':
            continue
        if not previous and all(row[k] == v for k, v in DEFAULTS.items()) and not row['clear_passport']:
            continue
        # Missing fields must not silently clear a saved row, verification or country.
        if any(f'trip.{i}.{key}' not in values for key in DEFAULTS):
            raise FormInvalid(f'Поездка №{i + 1}: форма неполная. Откройте историю заново.')
        if row['basis'] not in BASES or row['evidence'] not in EVIDENCE or row['confirmed'] not in ('true', 'false'):
            raise FormInvalid(f'Поездка №{i + 1}: выберите значения из списков.')
        try:
            if date.fromisoformat(row['entry_date']).isoformat() != row['entry_date']:
                raise ValueError
            if row['exit_state'] == 'date':
                if date.fromisoformat(row['exit_date']).isoformat() != row['exit_date']:
                    raise ValueError
                end = row['exit_date']
            elif row['exit_state'] == 'ongoing':
                end = None
            else:
                raise ValueError
        except ValueError:
            raise FormInvalid(f'Поездка №{i + 1}: укажите фактические даты или явно выберите «Ещё в Кыргызстане». Неизвестная дата не считается открытой поездкой.') from None
        country = row['passport_country'] or None
        if country and country not in country_codes and (not previous or country != previous['passport_country']):
            raise FormInvalid(f'Поездка №{i + 1}: выберите страну паспорта из списка.')
        passport = previous['passport_ref'] if previous else None
        if row['clear_passport'] == 'yes' or previous and country != previous['passport_country']:
            passport = None
        result.append({'ref': previous['ref'] if previous else f'ui-{request_key[:32]}-{i}',
            'entry_date': row['entry_date'], 'exit_date': end, 'basis': row['basis'], 'passport_country': country,
            'passport_ref': passport, 'evidence': row['evidence'], 'confirmed': row['confirmed'] == 'true'})
    if not result and state == 'true' and values.get('no_trips') != 'yes':
        raise FormInvalid('Подтвердите, что поездок не было, или отметьте историю как неполную.')
    if result and values.get('no_trips') == 'yes':
        raise FormInvalid('Указаны поездки и одновременно выбран ответ «Поездок не было».')
    return {'format': 'kg-stay-history/1', 'as_of': as_of,
            'history_complete': {'true': True, 'false': False, 'unknown': None}[state], 'intervals': result}
