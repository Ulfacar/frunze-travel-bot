"""Independent native warning and signed-envelope controls, actual journals."""
from urllib.parse import urlencode
import pytest
import app.admin.router as ar
from app.domain.entry_storage import EntryStorageUnavailable
from tests import test_admin_work_review as native
from tests.test_admin_work_review import (env,clock,review_clock,connected_clock,route_clock,admins,
    enforce_sqlite_foreign_keys,core,ui,Form)
from tests.test_admin_workday import _login


def test_triggered_margin_and_late_filing_are_visible(env,tmp_path,monkeypatch):
    original=core.deadline.current.setup
    def near_end(env,path,**kwargs):
        return original(env,path,**(kwargs|{'until':'2026-10-13'}))
    monkeypatch.setattr(core.deadline.current,'setup',near_end)
    native.setup(env,tmp_path,monkeypatch)
    report=core.read(env)['current']['report']
    assert report['status']=='calculated'
    assert report['current_stay']['checks']['working_day_margin']['status']=='triggered'
    assert report['within_filing_deadline'] is False
    response=env['client'].get(native.url(env))
    assert response.status_code==200
    # This explicitly recorded stop must be disclosed, not merely the generic
    # caveat that work/stay permission needs separate confirmation.
    assert 'запас рабочих дней' in response.text.lower()
    assert 'Выявлено — требуется специалист' in response.text
    assert 'Условная дата подачи прошла' in response.text


def test_signed_route_session_language_and_stale_tokens(env,tmp_path,monkeypatch):
    native.setup(env,tmp_path,monkeypatch);before=core.counts(env)
    form=native.form(env);path=native.url(env)
    other=_login('admin')
    try:
        other.get(path)
        assert other.post(path,data=form,follow_redirects=False).status_code==403
    finally:other.close()
    assert env['client'].post(path.replace('/applicants/'+str(env['person']['id'])+'/', '/applicants/2147483647/'),data=form,follow_redirects=False).status_code==403
    assert native.post(env,form,language='en').status_code==422
    for key in ('_wr_action','_wr_signature','_wr_key'):
        response=env['client'].post(path,content=urlencode(form)+'&'+key+'='+form[key],headers={'content-type':'application/x-www-form-urlencoded'},follow_redirects=False)
        assert response.status_code==422
    assert env['client'].post(path,json=form,follow_redirects=False).status_code==415
    assert core.counts(env)==before
    other_form=native.form(env)
    assert native.post(env,form).status_code==303
    assert native.post(env,other_form).status_code==409
    assert core.counts(env)==[before[0]+1,before[1]+1]
    # Exact same signed command remains a no-op retry after fresh authority loss.
    monkeypatch.setattr(ar.settings,'kg_work_review_authorities',[])
    assert native.post(env,form).status_code==303
    assert core.counts(env)==[before[0]+1,before[1]+1]


def test_unknown_commit_reader_failure_retry_is_original_envelope(env,tmp_path,monkeypatch):
    native.setup(env,tmp_path,monkeypatch);request=native.form(env,language='en');before=core.counts(env)
    record=ui.service.record;read=ui.service.read
    async def lost(*args,**kwargs):
        await record(*args,**kwargs)
        raise EntryStorageUnavailable('synthetic-commit-ack-lost')
    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic-read-unavailable')
    monkeypatch.setattr(ui.service,'record',lost);monkeypatch.setattr(ui.service,'read',unavailable)
    response=native.post(env,request,language='en')
    assert response.status_code==503 and response.headers['cache-control']=='no-store'
    retained=Form(response.text,'work-review-retry').data
    assert retained==request and 'save outcome is unknown' in response.text
    assert not Form(response.text,'work-review-refresh').data
    monkeypatch.setattr(ui.service,'record',record);monkeypatch.setattr(ui.service,'read',read)
    monkeypatch.setattr(ar.settings,'kg_work_review_authorities',[])
    assert native.post(env,retained,language='en').status_code==303
    assert core.counts(env)==[before[0]+1,before[1]+1]
