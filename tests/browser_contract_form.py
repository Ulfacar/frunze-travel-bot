"""Опциональная браузерная приёмка: запускать явно, Chromium уже установлен.

python -m pytest tests/browser_contract_form.py -q
Изолированный FastAPI слушает только loopback, БД и переписка синтетические.
Внешние запросы браузера блокируются. Production не затрагивается.
"""
from pathlib import Path
import socket
import threading
import time
from urllib.parse import urlsplit

import pytest

from tests.test_admin_contracts import URL, env, snapshot
import app.admin.router as ar


def test_mobile_and_desktop_form_native_submit_without_javascript(env, monkeypatch):
    api = pytest.importorskip("playwright.sync_api")
    sm, conv, ids, client = env
    screenshots = Path("runs/contract-ui-20261006")
    screenshots.mkdir(parents=True, exist_ok=True)

    from fastapi import FastAPI
    from starlette.middleware.sessions import SessionMiddleware
    import uvicorn
    local_app = FastAPI()
    # Отдельное приложение, только для теста: secure-cookie требует HTTPS, а тут loopback HTTP.
    local_app.add_middleware(SessionMiddleware, secret_key="synthetic-browser-session", https_only=False)
    local_app.include_router(ar.router)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(local_app, log_level="error", lifespan="off"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started
        origin = f"http://127.0.0.1:{port}"
        with api.sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            scenarios = ((False, 360, "light"), (False, 1280, "light"),
                         (True, 360, "light"), (True, 360, "dark"),
                         (True, 1280, "light"), (True, 1280, "dark"))
            for new_look, width, theme in scenarios:
                monkeypatch.setattr(ar.settings, "admin_new_look_enabled", new_look)
                label = f"{'new' if new_look else 'old'}-{width}-{theme}"
                context = browser.new_context(viewport={"width": width, "height": 850},
                                              java_script_enabled=False, color_scheme=theme)
                context.route("**/*", lambda route: route.continue_() if
                              urlsplit(route.request.url).netloc == f"127.0.0.1:{port}" else route.abort())
                login = context.request.post(origin + "/admin/login", form={"login": "ademi", "password": "frunze"})
                assert login.status == 200
                page = context.new_page()
                page.goto(origin + URL, wait_until="networkidle")
                assert page.locator("h1").inner_text() == "Договор подписан"
                page.locator("#contract-product").select_option(str(ids["tour"]))
                page.locator("#contract-reference").fill(f"BROWSER-{label}")
                page.locator("#contract-signed").fill("2026-10-06T12:00")
                page.locator("#contract-amount").fill("12345.67")
                page.locator("#contract-currency").fill("KGS")
                page.locator("#contract-confirmed").check()
                assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
                if new_look:
                    assert page.evaluate("getComputedStyle(document.documentElement).colorScheme") == theme
                page.evaluate("scrollTo(0, 0)")
                page.screenshot(path=str(screenshots / f"form-{label}.png"), full_page=True)
                page.get_by_role("button", name="Зафиксировать договор и открыть услугу").click()
                page.wait_for_url("**/admin/case/*", timeout=10000)
                assert f"BROWSER-{label}" in page.locator("h1").inner_text()
                page.screenshot(path=str(screenshots / f"case-{label}.png"), full_page=True)
                context.close()
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
    assert len(snapshot(sm)["service_cases"]) == 6
    print(f"Browser PASS: 6 native submissions; 0 horizontal overflows; screenshots: {screenshots.resolve()}")
