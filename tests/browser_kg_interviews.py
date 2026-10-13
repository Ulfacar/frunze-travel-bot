"""Actual native questionnaire, acknowledgement and retry in mobile/no-JS browsers."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
import app.admin.kg_interviews as ui
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import env
from tests.test_entry_interviews import admins,policy
from tests.test_entry_applications import person,enforce_sqlite_foreign_keys


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_interview_and_acceptance(env,monkeypatch,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    applicant=person(env);monkeypatch.setattr(ar.settings,'kg_interview_policy',{})
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-interview-browser',https_only=False)
    local.include_router(ar.router);artifacts=Path('runs/e6-12-interview-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started;origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch();context=browser.new_context(viewport={'width':width,'height':850},java_script_enabled=js)
            context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
            page=context.new_page();url=origin+ui._url(env['cases']['visa'],applicant['id']);page.goto(url,wait_until='networkidle')
            assert page.locator('#kg-interview-disabled').is_visible()
            monkeypatch.setattr(ar.settings,'kg_interview_policy',policy().document());page.reload(wait_until='networkidle')
            def form(name):return page.locator(f'form[data-interview-action="{name}"]')
            def submit(name):form(name).locator('button').click();page.wait_for_load_state('networkidle')
            form('start').locator('[name="owner"]').select_option('admin')
            form('start').locator('[name="language"]').select_option('en');submit('start')
            assert page.get_by_role('heading',name='A6 · Has this applicant given consent to data processing?').is_visible()
            assert 1<=form('answer').locator('section.question').count()<=3
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/f'interview-questions-{width}.png'),full_page=True)
            for select in form('answer').locator('select[name^="m"]').all():select.select_option('unknown')
            form('answer').locator('[name="m0"]').focus();assert form('answer').locator('[name="m0"]').evaluate('(e)=>document.activeElement===e')
            submit('answer');submit('pause');assert form('answer').count()==0
            submit('language');submit('resume');assert form('answer').count()==1
            # Save a valid answer through the actual correction form.
            page.goto(url+'?field=entry_on',wait_until='networkidle')
            form('correct').locator('[name="m0"]').select_option('value');form('correct').locator('[name="v0"]').fill('2026-12-01')
            submit('correct')
            original=ui.service.record_action;original_read=ui.service.read_interview
            async def uncertain(*args,**kwargs):
                await original(*args,**kwargs);raise EntryStorageUnavailable('synthetic lost ACK')
            async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic reread unavailable')
            monkeypatch.setattr(ui.service,'record_action',uncertain);monkeypatch.setattr(ui.service,'read_interview',unavailable)
            submit('handoff');assert page.get_by_role('alert').is_visible() and form('retry').is_visible()
            page.screenshot(path=str(artifacts/f'interview-retry-{width}.png'),full_page=True)
            monkeypatch.setattr(ui.service,'record_action',original);monkeypatch.setattr(ui.service,'read_interview',original_read)
            submit('retry');assert form('answer').count()==0
            assert page.get_by_role('heading',name='Ожидает принятия специалистом').is_visible()
            form('ack').locator('[name="confirmed"]').check();submit('ack')
            assert page.get_by_role('heading',name='Принято специалистом').is_visible()
            page.goto(url+'?field=contact_name',wait_until='networkidle')
            form('correct').locator('[name="m0"]').select_option('value');form('correct').locator('[name="v0"]').fill('Synthetic applicant')
            submit('correct');assert form('answer').count()==0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/f'interview-accepted-{width}.png'),full_page=True)
            if width==1365:
                page.emulate_media(media='print');page.pdf(path=str(artifacts/'interview-demo.pdf'),prefer_css_page_size=True)
                import fitz
                with fitz.open(artifacts/'interview-demo.pdf') as printed:
                    assert 1<=len(printed)<=8 and all(p.get_text().strip() for p in printed)
                    full='\n'.join(p.get_text() for p in printed)
                    assert 'Зафиксированная карточка передачи' in full and 'Принял admin' in full and 'Synthetic applicant' in full
            context.close();browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
