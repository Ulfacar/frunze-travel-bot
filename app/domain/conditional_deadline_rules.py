"""Closed source-clause meanings for separately delegated internal reminders."""
from dataclasses import dataclass
from datetime import date
import json

from app.domain.entry_anchor_rules import fail, shape, text, day
from app.domain.entry_storage import _hash
from app.knowledge.deadlines import _calculate, DeadlineError
from app.knowledge.work_calendar import CalendarError, WorkCalendars

FORMAT = 'kg-conditional-deadline/2'
SOURCE_HASH = '141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2'
# New identities are explicit internal clause mappings, never imported legal units.
RULES = {
    'KG.DL.INTERNAL_TS_EXIT_REVIEW': ('visa_period', 5, 'calendar_days', 'before', '19.2', 80, '19.2'),
    'KG.DL.INTERNAL_B_RENEWAL_PREPARATION': ('visa_period', 15, 'working_days', 'before', '19.3', 80, '19.3'),
    'KG.DL.INTERNAL_RL_RES_PREPARATION': ('visa_period', 15, 'working_days', 'before', '19.5', 80, '19.5'),
    'KG.DL.INTERNAL_RL_RES_REVIEW': ('visa_period', 10, 'working_days', 'before', '19.5', 80, '19.5'),
    'KG.DL.INTERNAL_S_RES_REVIEW': ('visa_period', 10, 'working_days', 'before', '19.7', 81, '19.7'),
    'KG.DL.VISA_EXTENSION': ('visa_period', 5, 'working_days', 'before', '13.2', 61, '19.11'),
    'KG.DL.RC_BEFORE_EP_END': ('permit_period', 10, 'working_days', 'before', '13.2', 61, '19.9/19.11'),
    'KG.DL.EP_BEFORE_RC_END': ('resident_period', 7, 'working_days', 'before', '13.2', 61, '19.9/19.11'),
    'KG.DL.REGISTRATION_CODE_PAYMENT': ('registration_payment_code', 3, 'working_days', 'after', '13.2', 62, '19.12'),
    'KG.DL.REGISTRATION_EXTENSION': ('registration_period', None, 'identity_date', None, '13.2', 62, '19.11/19.12'),
    'KG.DL.REREGISTRATION': ('effective_registration_changes', 10, 'working_days', 'after', '13.2', 62, '19.12'),
    'KG.DL.DISMISSAL_NOTIFICATION': ('employment_ended', 3, 'calendar_days', 'after', '13.2', 61, '19.9'),
    'KG.DL.EXIT_AFTER_EP_END': ('permit_terminated', 30, 'calendar_days', 'after', '13.2', 62, '19.9'),
    'KG.DL.INTERNAL_DISMISSAL_EXIT_PLAN': ('employment_ended', 30, 'calendar_days', 'after', '19.9', 82, '19.9'),
    'KG.DL.INTERNAL_RES_PREPARATION': ('permit_period', 15, 'working_days', 'before', '19.9', 82, '19.9'),
    'KG.DL.INTERNAL_EAEU_REG_REVIEW': ('registration_period', 10, 'working_days', 'before', '19.10', 82, '19.10'),
    'KG.DL.INTERNAL_ABSENCE_REG_REVIEW': ('actual_absence', 30, 'calendar_days_threshold', None, '19.12', 83, '19.12'),
}
CLAUSES = {
    'KG.DL.INTERNAL_TS_EXIT_REVIEW': 'За 5 дней до окончания TS — «выезд»',
    'KG.DL.INTERNAL_B_RENEWAL_PREPARATION': '−15 р.д.: «нужно ли продление?»',
    'KG.DL.INTERNAL_RL_RES_PREPARATION': '−15 р.д. до окончания RL: старт резидент-карты',
    'KG.DL.INTERNAL_RL_RES_REVIEW': '−10 р.д.: дедлайн',
    'KG.DL.INTERNAL_S_RES_REVIEW': '−10 р.д. до окончания визы — резидент-карта',
    'KG.DL.INTERNAL_DISMISSAL_EXIT_PLAN': 'Увольнение (если): план выезда. Выезжает ≤ 30 дн. WX1. Таймеры 3 к.д. и 30 дн',
    'KG.DL.INTERNAL_RES_PREPARATION': 'ЕР −15 р.д. старт; −10 р.д. дедлайн',
    'KG.DL.INTERNAL_EAEU_REG_REVIEW': 'Напоминания: −10 р.д. до окончания 60-дневной регистрации — продление на год.',
    'KG.DL.INTERNAL_ABSENCE_REG_REVIEW': 'выезд на 30+ дней — новая регистрация',
}
VISA_RENEWAL_RULES = frozenset(('KG.DL.VISA_EXTENSION', 'KG.DL.INTERNAL_B_RENEWAL_PREPARATION'))
VISA_SCOPES = {
    'KG.DL.INTERNAL_TS_EXIT_REVIEW': ('TS', ('tourism',)),
    'KG.DL.INTERNAL_B_RENEWAL_PREPARATION': ('B', ('business_meeting', 'event', 'medical')),
    'KG.DL.INTERNAL_RL_RES_PREPARATION': ('RL', ('relatives_kg_citizen',)),
    'KG.DL.INTERNAL_RL_RES_REVIEW': ('RL', ('relatives_kg_citizen',)),
    'KG.DL.INTERNAL_S_RES_REVIEW': ('S', ('study',)),
}


