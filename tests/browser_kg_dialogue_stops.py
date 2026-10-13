from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

import app.admin.router as ar
import app.admin.kg_channel_stops as ui
from tests.test_dialogue_stops import env,admins,activation,start,dialog,parameters,run,resolve,action


@pytest.mark.parametrize('width,js',[(390,True),(1365,False)])
def test_causal_history_and_privacy_hold_render_without_raw_message(env,monkeypatch,width,js):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    iv=start(env);did=dialog(env);args=parameters(env,iv,did)
    run(env,args);action(env,iv,'ack')
    run(env,args|dict(provider_id='HOLD',text='Do not store this'+' x'*1100,voice=True))
    monkeypatch.setattr(ui,'resolve_dialog',resolve)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-cause-browser',https_only=False)
    local.include_router(ar.router);artifacts=Path('runs/e629-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started;origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch()
            context=browser.new_context(viewport={'width':width,'height':900},java_script_enabled=js)
            context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
            page=context.new_page();page.goto(origin+ui._url(env['cases']['visa'],iv['applicant_id'],iv['interview_id']),wait_until='networkidle')
            panel=page.locator('#stop-causes');assert panel.locator('article').count()==2
            assert 'Возможное ограничение обработки данных' in panel.inner_text()
            assert 'Удаление данных не выполнялось' in panel.inner_text()
            assert 'Do not store this' not in page.locator('main').inner_text()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(artifacts/f'causes-{width}.png'),full_page=True)
            page.emulate_media(media='print');page.pdf(path=str(artifacts/f'causes-{width}.pdf'),prefer_css_page_size=True)
            import fitz
            with fitz.open(artifacts/f'causes-{width}.pdf') as pdf:
                assert 1<=len(pdf)<=3 and all(p.get_text().strip() for p in pdf)
                text='\n'.join(p.get_text() for p in pdf)
                assert 'Причины остановки' in text and 'Удаление данных не выполнялось' in text
                for i,pdfpage in enumerate(pdf):pdfpage.get_pixmap().save(artifacts/f'print-{width}-{i+1}.png')
            context.close();browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
