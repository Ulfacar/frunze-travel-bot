"""Native approved answers: mobile and no-JavaScript desktop, synthetic only."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_admin_kg_knowledge_publication import publisher
from tests.test_knowledge_publication import IDS, release, activate, publish
from tests.test_knowledge_answers import source_clock


@pytest.mark.parametrize('width,js', [(390, True), (1365, False)])
def test_native_answer_and_withdrawal(publisher, width, js):
    from playwright.sync_api import sync_playwright
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    activate(publisher)
    local = FastAPI()
    local.add_middleware(SessionMiddleware, secret_key='synthetic-answers', https_only=False)
    local.include_router(ar.router)
    artifacts = Path('runs/answer-browser')
    artifacts.mkdir(parents=True, exist_ok=True)
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(local, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True)
    thread.start()
    try:
        until = time.monotonic() + 5
        while not server.started and time.monotonic() < until:
            time.sleep(.05)
        assert server.started
        origin = f'http://127.0.0.1:{port}'
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': width, 'height': 850}, java_script_enabled=js)
            external = []
            def route_request(route):
                if urlsplit(route.request.url).netloc == f'127.0.0.1:{port}':
                    route.continue_()
                else:
                    external.append(route.request.url)
                    route.abort()
            context.route('**/*', route_request)
            assert context.request.post(origin + '/admin/login', form={'login': 'admin', 'password': 'frunze'}).status == 200
            page = context.new_page()
            page.goto(origin + '/admin/kg-entry/knowledge', wait_until='networkidle')
            external.clear()  # The existing PDF search uses the standard admin assets.
            page.get_by_role('link', name='Ответы по утверждённым источникам').click()
            page.wait_for_load_state('networkidle')
            assert page.locator('#kg-answer-empty').count() == 1
            page.get_by_label('Коды правил через запятую').fill(','.join(IDS))
            page.get_by_label('Язык ответа / Answer language').select_option('en')
            page.get_by_role('button', name='Сформировать ответ').click()
            page.wait_for_load_state('networkidle')
            assert page.locator('.kg-answer-text').count() == 2
            assert 'Counting direction: before' in page.locator('.kg-answer-text').first.inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts / f'answers-{width}.png'), full_page=True)
            if width == 1365:
                page.emulate_media(media='print')
                page.pdf(path=str(artifacts / 'answers.pdf'), prefer_css_page_size=True)
                import fitz
                with fitz.open(artifacts / 'answers.pdf') as printed:
                    text = ''.join(sheet.get_text() for sheet in printed)
                    assert all(identifier in text for identifier in IDS) and 'Applicability' in text
                    for i, sheet in enumerate(printed):
                        sheet.get_pixmap().save(artifacts / f'print-{i + 1}.png')
                page.emulate_media(media='screen')
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(publish, publisher, 'withdraw').result(timeout=20)
            page.reload(wait_until='networkidle')
            assert page.locator('.kg-answer-text').count() == 0
            assert 'Specialist review is required.' in page.locator('#kg-answer-result').inner_text()
            assert not external, 'answer screen attempted third-party asset requests'
            assert not page.locator('link[rel=preconnect]').count()
            page.screenshot(path=str(artifacts / f'fallback-{width}.png'), full_page=True)
            context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
