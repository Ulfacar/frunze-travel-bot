"""Actual native candidate/fallback, mobile dark and desktop English without JS."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import re
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_approved_qualification import ready, clock, profile, save, POLICY, publish


@pytest.mark.parametrize('width,js,theme,language', [(390, True, 'dark', 'ru'), (1365, False, 'light', 'en')])
def test_candidate_and_withdrawal_browser(ready, monkeypatch, width, js, theme, language):
    from playwright.sync_api import sync_playwright
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    doc = profile(); doc['language'] = language
    save(ready, ready['person'], revision=1, key='browser-language', doc=doc)
    monkeypatch.setattr(ar.settings, 'admin_new_look_enabled', True)
    monkeypatch.setattr(ar.settings, 'kg_qualification_policy', ready['policy'].document)
    monkeypatch.setattr(ar.settings, 'kg_knowledge_policy_ref', POLICY.reference)
    monkeypatch.setattr(ar.settings, 'kg_knowledge_policy_sha256', POLICY.fingerprint)
    monkeypatch.setattr(ar.settings, 'kg_knowledge_publishers', list(POLICY.publishers))
    local = FastAPI()
    local.add_middleware(SessionMiddleware, secret_key='synthetic-route-browser', https_only=False)
    local.include_router(ar.router)
    folder = Path('runs/approved-route-browser'); folder.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(local, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets':[listener]}, daemon=True); thread.start()
    try:
        until = time.monotonic()+5
        while not server.started and time.monotonic()<until: time.sleep(.05)
        assert server.started
        origin = f'http://127.0.0.1:{port}'
        url = f"/admin/case/{ready['cases']['visa']}/kg-entry/applicants/{ready['person']['id']}/route"
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width':width,'height':850}, java_script_enabled=js, color_scheme=theme)
            context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login', form={'login':'admin','password':'frunze'}).status==200
            page=context.new_page(); page.goto(origin+url, wait_until='networkidle')
            channels=[int(n) for n in re.findall(r'\d+',page.evaluate('getComputedStyle(document.body).backgroundColor'))[:3]]
            assert len(channels)==3 and (max(channels)<80 if theme=='dark' else min(channels)>200)
            assert page.locator('#kg-route-candidate').count()==1
            assert page.locator('main').get_attribute('lang')==language
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(folder/f'candidate-{width}-{theme}.png'), full_page=True)
            if not js:
                page.emulate_media(media='print'); page.pdf(path=str(folder/'candidate.pdf'), prefer_css_page_size=True)
                import fitz
                with fitz.open(folder/'candidate.pdf') as document:
                    assert len(document)==1
                    assert 'have not been determined' in ''.join(sheet.get_text() for sheet in document)
                    document[0].get_pixmap().save(folder/'print-candidate.png')
                page.emulate_media(media='screen')
            # The synchronous Playwright context owns an event loop; the domain
            # helper starts its own loop and must run outside that context's thread.
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(publish, ready, 'withdraw').result(timeout=15)
            page.reload(wait_until='networkidle')
            assert page.locator('#kg-route-candidate').count()==0
            assert page.locator('#kg-route-fallback').count()==1
            page.screenshot(path=str(folder/f'fallback-{width}-{theme}.png'), full_page=True)
            if not js:
                page.emulate_media(media='print'); page.pdf(path=str(folder/'fallback.pdf'), prefer_css_page_size=True)
                with fitz.open(folder/'fallback.pdf') as document:
                    text = ''.join(sheet.get_text() for sheet in document)
                    assert len(document)==1 and 'Not all necessary rules' in text
                    document[0].get_pixmap().save(folder/'print-fallback.png')
            context.close(); browser.close()
    finally:
        server.should_exit=True; thread.join(timeout=10); listener.close()
