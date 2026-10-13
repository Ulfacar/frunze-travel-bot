"""Explicit local browser check: python -m pytest tests/browser_kg_entry.py -q -s.

Synthetic SQLite, isolated loopback app, outside requests aborted. No production.
"""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_kg_entry import env, count, saved


def test_mobile_desktop_save_reload_and_historical_view(env,monkeypatch):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    local=FastAPI()
    local.add_middleware(SessionMiddleware,secret_key='synthetic-kg-browser-session',https_only=False)
    local.include_router(ar.router)
    screenshots=Path('runs/e5-04c-intake-browser');screenshots.mkdir(parents=True,exist_ok=True)
    review_shots=screenshots
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        deadline=time.monotonic()+5
        while not server.started and time.monotonic()<deadline:time.sleep(.05)
        assert server.started
        origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch()
            for width,js,language in [(390,True,'ru'),(1365,False,'en')]:
                context=browser.new_context(viewport={'width':width,'height':850},java_script_enabled=js)
                context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
                assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
                page=context.new_page()
                page.goto(origin+f"/admin/case/{env['cases']['visa']}",wait_until='networkidle')
                page.get_by_role('link',name='Анкета въезда в Кыргызстан').click()
                page.wait_for_url('**/kg-entry')
                page.locator('#kg-language').select_option(language)
                page.locator('#kg-citizenship').select_option(['RUS'])
                page.locator('#kg-entry_passport_country').select_option('RUS')
                page.locator('#kg-document_type').select_option('ordinary')
                page.locator('[name="passport_expiry_state"]').select_option('value')
                page.locator('#kg-passport_expiry').fill('2030-01-01')
                page.locator('#kg-purpose').select_option('tourism')
                page.locator('#kg-current_location').select_option('abroad')
                page.locator('#kg-client_type').select_option('b2c')
                page.locator('[name="applicants_count_state"]').select_option('value')
                page.locator('#kg-applicants_count').fill('2')
                page.locator('#kg-purpose_details').fill('Синтетический семейный визит')
                page.locator('#kg-family-state').select_option('value')
                if not page.locator('#kg-family-members').get_attribute('open') and not js:
                    # Native details disclosure remains usable without JavaScript.
                    if not page.locator('#kg-family-0-relation').is_visible():
                        page.locator('#kg-family-members > summary').click()
                page.locator('#kg-family-0-relation').select_option('child')
                page.locator('[name="family.0.age_state"]').select_option('value')
                page.locator('#kg-family-0-age').fill('0')
                page.locator('#kg-family-0-travels_together').select_option('true')
                page.locator('#kg-family-0-both_parents_travel').select_option('false')
                if js:
                    page.locator('#kg-family-state').select_option('none')
                    assert page.locator('#kg-family-0-age').is_disabled()
                    page.locator('#kg-family-state').select_option('value')
                    assert page.locator('#kg-family-0-age').is_enabled()
                page.locator('#kg-inviting_party-exists').select_option('true')
                page.locator('#kg-inviting_party-type').select_option('company')
                page.locator('#kg-inviting_party-can_issue_letter').select_option('false')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.locator('#kg-language').focus()
                assert page.locator('#kg-language').evaluate('(e)=>document.activeElement===e')
                page.screenshot(path=str(screenshots/f'form-{width}.png'),full_page=True)
                page.get_by_role('button',name='Сохранить анкету').click()
                page.wait_for_url('**/kg-entry?qualification_id=*')
                page.wait_for_load_state('networkidle')
                assert page.locator('#kg-result-title').inner_text()=='Нужно уточнить сведения'
                assert page.locator('#kg-next-questions li').count()<=3
                assert page.locator('#kg-passport_expiry').input_value()=='2030-01-01'
                page.reload(wait_until='networkidle')
                assert page.locator('#kg-language').input_value()==language
                assert page.locator('#kg-family-0-age').input_value()=='0'
                assert page.locator('#kg-purpose_details').input_value()=='Синтетический семейный визит'
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(screenshots/f'saved-{width}.png'),full_page=True)
                saved_url=page.url
                page.get_by_role('link',name='Карточка для проверки',exact=True).click()
                page.wait_for_url('**/kg-entry/review/*')
                assert page.get_by_role('heading',name='Карточка проверки въезда в Кыргызстан',exact=True).count()==1
                assert page.locator('#kg-card-revision').inner_text().startswith('Анкета №')
                assert page.get_by_role('heading',name='Член семьи №1',exact=True).count()==1
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.locator('#kg-print').is_visible()==js
                page.get_by_role('link',name='← К этой версии анкеты').focus()
                assert page.get_by_role('link',name='← К этой версии анкеты').evaluate('(e)=>document.activeElement===e')
                page.screenshot(path=str(review_shots/f'review-{width}.png'),full_page=True)
                page.emulate_media(media='print')
                assert page.locator('.topbar').is_hidden() and page.locator('.kg-no-print').first.is_hidden()
                assert page.locator('#kg-card-checks').is_visible()
                if width==1365:
                    page.pdf(path=str(review_shots/'review-demo.pdf'),prefer_css_page_size=True)
                page.emulate_media(media='screen')
                review_url=page.url
                page.get_by_role('link',name='Поиск по исходному PDF',exact=True).click()
                page.locator('#kg-search-query').fill('семья')
                page.locator('#kg-search-block').select_option('10')
                page.get_by_role('button',name='Найти',exact=True).click()
                page.wait_for_load_state('networkidle')
                assert page.locator('#kg-search-count').is_visible()
                assert page.locator('.kg-fragment').first.inner_text().startswith('# БЛОК 10')
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(screenshots/f'search-{width}.png'),full_page=True)
                page.get_by_role('link',name='← Рабочий день',exact=True).click()
                page.wait_for_url('**/admin/work')
                assert page.get_by_role('heading',name='Рабочий день',exact=True).count()==1
                page.goto(review_url,wait_until='networkidle')
                page.get_by_role('link',name='← К этой версии анкеты').click()
                page.wait_for_url(saved_url)
                if width==1365:
                    page.get_by_role('link',name='Предыдущая версия',exact=True).click()
                    assert page.locator('#kg-entry-form button[type=submit]').count()==0
                    assert page.locator('#kg-language').is_disabled()
                    page.get_by_role('link',name='Последняя анкета',exact=True).click()
                    assert page.locator('#kg-language').input_value()=='en'
                context.close()
            browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
    assert count(env)==2 and saved(env)['revision']==2
    assert saved(env)['input']['profile']['family'][0]['age']==0
    print('Browser PASS: mobile/desktop, native save with/without JS, reload, history, review card/print/PDF, labels/focus, no horizontal overflow')
