"""Native post-issue proof flow, mobile/no-JS and historical print."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_issued import setup,read


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_issued_review_receipt_actual_entry_and_history(env,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    app=setup(env)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-issued-preview',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-02c-issued-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started
        origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch();context=browser.new_context(viewport={'width':width,'height':850},java_script_enabled=js)
            context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
            page=context.new_page();page.goto(origin+env['url']+f'/applications?application_id={app["id"]}',wait_until='networkidle')
            page.get_by_role('link',name='После выдачи',exact=True).click();page.wait_for_load_state('networkidle')
            def submit(action):
                form=page.locator('#kg-is-'+action);form.locator('input[name=confirmed]').check()
                form.get_by_role('button',name='Сохранить запись',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('#kg-is-file-on').fill('2026-09-03')
            page.locator('#kg-is-file-fingerprint').fill('a'*64);page.locator('#kg-is-file-passport_fingerprint').fill('b'*64)
            submit('file')
            page.locator('#kg-is-review-on').fill('2026-09-04')
            for select in page.locator('#kg-is-review select').all():select.select_option('true')
            submit('review')
            page.locator('#kg-is-delivery-on').fill('2026-09-05');page.locator('#kg-is-channel').select_option('email')
            page.locator('#kg-is-delivery-proof').fill('c'*64);page.locator('#kg-is-delivery-pamphlet').fill('d'*64)
            submit('delivery')
            assert 'Получение клиентом: не подтверждено' in page.locator('#kg-is-summary').inner_text()
            page.locator('#kg-is-receipt-on').fill('2026-09-06');page.locator('#kg-is-receipt-proof').fill('e'*64)
            page.locator('#kg-is-identity_checked').select_option('true');submit('receipt')
            page.locator('#kg-is-travel-on').fill('2026-09-07');page.locator('#kg-is-direction').select_option('entry')
            page.locator('#kg-is-travel-proof').fill('f'*64);page.locator('#kg-is-travel-passport_fingerprint').fill('b'*64)
            submit('travel')
            assert 'Фактических въездов: 1' in page.locator('#kg-is-summary').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-is-file-on').focus();assert page.locator('#kg-is-file-on').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'issued-{width}.png'))
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-is-file').is_hidden() and page.locator('#kg-is-summary').is_visible()
                page.pdf(path=str(artifacts/'issued-demo.pdf'),prefer_css_page_size=True)
                page.emulate_media(media='screen')
            page.locator('#kg-is-history').get_by_role('link',name='Версия 2',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-is-historical').is_visible() and page.locator('#kg-is-file').count()==0
            assert 'Фактических въездов: 0' in page.locator('#kg-is-summary').inner_text()
            page.get_by_role('link',name='Открыть текущую',exact=True).click();page.wait_for_load_state('networkidle')
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
    assert read(env,app)['current_revision']==5
