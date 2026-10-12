"""Installed native session status, mobile/no-JS and actual print artifacts."""
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest
from sqlalchemy import delete

import app.admin.router as ar
import app.admin.kg_channel_stops as ui
from app.domain import dialogue_sessions as service
from app.integrations.crm.db import ConvMessage, AuditLog
from app.integrations.panel import store as panel_store
from tests.test_dialogue_sessions import (env,clock,current_clock,connected_clock,route_clock,admins,
    activation,persistent_panel,enforce_sqlite_foreign_keys,setup,receive,journal_state,ROUTE,resolve)


def test_native_session_terminal_delivery_inbox_and_print(env,tmp_path,monkeypatch):
    api=pytest.importorskip('playwright.sync_api')
    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    setup(env,tmp_path);first=receive(env)
    async def attempt():
        async with env['engine'].begin() as conn:
            await conn.run_sync(lambda sync: AuditLog.__table__.create(sync,checkfirst=True))
        cap=await service.claim(env['engine'],route=ROUTE,session_id=first['session_id'],
            prompt_revision=first['prompt_revision'],authority=env['authority'],resolver=resolve)
        await service.record_outcome(env['engine'],route=ROUTE,capability=cap,outcome='unknown')
        async with env['sm']() as s:
            await s.execute(delete(ConvMessage));await s.commit()
    asyncio.run(attempt())
    receive(env,'Delete my data','SYN-PRIVACY',authority=None)
    before=len(journal_state(env)[1])
    monkeypatch.setattr(ui,'resolve_dialog',resolve)
    monkeypatch.setattr(panel_store,'_pg_store',panel_store.PostgresConversationStore(env['sm']))
    local=FastAPI();local.add_middleware(SessionMiddleware,secret_key='synthetic-session-browser',https_only=False)
    local.include_router(ar.router)
    artifacts=Path('runs/e629c-browser');artifacts.mkdir(parents=True,exist_ok=True)
    listener=socket.socket();listener.bind(('127.0.0.1',0));port=listener.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(local,log_level='error',lifespan='off'))
    thread=threading.Thread(target=server.run,kwargs={'sockets':[listener]},daemon=True);thread.start()
    try:
        until=time.monotonic()+5
        while not server.started and time.monotonic()<until:time.sleep(.05)
        assert server.started;origin=f'http://127.0.0.1:{port}'
        with api.sync_playwright() as p:
            browser=p.chromium.launch()
            for width,js in [(390,True),(1365,False)]:
                context=browser.new_context(viewport={'width':width,'height':900},java_script_enabled=js)
                context.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==f'127.0.0.1:{port}' else route.abort())
                url=ui._url(env['cases']['visa'],env['person']['id'],env['iv']['interview_id'])
                assert context.request.post(origin+'/admin/login',form={'login':'admin','password':'frunze','next':url}).status==200
                page=context.new_page()
                page.goto(origin+ui._url(env['cases']['visa'],env['person']['id'],env['iv']['interview_id']),wait_until='networkidle')
                panel=page.locator('#dialogue-sessions');text=panel.inner_text()
                for label in ('Автоматическая анкета остановлена','Сбор данных остановлен',
                    'Удаление данных не выполнялось','отдельная запись остановки канала не создавалась',
                    'при отправке сейчас включена','Исходный текст недоступен','Автоматического повтора не будет'):
                    assert label in text
                assert 'Delete my data' not in page.locator('main').inner_text()
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                panel.locator('summary').focus();panel.locator('summary').press('Enter')
                assert panel.locator('details').get_attribute('open') is not None
                assert 'Вопросы' in panel.inner_text() or '1.1:' in panel.inner_text()
                page.evaluate('window.scrollTo(0,0)')
                page.screenshot(path=str(artifacts/f'session-{width}.png'),full_page=True)
                panel.get_by_role('link',name='Обновить состояние без повторной отправки').click()
                page.wait_for_load_state('networkidle')
                with ThreadPoolExecutor(max_workers=1) as executor:
                    assert len(executor.submit(journal_state,env).result()[1])==before
                page.locator('#dialogue-sessions summary').click()
                page.emulate_media(media='print')
                filename=artifacts/f'session-{width}.pdf'
                page.pdf(path=str(filename),prefer_css_page_size=True)
                import fitz
                with fitz.open(filename) as printed:
                    assert 1<=len(printed)<=2 and all(len(p.get_text().strip())>150 for p in printed)
                    text='\n'.join(p.get_text() for p in printed)
                    assert 'Сбор данных остановлен' in text and 'неизвестен' in text
                    for i,pdfpage in enumerate(printed):pdfpage.get_pixmap().save(artifacts/f'session-print-{width}-{i+1}.png')
                context.close()
            browser.close()
    finally:server.should_exit=True;thread.join(timeout=10);listener.close()
