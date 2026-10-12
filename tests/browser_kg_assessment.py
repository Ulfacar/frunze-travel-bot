"""Real browser: RU mobile/dark and EN desktop/light, no-JS and printed evidence."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_connected_qualification import setup, clock, route_clock, admins, publish
from tests.test_admin_kg_assessment import configure


@pytest.mark.parametrize('width,js,theme,language', [(390, True, 'dark', 'ru'), (1365, False, 'light', 'en')])
def test_actual_assessment_and_withdrawal(env, tmp_path, monkeypatch, width, js, theme, language):
    from playwright.sync_api import sync_playwright
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    import fitz
    setup(env, tmp_path, language=language)
    url = configure(env, monkeypatch)
    monkeypatch.setattr(ar.settings, 'admin_new_look_enabled', True)
    local = FastAPI(); local.add_middleware(SessionMiddleware, secret_key='synthetic-assessment-browser', https_only=False)
    local.include_router(ar.router)
    folder = Path('runs/e628-browser'); folder.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(local, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True); thread.start()
    try:
        until = time.monotonic() + 5
        while not server.started and time.monotonic() < until:
            time.sleep(.05)
        assert server.started
        origin = f'http://127.0.0.1:{port}'
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': width, 'height': 850}, java_script_enabled=js, color_scheme=theme)
            context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).netloc == f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin + '/admin/login', form={'login': 'admin', 'password': 'frunze'}).status == 200
            page = context.new_page(); page.goto(origin + url, wait_until='networkidle')
            assert page.locator('main').get_attribute('lang') == language
            assert page.locator('#assessment-duration').count() == 1
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert '90 / 180' in page.locator('#assessment-duration').inner_text()
            colours = page.locator('main p, main a, main h1, main h2, main dt, main dd').evaluate_all('''es => es.map(e => {
                let p=e, bg=getComputedStyle(p).backgroundColor;
                while(p.parentElement && (bg==='rgba(0, 0, 0, 0)' || bg==='transparent')) {
                    p=p.parentElement; bg=getComputedStyle(p).backgroundColor;
                }
                return {fg:getComputedStyle(e).color,bg};
            })''')
            def luminance(rgb):
                channels = [int(x)/255 for x in re.findall(r'\d+', rgb)[:3]]
                return sum((c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4)*w
                           for c, w in zip(channels, (.2126,.7152,.0722)))
            for pair in colours:
                low, high = sorted(luminance(v) for v in pair.values())
                assert (high+.05)/(low+.05) >= 4.5
            page.keyboard.press('Tab')
            assert page.evaluate('document.activeElement.tagName') == 'A'
            page.screenshot(path=str(folder/f'assessment-{width}.png'), full_page=True)
            page.emulate_media(media='print')
            filename = folder/f'assessment-{width}.pdf'
            page.pdf(path=str(filename), prefer_css_page_size=True)
            with fitz.open(filename) as pdf:
                assert 1 <= len(pdf) <= 2
                text = ''.join(sheet.get_text() for sheet in pdf)
                assert '90 / 180' in text and '10 / 30' in text
                assert ('does not guarantee' if language == 'en' else 'не гарантирует') in text
                pdf[0].get_pixmap().save(folder/f'print-{width}.png')
            page.emulate_media(media='screen')
            with ThreadPoolExecutor(max_workers=1) as pool:
                pool.submit(publish, env, 'withdraw', ids=env['published']).result(timeout=25)
            page.reload(wait_until='networkidle')
            assert page.locator('#assessment-duration').count() == 0
            assert ('Specialist review required' if language == 'en' else 'Требуется проверка специалиста') in page.locator('#assessment-result').inner_text()
            page.screenshot(path=str(folder/f'fallback-{width}.png'), full_page=True)
            context.close(); browser.close()
    finally:
        server.should_exit = True; thread.join(timeout=10); listener.close()
