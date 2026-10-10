"""Real native receive/correlate/verify/retry flow, mobile and no JavaScript."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
import app.admin.kg_portal as ui
from app.domain.entry_storage import EntryStorageUnavailable
from tests.test_admin_kg_entry import env
from tests.test_entry_portal import setup,read
from tests.test_entry_portal_parser import policy,message
from tests.test_entry_applications import enforce_sqlite_foreign_keys


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_portal_flow_and_lost_ack_recovery(env,monkeypatch,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    setup(env)
    monkeypatch.setattr(ar.settings,'kg_portal_observation_policy',{})
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-portal-browser',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-11-portal-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page=context.new_page();url=origin+env['url']+'/portal';page.goto(url,wait_until='networkidle')
            assert page.locator('#kg-portal-disabled').is_visible()
            monkeypatch.setattr(ar.settings,'kg_portal_observation_policy',policy().document());page.reload(wait_until='networkidle')
            form=page.locator('form[data-portal-action="receive-paste"]');form.locator('..').locator('summary').click()
            for name,value in dict(transport_id='SYN-BROWSER',archive_reference='SYN-ARCHIVE',archive_proof='d'*64,text=message()).items():
                form.locator(f'[name="{name}"]').fill(value)
            form.locator('textarea').focus();assert form.locator('textarea').evaluate('(e)=>document.activeElement===e')
            form.locator('button').click();page.wait_for_load_state('networkidle')
            receipt_id=int(page.url.split('receipt_id=')[-1])
            form=page.locator('form[data-portal-action="correlate"]');form.locator('[name="confirmed"]').check()
            form.locator('button').click();page.wait_for_load_state('networkidle')
            form=page.locator('form[data-portal-action="confirm"]')
            for name,value in dict(on='2026-10-10',verification_reference='SYN-BROWSER-CHECK',verification_proof='e'*64).items():
                form.locator(f'[name="{name}"]').fill(value)
            form.locator('[name="source"]').select_option('portal')
            form.locator('[name="confirmed"]').check();form.locator('[name="cycle_verified"]').check()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/f'portal-confirm-{width}.png'),full_page=True)
            original=ui.service.record_action
            async def uncertain(*args,**kwargs):
                await original(*args,**kwargs)
                raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
            monkeypatch.setattr(ui.service,'record_action',uncertain)
            form.locator('button').click();page.wait_for_load_state('networkidle')
            assert page.get_by_role('alert').is_visible() and page.locator('form[data-portal-action="retry"]').is_visible()
            page.screenshot(path=str(artifacts/f'portal-retry-{width}.png'),full_page=True)
            monkeypatch.setattr(ui.service,'record_action',original)
            page.locator('form[data-portal-action="retry"] button').click();page.wait_for_load_state('networkidle')
            assert page.get_by_role('heading',name='Подтверждение записано в заявку').is_visible()
            assert page.locator('.kg-portal form').count()==0
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/f'portal-{width}.png'),full_page=True)
            if width==1365:
                page.emulate_media(media='print');page.pdf(path=str(artifacts/'portal-demo.pdf'),prefer_css_page_size=True)
                import fitz
                with fitz.open(artifacts/'portal-demo.pdf') as printed:
                    assert 1<=len(printed)<=2 and all(p.get_text().strip() for p in printed)
                    assert 'Уведомления портала' in printed[0].get_text()
            context.close();browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
    assert read(env,{'id':receipt_id})['state']['disposition']=='applied'
