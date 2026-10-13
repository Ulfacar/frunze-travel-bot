"""Explicit synthetic loopback browser check; all external traffic is blocked."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import counts


@pytest.mark.parametrize('width,js', [(390, True), (1365, False)])
def test_separate_applicants_correction_retry_and_independent_result(env, width, js):
    api = pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    local = FastAPI()
    local.add_middleware(SessionMiddleware, secret_key='synthetic-applications-browser', https_only=False)
    local.include_router(ar.router)
    artifacts = Path('runs/e6-01a-applications-browser'); artifacts.mkdir(parents=True, exist_ok=True)
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
            page.get_by_role('link', name='Заявители и подачи', exact=True).click()
            page.wait_for_url('**/kg-entry/applications')
            registry = page.url
            for role in ('primary', 'child'):
                page.locator('#kg-applicant-role').select_option(role)
                page.get_by_role('button', name='Добавить заявителя', exact=True).click()
                page.wait_for_load_state('networkidle')
            assert page.locator('#kg-applicants li').count() == 2
            persons = page.locator('#kg-application-applicant option').evaluate_all('(xs)=>xs.map(x=>x.value).filter(Boolean)')
            page.locator('#kg-application-applicant').select_option(persons[0])
            page.locator('#kg-application-procedure').select_option('visa')
            page.get_by_role('button', name='Создать черновик заявки', exact=True).click()
            page.wait_for_url('**/applications?application_id=*')
            original = page.url
            assert 'попытка 1' in page.locator('#kg-application-title').inner_text()
            for status, day in [('submitted', '01'), ('revision_requested', '02'), ('submitted', '03'), ('refused', '04')]:
                page.locator('#kg-event-status').select_option(status)
                page.locator('#kg-event-date').fill(f'2026-09-{day}')
                page.locator('#kg-event-source').select_option('portal')
                page.locator('#kg-event-reference').fill('AB12CD34')
                page.locator('#kg-event-confirmed').check()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.get_by_role('button', name='Сохранить факт', exact=True).click()
                page.wait_for_load_state('networkidle')
            assert page.locator('#kg-application-events .event').count() == 5
            assert 'Отказ' in page.locator('#kg-application-status').inner_text()
            assert page.locator('#kg-event-form').count() == 0
            page.screenshot(path=str(artifacts / f'refusal-{width}.png'), full_page=True)
            page.get_by_role('button', name='Создать связанную повторную попытку', exact=True).click()
            page.wait_for_load_state('networkidle')
            assert page.url != original and 'попытка 2' in page.locator('#kg-application-title').inner_text()
            assert page.locator('#kg-event-reference').input_value() == ''
            page.get_by_role('link', name='Предыдущая попытка', exact=False).click()
            page.wait_for_url(original)
            assert page.locator('#kg-application-events .event').count() == 5
            assert 'AB12CD34' in page.locator('#kg-application-reference').inner_text()
            assert page.locator('#kg-retry-form').count() == 0
            page.goto(registry, wait_until='networkidle')
            page.locator('#kg-application-applicant').select_option(persons[1])
            page.locator('#kg-application-procedure').select_option('registration')
            page.get_by_role('button', name='Создать черновик заявки', exact=True).click()
            page.wait_for_load_state('networkidle')
            for status, day in [('submitted', '05'), ('approved', '06')]:
                page.locator('#kg-event-status').select_option(status)
                page.locator('#kg-event-date').fill(f'2026-09-{day}')
                page.locator('#kg-event-source').select_option('official_document')
                page.locator('#kg-event-confirmed').check()
                page.get_by_role('button', name='Сохранить факт', exact=True).click()
                page.wait_for_load_state('networkidle')
            assert 'Одобрено' in page.locator('#kg-application-status').inner_text()
            assert 'Отказ' in page.locator('#kg-applications').inner_text() and 'Черновик' in page.locator('#kg-applications').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-applicant-role').focus()
            assert page.locator('#kg-applicant-role').evaluate('(e)=>document.activeElement===e')
            page.screenshot(path=str(artifacts / f'register-{width}.png'), full_page=True)
            if width == 1365:
                page.emulate_media(media='print')
                assert page.locator('.topbar').is_hidden() and page.locator('#kg-applicant-form').is_hidden()
                assert page.get_by_role('heading', name='Новая отдельная процедура', exact=True).is_hidden()
                assert page.locator('#kg-applicants-print').is_visible()
                assert page.locator('#kg-applicants-print li').count() == 2
                page.pdf(path=str(artifacts / 'applications-demo.pdf'), prefer_css_page_size=True)
            context.close(); browser.close()
    finally:
        server.should_exit = True; thread.join(timeout=10); listener.close()
    assert counts(env) == (2, 3, 9, 1, 0)
