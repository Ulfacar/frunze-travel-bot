"""Actual local browser POST/retry at RES registration and dismissal follow-up."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

from tests.test_work_process_v2 import base_env,env,complete_work_flow,attest,transition,read
from tests.test_entry_applications import enforce_sqlite_foreign_keys


def test_resident_basis_and_dismissal_in_real_mobile_and_nojs_browser(env,monkeypatch):
    from playwright.sync_api import sync_playwright
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    import app.admin.router as ar
    import app.admin.kg_process_journal as ui
    from app.domain.entry_storage import EntryStorageUnavailable

    artifacts=Path('runs/work-browser');artifacts.mkdir(parents=True,exist_ok=True)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-work-browser',https_only=False)
    local.include_router(ar.router)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    until=time.monotonic()+5
    while not server.started and time.monotonic()<until:time.sleep(.05)
    assert server.started
    origin=f'http://127.0.0.1:{port}'
    def open_form(page,url,name):
        page.goto(url,wait_until='networkidle')
        form=page.locator('[id="kg-pj-'+name+'"]')
        form.locator('..').locator('summary').click()
        assert form.locator('button').is_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        return form

    def fill(form,values):
        for key in ('value','source'):form.locator('[name="'+key+'"]').select_option(values[key])
        for key in ('valid_through','reference','proof','basis_valid_from','basis_valid_until','basis_registration_from','basis_registration_until'):
            field=form.locator('[name="'+key+'"]')
            if field.count():field.fill(values[key])
        form.locator('[name="confirmed"]').check()

    def contexts(browser):
        items=[]
        for width,js in ((390,True),(1365,False)):
            context=browser.new_context(viewport={'width':width,'height':900},java_script_enabled=js)
            context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
            items.append((width,context,context.new_page()))
        return items

    def native_basis(env,root,values):
        url=origin+env['url']+'/applications/'+str(root['id'])+'/process-journal'
        with sync_playwright() as p:
            browser=p.chromium.launch();items=contexts(browser)
            for width,context,page in items:
                form=open_form(page,url,'attest-resident_registration.resident_registration_basis_reviewed')
                assert form.locator('input[type="number"]').count()==0
                fill(form,values)
                form.locator('button').scroll_into_view_if_needed()
                page.screenshot(path=str(artifacts/f'basis-form-{width}.png'))
            page=items[1][2]  # actual POST with JavaScript disabled
            original=ui.service.record_process_operation
            async def uncertain(*args,**kwargs):
                await original(*args,**kwargs)
                raise EntryStorageUnavailable('commit_outcome_unknown_retry_same_request')
            monkeypatch.setattr(ui.service,'record_process_operation',uncertain)
            form.locator('button').click();page.wait_for_load_state('networkidle')
            assert page.get_by_role('alert').is_visible() and page.locator('#kg-pj-retry').is_visible()
            page.locator('#kg-pj-retry').scroll_into_view_if_needed()
            page.screenshot(path=str(artifacts/'basis-retry-1365.png'))
            monkeypatch.setattr(ui.service,'record_process_operation',original)
            page.locator('#kg-pj-retry button').click();page.wait_for_load_state('networkidle')
            assert page.get_by_role('alert').count()==0
            for _,context,_ in items:context.close()
            browser.close()

    try:
        root,entered,moved,allowed=complete_work_flow(env,monkeypatch,native_basis=native_basis)
        attest(env,root,'termination_observed',source='official_document')
        transition(env,root,'WX1',package_policy=allowed)
        url=origin+env['url']+'/applications/'+str(root['id'])+'/process-journal'
        with sync_playwright() as p:
            browser=p.chromium.launch();items=contexts(browser)
            for width,context,page in items:
                page.goto(url,wait_until='networkidle')
                assert 'WX1' in page.locator('#kg-pj-summary h2').inner_text()
                assert page.locator('#kg-pj-stage-notice').is_visible()
                page.locator('#kg-pj-summary').scroll_into_view_if_needed()
                page.screenshot(path=str(artifacts/f'dismissal-{width}.png'))
            page=items[0][2]
            for fact in ('termination_notice_recorded','cancellation_request_recorded','departure_plan_recorded'):
                form=open_form(page,url,'attest-permit.'+fact)
                fill(form,dict(value='true',source='official_document',valid_through='2026-12-31',reference='SYNTHETIC-BROWSER',proof='3'*64))
                form.locator('button').click();page.wait_for_load_state('networkidle')
                assert page.get_by_role('alert').count()==0
            for _,context,_ in items:context.close()
            browser.close()
        assert read(env,root)['readiness']['transitions']==[]
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
