"""Post-issue metadata facts. Verification never grants permission to travel."""
from copy import deepcopy
from datetime import date
import re

from app.domain.entry_storage import EntryStorageInvalid

CHECKS = {
    'name': 'ФИО и латиница по MRZ', 'birth_date': 'Дата рождения',
    'sex_citizenship': 'Пол и гражданство', 'passport_number': 'Номер паспорта для въезда',
    'passport_dates': 'Даты паспорта, если указаны', 'visa_type': 'Категория и тип по заказу',
    'entries': 'Кратность по маршруту', 'validity': 'Срок действия по датам поездки',
    'stay_duration': 'Срок пребывания', 'inviter': 'Приглашающая сторона по письму',
    'qr': 'QR-код открывает запись портала', 'photo': 'Фото заявителя',
}
CHANNELS = {'messenger': 'Мессенджер', 'email': 'E-mail', 'crm': 'Копия в CRM'}
CAUSES = {'authority': 'Ошибка госоргана', 'company': 'Ошибка в нашей анкете',
          'client': 'Данные клиента / другой паспорт', 'unknown': 'Причина пока неизвестна'}
FIELDS = {
    'file': {'fingerprint', 'passport_fingerprint', 'on'},
    'review': {'version', 'fingerprint', 'passport_fingerprint', 'on', 'checks'},
    'correction': {'version', 'fingerprint', 'on', 'cause', 'proof'},
    'delivery': {'version', 'fingerprint', 'on', 'channel', 'proof', 'pamphlet'},
    'receipt': {'version', 'fingerprint', 'on', 'proof', 'identity_checked'},
    'passport_change': {'passport_fingerprint', 'on'},
    'travel': {'direction', 'on', 'proof', 'source', 'passport_fingerprint'},
}
MAX_REVISIONS = 250
MAX_BYTES = 4*1024*1024
CHECKLIST_DEFINITION = {
    'version': 'pdf-1.1-issued-checks/1', 'section': '16.1', 'page': 68,
    'source_sha256': '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2',
    'checks': CHECKS,
}


def invalid(code='invalid_issued_operation'):
    raise EntryStorageInvalid(code)


def normalize(operation, *, cutoff):
    if type(operation) is not dict or set(operation) != {'action', 'data', 'confirmed'}:
        invalid()
    action = operation['action']; data = operation['data']
    if type(action) is not str or action not in FIELDS or type(data) is not dict or set(data) != FIELDS[action]:
        invalid()
    if operation['confirmed'] is not True:
        invalid('issued_confirmation_required')
    for key in ('fingerprint', 'passport_fingerprint', 'proof', 'pamphlet'):
        if key in data and (type(data[key]) is not str or not re.fullmatch('[a-f0-9]{64}', data[key])):
            invalid('invalid_issued_fingerprint')
    if 'version' in data and (type(data['version']) is not int or not 1 <= data['version'] <= MAX_REVISIONS):
        invalid('invalid_issued_version')
    try:
        day = date.fromisoformat(data['on'])
        if day.isoformat() != data['on'] or day > cutoff:
            raise ValueError
    except (ValueError, TypeError):
        invalid('invalid_issued_date')
    if action == 'review':
        checks = data['checks']
        if type(checks) is not dict or set(checks) != set(CHECKS):
            invalid('incomplete_issued_checks')
        for key, value in checks.items():
            if type(value) is not bool and value is not None and not (key == 'passport_dates' and value == 'not_present'):
                invalid('invalid_issued_checks')
    if action == 'correction' and (type(data['cause']) is not str or data['cause'] not in CAUSES):
        invalid()
    if action == 'delivery' and (type(data['channel']) is not str or data['channel'] not in CHANNELS):
        invalid()
    if action == 'receipt' and type(data['identity_checked']) is not bool and data['identity_checked'] is not None:
        invalid('invalid_issued_recipient_check')
    if action == 'travel' and (data['direction'] not in ('entry', 'exit') or data['source'] not in ('stamp', 'official_record')):
        invalid('invalid_actual_travel_fact')
    return deepcopy(operation)


def verified(snapshot):
    review = snapshot.get('review')
    return bool(review and not snapshot.get('correction') and
                review['version'] == snapshot['version'] and
                review['passport_revision'] == snapshot['passport_revision'] and
                review['passport_fingerprint'] == snapshot['current_passport'] == snapshot['issued_passport'] and
                all(value is True or key == 'passport_dates' and value == 'not_present'
                    for key, value in review['checks'].items()))


