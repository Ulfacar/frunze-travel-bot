import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event

import app.admin.kg_templates as ui
import app.admin.router as ar
import app.main as main
from app.knowledge.template_preview import TemplatePreviewInvalid
from tests.test_admin_kg_entry import Form,env
from tests.test_admin_workday import _login

URL='/admin/kg-entry/templates'


def form(env,template='KG.TPL.A06'):
    response=env['client'].get(URL,params={'template':template})
    assert response.status_code==200
    return Form(response.text,'kg-tpl-preview').data


def test_native_dates_retention_no_sql_and_no_send(env,monkeypatch):
    queries=[]
    def capture(conn,cursor,sql,params,ctx,many):queries.append(sql)
    def forbidden():raise AssertionError('domain access')
    monkeypatch.setattr(ar,'_domain_sessionmaker',forbidden)
    event.listen(env['engine'].sync_engine,'before_cursor_execute',capture)
    try:
        values=form(env);values.update(p01='2026-10-01',p02='SYN-12',p03='5',p04='2026-10-08')
        response=env['client'].post(URL,data=values)
        assert response.status_code==200 and 'подана 2026-10-01' in response.text
        assert 'до\n2026-10-08' in response.text and 'отправка не разрешена' in response.text
        assert Form(response.text,'kg-tpl-preview').data==values
        assert response.headers['cache-control']=='no-store' and response.headers['referrer-policy']=='no-referrer'
        assert queries==[]
    finally:event.remove(env['engine'].sync_engine,'before_cursor_execute',capture)


def test_html_escape_missing_calculation_and_source_status(env):
    values=form(env,'KG.TPL.A03');values['p01']='<script>alert(1)</script>'
    response=env['client'].post(URL,data=values)
    assert response.status_code==200
    assert '<script>alert(1)</script>' not in response.text and '&lt;script&gt;' in response.text
    response=env['client'].get(URL,params={'template':'KG.TPL.A08'})
    assert 'дата = +30 дней' in response.text and 'шаблон заблокирован' in response.text
    assert 'name="p02"' not in response.text
    assert response.text.count('Нужен подтверждённый расчёт')==1


def test_invalid_values_retained_without_fake_result(env):
    values=form(env);values.update(p01='2026-02-30',p02='SYN-12',p03='5')
    response=env['client'].post(URL,data=values)
    assert response.status_code==422 and 'id="kg-tpl-result"' not in response.text
    assert Form(response.text,'kg-tpl-preview').data==values


def test_tampered_cross_session_duplicate_and_extra_fields(env):
    values=form(env)
    assert env['client'].post(URL,data={**values,'_tpl_id':'KG.TPL.A03'}).status_code==403
    assert env['client'].post(URL,data={**values,'_tpl_catalog':'a'*64}).status_code==403
    assert env['client'].post(URL,data={**values,'send':'true'}).status_code==422
    other=_login('admin')
    try:assert other.post(URL,data=values).status_code==403
    finally:other.close()
    from urllib.parse import urlencode
    body=urlencode(values)+'&p01=2026-10-01'
    assert env['client'].post(URL,content=body,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==422
    assert env['client'].get(URL+'?template=KG.TPL.A06&template=KG.TPL.A03').status_code==422
    assert env['client'].get(URL+'?other=true').status_code==422


@pytest.mark.parametrize('login',[None,'medina','ademi'])
def test_auth_before_source_read(env,monkeypatch,login):
    def forbidden():raise AssertionError('source read')
    monkeypatch.setattr(ui,'load_catalog',forbidden)
    client=_login(login) if login else TestClient(main.app,base_url='https://testserver')
    try:
        assert client.get(URL).status_code==(401 if login is None else 403)
        assert client.post(URL,data={}).status_code==(401 if login is None else 403)
    finally:client.close()


def test_off_switch_catalog_failure_and_navigation(env,monkeypatch):
    assert URL in env['client'].get(env['url']).text
    values=form(env)
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',False)
    assert env['client'].get(URL).status_code==404
    assert env['client'].post(URL,data=values).status_code==404
    monkeypatch.setattr(ar.settings,'admin_kg_entry_enabled',True)
    def broken():raise TemplatePreviewInvalid('template_catalog_invalid')
    monkeypatch.setattr(ui,'load_catalog',broken)
    assert env['client'].get(URL).status_code==503
    assert env['client'].post(URL,data=values).status_code==503


def test_bounds_content_type_and_no_write_permission_needed(env,monkeypatch):
    values=form(env)
    assert env['client'].post(URL,json=values).status_code==415
    assert env['client'].post(URL,content='x'*16385,headers={'content-type':'application/x-www-form-urlencoded'}).status_code==413
    assert env['client'].post(URL,data={**values,'p02':'x'*501}).status_code==422
    # Read-only preview does not depend on the write flag and performs no mutation.
    monkeypatch.setattr(ar.settings,'service_cases_enabled',False)
    assert env['client'].post(URL,data=values).status_code==200
