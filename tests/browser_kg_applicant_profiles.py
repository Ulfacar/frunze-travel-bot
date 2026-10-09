"""Native register to individual interview, mobile and without JavaScript."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_applicant_profiles import person, read, enforce_sqlite_foreign_keys


@pytest.mark.parametrize('width,js', [(390,True),(1365,False)])
def test_native_person_profiles_remain_separate(env,width,js):
    api = pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    adult = person(env)
    child = person(env,'child',role='child')
    local = FastAPI()
    local.add_middleware(SessionMiddleware,secret_key='synthetic-applicant-profile',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-04-profile-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started
        origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch();context=browser.new_context(viewport={'width':width,'height':850},java_script_enabled=js)
            context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
            page=context.new_page();page.goto(origin+env['url']+'/applications',wait_until='networkidle')
            page.locator('summary',has_text='Все заявители:').click()
            page.get_by_role('link',name=f'Анкета заявителя №{adult["id"]}',exact=True).click()
            page.wait_for_load_state('networkidle')
            assert f'заявитель №{adult["id"]}' in page.locator('h1').inner_text()
            page.locator('#kg-language').select_option('en')
            page.locator('#kg-purpose').select_option('work_hire')
            page.get_by_role('button',name='Сохранить анкету',exact=True).click();page.wait_for_load_state('networkidle')
            assert 'Сохранённая версия №1' in page.locator('.kg-wrap').inner_text()
            assert 'Причины проверки' in page.locator('.kg-wrap').inner_text()
            assert page.locator('#kg-next-questions').count()==0
            page.locator('#kg-purpose').select_option('tourism')
            page.get_by_role('button',name='Сохранить анкету',exact=True).click();page.wait_for_load_state('networkidle')
            assert 'Сохранённая версия №2' in page.locator('.kg-wrap').inner_text()
            assert page.locator('#kg-next-questions').count()==1
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-language').focus()
            assert page.locator('#kg-language').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0, 0)')
            page.screenshot(path=str(artifacts/f'profile-{width}.png'))
            page.get_by_role('link',name='Предыдущая версия',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-purpose').input_value()=='work_hire'
            assert page.get_by_role('button',name='Сохранить анкету',exact=True).count()==0
            page.get_by_role('link',name='Заявители и подачи',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('summary',has_text='Все заявители:').click()
            page.get_by_role('link',name=f'Анкета заявителя №{child["id"]}',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-purpose').input_value()==''
            assert page.locator('#kg-language').input_value()=='ru'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            context.close();browser.close()
        assert read(env,adult)['current_revision']==2 and read(env,child)['saved'] is None
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
