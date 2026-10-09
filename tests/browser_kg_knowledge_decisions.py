"""Review -> rejection -> preserved source/history on mobile and no-JS desktop."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_knowledge_decisions import read


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_knowledge_review_history_and_print(env,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-review',https_only=False);local.include_router(ar.router)
    artifacts=Path('runs/e6-07a-review-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page=context.new_page();page.goto(origin+'/admin/kg-entry/knowledge',wait_until='networkidle')
            page.get_by_role('link',name='Журнал проверки импортированных правил').click();page.wait_for_load_state('networkidle')
            page.locator('#kg-review-query').fill('KG.DL.TEST');page.get_by_role('button',name='Показать правила').click();page.wait_for_load_state('networkidle')
            page.locator('article h2 a').click();page.wait_for_load_state('networkidle')
            def fill(verdict):
                page.locator(f'#kg-review-{verdict}-ref').fill('SYNTHETIC-01')
                page.locator(f'#kg-review-{verdict}-proof').fill('a'*64)
                page.locator(f'#kg-review-{verdict}-date').fill('2026-09-01')
                page.locator(f'#kg-review-{verdict} input[name=confirmed]').check()
            fill('confirmed');page.locator('#kg-review-confirmed-due').fill('2026-12-01')
            page.get_by_role('button',name='Записать подтверждение',exact=True).click();page.wait_for_load_state('networkidle')
            assert 'Повторная проверка до 2026-12-01' in page.locator('#kg-review-result').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-review-confirmed-ref').focus();assert page.locator('#kg-review-confirmed-ref').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'review-{width}.png'))
            page.get_by_text('Отклонение',exact=True).click();fill('rejected')
            page.locator('#kg-review-rejected-reason').select_option('outdated')
            page.get_by_role('button',name='Записать отклонение',exact=True).click();page.wait_for_load_state('networkidle')
            assert 'Сведения устарели' in page.locator('#kg-review-result').inner_text()
            page.get_by_role('link',name='Запись №1',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-review-historical').count()==1 and page.locator('#kg-review-confirmed').count()==0
            assert '2026-12-01' in page.locator('#kg-review-result').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'review-history-{width}.png'))
            if width==1365:
                page.emulate_media(media='print');page.pdf(path=str(artifacts/'review-demo.pdf'),prefer_css_page_size=True)
                import fitz
                with fitz.open(artifacts/'review-demo.pdf') as printed:
                    assert len(printed)==1 and '2026-12-01' in printed[0].get_text()
            context.close();browser.close()
        assert read(env)['current_revision']==2 and read(env)['selected']['decision']['verdict']=='rejected'
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
