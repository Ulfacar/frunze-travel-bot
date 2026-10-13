from datetime import date
from copy import deepcopy
import json

import pytest

from app.knowledge.current_stay_checks import working_margin
from app.knowledge.work_calendar import WorkCalendars
from tests.test_admin_kg_entry import FIX


def calendars(): return json.loads((FIX/'synthetic_work_calendars.json').read_text('utf-8'))


@pytest.mark.parametrize('today,until,include_today,include_until,count', [
    ('2026-10-09','2026-10-12',True,True,1),
    ('2026-10-10','2026-10-10',True,True,1),
    ('2026-10-10','2026-10-10',False,True,0),
    ('2026-10-10','2026-10-10',True,False,0),
    ('2026-12-30','2027-01-04',False,True,3),
])
def test_explicit_overrides_endpoints_and_new_year(today, until, include_today, include_until, count):
    result = working_margin(today=date.fromisoformat(today), until=date.fromisoformat(until),
        calendars=WorkCalendars(calendars()), include_today=include_today, include_until=include_until)
    assert result['working_days'] == count and result['exact'], result


@pytest.mark.parametrize('change', ['missing', 'provisional', 'scan_bound'])
def test_unknown_calendar_cannot_guess_weekdays(change):
    doc = calendars()
    if change == 'missing': doc['calendars'] = doc['calendars'][:1]
    elif change == 'provisional': doc['calendars'][1].update(completeness='provisional', provisional_note='SYNTHETIC incomplete')
    else:
        for y in doc['calendars']: y.update(week_rest_days=[1,2,3,4,5,6,7], days=[])
    result = working_margin(today=date(2026,12,30) if change!='scan_bound' else date(2026,1,1),
        until=date(2027,1,4), calendars=WorkCalendars(doc), include_today=True, include_until=True)
    assert result['status']=='unknown' and result['working_days'] is None
