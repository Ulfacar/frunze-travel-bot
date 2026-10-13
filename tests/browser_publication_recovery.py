"""Real native withdrawal at capacity: phone/dark and desktop/no JavaScript."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
from app.domain import knowledge_publication as service
import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_admin_kg_knowledge_publication import publisher, url
from tests.test_knowledge_publication import release, activate


@pytest.mark.parametrize('width,js,theme', [(390, True, 'dark'), (1365, False, 'light')])
def test_capacity_withdrawal_native_browser(publisher, monkeypatch, width, js, theme):
    from playwright.sync_api import sync_playwright
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    activate(publisher)
    monkeypatch.setattr(service, 'MAX_REVISIONS', 3)
    monkeypatch.setattr(ar.settings, 'admin_new_look_enabled', True)
    local = FastAPI()
    local.add_middleware(SessionMiddleware, secret_key='synthetic-publication-recovery', https_only=False)
    local.include_router(ar.router)
    folder = Path('runs/publication-recovery-browser'); folder.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(local, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[listener]}, daemon=True); thread.start()
    try:
        until = time.monotonic()+5
        while not server.started and time.monotonic() < until: time.sleep(.05)
        assert server.started
        origin = f'http://127.0.0.1:{port}'
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':width, 'height':850}, java_script_enabled=js, color_scheme=theme)
            context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).netloc == f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login', form={'login':'admin', 'password':'frunze'}).status == 200
            page = context.new_page(); page.goto(origin+url(publisher), wait_until='networkidle')
            background = page.evaluate('getComputedStyle(document.body).backgroundColor')
            import re
            channels = [int(n) for n in re.findall(r'\d+', background)[:3]]
            assert len(channels) == 3 and (max(channels) < 80 if theme == 'dark' else min(channels) > 200), background
            form = page.locator('#kg-publication-withdraw')
            assert form.count() == 1 and form.get_by_role('button').is_enabled()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(folder/f'before-{width}-{theme}.png'), full_page=True)
            form.get_by_role('checkbox').check(); form.get_by_role('button').click()
            page.wait_for_load_state('networkidle')
            assert 'выведена из использования' in page.locator('#kg-publication-summary').inner_text()
            assert page.locator('#kg-publication-withdraw,#kg-publication-review,#kg-publication-rollback').count() == 0
            assert page.locator('#kg-publication-history li').count() == 4
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(folder/f'after-{width}-{theme}.png'), full_page=True)
            if not js:
                page.emulate_media(media='print'); page.pdf(path=str(folder/'withdrawal.pdf'), prefer_css_page_size=True)
                import fitz
                with fitz.open(folder/'withdrawal.pdf') as document:
                    assert 'Отозвать активную версию' in ''.join(sheet.get_text() for sheet in document)
                    for i,sheet in enumerate(document): sheet.get_pixmap().save(folder/f'print-{i+1}.png')
            context.close(); browser.close()
    finally:
        server.should_exit = True; thread.join(timeout=10); listener.close()
