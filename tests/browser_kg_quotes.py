"""Real mobile and no-JavaScript preview/save/retry/history/print flow."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
import app.admin.kg_quotes as ui
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_entry_quotes import env,admins,policy,subject


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_quote_preview_save_and_recovery(env,monkeypatch,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    app=subject(env);monkeypatch.setattr(ar.settings,'kg_quote_policy',{})
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-quote-browser',https_only=False)
    local.include_router(ar.router);artifacts=Path('runs/e6-13-quote-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page=context.new_page();url=origin+ui._url(env['cases']['visa'],app['id']);page.goto(url,wait_until='networkidle')
            assert page.locator('#quote-disabled').is_visible()
            monkeypatch.setattr(ar.settings,'kg_quote_policy',policy().document());page.reload(wait_until='networkidle')
            def form(name):return page.locator(f'form[data-quote-action="{name}"]')
            def submit(name):form(name).locator('button').click();page.wait_for_load_state('networkidle')
            form('preview').locator('[name="urgent"]').select_option('1')
            form('preview').locator('[name="additional_blocks"]').focus();assert form('preview').locator('[name="additional_blocks"]').evaluate('(node)=>node===document.activeElement')
            submit('preview');assert page.locator('#quote-preview').is_visible() and form('save').is_visible()
            assert '200.00 USD' in page.locator('#quote-preview').inner_text()
            assert 'Полная цена не определена' in page.locator('#quote-preview').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/f'quote-preview-{width}.png'),full_page=True)
            original=ui.service.save_quote;original_read=ui.service.read_quotes
            async def uncertain(*a,**kw):await original(*a,**kw);raise EntryStorageUnavailable('synthetic lost ACK')
            async def unavailable(*a,**kw):raise EntryStorageUnavailable('synthetic reread failure')
            monkeypatch.setattr(ui.service,'save_quote',uncertain);monkeypatch.setattr(ui.service,'read_quotes',unavailable)
            submit('save');assert form('retry').is_visible() and page.get_by_role('alert').is_visible()
            page.screenshot(path=str(artifacts/f'quote-retry-{width}.png'),full_page=True)
            monkeypatch.setattr(ui.service,'save_quote',original);monkeypatch.setattr(ui.service,'read_quotes',original_read)
            submit('retry');assert page.locator('#quote-saved').is_visible()
            monkeypatch.setattr(ar.settings,'kg_quote_policy',{});page.reload(wait_until='networkidle')
            assert page.locator('#quote-disabled').is_visible() and 'Нет действующих полномочий' in page.locator('#quote-saved').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/f'quote-saved-{width}.png'),full_page=True)
            if width==1365:
                page.emulate_media(media='print');page.pdf(path=str(artifacts/'quote-demo.pdf'),prefer_css_page_size=True)
                import fitz
                with fitz.open(artifacts/'quote-demo.pdf') as printed:
                    assert 1<=len(printed)<=4 and all(page.get_text().strip() for page in printed)
                    full='\n'.join(page.get_text() for page in printed)
                    assert 'Полная цена не определена' in full and '200.00 USD' in full and 'Нет действующих полномочий' in full
            context.close();browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
