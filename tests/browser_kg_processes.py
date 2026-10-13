"""Synthetic native process review; no application changes or outside requests."""
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
def test_native_process_preview_guards_branches_navigation_and_print(env,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    before=counts(env)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-process-preview',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-01c-process-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started
        origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context(viewport={'width':width,'height':850},java_script_enabled=js)
            context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
            page=context.new_page();page.goto(origin+env['url'],wait_until='networkidle')
            page.get_by_role('link',name='Проверка черновых процессов',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('#kg-process-stage').select_option('V14')
            page.get_by_role('button',name='Открыть этап',exact=True).click();page.wait_for_load_state('networkidle')
            page.get_by_role('button',name='Проверить сценарий',exact=True).click();page.wait_for_load_state('networkidle')
            assert 'Для проверки не хватает сведений' in page.locator('#kg-process-result').inner_text()
            for key in ('consent_confirmed','documents_accepted','portal_draft_created'):page.locator('#kg-fact-'+key).select_option('true')
            page.locator('#kg-fact-documents_current').select_option('false')
            page.get_by_role('button',name='Проверить сценарий',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('[data-check="documents_current"]').get_attribute('data-state')=='not_met'
            page.locator('#kg-fact-documents_current').select_option('true')
            page.get_by_role('button',name='Проверить сценарий',exact=True).click();page.wait_for_load_state('networkidle')
            result=page.locator('#kg-process-result').inner_text()
            assert 'Условия чернового перехода выполнены в сценарии' in result
            assert 'Выполнение не разрешено' in result and 'остаётся V14' in result
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-process-target').focus()
            assert page.locator('#kg-process-target').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'visa-{width}.png'),full_page=True)
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-process-check').is_hidden() and page.locator('#kg-process-result').is_visible()
                page.pdf(path=str(artifacts/'process-demo.pdf'),prefer_css_page_size=True)
                page.emulate_media(media='screen')
            page.locator('#kg-process-name').select_option('regularization')
            page.get_by_role('button',name='Открыть процесс',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('#kg-process-stage').select_option('U06')
            page.get_by_role('button',name='Открыть этап',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('#kg-process-target').select_option('U07')
            page.locator('#kg-fact-decision').select_option('approved')
            page.locator('#kg-fact-exit_visa_issued').select_option('true')
            page.locator('#kg-fact-regularization_route').select_option('registration')
            page.get_by_role('button',name='Проверить сценарий',exact=True).click();page.wait_for_load_state('networkidle')
            assert 'Условия чернового перехода не выполнены' in page.locator('#kg-process-result').inner_text()
            assert 'отдельной регистрационной' in page.locator('#kg-process-notice').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'branch-{width}.png'),full_page=True)
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
    assert counts(env)==before