def definition(identifier):
    if type(identifier) is not str or identifier not in RULES: fail('conditional_deadline_rule_unsupported')
    kind, amount, unit, direction, section, page, sop = RULES[identifier]
    return dict(rule_id=identifier, anchor_kind=kind, amount=amount, unit=unit, direction=direction,
        section=section, printed_page=str(page), sop=sop, source_hash=SOURCE_HASH,
        source_kind='internal_clause_mapping' if identifier in CLAUSES else 'retained_null_deadline_unit',
        clause=CLAUSES.get(identifier), timezone='Asia/Bishkek', scope='internal_specialist_review_only')


@dataclass(frozen=True, init=False)
class ConditionalPolicy:
    encoded: str

    def __init__(self, document):
        shape(document, ('format', 'reference', 'proof', 'operators', 'valid_from', 'review_due_on',
            'rule_id', 'definition_hash', 'source_hash', 'bundle_hash', 'projection_hash', 'catalog_hash', 'rule_hash',
            'publication_policy_hash', 'required_units', 'anchor_policy_hash', 'calendar_hash', 'calendar_reference',
            'calendar_proof', 'calendar_valid_from', 'calendar_review_due_on', 'count_anchor_day',
            'boundary_inclusive', 'code_anchor', 'period_counting', 'absence_counting', 'absence_handling'))
        if document['format'] != FORMAT: fail('conditional_deadline_policy_invalid')
        spec = definition(document['rule_id'])
        if document['source_hash'] != SOURCE_HASH or document['definition_hash'] != _hash(spec): fail('conditional_deadline_definition_changed')
        for key, value in document.items():
            if key.endswith('_hash') or key in ('proof', 'calendar_proof'): text(value, r'[a-f0-9]{64}')
        for key in ('reference', 'calendar_reference'): text(document[key], r'[A-Z][A-Z0-9._/-]{0,79}')
        operators = document['operators']; required = document['required_units']
        if type(operators) is not list or not 1 <= len(operators) <= 20 or any(type(v) is not str for v in operators) or len(set(operators)) != len(operators): fail()
        for operator in operators:
            text(operator, r'[a-z0-9_.-]{1,64}')
            if operator in ('bot', 'system'): fail()
        if type(required) is not list or not 1 <= len(required) <= 64 or any(type(v) is not str for v in required) or len(set(required)) != len(required): fail()
        for unit in required: text(unit, r'KG\.[A-Z0-9_.]{1,100}')
        if any(day(document[a]) > day(document[b]) for a, b in (('valid_from', 'review_due_on'), ('calendar_valid_from', 'calendar_review_due_on'))): fail()
        for key in ('count_anchor_day', 'boundary_inclusive'):
            if type(document[key]) is not bool: fail()
        if document['code_anchor'] not in ('not_applicable', 'official_code_issued_on', 'official_code_received_on'): fail()
        if (spec['anchor_kind'] == 'registration_payment_code') != (document['code_anchor'] != 'not_applicable'): fail()
        if document['rule_id'] == 'KG.DL.INTERNAL_EAEU_REG_REVIEW':
            if document['period_counting'] not in ('elapsed_dates', 'both_boundary_dates'): fail()
        elif document['period_counting'] != 'not_applicable': fail()
        if spec['anchor_kind'] == 'actual_absence':
            if document['absence_counting'] not in ('elapsed_dates', 'both_boundary_dates') or document['absence_handling'] != 'observed_review_day': fail()
        elif document['absence_counting'] != 'not_applicable' or document['absence_handling'] != 'not_applicable': fail()
        if spec['source_kind'] == 'internal_clause_mapping' and document['rule_hash'] != _hash(spec): fail('conditional_deadline_clause_changed')
        object.__setattr__(self, 'encoded', json.dumps(document, sort_keys=True, separators=(',', ':'), ensure_ascii=False))

    @property
    def document(self): return json.loads(self.encoded)

    @property
    def digest(self): return _hash(self.document)


def calculate(policy, anchor_on, calendars, *, on):
    """Return a conditional review date only; identity dates need no offset hack."""
    p = policy.document; spec = definition(p['rule_id']); day(anchor_on); day(on)
    if spec['unit'] == 'calendar_days_threshold': fail('conditional_deadline_trigger_not_arithmetic')
    if not p['valid_from'] <= on <= p['review_due_on']: fail('conditional_deadline_authority_expired')
    if spec['unit'] == 'identity_date':
        return dict(due=anchor_on, anchor_local=anchor_on, mode='identity_date', calendar_trace=[], calendar_years_used=[])
    if (not isinstance(calendars, WorkCalendars) or calendars.content_hash != p['calendar_hash'] or
            any(c['completeness'] != 'complete' for c in calendars.describe()) or
            not p['calendar_valid_from'] <= on <= p['calendar_review_due_on']):
        fail('conditional_deadline_calendar_unavailable')
    rule = dict(value=spec['amount'], unit=spec['unit'], direction=spec['direction'], shift_from_nonworking='none',
        boundary_inclusive=p['boundary_inclusive'])
    try:
        result = _calculate(rule, anchor_on, dict(count_anchor_day=p['count_anchor_day'], month_end=None, hours_mode=None), calendars)
    except (CalendarError, DeadlineError) as exc: fail(exc.code)
    if any(not p['calendar_valid_from'] <= row['date'] <= p['calendar_review_due_on'] for row in result['calendar_trace']):
        fail('conditional_deadline_calendar_scan_unapproved')
    return result


def absence_threshold(policy, exited_on, returned_on):
    p = policy.document
    if definition(p['rule_id'])['anchor_kind'] != 'actual_absence': fail()
    days = (day(returned_on) - day(exited_on)).days
    if days < 0: fail('conditional_deadline_absence_dates_invalid')
    count = days + int(p['absence_counting'] == 'both_boundary_dates')
    return dict(days=count, threshold=30, triggered=count>=30, filing_due_on=None)
