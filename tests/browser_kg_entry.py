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
    screenshots=Path('runs/e5-04a-crm-browser');screenshots.mkdir(parents=True,exist_ok=True)
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
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(screenshots/f'saved-{width}.png'),full_page=True)
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
    print('Browser PASS: mobile/desktop, native save with/without JS, reload, history, labels/focus, no horizontal overflow')
