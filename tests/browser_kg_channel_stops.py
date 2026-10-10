"""Real local mobile/no-JS preview, explicit stop, recovery and print."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
import app.admin.kg_channel_stops as ui
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_entry_channel_stops import env,admins,activation,start,dialog,resolve,policy


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_stop_preview_confirmation_recovery_and_print(env,monkeypatch,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    iv=start(env);dialog(env);monkeypatch.setattr(ui,'resolve_dialog',resolve)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-stop-browser',https_only=False)
    local.include_router(ar.router);artifacts=Path('runs/e6-14-channel-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page=context.new_page();url=origin+ui._url(env['cases']['visa'],iv['applicant_id'],iv['interview_id'])
            page.goto(url,wait_until='networkidle')
            def submit(name):page.locator('#stop-'+name+' button').click();page.wait_for_load_state('networkidle')
            page.locator('#stop-dialog').focus();assert page.locator('#stop-dialog').evaluate('(node)=>node===document.activeElement')
            submit('select');assert page.locator('#stop-preview').is_visible() and page.locator('#stop-save').is_visible()
            assert '996700000001' in page.locator('#stop-preview').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/f'stop-preview-{width}.png'),full_page=True)
            page.locator('#stop-confirm').check()
            original=ui.service.bind_stop;original_read=ui.service.list_stops
            async def uncertain(*a,**kw):await original(*a,**kw);raise EntryStorageUnavailable('synthetic lost ACK')
            async def unavailable(*a,**kw):raise EntryStorageUnavailable('synthetic read failure')
            monkeypatch.setattr(ui.service,'bind_stop',uncertain);monkeypatch.setattr(ui.service,'list_stops',unavailable)
            submit('save');assert page.locator('#stop-retry').is_visible() and page.get_by_role('alert').is_visible()
            page.screenshot(path=str(artifacts/f'stop-retry-{width}.png'),full_page=True)
            monkeypatch.setattr(ui.service,'bind_stop',original);monkeypatch.setattr(ui.service,'list_stops',original_read)
            monkeypatch.setattr(ar.settings,'kg_channel_stop_policy',{})
            submit('retry');assert 'Автоответы остановлены' in page.locator('#stop-current').inner_text()
            assert not page.locator('#stop-select').count()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/f'stop-saved-{width}.png'),full_page=True)
            if width==1365:
                page.emulate_media(media='print');page.pdf(path=str(artifacts/'stop-demo.pdf'),prefer_css_page_size=True)
                import fitz
                with fitz.open(artifacts/'stop-demo.pdf') as printed:
                    assert 1<=len(printed)<=3 and all(page.get_text().strip() for page in printed)
                    full='\n'.join(page.get_text() for page in printed)
                    assert 'Автоответы остановлены' in full and '996700000001' in full and 'Принятие карточки' in full
                    for number,page in enumerate(printed):page.get_pixmap(matrix=fitz.Matrix(1.2,1.2)).save(artifacts/f'stop-print-{number+1}.png')
            context.close();browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
