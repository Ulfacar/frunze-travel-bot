"""Own loopback Chromium/no-JS native flow and rendered output inspection."""
from pathlib import Path
import json,re,socket,threading,time
from urllib.parse import urlsplit
from tests import test_admin_actual_dates as native
from tests.test_admin_actual_dates import env,clock,enforce_sqlite_foreign_keys
from app.domain.entry_storage import EntryStorageUnavailable


def luminance(rgb):
    channels=[int(n)/255 for n in re.findall(r'\d+',rgb)[:3]]
    return sum((c/12.92 if c<=.04045 else ((c+.055)/1.055)**2.4)*w for c,w in zip(channels,(.2126,.7152,.0722)))


def test_real_native_themes_nojs_print_and_withdrawn_authority(env,tmp_path,monkeypatch):
    from playwright.sync_api import sync_playwright
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn,fitz
    native.setup(env,tmp_path,monkeypatch)
    monkeypatch.setattr(native.ar.settings,'admin_new_look_enabled',True)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-actual-date-review',https_only=False)
    local.include_router(native.ar.router)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    until=time.monotonic()+5
    while not server.started and time.monotonic()<until:time.sleep(.05)
    assert server.started
    folder=Path('runs/reviewer-browser');folder.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[]
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            for language,theme,width,js in [('ru','dark',390,True),('en','light',1365,False)]:
                context=browser.new_context(viewport={'width':width,'height':950},java_script_enabled=js,color_scheme=theme)
                context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
                origin=f'http://127.0.0.1:{port}'
                assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
                page=context.new_page();response=page.goto(origin+native.url(env,language),wait_until='networkidle')
                assert response.status==200
                main=page.locator('main.actual-dates');assert main.get_attribute('lang')==language
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                assert '2026-10-19' in main.inner_text()
                bg=page.locator('body').evaluate('e=>getComputedStyle(e).backgroundColor')
                assert luminance(bg)<.1 if theme=='dark' else luminance(bg)>.8
                main.locator('details').evaluate_all('es=>es.forEach(e=>e.open=true)')
                pairs=main.locator('p,a,h1,h2,label,summary,button,input:not([type=hidden]),select').evaluate_all('''es=>es.filter(e=>e.offsetWidth&&e.offsetHeight).map(e=>{
                    let p=e,bg=getComputedStyle(p).backgroundColor;
                    while(p.parentElement&&(bg==='rgba(0, 0, 0, 0)'||bg==='transparent')){p=p.parentElement;bg=getComputedStyle(p).backgroundColor;}
                    return {fg:getComputedStyle(e).color,bg,text:e.innerText||e.value};})''')
                for pair in pairs:
                    low,high=sorted(luminance(pair[k]) for k in ('fg','bg'))
                    if (high+.05)/(low+.05)<4.5:errors.append(dict(stage='screen-contrast',language=language,theme=theme,pair=pair))
                main.locator('a').first.focus();page.keyboard.press('Tab')
                assert main.locator('a').nth(1).evaluate('e=>e===document.activeElement')
                assert main.locator('a').nth(1).evaluate('e=>parseInt(getComputedStyle(e).outlineWidth)')>=3
                page.screenshot(path=str(folder/f'{language}-{theme}-expanded.png'),full_page=True)
                if language=='en':
                    form=page.locator('#actual-dates-conditional_review')
                    form.locator('[name=confirmed]').check();form.locator('button').click();page.wait_for_load_state('networkidle')
                    form=page.locator('#actual-dates-reconcile')
                    form.locator('[name=confirmed]').check();form.locator('button').click();page.wait_for_load_state('networkidle')
                    assert 'Planned' in main.inner_text()
                    assert main.locator('#conditional-current').inner_text().count('2026-10-19')>=2
                page.emulate_media(media='print')
                colors=page.locator('html,body,main.actual-dates,.actual-dates .panel').evaluate_all('es=>es.map(e=>({tag:e.tagName,fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor}))')
                pdfpath=folder/f'{language}-{theme}.pdf';page.pdf(path=str(pdfpath),prefer_css_page_size=True,print_background=True)
                with fitz.open(pdfpath) as doc:
                    texts=[sheet.get_text() for sheet in doc]
                    for i,sheet in enumerate(doc):sheet.get_pixmap().save(folder/f'{language}-{theme}-print-{i+1}.png')
                    assert all(t.strip() for t in texts),texts
                    assert '2026-10-19' in ''.join(texts)
                    assert len(doc)==1
                    assert not any(v in ''.join(texts) for v in ('Сохранить факт','Отозвать факт','Record evidence','Withdraw evidence'))
                    checks.append(dict(language=language,theme=theme,width=width,js=js,pages=len(doc),print_colors=colors,contrast_samples=len(pairs)))
                for color in colors:
                    if color['tag'] in ('HTML','BODY') and color['bg'] not in ('transparent','rgba(0, 0, 0, 0)') and luminance(color['bg'])<.8:
                        errors.append(dict(stage='print-background',language=language,theme=theme,color=color))
                page.emulate_media(media='screen')
                if language=='en':
                    monkeypatch.setattr(native.ar.settings,'kg_conditional_deadline_authorities',[])
                    page.reload(wait_until='networkidle')
                    current=main.locator('#conditional-current').inner_text()
                    assert 'Date not established' in current and 'Recorded evidence: 2026-10-19' in current
                    assert not page.locator('#actual-dates-conditional_review').count()
                    page.screenshot(path=str(folder/'authority-withdrawn.png'),full_page=True)
                    form=page.locator('#actual-dates-conditional_clear')
                    form.locator('[name=confirmed]').check();form.locator('button').click();page.wait_for_load_state('networkidle')
                    assert 'Cancelled' in main.inner_text()
                    original_scope=native.ui.anchors.scope
                    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic-registry-unavailable')
                    monkeypatch.setattr(native.ui.anchors,'scope',unavailable)
                    response=page.reload(wait_until='networkidle')
                    assert response.status==503 and response.headers['cache-control']=='no-store'
                    assert 'Evidence cannot be verified' in main.locator('[role=alert]').inner_text()
                    assert main.locator('form[id^="actual-dates-"]').count()==0
                    page.screenshot(path=str(folder/'registry-unavailable.png'),full_page=True)
                    monkeypatch.setattr(native.ui.anchors,'scope',original_scope)
                context.close()
            browser.close()
    finally:
        (folder/'checks.json').write_text(json.dumps(dict(checks=checks,errors=errors),ensure_ascii=False,indent=2),'utf8')
        server.should_exit=True;thread.join(timeout=10);listener.close()
    assert not errors,errors
