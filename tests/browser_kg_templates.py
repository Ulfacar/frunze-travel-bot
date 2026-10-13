"""Synthetic native typed-message preview, mobile/no-JS and print."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from tests.test_admin_kg_entry import env


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_template_fields_print_and_source_block(env,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-template-preview',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-03a-template-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page=context.new_page();page.goto(origin+env['url'],wait_until='networkidle')
            page.get_by_role('link',name='Черновики сообщений',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('#kg-tpl-template').select_option('KG.TPL.A06')
            page.get_by_role('button',name='Открыть шаблон',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('#kg-tpl-p01').fill('2026-10-01');page.locator('#kg-tpl-p02').fill('SYN-12')
            page.locator('#kg-tpl-p03').select_option('5');page.locator('#kg-tpl-p04').fill('2026-10-08')
            page.get_by_role('button',name='Показать черновик',exact=True).click();page.wait_for_load_state('networkidle')
            result=page.locator('#kg-tpl-result').inner_text()
            assert 'отправка не разрешена' in result and '2026-10-01' in result and '2026-10-08' in result
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-tpl-p01').focus();assert page.locator('#kg-tpl-p01').evaluate('(e)=>document.activeElement===e')
            page.screenshot(path=str(artifacts/f'form-{width}.png'))
            page.locator('#kg-tpl-result').evaluate('(e)=>e.scrollIntoView({block:"start"})')
            page.screenshot(path=str(artifacts/f'result-{width}.png'))
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-tpl-preview').is_hidden() and page.locator('#kg-tpl-result').is_visible()
                page.pdf(path=str(artifacts/'template-demo.pdf'),prefer_css_page_size=True)
                page.emulate_media(media='screen')
            page.locator('#kg-tpl-template').select_option('KG.TPL.A08')
            page.get_by_role('button',name='Открыть шаблон',exact=True).click();page.wait_for_load_state('networkidle')
            assert '{дата = +30 дней}' in page.locator('#kg-tpl-text').inner_text()
            assert page.locator('#kg-tpl-p02').count()==0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
