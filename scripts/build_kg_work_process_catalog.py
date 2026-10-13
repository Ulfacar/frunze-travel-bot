"""Derive a separate unapproved work-process revision; never rewrite v1.1."""
import hashlib
import json
from pathlib import Path


def build(root):
    source = root / 'knowledge/kg_entry/processes_v1_1/catalog.json'
    raw = source.read_bytes().replace(b'\r\n', b'\n')
    assert hashlib.sha256(raw).hexdigest() == 'cc17f508dee484534b9667a0235402630db8848618450109f9bcd746b2d78a6c'
    data = json.loads(raw)
    data['version'] = 'pdf-1.1-work-review-2'
    data['predecessor_sha256'] = hashlib.sha256(raw).hexdigest()
    data['work_evidence_revision'] = 2
    data['facts'].update({
        'actual_presence_confirmed': dict(type='boolean', label='Подтверждено текущее пребывание заявителя'),
        'resident_registration_basis_reviewed': dict(type='boolean', label='Основание новой регистрации — выданная резидент-карта'),
        'termination_observed': dict(type='boolean', label='Подтверждено увольнение или ликвидация работодателя'),
        'termination_notice_recorded': dict(type='boolean', label='Подтверждено уведомление МИД'),
        'cancellation_request_recorded': dict(type='boolean', label='Подтверждена подача заявления на аннулирование'),
        'departure_plan_recorded': dict(type='boolean', label='Согласован план выезда'),
    })
    for edge in data['edges']:
        if (edge['from'], edge['to']) == ('W14', 'W15'):
            edge['requires'].pop('actual_entry_confirmed')
            edge['requires']['actual_presence_confirmed'] = True
        if (edge['from'], edge['to']) == ('W19', 'W20'):
            edge['requires']['resident_registration_basis_reviewed'] = True
    for n in range(3, 22):
        data['edges'].append(dict(from_=f'W{n:02}', to='WX1'))
        data['edges'][-1] = {'from': f'W{n:02}', 'to': 'WX1', 'basis': 'draft_proposal',
            'proposed_effect': 'same_process', 'requires': {'termination_observed': True}}
    data['notices']['WX1'] = ('Менеджер фиксирует увольнение, уведомление МИД и заявление на аннулирование; '
        'проверяет сроки 3 календарных дня и 30 дней по исходному PDF. Запись не отправляет уведомления '
        'и не подтверждает право на пребывание. Выезд подтверждается отдельно.')
    target = root / 'knowledge/kg_entry/processes_work_v2/catalog.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    result = (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode()
    target.write_bytes(result)
    return hashlib.sha256(result).hexdigest()


if __name__ == '__main__':
    print(build(Path(__file__).resolve().parents[1]))
