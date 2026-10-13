"""Synthetic native checklist flow with no outside requests or stored answers."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import counts


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_document_checklist_review_versions_and_print(env,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    before=counts(env)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-documents-preview',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-02a-documents-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page.get_by_role('link',name='Черновой чек-лист документов',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-state-d06_0').count()==1 and page.locator('#kg-state-d06_1').count()==1
            page.get_by_role('button',name='Проверить матрицу',exact=True).click();page.wait_for_load_state('networkidle')
            assert 'В сценарии остались вопросы' in page.locator('#kg-doc-result').inner_text()
            for select in page.locator('#kg-doc-check select[name^="state_"]').all():select.select_option('checked')
            for select in page.locator('#kg-doc-check select[name^="applies_"]').all():select.select_option('false')
            page.locator('#kg-doc-current').select_option('true')
            page.get_by_role('button',name='Проверить матрицу',exact=True).click();page.wait_for_load_state('networkidle')
            text=page.locator('#kg-doc-result').inner_text()
            assert 'Обязательные строки матрицы отмечены проверенными' in text
            assert 'Комплект не принят. Подача не разрешена.' in text
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-doc-current').focus()
            assert page.locator('#kg-doc-current').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'form-{width}.png'))
            page.locator('#kg-doc-result').evaluate('(e)=>e.scrollIntoView({block:"start"})');page.screenshot(path=str(artifacts/f'result-{width}.png'))
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-doc-check').is_hidden() and page.locator('#kg-doc-result').is_visible()
                page.pdf(path=str(artifacts/'document-checklist-demo.pdf'),prefer_css_page_size=True)
                page.emulate_media(media='screen')
            page.locator('#kg-doc-current').select_option('false')
            page.get_by_role('button',name='Проверить матрицу',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-result="d01_0"]').get_attribute('data-outcome')=='not_current'
            page.locator('#kg-doc-product').select_option('REG')
            page.get_by_role('button',name='Открыть чек-лист',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-doc-result').count()==0
            assert page.locator('#kg-state-d01_0').input_value()=='unknown'
            assert 'Face ID' in page.content() and page.locator('#kg-state-d03_0').count()==0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
    assert counts(env)==before
