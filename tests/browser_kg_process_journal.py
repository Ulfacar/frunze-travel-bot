"""Native process flow, keyboard/mobile/no-JS and printable local evidence."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
import app.admin.kg_process_journal as ui
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import person,application,enforce_sqlite_foreign_keys
from tests.test_entry_processes import policy,read


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_process_and_exact_retry(env,monkeypatch,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    subject=application(env,person(env))
    monkeypatch.setattr(ar.settings,'kg_process_execution_policy',{})
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-process-browser',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-10-process-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page=context.new_page();url=origin+env['url']+'/applications/'+str(subject['id'])+'/process-journal'
            page.goto(url,wait_until='networkidle')
            assert page.locator('#kg-pj-disabled').is_visible() and page.locator('#kg-pj-initialize').count()==0
            monkeypatch.setattr(ar.settings,'kg_process_execution_policy',policy().document());page.reload(wait_until='networkidle')
            page.locator('#kg-pj-initialize input[name="confirmed"]').check()
            page.locator('#kg-pj-initialize button').click();page.wait_for_load_state('networkidle')
            form=page.locator('[id="kg-pj-attest-visa.conversation_started"]')
            form.locator('..').locator('summary').click()
            form.locator('[name="value"]').select_option('true');form.locator('[name="valid_through"]').fill('2026-12-31')
            form.locator('[name="reference"]').fill('SYNTHETIC');form.locator('[name="proof"]').fill('3'*64)
            form.locator('[name="confirmed"]').check();form.locator('[name="proof"]').focus()
            assert form.locator('[name="proof"]').evaluate('(e)=>document.activeElement===e')
            original=ui.service.record_process_operation
            async def uncertain(*args,**kwargs):
                await original(*args,**kwargs)
                raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
            monkeypatch.setattr(ui.service,'record_process_operation',uncertain)
            form.locator('button').click();page.wait_for_load_state('networkidle')
            assert page.get_by_role('alert').is_visible() and page.locator('#kg-pj-retry').is_visible()
            page.screenshot(path=str(artifacts/f'process-retry-{width}.png'),full_page=True)
            monkeypatch.setattr(ui.service,'record_process_operation',original)
            page.locator('#kg-pj-retry button').click();page.wait_for_load_state('networkidle')
            move=page.locator('#kg-pj-transition-V02');move.locator('[name="confirmed"]').check();move.locator('button').click()
            page.wait_for_load_state('networkidle')
            assert 'V02' in page.locator('#kg-pj-summary h2').inner_text()
            assert 'Квалификация' in page.locator('#kg-pj-summary h2').inner_text() or len(page.locator('#kg-pj-summary h2').inner_text())>8
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.evaluate("window.scrollTo({top:0,behavior:'instant'})");page.screenshot(path=str(artifacts/f'process-{width}.png'),full_page=True)
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-pj-stop').is_hidden() and page.locator('#kg-pj-summary').is_visible()
                page.pdf(path=str(artifacts/'process-demo.pdf'),prefer_css_page_size=True)
                page.emulate_media(media='screen')
                import fitz
                with fitz.open(artifacts/'process-demo.pdf') as printed:
                    assert 1<=len(printed)<=2 and all(p.get_text().strip() for p in printed)
                    assert 'Этапы заявки' in printed[0].get_text()
            page.goto(url+'?revision=1',wait_until='networkidle')
            assert page.locator('#kg-pj-historical').is_visible() and page.locator('.kg-process form').count()==0
            context.close();browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
    assert read(env,subject)['current_revision']==3
