"""Native conditional review, actual save, RU/EN, stops, currentness and contrast."""
from pathlib import Path
import re,socket,threading,time
from urllib.parse import urlsplit
import app.admin.router as ar
from tests import test_admin_work_review as native
from tests.test_admin_work_review import (env,clock,review_clock,connected_clock,route_clock,admins,
    enforce_sqlite_foreign_keys,core,ui)
from app.domain.entry_storage import EntryStorageUnavailable


def test_work_review_real_browser(env,tmp_path,monkeypatch):
    from playwright.sync_api import sync_playwright
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn,fitz
    original=core.deadline.current.setup
    monkeypatch.setattr(core.deadline.current,'setup',lambda e,p,**kw:original(e,p,**(kw|{'until':'2026-10-13'})))
    native.setup(env,tmp_path,monkeypatch)
    monkeypatch.setattr(ar.settings,'admin_new_look_enabled',True)
    before=core.counts(env)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-work-review-browser',https_only=False)
    local.include_router(ar.router)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    until=time.monotonic()+5
    while not server.started and time.monotonic()<until:time.sleep(.05)
    assert server.started
    origin=f'http://127.0.0.1:{port}';folder=Path('runs/review-work-browser-themed');folder.mkdir(parents=True,exist_ok=True)
    def luminance(rgb):
        channels=[int(n)/255 for n in re.findall(r'\d+',rgb)[:3]]
        return sum((c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4)*w for c,w in zip(channels,(.2126,.7152,.0722)))
    try:
        for width,js,theme,language in ((390,True,'dark','ru'),(1365,False,'light','en')):
            with sync_playwright() as p:
                browser=p.chromium.launch();context=browser.new_context(viewport={'width':width,'height':950},java_script_enabled=js,color_scheme=theme)
                context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
                assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
                page=context.new_page();page.goto(origin+native.url(env,language),wait_until='networkidle')
                main=page.locator('main.work-review');assert main.get_attribute('lang')==language
                bg=page.locator('body').evaluate('e=>getComputedStyle(e).backgroundColor')
                assert (luminance(bg)<.1 if theme=='dark' else luminance(bg)>.8),bg
                stop=page.locator('#work-review-stops');assert stop.is_visible()
                assert ('требуется специалист' if language=='ru' else 'specialist review required') in stop.inner_text()
                assert ('дата подачи прошла' if language=='ru' else 'filing date has passed') in stop.inner_text()
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                pairs=page.locator('main.work-review p, main.work-review a, main.work-review h1, main.work-review h2, main.work-review li, main.work-review label, main.work-review button').evaluate_all('''es=>es.filter(e=>e.offsetWidth&&e.offsetHeight).map(e=>{
                    let p=e,bg=getComputedStyle(p).backgroundColor;
                    while(p.parentElement&&(bg==='rgba(0, 0, 0, 0)'||bg==='transparent')){p=p.parentElement;bg=getComputedStyle(p).backgroundColor;}
                    return {fg:getComputedStyle(e).color,bg,text:e.innerText};})''')
                for pair in pairs:
                    low,high=sorted(luminance(pair[k]) for k in ('fg','bg'))
                    assert (high+.05)/(low+.05)>=4.5,pair
                main.locator('a').first.focus();page.keyboard.press('Tab')
                assert main.locator('a').nth(1).evaluate('e=>e===document.activeElement')
                assert main.locator('a').nth(1).evaluate('e=>parseInt(getComputedStyle(e).outlineWidth)')>=3
                page.screenshot(path=str(folder/f'positive-{width}.png'),full_page=True)
                if language=='en':
                    # A real no-JS signed POST creates the separate review task.
                    form=page.locator('#work-review-refresh');form.locator('[name="confirmed"]').check();form.locator('button').click();page.wait_for_load_state('networkidle')
                    assert page.locator('#work-review-history').is_visible()
                    page.emulate_media(media='print');pdfpath=folder/'review-en.pdf';page.pdf(path=str(pdfpath),prefer_css_page_size=True)
                    with fitz.open(pdfpath) as pdf:
                        assert 1<=len(pdf)<=2
                        words=''.join(sheet.get_text() for sheet in pdf)
                        assert 'internal reminder' in words and 'filing date has passed' in words
                        for i,sheet in enumerate(pdf):sheet.get_pixmap().save(folder/f'print-{i+1}.png')
                    page.emulate_media(media='screen')
                    monkeypatch.setattr(ar.settings,'kg_work_review_authorities',[])
                    page.reload(wait_until='networkidle')
                    assert 'Current calculation evidence is not confirmed' in main.inner_text()
                    assert page.locator('#work-review-cancel').is_visible()
                    page.screenshot(path=str(folder/'withdrawn-1365.png'),full_page=True)
                    original_read=ui.service.read
                    async def unavailable(*a,**kw):raise EntryStorageUnavailable('synthetic-reader-unavailable')
                    monkeypatch.setattr(ui.service,'read',unavailable)
                    response=page.reload(wait_until='networkidle');assert response.status==503
                    assert 'Evidence could not be verified' in page.locator('[role="alert"]').inner_text()
                    assert main.locator('form').count()==0
                    page.screenshot(path=str(folder/'unavailable-1365.png'),full_page=True)
                    monkeypatch.setattr(ui.service,'read',original_read)
                context.close();browser.close()
        assert core.counts(env)==[before[0]+1,before[1]+1]
    finally:
        server.should_exit=True;thread.join(timeout=10);listener.close()
