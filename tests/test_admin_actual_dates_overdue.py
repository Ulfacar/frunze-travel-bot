"""Real current date stays visible as overdue, without inventing a later expiry."""
from datetime import datetime,timezone
from tests import test_admin_actual_dates as native
from tests.test_admin_actual_dates import env,clock,enforce_sqlite_foreign_keys
from tests.test_admin_actual_dates_review import record_form,registration


def test_real_overdue_report_and_known_invalid_form_are_distinct(env,tmp_path,monkeypatch):
    native.setup(env,tmp_path,monkeypatch)
    before=native.core.actual.read(env,env['prepared'])['revision']
    data=registration(record_form(env,'registration_period'))
    data['valid_until']='2026-13-55'
    response=native.post(env,data,'en')
    assert response.status_code==422 and 'Check fields and current evidence' in response.text
    assert 'actual-dates-retry' not in response.text
    assert native.core.actual.read(env,env['prepared'])['revision']==before
    monkeypatch.setattr(native.ui.deadlines.sources,'_now',lambda:datetime(2026,10,20,10,tzinfo=timezone.utc))
    for language,message in [('ru','Дата проверки прошла — требуется специалист.'),('en','The review date has passed — specialist review required.')]:
        response=env['client'].get(native.url(env,language))
        assert response.status_code==200
        assert message in response.text and '2026-10-19' in response.text
        assert '2026-11-01' in response.text
    assert native.core.actual.read(env,env['prepared'])['revision']==before
