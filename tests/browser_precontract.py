"""Loopback only; actual no-JS forms with synthetic contracts and no providers."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
from tests.test_admin_precontract import env,contract_env
from tests.test_admin_contracts import snapshot


def test_mobile_dark_and_desktop_nojs_same_case_contract(env,monkeypatch):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    monkeypatch.setattr(ar.settings,'admin_new_look_enabled',True)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-preliminary-browser',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e630-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started;origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch()
            for width,theme in [(390,'dark'),(1365,'light')]:
                context=browser.new_context(viewport={'width':width,'height':900},java_script_enabled=False,color_scheme=theme)
                context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
                assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze','next':env['url']}).status==200
                page=context.new_page();page.goto(origin+env['url'],wait_until='networkidle')
                page.locator('#pre-product').select_option(index=1)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                page.screenshot(path=str(artifacts/f'open-{width}.png'),full_page=True)
                page.get_by_role('button',name='Открыть карточку до договора').click()
                page.wait_for_url('**/admin/case/*')
                card=page.url
                page.goto(card+'/contract',wait_until='networkidle')
                page.locator('#pre-reference').fill(f'SYN-BROWSER-{width}')
                page.locator('#pre-signed').fill('2026-10-13T14:00')
                page.locator('#pre-amount').fill('100.50')
                page.locator('#pre-currency').fill('KGS')
                page.locator('#pre-confirmed').check()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                assert page.get_by_role('button',name='Сохранить договор в этой карточке').is_enabled()
                page.screenshot(path=str(artifacts/f'sign-{width}.png'),full_page=True)
                page.get_by_role('button',name='Сохранить договор в этой карточке').click()
                page.wait_for_url(card)
                assert f'SYN-BROWSER-{width}' in page.locator('h1').inner_text()
                page.reload(wait_until='networkidle')
                assert f'SYN-BROWSER-{width}' in page.locator('h1').inner_text()
                page.goto(card+'/contract',wait_until='networkidle')
                assert 'Договор уже записан' in page.locator('[role=alert]').inner_text()
                assert page.get_by_role('button',name='Сохранить договор в этой карточке').count()==0
                assert f'SYN-BROWSER-{width}' in page.locator('main').inner_text()
                page.screenshot(path=str(artifacts/f'recorded-{width}.png'),full_page=True)
                context.close()
            browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
    rows=snapshot(env['sm'])
    assert len(rows['service_cases'])==2 and len(rows['calendar_tasks'])==2 and not rows['service_payments']
