"""Native complete package, historical review and print on synthetic data."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import person,application,enforce_sqlite_foreign_keys
from tests.test_entry_document_packages import read


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_document_package_versions_and_history(env,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    app=application(env,person(env))
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-document-package',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-08-package-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started;origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch();context=browser.new_context(viewport={'width':width,'height':850},java_script_enabled=js)
            context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
            page=context.new_page();page.goto(origin+env['url']+'/applications?application_id='+str(app['id']),wait_until='networkidle')
            page.get_by_role('link',name='Полный комплект документов',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('#kg-dp-product').select_option('TR');page.locator('#kg-di-confirm-initialize').check()
            page.locator('#kg-dp-initialize button').click();page.wait_for_load_state('networkidle')
            page.locator('#kg-dp-item').select_option('t08_02');page.locator('#kg-dp-select button').click();page.wait_for_load_state('networkidle')
            page.locator('#kg-dp-fingerprint').fill('a'*64);page.locator('#kg-di-date-receive').fill('2026-09-01')
            page.locator('#kg-dp-source').select_option('client_copy');page.locator('#kg-di-confirm-receive').check()
            page.locator('#kg-dp-receive button').click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-item="t08_02"]').get_attribute('data-state')=='received'
            assert page.locator('#kg-dp-approve').count()==0
            page.locator('#kg-di-date-review').fill('2026-09-02');page.locator('#kg-dp-outcome').select_option('checked')
            page.locator('#kg-di-confirm-review').check();page.locator('#kg-dp-review button').click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-item="t08_02"]').get_attribute('data-state')=='checked'
            page.locator('#kg-di-date-passport_change').fill('2026-09-03');page.locator('#kg-di-confirm-passport_change').check()
            page.locator('#kg-dp-passport_change button').click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-item="t08_02"]').get_attribute('data-state')=='recheck'
            assert 'Текущая приёмка не подтверждена' in page.locator('#kg-dp-summary').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-dp-item').focus();assert page.locator('#kg-dp-item').evaluate('(e)=>document.activeElement===e')
            page.evaluate("window.scrollTo({top:0,behavior:'instant'})");page.screenshot(path=str(artifacts/f'package-{width}.png'))
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-dp-receive').is_hidden() and page.locator('#kg-dp-all').is_visible()
                page.pdf(path=str(artifacts/'package-demo.pdf'),prefer_css_page_size=True);page.emulate_media(media='screen')
            page.get_by_role('link',name='Версия 3',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-dp-historical').is_visible() and page.locator('#kg-dp-receive').count()==0
            assert page.locator('[data-item="t08_02"]').get_attribute('data-state')=='checked'
            page.get_by_role('link',name='Открыть текущую',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-item="t08_02"]').get_attribute('data-state')=='recheck'
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
    assert read(env,app)['current_revision']==4


def test_native_acceptance_and_revocation(env,monkeypatch):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    from app.domain import entry_applications as applications
    from tests.test_entry_document_packages import setup,complete
    app=setup(env);allowed=complete(env,app)
    monkeypatch.setattr(ar.settings,'kg_document_package_policy',allowed.document())
    monkeypatch.setattr(ar,'_bishkek_today',applications._today)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-package-acceptance',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-08-package-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started;origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch();context=browser.new_context(viewport={'width':1365,'height':850},java_script_enabled=False)
            context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
            page=context.new_page();page.goto(origin+env['url']+'/applications/'+str(app['id'])+'/document-package',wait_until='networkidle')
            page.locator('#kg-dp-ref-approve').fill('SYNTHETIC-REVIEW');page.locator('#kg-dp-proof-approve').fill('f'*64)
            page.locator('#kg-di-confirm-approve').check();page.locator('#kg-dp-approve button').click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-dp-accepted').is_visible()
            assert 'Подача не разрешена' in page.locator('#kg-dp-summary').inner_text()
            page.evaluate("window.scrollTo({top:0,behavior:'instant'})");page.screenshot(path=str(artifacts/'package-accepted.png'))
            page.locator('#kg-di-date-revoke').fill(applications._today().isoformat())
            page.locator('#kg-dp-revoke-reason').select_option('review_error');page.locator('#kg-di-confirm-revoke').check()
            page.locator('#kg-dp-revoke button').click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-dp-not-accepted').is_visible() and page.locator('#kg-dp-accepted').count()==0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
    assert read(env,app,policy=allowed)['current_acceptance']['accepted'] is False
