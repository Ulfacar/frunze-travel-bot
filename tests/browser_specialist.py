"""Loopback no-JS desktop/mobile acceptance with synthetic specialist authority."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from tests.test_admin_kg_specialist import env,admins,clock,enforce_sqlite_foreign_keys,setup,configure,url,ON,read


def test_actual_nojs_review_quote_readability_mobile_dark_and_desktop_light(env,tmp_path,monkeypatch):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    setup(env,tmp_path);configure(env,monkeypatch)
    monkeypatch.setattr(ar.settings,'admin_new_look_enabled',True)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-specialist-browser',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/specialist-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started;origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch()
            for width,theme,language in [(390,'dark','ru'),(1365,'light','en')]:
                context=browser.new_context(viewport={'width':width,'height':900},java_script_enabled=False,color_scheme=theme)
                context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
                assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze','next':url(env,language)}).status==200
                page=context.new_page();page.goto(origin+url(env,language),wait_until='networkidle')
                form=page.locator('#specialist-record');form.locator('#disposition').select_option('manual_internal_plan')
                for field,value in {'meeting_nonprofit':'yes','local_work':'no','host_legal_entity_in_kg':'yes'}.items():form.locator('#'+field).select_option(value)
                form.locator('#reviewed_on').fill(ON)
                for row in env['findings']['evidence']:
                    for key in ('reference','proof','on'):form.locator('#'+row['fact']+'_'+key).fill(row[key])
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.evaluate("Array.from(document.querySelectorAll('.specialist button')).every(b=>getComputedStyle(b).color==='rgb(255, 255, 255)'&&getComputedStyle(b).backgroundColor==='rgb(21, 76, 63)')")
                assert page.evaluate("Array.from(document.querySelectorAll('.specialist input:not([type=hidden]),.specialist select')).every(e=>e.labels.length>0)")
                page.screenshot(path=str(artifacts/f'review-{width}.png'),full_page=True)
                form.locator('button').click();page.wait_for_load_state('networkidle')
                page.locator('#specialist-save button').click();page.wait_for_load_state('networkidle')
                page.locator('#specialist-preview button').click();page.wait_for_load_state('networkidle')
                assert '100.00 USD' in page.locator('#specialist-confirmation').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(artifacts/f'quote-{width}.png'),full_page=True)
                page.locator('#specialist-save button').click();page.wait_for_load_state('networkidle');page.reload(wait_until='networkidle')
                assert page.locator('a[href*="quotes?revision="]').count()==(1 if width==390 else 2)
                page.screenshot(path=str(artifacts/f'saved-{width}.png'),full_page=True)
                context.close()
            browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
    assert read(env)['revision']==4
