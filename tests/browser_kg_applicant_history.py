"""Actual native controls at mobile and no-JS desktop, RU/EN and print."""
from pathlib import Path
import socket
import re
import threading
import time
from urllib.parse import urlsplit

import pytest
import app.admin.router as ar
from tests.test_admin_kg_entry import env
from tests.test_applicant_stay_history import clock,setup,read,profiles
from tests.test_entry_applications import enforce_sqlite_foreign_keys


@pytest.mark.parametrize('width,js,language,theme',[(390,True,'ru','dark'),(1365,False,'en','light')])
def test_personal_visit_completeness_new_passport_historical_and_print(env,monkeypatch,width,js,language,theme):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    monkeypatch.setattr(ar.settings,'admin_new_look_enabled',True)
    subject,profile=setup(env)
    if language=='en':
        doc=profiles.request();doc['language']='en';profiles.save(env,subject,revision=1,key='en',doc=doc)
    app=FastAPI();app.add_middleware(SessionMiddleware,secret_key='synthetic-personal-history',https_only=False);app.include_router(ar.router)
    artifacts=Path('runs/e627-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started;origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch();context=browser.new_context(viewport={'width':width,'height':900},java_script_enabled=js,color_scheme=theme)
            context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
            assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
            page=context.new_page();url=origin+env['url']+f'/applicants/{subject["id"]}/history';page.goto(url)
            channels=[int(n) for n in re.findall(r'\d+',page.evaluate('getComputedStyle(document.body).backgroundColor'))[:3]]
            assert len(channels)==3 and (max(channels)<80 if theme=='dark' else min(channels)>200)
            assert page.locator('main').get_attribute('lang')==language
            page.locator('#history-complete').select_option('true');page.locator('#summary-passport').select_option('new')
            page.locator('#kg-ah-summary [name=confirmed]').check();page.locator('#kg-ah-summary button').click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-ah-status').get_attribute('data-status')=='recorded_inputs'
            page.locator('#visit-entry').fill('2026-09-01');page.locator('#visit-exit').fill('2026-09-10')
            page.locator('#visit-basis').select_option('visa_free');page.locator('#visit-country').fill('RUS')
            page.locator('#visit-passport').select_option('0');page.locator('#visit-evidence').select_option('passport_stamp')
            page.locator('#kg-ah-visit [name=verified]').check();page.locator('#kg-ah-visit [name=confirmed]').check()
            page.locator('#kg-ah-visit button').click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-ah-status').get_attribute('data-status')=='review_required'
            page.locator('#history-complete').select_option('true');page.locator('#kg-ah-summary [name=confirmed]').check()
            page.locator('#kg-ah-summary button').click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-ah-status').get_attribute('data-status')=='recorded_inputs'
            page.locator('#summary-passport').select_option('new');page.locator('#kg-ah-summary [name=confirmed]').check()
            page.locator('#kg-ah-summary button').click();page.wait_for_load_state('networkidle')
            assert page.locator('#kg-ah-status').get_attribute('data-status')=='review_required'
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            colours=page.locator('main button').evaluate_all('(es)=>es.map(e=>({fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor}))')
            def luminance(rgb):
                channels=[int(x)/255 for x in re.findall(r'\d+',rgb)[:3]]
                linear=[c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4 for c in channels]
                return sum(v*w for v,w in zip(linear,(.2126,.7152,.0722)))
            for colours_pair in colours:
                a,b=sorted(luminance(value) for value in colours_pair.values())
                assert (b+.05)/(a+.05)>=4.5
            page.locator('#history-date').focus();assert page.locator('#history-date').evaluate('(e)=>document.activeElement===e')
            page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(artifacts/f'history-{width}.png'))
            page.goto(url+'?revision=3');assert page.locator('#kg-ah-historical').count()==1
            assert page.locator('main form').count()==0 and '2026-09-10' in page.locator('#kg-ah-visits').inner_text()
            page.emulate_media(media='print');page.pdf(path=str(artifacts/f'history-{width}.pdf'),prefer_css_page_size=True)
            assert page.locator('#kg-ah-visits').is_visible()
            page.screenshot(path=str(artifacts/f'print-{width}.png'))
            import fitz
            with fitz.open(artifacts/f'history-{width}.pdf') as pdf:
                assert len(pdf)==1
                assert '2026-09-10' in ''.join(sheet.get_text() for sheet in pdf)
                pdf[0].get_pixmap().save(artifacts/f'pdf-{width}.png')
            context.close();browser.close()
        assert read(env,subject)['current_revision']==4
        assert read(env,subject)['current']['findings']==['passport_continuity_requires_review']
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
