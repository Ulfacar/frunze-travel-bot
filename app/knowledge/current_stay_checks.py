"""Bounded arithmetic only; callers must separately establish facts and authority."""
from datetime import date

from app.knowledge.work_calendar import CalendarError

MAX_SCAN_DAYS = 366


def working_margin(*, today, until, calendars, include_today, include_until):
    """Prove <5 or >=5; an early >=5 result is a lower bound, not an exact total."""
    if type(today) is not date or type(until) is not date or type(include_today) is not bool or type(include_until) is not bool:
        raise ValueError('invalid_margin_input')
    if until < today:
        return dict(status='not_triggered', applicability='expired_instead', working_days=None, exact=False, days=[])
    start = today.toordinal() + int(not include_today)
    end = until.toordinal() - int(not include_until)
    checked = []; count = 0
    for ordinal in range(start, min(end + 1, start + MAX_SCAN_DAYS)):
        try:
            item = calendars.day(date.fromordinal(ordinal))
        except CalendarError as exc:
            return dict(status='unknown', reason=exc.code, working_days=None, exact=False, days=checked)
        checked.append(item); count += int(item['is_working'])
        if count >= 5:
            return dict(status='not_triggered', applicability='applicable', working_days=count,
                        exact=ordinal == end, days=checked)
    if end >= start + MAX_SCAN_DAYS:
        return dict(status='unknown', reason='calendar_scan_bound', working_days=None, exact=False, days=checked)
    return dict(status='triggered' if count < 5 else 'not_triggered', applicability='applicable',
                working_days=count, exact=True, days=checked)


def observed_headroom(arithmetic):
    """Never subtract a projected exit day from an observed open current stay."""
    scenario = arithmetic.get('scenario')
    if scenario is None or len(scenario['daily']) != 1:
        return dict(status='unknown', reason='observed_arithmetic_unresolved')
    used = scenario['daily'][0]['reported_history_days']
    headroom = scenario['limit_days'] - used
    return dict(status='triggered' if headroom <= 3 else 'not_triggered', applicability='applicable',
                observed_days=used, limit_days=scenario['limit_days'], window_days=scenario['window_days'],
                current_window_headroom=headroom, exceeded=headroom < 0,
                window_start=scenario['daily'][0]['window_start'], window_end=scenario['daily'][0]['window_end'],
                days_until_exit=None)
