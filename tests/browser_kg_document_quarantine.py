"""Real multipart intake and uncertain-commit recovery, using synthetic bytes only."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
import app.admin.kg_document_quarantine as ui
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import env
from tests.test_entry_applications import enforce_sqlite_foreign_keys
from tests.test_entry_document_packages import setup, read
from tests.test_entry_quarantine import policy
from tests.test_quarantine_multipart import PDF


@pytest.mark.parametrize('width,js', [(390,True),(1365,False)])
def test_native_quarantine_upload_and_retry(env,monkeypatch,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    app=setup(env)
    monkeypatch.setattr(ar.settings,'kg_document_quarantine_policy',{})
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-quarantine-browser',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-09-quarantine-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page=context.new_page();package=origin+env['url']+'/applications/'+str(app['id'])+'/document-package'
            page.goto(package,wait_until='networkidle')
            page.get_by_role('link',name='Файлы заявки',exact=True).click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-q-disabled').is_visible() and page.locator('#kg-q-upload').count()==0
            monkeypatch.setattr(ar.settings,'kg_document_quarantine_policy',policy().document())
            page.reload(wait_until='networkidle')
            page.locator('#kg-q-item').select_option('t08_02');page.locator('#kg-q-select button').click();page.wait_for_load_state('networkidle')
            page.locator('#kg-q-on').fill('2026-09-03');page.locator('#kg-q-source').select_option('client_copy')
            page.locator('#kg-q-file').set_input_files({'name':'synthetic.pdf','mimeType':'application/pdf','buffer':b'MZinvalid PDF'})
            page.locator('#kg-q-confirm').check();page.locator('#kg-q-upload button').click();page.wait_for_load_state('networkidle')
            assert page.get_by_role('alert').is_visible() and page.locator('[data-file-id]').count()==0
            original=ui.service.record_upload
            async def uncertain(*args,**kwargs):
                await original(*args,**kwargs)
                raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
            monkeypatch.setattr(ui.service,'record_upload',uncertain)
            page.locator('#kg-q-file').set_input_files({'name':'synthetic.pdf','mimeType':'application/pdf','buffer':PDF})
            page.locator('#kg-q-upload button').click();page.wait_for_load_state('networkidle')
            assert page.get_by_role('alert').is_visible() and page.locator('#kg-q-saved').count()==0
            assert page.locator('input[name="_q_sha256"]').input_value()
            assert page.locator('[data-file-id]').count()==1
            page.evaluate("window.scrollTo({top:0,behavior:'instant'})");page.screenshot(path=str(artifacts/f'quarantine-retry-{width}.png'),full_page=True)
            monkeypatch.setattr(ui.service,'record_upload',original)
            page.locator('#kg-q-file').set_input_files({'name':'synthetic.pdf','mimeType':'application/pdf','buffer':PDF})
            page.locator('#kg-q-upload button').click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-q-saved').is_visible() and page.locator('[data-file-id]').count()==1
            assert page.locator('[data-file-id] a').count()==0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-q-file').focus();assert page.locator('#kg-q-file').evaluate('(e)=>document.activeElement===e')
            page.evaluate("window.scrollTo({top:0,behavior:'instant'})");page.screenshot(path=str(artifacts/f'quarantine-{width}.png'),full_page=True)
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-q-upload').is_hidden() and page.locator('[data-file-id]').is_visible()
                page.pdf(path=str(artifacts/'quarantine-demo.pdf'),prefer_css_page_size=True);page.emulate_media(media='screen')
                import fitz
                with fitz.open(artifacts/'quarantine-demo.pdf') as printed:
                    assert len(printed)==1 and 'История загрузок' in printed[0].get_text()
            page.goto(package+'?item=t08_02',wait_until='networkidle')
            assert page.locator('[data-item="t08_02"]').get_attribute('data-state')=='quarantined'
            assert page.locator('#kg-dp-review').count()==0 and page.locator('#kg-dp-approve').count()==0
            context.close();browser.close()
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
    inventory=read(env,app)
    assert inventory['current_revision']==2 and len(inventory['quarantine'])==1
