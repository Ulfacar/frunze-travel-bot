"""Explicit synthetic browser test; loopback only, no external traffic or real clients."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env, saved
from tests.test_admin_kg_history import count, latest, url


@pytest.mark.parametrize('width,js', [(390, True), (1365, False)])
def test_native_history_and_pinned_card(env, width, js):
    api = pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    local = FastAPI()
    local.add_middleware(SessionMiddleware, secret_key='synthetic-history-browser', https_only=False)
    local.include_router(ar.router)
    artifacts = Path('runs/e5-04d-history-browser'); artifacts.mkdir(parents=True, exist_ok=True)
    listener = socket.socket(); listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(local, log_level='error', lifespan='off'))
    thread = threading.Thread(target=server.run, kwargs={'sockets': [listener]}, daemon=True); thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline: time.sleep(.05)
        assert server.started
        origin = f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': width, 'height': 850}, java_script_enabled=js)
            context.route('**/*', lambda route: route.continue_() if urlsplit(route.request.url).netloc == f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin + '/admin/login', form={'login': 'admin', 'password': 'frunze'}).status == 200
            page = context.new_page(); page.goto(origin + env['url'], wait_until='networkidle')
            page.get_by_role('link', name='История поездок в Кыргызстан', exact=True).click()
            page.wait_for_url('**/kg-entry/history')
            page.locator('#history-complete').select_option('true')
            page.locator('#trip-0-entry').fill('2026-09-01')
            page.locator('#trip-0-exit-state').select_option('date')
            page.locator('#trip-0-exit').fill('2026-09-10')
            page.locator('#trip-0-country').fill('RUS')
            page.locator('#trip-0-basis').select_option('visa_free')
            page.locator('#trip-0-evidence').select_option('passport_stamp')
            page.locator('#trip-0-confirmed').select_option('true')
            page.get_by_role('button', name='Добавить поездку', exact=True).click()
            page.wait_for_load_state('networkidle')
            assert page.locator('#trip-0-entry').input_value() == '2026-09-01'
            page.locator('#trip-1-entry').fill('2026-09-20')
            page.locator('#trip-1-exit-state').select_option('ongoing')
            page.locator('#trip-1-country').fill('RUS')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#history-complete').focus()
            assert page.locator('#history-complete').evaluate('(e)=>document.activeElement===e')
            page.get_by_role('button', name='Сохранить историю', exact=True).click()
            page.wait_for_url('**/history?history_id=*'); page.wait_for_load_state('networkidle')
            assert 'версия 1' in page.locator('#history-version').inner_text()
            page.screenshot(path=str(artifacts / f'history-{width}.png'), full_page=True)
            page.get_by_role('link', name='Использовать эту историю в новой проверке', exact=True).click()
            page.wait_for_url('**/kg-entry?history_id=*')
            assert page.locator('#kg-selected-history').is_visible()
            page.get_by_role('button', name='Сохранить анкету', exact=True).click()
            page.wait_for_url('**/kg-entry?qualification_id=*')
            page.get_by_role('link', name='Карточка для проверки', exact=True).click()
            page.wait_for_url('**/kg-entry/review/*'); page.wait_for_load_state('networkidle')
            assert page.locator('#kg-card-history').is_visible()
            assert '2026-09-10' in page.locator('main').inner_text()
            assert 'Ещё в Кыргызстане на дату истории' in page.locator('main').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts / f'card-{width}.png'), full_page=True)
            card = page.url
            if width == 1365:
                page.emulate_media(media='print')
                page.pdf(path=str(artifacts / 'history-card-demo.pdf'), prefer_css_page_size=True)
                page.emulate_media(media='screen')
            page.goto(origin + url(env), wait_until='networkidle')
            page.locator('#trip-0-exit').fill('2026-09-11')
            page.get_by_role('button', name='Сохранить историю', exact=True).click()
            page.wait_for_url('**/history?history_id=*')
            assert 'версия 2' in page.locator('#history-version').inner_text()
            page.goto(card, wait_until='networkidle')
            assert '2026-09-10' in page.locator('main').inner_text() and '2026-09-11' not in page.locator('main').inner_text()
            page.get_by_role('link', name='Открыть эту версию истории', exact=True).click()
            assert page.locator('#history-outdated').is_visible() and page.locator('#trip-0-entry').is_disabled()
            assert page.get_by_role('button', name='Сохранить историю', exact=True).count() == 0
            context.close(); browser.close()
    finally:
        server.should_exit = True; thread.join(timeout=10); listener.close()
    assert count(env) == 2 and latest(env)['revision'] == 2
    assert saved(env)['result']['history']['revision'] == 1