def apply_operation(snapshot, operation, *, actor, approved_on):
    action = operation['action']; data = operation['data']
    result = deepcopy(snapshot) if snapshot else dict(format='entry-issued-document/1', definition=deepcopy(CHECKLIST_DEFINITION),version=0,
        fingerprint=None, issued_passport=None, current_passport=None, passport_revision=0, passport_checked_on=None, issued_on=None,
        review=None, correction=None, deliveries={}, receipt=None, travel=[])
    if action == 'file':
        if data['on'] < approved_on or result['issued_on'] and data['on'] < result['issued_on']:
            invalid('invalid_issued_date')
        if data['fingerprint'] == result['fingerprint']:
            invalid('issued_content_unchanged')
        if result['current_passport'] is not None and data['passport_fingerprint'] != result['current_passport']:
            invalid('issued_passport_mismatch')
        passport_checked_on=max(data['on'],result['passport_checked_on'] or data['on'])
        result.update(version=result['version']+1, fingerprint=data['fingerprint'],passport_revision=result['passport_revision'] or 1,
            issued_passport=data['passport_fingerprint'], current_passport=data['passport_fingerprint'],
            issued_on=data['on'],passport_checked_on=passport_checked_on, review=None, correction=None, deliveries={}, receipt=None)
        return result
    if action == 'travel':
        if any(f['proof'] == data['proof'] or (f['direction'],f['on'],f['passport_fingerprint']) ==
               (data['direction'],data['on'],data['passport_fingerprint']) for f in result['travel']):
            invalid('duplicate_actual_travel_fact')
        # Actual facts can arrive late or reveal a missed internal check. Retain
        # the evidence, without claiming the trip was authorized or a task done.
        result['travel'].append({**data, 'actor': actor})
        return result
    if not result['version']:
        invalid('issued_file_missing')
    if action == 'passport_change':
        if data['passport_fingerprint'] == result['current_passport']:
            invalid('issued_passport_unchanged')
        if data['on'] < result['passport_checked_on']:
            invalid('invalid_issued_date')
        result['current_passport'] = data['passport_fingerprint']
        result['passport_revision'] += 1
        result['passport_checked_on'] = data['on']
        return result
    if data['version'] != result['version'] or data['fingerprint'] != result['fingerprint']:
        invalid('issued_version_changed')
    if data['on'] < result['issued_on']:
        invalid('invalid_issued_date')
    if action == 'review':
        if data['passport_fingerprint'] != result['current_passport'] or data['passport_fingerprint'] != result['issued_passport']:
            invalid('issued_passport_mismatch')
        if result['review'] and data['on'] < result['review']['on']:
            invalid('invalid_issued_date')
        if data['on'] < result['passport_checked_on']:
            invalid('invalid_issued_date')
        generation=result['review']['generation']+1 if result['review'] else 1
        result['review'] = {**data, 'actor': actor,'passport_revision':result['passport_revision'],'generation':generation}
        # A correction is resolved by a replacement official file, not by checking
        # the same erroneous file again. New file operation clears correction.
    elif action == 'correction':
        result['correction'] = {**data, 'actor': actor}
    elif action == 'delivery':
        if not verified(result):
            invalid('issued_review_required')
        if data['on'] < result['review']['on']:
            invalid('invalid_issued_date')
        previous = result['deliveries'].get(data['channel'])
        if previous and (previous['proof'] == data['proof'] or data['on'] < previous['on']):
            invalid('issued_delivery_already_recorded')
        result['deliveries'][data['channel']] = {**data, 'actor': actor,'passport_revision':result['passport_revision'],
                                                'review_generation':result['review']['generation']}
    elif action == 'receipt':
        client_deliveries = [v for k,v in result['deliveries'].items() if k in ('email','messenger')]
        if not client_deliveries or data['on'] < min(d['on'] for d in client_deliveries):
            invalid('issued_delivery_missing')
        if result['receipt'] is not None and (result['receipt']['proof']==data['proof'] or
            result['receipt']['passport_revision']==result['passport_revision'] and result['receipt']['identity_checked'] is True):
            invalid('issued_receipt_already_recorded')
        result['receipt'] = {**data, 'actor': actor,'passport_revision':result['passport_revision']}
    return result


def summarize(snapshot):
    return dict(version=snapshot['version'], verification_current=verified(snapshot),
                correction_pending=bool(snapshot['correction']),
                delivery_complete=bool(verified(snapshot) and set(snapshot['deliveries']) == set(CHANNELS) and
                    all(d['passport_revision']==snapshot['passport_revision'] and
                        d['review_generation']==snapshot['review']['generation'] for d in snapshot['deliveries'].values())),
                receipt_recorded=snapshot['receipt'] is not None,
                receipt_current_and_checked=bool(snapshot['receipt'] and verified(snapshot) and snapshot['receipt']['identity_checked'] is True and
                    snapshot['receipt']['passport_revision']==snapshot['passport_revision']),
                actual_entries=sum(f['direction']=='entry' for f in snapshot['travel']),
                actual_exits=sum(f['direction']=='exit' for f in snapshot['travel']),
                travel_permission_granted=False, service_completed=False)
