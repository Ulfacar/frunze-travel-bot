"""Publication through native forms on mobile and a desktop without JavaScript."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_admin_kg_knowledge_publication import publisher
from tests.test_knowledge_publication import IDS, release, runtime


@pytest.mark.parametrize('width,js', [(390,True), (1365,False)])
def test_native_publication_and_withdrawal(publisher, width, js):
    api = pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    local = FastAPI(); local.add_middleware(SessionMiddleware, secret_key='synthetic-publication', https_only=False)
    local.include_router(ar.router)
    artifacts = Path('runs/e6-07b-publication-browser'); artifacts.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(); listener.bind(('127.0.0.1',0)); port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(local, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[listener]}, daemon=True); thread.start()
    try:
        until = time.monotonic()+5
        while not server.started and time.monotonic()<until: time.sleep(.05)
        assert server.started; origin = f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser = p.chromium.launch(); context = browser.new_context(viewport={'width':width,'height':850}, java_script_enabled=js)
            context.route('**/*', lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login', form={'login':'admin','password':'frunze'}).status==200
            page = context.new_page(); page.goto(origin+'/admin/kg-entry/reviews', wait_until='networkidle')
            page.get_by_role('link', name='Публикация проверенных правил').click(); page.wait_for_load_state('networkidle')
            page.locator('#kg-publication-version').select_option(str(publisher['release']))
            page.locator('#kg-publication-units').fill(','.join(IDS))
            page.get_by_role('button', name='Проверить готовность').click(); page.wait_for_load_state('networkidle')
            for action,label in [('review','Передать на проверку'), ('approve','Утвердить выбранные правила'), ('activate','Активировать версию')]:
                page.locator(f'#kg-publication-{action} input[name=confirmed]').check()
                page.get_by_role('button', name=label, exact=True).click(); page.wait_for_load_state('networkidle')
            assert 'Состояние: активна' in page.locator('#kg-publication-summary').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-publication-units').focus()
            assert page.locator('#kg-publication-units').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0,0)'); page.screenshot(path=str(artifacts/f'publication-{width}.png'))
            if width == 1365:
                page.emulate_media(media='print'); page.pdf(path=str(artifacts/'publication-demo.pdf'), prefer_css_page_size=True)
                import fitz
                with fitz.open(artifacts/'publication-demo.pdf') as printed:
                    assert len(printed) <= 2 and 'Состояние: активна' in ''.join(p.get_text() for p in printed)
                page.emulate_media(media='screen')
            page.locator('#kg-publication-withdraw input[name=confirmed]').check()
            page.get_by_role('button', name='Отозвать активную версию', exact=True).click(); page.wait_for_load_state('networkidle')
            assert 'Состояние: выведена из использования' in page.locator('#kg-publication-summary').inner_text()
            context.close(); browser.close()
        assert runtime(publisher)['version_id'] is None
    finally:
        server.should_exit=True; thread.join(timeout=10); listener.close()
