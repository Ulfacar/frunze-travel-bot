"""Actual loopback Chromium/no-JS source-review operation and rendered evidence."""
import json,re,socket,threading,time
from pathlib import Path
from urllib.parse import urlsplit
from tests import test_admin_operator_sop as native
from tests.test_admin_operator_sop import env,enforce_sqlite_foreign_keys
from app.domain.entry_storage import EntryStorageUnavailable

def luminance(rgb):
    numbers=[int(x)/255 for x in re.findall(r'\d+',rgb)[:3]]
    return sum((x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4)*w for x,w in zip(numbers,(.2126,.7152,.0722)))

def test_actual_sop_nojs_themes_time_print_and_authority(env,tmp_path,monkeypatch):
    from playwright.sync_api import sync_playwright
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn,fitz
    native.setup(env,tmp_path,monkeypatch)
    monkeypatch.setattr(native.ar.settings,'admin_new_look_enabled',True)
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-sop-review-browser',https_only=False)
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
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch()
            for language,theme,width,js in [('ru','dark',390,True),('en','light',1365,False)]:
                context=browser.new_context(viewport={'width':width,'height':950},java_script_enabled=js,color_scheme=theme)
                context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
                origin=f'http://127.0.0.1:{port}'
                assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze'}).status==200
                page=context.new_page();response=page.goto(origin+native.url(env,language),wait_until='networkidle')
                assert response.status==200
                main=page.locator('main.sop-review');assert main.get_attribute('lang')==language
                for name,identity in zip(('case_label','person_label','application_label'),env['ids']):
                    assert native.ui.TEXT[language][name]+' #'+str(identity) in main.inner_text()
                assert ' ? ' not in main.inner_text()
                if page.evaluate('document.documentElement.scrollWidth>innerWidth'):errors.append(dict(kind='overflow',language=language))
                bg=page.locator('body').evaluate('e=>getComputedStyle(e).backgroundColor')
                assert luminance(bg)<.1 if theme=='dark' else luminance(bg)>.8
                pairs=main.locator('p,a,h1,h2,label,button,input:not([type=hidden]),select,dt,dd').evaluate_all('''es=>es.filter(e=>e.offsetWidth&&e.offsetHeight).map(e=>{
                    let p=e,bg=getComputedStyle(p).backgroundColor;
                    while(p.parentElement&&(bg==='rgba(0, 0, 0, 0)'||bg==='transparent')){p=p.parentElement;bg=getComputedStyle(p).backgroundColor;}
                    return {fg:getComputedStyle(e).color,bg,text:e.innerText||e.value,font:getComputedStyle(e).fontFamily,size:getComputedStyle(e).fontSize};})''')
                for pair in pairs:
                    if not pair['text']:continue
                    low,high=sorted(luminance(pair[k]) for k in ('fg','bg'))
                    if (high+.05)/(low+.05)<4.5:errors.append(dict(kind='contrast',language=language,pair=pair))
                main.locator('a').first.focus();page.keyboard.press('Tab')
                assert main.locator('a').nth(1).evaluate('e=>e===document.activeElement')
                assert main.locator('a').nth(1).evaluate('e=>parseInt(getComputedStyle(e).outlineWidth)')>=3
                page.screenshot(path=str(folder/f'{language}-{theme}-form.png'),full_page=True)
                if language=='ru':
                    form=page.locator('#sop-operator_review')
                    assert form.locator('[name=reference],[name=proof]').count()==0
                    for name,value in dict(on='2026-11-02',time='00:30').items():form.locator(f'[name={name}]').fill(value)
                    form.locator('[name=reason]').select_option('verify_missing_facts');form.locator('[name=confirmed]').check()
                    form.locator('button').click();page.wait_for_load_state('networkidle')
                    form=page.locator('#sop-reconcile');form.locator('[name=confirmed]').check();form.locator('button').click();page.wait_for_load_state('networkidle')
                assert '2026-11-02' in main.inner_text() and '00:30' in main.inner_text()
                assert native.ui.TEXT[language]['planned'] in main.inner_text()
                page.screenshot(path=str(folder/f'{language}-{theme}-saved.png'),full_page=True)
                page.emulate_media(media='print')
                colors=page.locator('html,body,main.sop-review').evaluate_all('es=>es.map(e=>({tag:e.tagName,fg:getComputedStyle(e).color,bg:getComputedStyle(e).backgroundColor}))')
                pdf=folder/f'{language}-{theme}.pdf';page.pdf(path=str(pdf),prefer_css_page_size=True,print_background=True)
                with fitz.open(pdf) as doc:
                    texts=[sheet.get_text() for sheet in doc]
                    for i,sheet in enumerate(doc):sheet.get_pixmap().save(folder/f'{language}-{theme}-print-{i+1}.png')
                    if len(doc)!=1 or any(not x.strip() for x in texts):errors.append(dict(kind='print-pages',language=language,pages=len(doc),texts=texts))
                    assert '2026-11-02' in ''.join(texts) and '00:30' in ''.join(texts)
                    for name in ('case_label','person_label','application_label'):
                        assert native.ui.TEXT[language][name] in ''.join(texts)
                    checks.append(dict(language=language,theme=theme,width=width,js=js,pages=len(doc),colors=colors,samples=pairs))
                for color in colors:
                    if color['bg'] not in ('transparent','rgba(0, 0, 0, 0)') and luminance(color['bg'])<.8:errors.append(dict(kind='print-background',language=language,color=color))
                page.emulate_media(media='screen')
                if language=='en':
                    # No-JS form actually withdraws/reconciles, not just renders.
                    monkeypatch.setattr(native.ar.settings,'kg_operator_sop_authorities',[])
                    page.reload(wait_until='networkidle')
                    assert not page.locator('#sop-operator_review').count()
                    assert 'Needs reconciliation' in main.inner_text() and '2026-11-02' in main.inner_text()
                    assert 'for this stage' not in main.inner_text()
                    assert native.ui.TEXT[language]['confirm_clear'] in main.inner_text()
                    page.screenshot(path=str(folder/'authority-withdrawn.png'),full_page=True)
                    form=page.locator('#sop-operator_review_clear');form.locator('[name=confirmed]').check();form.locator('button').click();page.wait_for_load_state('networkidle')
                    assert 'Cancelled' in main.inner_text()
                    original=native.ui.service.preview
                    async def unavailable(*args,**kwargs):raise EntryStorageUnavailable('synthetic-source-reader-down')
                    monkeypatch.setattr(native.ui.service,'preview',unavailable)
                    response=page.reload(wait_until='networkidle');assert response.status==503 and response.headers['cache-control']=='no-store'
                    assert main.locator('form[method=post]').count()==0
                    page.screenshot(path=str(folder/'reader-unavailable.png'),full_page=True)
                    monkeypatch.setattr(native.ui.service,'preview',original)
                context.close()
            browser.close()
    finally:
        (folder/'checks.json').write_text(json.dumps(dict(checks=checks,errors=errors),ensure_ascii=False,indent=2),encoding='utf-8')
        server.should_exit=True;thread.join(timeout=10);listener.close()
    assert not errors,errors
