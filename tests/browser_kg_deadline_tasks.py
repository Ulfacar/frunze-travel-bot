"""Native task lifecycle on mobile and desktop without JavaScript."""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_entry_deadline_tasks import seed, read


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_native_task_lifecycle_history_and_print(env,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    app=seed(env)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-task',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e6-06-task-browser');artifacts.mkdir(parents=True,exist_ok=True)
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
            page=context.new_page();page.goto(origin+env['url']+f"/applications/{app['id']}/deadlines?rule=KG.DL.TEST",wait_until='networkidle')
            page.get_by_role('link',name='Задача контроля срока',exact=True).click();page.wait_for_load_state('networkidle')
            def submit(action):
                page.locator(f'#kg-task-{action} input[name=confirmed]').check()
                page.locator(f'#kg-task-{action} button[type=submit]').click();page.wait_for_load_state('networkidle')
            submit('sync')
            assert 'Запланирована' in page.locator('#kg-task-current').inner_text()
            page.locator('#kg-task-reason').select_option('urgent');submit('escalate')
            assert 'Приоритет: высокий' in page.locator('#kg-task-current').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.locator('#kg-task-complete button').focus()
            assert page.locator('#kg-task-complete button').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'task-{width}.png'))
            submit('complete')
            assert 'Выполнена' in page.locator('#kg-task-current').inner_text()
            assert page.locator('#kg-task-complete').count()==0
            assert 'срочная задача' in page.locator('#kg-task-events').inner_text()
            submit('sweep')
            assert 'Обработано правил: 1' in page.locator('#kg-task-batch').inner_text()
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'task-completed-{width}.png'))
            if width==1365:
                page.emulate_media(media='print')
                assert page.locator('#kg-task-sync').is_hidden() and page.locator('#kg-task-current').is_visible()
                page.pdf(path=str(artifacts/'task-demo.pdf'),prefer_css_page_size=True)
                import fitz
                with fitz.open(artifacts/'task-demo.pdf') as printed:
                    assert len(printed)==1 and 'Выполнена' in printed[0].get_text()
            context.close();browser.close()
        assert read(env,app)['current']['task']['status']=='completed'
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
