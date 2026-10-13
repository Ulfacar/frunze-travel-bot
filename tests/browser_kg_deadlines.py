"""Actual event selection, proposed arithmetic, manual evidence, history and print."""
import asyncio
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from app.domain.entry_storage import import_work_calendars
from tests.test_admin_kg_entry import ADMIN, env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_issued import setup,write
from tests.test_entry_deadlines import read
from tests.test_entry_storage import calendars


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_actual_anchor_manual_date_recalculation_and_history(env,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    app=setup(env)
    travel=write(env,app,'travel',dict(direction='entry',on='2026-09-07',source='stamp',proof='f'*64,passport_fingerprint='b'*64))
    imported=asyncio.run(import_work_calendars(env['engine'],actor=ADMIN,document=calendars()))
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-deadline',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-05-deadline-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page=context.new_page();page.goto(origin+env['url']+f"/applications?application_id={app['id']}",wait_until='networkidle')
            page.get_by_role('link',name='Сроки заявки',exact=True).click();page.wait_for_load_state('networkidle')
            page.locator('#kg-dl-anchor').select_option(f"travel:{travel['id']}")
            page.locator('#kg-dl-calendar').select_option([str(row['calendar_id']) for row in imported])
            page.locator('#kg-dl-policy').select_option('proposed');page.locator('#kg-dl-count').select_option('false')
            page.locator('#kg-dl-recalculate input[name=confirmed]').check()
            page.get_by_role('button',name='Сохранить расчёт',exact=True).click();page.wait_for_load_state('networkidle')
            result=page.locator('#kg-dl-result').inner_text()
            assert '2026-09-02' in result and 'Дата для внутреннего контроля: не установлена' in result
            page.locator('#kg-dl-due_on').fill('2026-10-20');page.locator('#kg-dl-evidence_on').fill('2026-09-10')
            page.locator('#kg-dl-proof').fill('a'*64);page.locator('#kg-dl-manual input[name=confirmed]').check()
            page.get_by_role('button',name='Записать дату',exact=True).click();page.wait_for_load_state('networkidle')
            assert 'Дата для внутреннего контроля: 2026-10-20' in page.locator('#kg-dl-result').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-dl-anchor').focus();assert page.locator('#kg-dl-anchor').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0, 0)');page.screenshot(path=str(artifacts/f'deadline-{width}.png'))
            page.locator('#kg-dl-result').evaluate('(e)=>window.scrollTo(0, e.getBoundingClientRect().top+scrollY-190)')
            page.screenshot(path=str(artifacts/f'deadline-result-{width}.png'))
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-dl-recalculate').is_hidden() and page.locator('#kg-dl-result').is_visible()
                page.pdf(path=str(artifacts/'deadline-demo.pdf'),prefer_css_page_size=True)
                page.emulate_media(media='screen')
            page.locator('#kg-dl-recalculate input[name=confirmed]').check()
            page.get_by_role('button',name='Сохранить расчёт',exact=True).click();page.wait_for_load_state('networkidle')
            assert 'Дата для внутреннего контроля: не установлена' in page.locator('#kg-dl-result').inner_text()
            page.get_by_role('link',name='Версия №2',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-dl-historical').count()==1
            assert page.locator('#kg-dl-manual').count()==0 and '2026-10-20' in page.locator('#kg-dl-result').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            context.close();browser.close()
        assert read(env,app)['current_revision']==3 and read(env,app)['selected']['snapshot']['manual'] is None
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
