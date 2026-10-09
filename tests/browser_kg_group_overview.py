"""Explicit loopback browser acceptance for whole-case group summary."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import counts
from tests.test_entry_group_overview import group


@pytest.mark.parametrize('width,js', [(390, True), (1365, False)])
def test_group_overview_filters_navigation_focus_mobile_and_print(env, width, js):
    api = pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    first, second, missing, approved, old, retry, registration, independent = group(env)
    before = counts(env)
    local = FastAPI(); local.add_middleware(SessionMiddleware, secret_key='synthetic-group-overview', https_only=False)
    local.include_router(ar.router)
    artifacts = Path('runs/e6-01b-group-browser'); artifacts.mkdir(parents=True, exist_ok=True)
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
            page = context.new_page(); registry = origin + env['url'] + '/applications'
            page.goto(registry, wait_until='networkidle')
            page.get_by_role('link', name='Сводка группы', exact=True).click(); page.wait_for_load_state('networkidle')
            assert page.locator('#kg-group-people article').count() == 3
            assert page.locator('#kg-group-people li[data-application]').count() == 4
            assert 'текущих заявок: 4' in page.locator('#kg-group-totals').inner_text()
            assert 'Есть заявители без заявок' in page.locator('#kg-group-summary-title').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-group-selection').focus()
            assert page.locator('#kg-group-selection').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(artifacts / f'overview-{width}.png'), full_page=True)
            page.locator('#kg-group-selection').select_option('draft')
            page.get_by_role('button', name='Применить фильтр', exact=True).click(); page.wait_for_load_state('networkidle')
            assert page.locator('#kg-group-people article').count() == 1
            assert page.locator('#kg-group-people li[data-application]').count() == 3
            assert 'Заявителей: 3' in page.locator('#kg-group-totals').inner_text()
            page.get_by_role('link', name=f'Предыдущая попытка №{old["id"]}', exact=True).click(); page.wait_for_load_state('networkidle')
            assert 'Отказ' in page.locator('#kg-application-status').inner_text()
            page.get_by_role('link', name='Сводка группы', exact=True).click(); page.wait_for_load_state('networkidle')
            page.locator('#kg-group-selection').select_option('without_applications')
            page.get_by_role('button', name='Применить фильтр', exact=True).click(); page.wait_for_load_state('networkidle')
            assert page.locator('#kg-group-people article').count() == 1
            assert 'Заявок пока нет' in page.locator('#kg-group-people').inner_text()
            page.evaluate('window.scrollTo(0,0)')
            page.screenshot(path=str(artifacts / f'filtered-{width}.png'), full_page=True)
            if width == 1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-group-filter').is_hidden() and page.locator('.topbar').is_hidden()
                assert page.locator('#kg-group-page-scope').is_visible()
                assert page.locator('#kg-group-read-at').is_visible()
                assert 'Фильтр: Нет заявок' in page.locator('#kg-group-page-scope').inner_text()
                page.pdf(path=str(artifacts / 'group-filtered-demo.pdf'), prefer_css_page_size=True)
                page.emulate_media(media='screen'); page.goto(registry + '/overview', wait_until='networkidle')
                page.emulate_media(media='print'); page.pdf(path=str(artifacts / 'group-all-demo.pdf'), prefer_css_page_size=True)
            context.close(); browser.close()
    finally:
        server.should_exit = True; thread.join(timeout=10); listener.close()
    assert counts(env) == before
