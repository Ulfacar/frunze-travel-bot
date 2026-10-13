"""Native persisted inventory, historical review and print on synthetic data."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import person,application,enforce_sqlite_foreign_keys
from tests.test_entry_documents import read


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_document_inventory_versions_and_history(env,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    app=application(env,person(env))
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-document-inventory',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-02b-inventory-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page.get_by_role('link',name='Документы этой заявки',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('#kg-di-product').select_option('TS');page.locator('#kg-di-confirm-initialize').check()
            page.locator('#kg-di-initialize button').click();page.wait_for_load_state('networkidle')
            page.locator('#kg-di-item').select_option('d03_0');page.locator('#kg-di-select button').click();page.wait_for_load_state('networkidle')
            page.locator('#kg-di-fingerprint').fill('a'*64);page.locator('#kg-di-date-receive').fill('2026-09-01')
            page.locator('#kg-di-source').select_option('client_copy');page.locator('#kg-di-confirm-receive').check()
            page.locator('#kg-di-receive button').click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-item="d03_0"]').get_attribute('data-state')=='received'
            page.locator('#kg-di-date-review').fill('2026-09-02');page.locator('#kg-di-outcome').select_option('checked')
            page.locator('#kg-di-confirm-review').check();page.locator('#kg-di-review button').click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-item="d03_0"]').get_attribute('data-state')=='checked'
            page.locator('#kg-di-date-passport_change').fill('2026-09-03');page.locator('#kg-di-confirm-passport_change').check()
            page.locator('#kg-di-passport_change button').click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-item="d03_0"]').get_attribute('data-state')=='recheck'
            assert 'Комплект не принят' in page.locator('#kg-di-summary').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-di-item').focus();assert page.locator('#kg-di-item').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'inventory-{width}.png'))
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-di-receive').is_hidden() and page.locator('#kg-di-all').is_visible()
                page.pdf(path=str(artifacts/'inventory-demo.pdf'),prefer_css_page_size=True);page.emulate_media(media='screen')
            page.get_by_role('link',name='Версия 3',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-di-historical').is_visible() and page.locator('#kg-di-receive').count()==0
            assert page.locator('[data-item="d03_0"]').get_attribute('data-state')=='checked'
            page.get_by_role('link',name='Открыть текущую',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-item="d03_0"]').get_attribute('data-state')=='recheck'
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
    assert read(env,app)['current_revision']==4
