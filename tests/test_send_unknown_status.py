"""MSG-02: «неизвестно, дошло ли» вместо «не доставлено» и повтор только с подтверждением.

Риск (ревью pm/ux 30.10): после таймаута Wappi сообщение могло уйти клиенту, а панель
писала «не доставлено» и предлагала «Повторить» — повтор отправлял второе. Wappi здесь
фейковый (`httpx.AsyncClient` подменён), сети нет. Номера синтетические.
"""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

import app.admin.router as admin_router
import app.config
import app.main as main
from app.admin import send_unknown
from app.channels import wappi
from app.config import ManagerConfig
from app.core import flags
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

UID = "getvisa:996555700001"
FLAG = send_unknown.FLAG
PASS = {"medina": "m1", "eliza": "e1", "aisina": "a1", "admin": "frunze"}
# `wappi.httpx` — это сам модуль httpx: подмена AsyncClient глобальна, настоящий храним.
REAL_ASYNC_CLIENT = httpx.AsyncClient


class FakeWappi:
    """Ответы по очереди; последний повторяется. Считает дошедшие до «Wappi» запросы."""

    def __init__(self, *modes):
        self.modes, self.calls = list(modes), 0

    async def post(self, url, **kw):
        self.calls += 1
        mode = self.modes.pop(0) if len(self.modes) > 1 else self.modes[0]
        req = httpx.Request("POST", url)
        if mode == "timeout":
            raise httpx.ReadTimeout("read timeout", request=req)
        if mode == "drop":
            raise httpx.RemoteProtocolError("server disconnected", request=req)
        if mode == "cancel":                     # обработчик отменили посреди отправки
            raise asyncio.CancelledError()
        if mode == "connect":
            self.calls -= 1                      # соединения не было — запрос не ушёл
            raise httpx.ConnectError("connection refused", request=req)
        if mode in ("402", "503"):
            return httpx.Response(int(mode), json={"detail": "x"}, request=req)
        if mode == "noid":                       # 200, но id сообщения нет
            return httpx.Response(200, json={"status": "done"}, request=req)
        if mode == "errbody":                    # 200 с телом-ошибкой
            return httpx.Response(200, json={"status": "error", "detail": "x"}, request=req)
        if mode == "nojson":                     # 200, тело не JSON
            return httpx.Response(200, text="OK", request=req)
        return httpx.Response(200, json={"status": "done", "message_id": "W-1"}, request=req)

    async def aclose(self):
        pass


@pytest.fixture
def env(monkeypatch):
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    flags.reset()
    admin_router._look_cache["key"] = None
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
        ManagerConfig(login="medina", name="Медина", password="m1"),
        ManagerConfig(login="eliza", name="Элиза", password="e1"),
        ManagerConfig(login="aisina", name="Айсина", password="a1")])
    monkeypatch.setattr(app.config.settings, "admin_chat_redesign_enabled", True)
    monkeypatch.setattr(app.config.settings, "wappi_token", "test-token")
    asyncio.run(get_conversation_store().add_message(
        UID, "client", "здравствуйте", channel="whatsapp", bot_id="getvisa",
        phone="996555700001", chat_id="996555700001@c.us"))
    asyncio.run(get_conversation_store().update_meta(UID, funnel="visa"))
    yield monkeypatch
    flags.reset()
    admin_router._look_cache["key"] = None


def _wappi(monkeypatch, *modes):
    fake = FakeWappi(*modes)
    monkeypatch.setattr(wappi.httpx, "AsyncClient", lambda *a, **k: fake)
    return fake


def _on():
    asyncio.run(flags.set_flag(FLAG, True))
    admin_router._look_cache["key"] = None


def _client(login="medina"):
    c = TestClient(main.app, base_url="https://testserver")
    assert c.post("/admin/login", data={"login": login, "password": PASS[login]}).status_code == 200
    return c


def _last():
    return panel_store._memory_store._conv[UID].messages[-1]


def _send(c, text="Подойти можно с 10:00"):
    return c.post(f"/admin/conversation/{UID}/send", data={"text": text})


def _confirm(c, mid):
    """Поля кнопки «Отправить ещё раз» так, как их отправит HTMX со страницы диалога."""
    import json
    import re
    html = c.get(f"/admin/conversation/{UID}").text
    found = re.search(r"resend/%d\" hx-vals='([^']+)'" % mid, html)
    return json.loads(found.group(1)) if found else {"confirm": "1"}


# ---------------------------- флаг OFF: как было ----------------------------

@pytest.mark.parametrize("mode", ["timeout", "drop", "503"])
def test_flag_off_everything_is_failed_as_before(env, mode):
    fake = _wappi(env, mode, "ok")
    c = _client()
    r = _send(c)
    assert r.headers["X-Action-Outcome"] == "failed" and _last().status == "failed"
    assert "Не уверены, что дошло" not in r.text and "Отправить ещё раз" not in r.text
    assert "'sent','failed']" in r.text                  # сброс поля ответа — прежний
    r = c.post(f"/admin/conversation/{UID}/resend/{_last().id}")   # прежний «Повторить»
    assert r.headers["X-Action-Outcome"] == "sent" and fake.calls == 2


def test_flag_off_confirm_field_changes_nothing(env):
    _wappi(env, "timeout")
    c = _client()
    _send(c)
    mid = _last().id
    asyncio.run(panel_store._memory_store.mark_message_status(message_id=mid, status="unknown"))
    r = c.post(f"/admin/conversation/{UID}/resend/{mid}", data={"confirm": "1"})
    assert r.headers["X-Action-Outcome"] == "denied"


# ---------------------------- флаг ON: классификация ----------------------------

@pytest.mark.parametrize("mode,status", [
    ("ok", "sent"),
    ("timeout", "unknown"),     # таймаут чтения после отправки
    ("drop", "unknown"),        # обрыв соединения после отправки
    ("503", "unknown"),         # шлюз 5xx: мог принять
    ("402", "failed"),          # явный отказ: не оплачено
    ("connect", "failed"),      # до Wappi не дошло
])
def test_status_after_send(env, mode, status):
    _on()
    _wappi(env, mode)
    r = _send(_client())
    assert (r.headers["X-Action-Outcome"], _last().status) == (status, status)


def test_unknown_message_shows_plain_words_and_confirm_button(env):
    _on()
    _wappi(env, "timeout")
    html = _send(_client()).text
    assert "Не уверены, что дошло — проверьте в WhatsApp" in html
    assert 'hx-confirm="Клиент может получить сообщение дважды. Отправить ещё раз?"' in html
    assert 'hx-vals=\'{"confirm": "1", "seen": "' in html and "Отправить ещё раз" in html
    assert "'sent','failed','unknown']" in html          # текст не остаётся в поле


# ---------------------------- флаг ON: повтор ----------------------------

def test_unknown_retry_without_confirmation_is_refused(env):
    _on()
    fake = _wappi(env, "timeout", "ok")
    c = _client()
    _send(c)
    r = c.post(f"/admin/conversation/{UID}/resend/{_last().id}")
    assert r.headers["X-Action-Outcome"] == "confirm_required"
    assert "Клиент может получить сообщение дважды" in r.text
    assert fake.calls == 1 and _last().status == "unknown"


def test_confirmed_retry_sends_once_even_when_confirmed_twice(env):
    _on()
    fake = _wappi(env, "timeout", "ok")
    c = _client()
    _send(c)
    mid = _last().id
    data = _confirm(c, mid)
    r1 = c.post(f"/admin/conversation/{UID}/resend/{mid}", data=data)
    r2 = c.post(f"/admin/conversation/{UID}/resend/{mid}", data=data)
    assert r1.headers["X-Action-Outcome"] == "sent"
    assert r2.headers["X-Action-Outcome"] == "denied"    # уже не unknown — ничего не шлём
    assert fake.calls == 2 and _last().status == "sent"
    audit = [a["action"] for a in panel_store._memory_store._audit]
    assert audit.count("resend_confirmed") == 1


def test_parallel_confirmations_send_once(env):
    """Два подтверждения одновременно (два клика, две вкладки): блокировка + перечтение."""
    _on()
    _wappi(env, "timeout")
    c = _client()
    _send(c)
    mid = _last().id
    data = _confirm(c, mid)
    fake = _wappi(env, "ok")
    real = fake.post

    async def slow(url, **kw):
        await asyncio.sleep(0.05)
        return await real(url, **kw)
    fake.post = slow

    async def two():
        transport = httpx.ASGITransport(app=main.app)
        async with REAL_ASYNC_CLIENT(transport=transport, base_url="https://testserver",
                                     cookies=c.cookies) as ac:
            return await asyncio.gather(*(ac.post(f"/admin/conversation/{UID}/resend/{mid}",
                                                  data=data) for _ in range(2)))
    outcomes = sorted(r.headers["X-Action-Outcome"] for r in asyncio.run(two()))
    # Второй либо отсечён ещё до блокировки (видит `pending`), либо после неё (`duplicate`).
    assert outcomes[1] == "sent" and outcomes[0] in ("denied", "duplicate")
    assert fake.calls == 1


def test_parallel_confirmations_after_repeat_timeout_send_once(env):
    """Ревью pdf, проба P1c: оба подтверждения прочитали `unknown` до блокировки, первый
    повтор снова упёрся в таймаут — второй не должен слать третью копию."""
    _on()
    _wappi(env, "timeout")
    c = _client()
    _send(c)
    mid = _last().id
    data = _confirm(c, mid)                      # обе вкладки видели одно и то же `unknown`
    fake = _wappi(env, "timeout")
    store = panel_store._memory_store
    real_update = store.update_meta

    async def slow_update(*a, **kw):             # PostgreSQL: десятки мс до блокировки
        await asyncio.sleep(0.05)
        return await real_update(*a, **kw)
    env.setattr(store, "update_meta", slow_update)

    async def two():
        transport = httpx.ASGITransport(app=main.app)
        async with REAL_ASYNC_CLIENT(transport=transport, base_url="https://testserver",
                                     cookies=c.cookies) as ac:
            return await asyncio.gather(*(ac.post(f"/admin/conversation/{UID}/resend/{mid}",
                                                  data=data) for _ in range(2)))
    outcomes = sorted(r.headers["X-Action-Outcome"] for r in asyncio.run(two()))
    assert fake.calls == 1                       # одна повторная отправка, не две
    assert outcomes == ["confirm_required", "unknown"]
    assert _last().status == "unknown"


def test_stale_confirmation_after_repeat_timeout_asks_again(env):
    """Вторая вкладка с прежним `unknown`: после нового таймаута её подтверждение устарело."""
    _on()
    _wappi(env, "timeout")
    c = _client()
    _send(c)
    mid = _last().id
    stale = _confirm(c, mid)
    fake = _wappi(env, "timeout", "ok")
    r1 = c.post(f"/admin/conversation/{UID}/resend/{mid}", data=stale)
    assert r1.headers["X-Action-Outcome"] == "unknown" and fake.calls == 1
    r2 = c.post(f"/admin/conversation/{UID}/resend/{mid}", data=stale)
    assert r2.headers["X-Action-Outcome"] == "confirm_required" and fake.calls == 1
    r3 = c.post(f"/admin/conversation/{UID}/resend/{mid}", data=_confirm(c, mid))
    assert r3.headers["X-Action-Outcome"] == "sent" and fake.calls == 2


def test_confirmed_retry_that_times_out_again_stays_unknown(env):
    _on()
    fake = _wappi(env, "timeout")
    c = _client()
    _send(c)
    r = c.post(f"/admin/conversation/{UID}/resend/{_last().id}", data=_confirm(c, _last().id))
    assert r.headers["X-Action-Outcome"] == "unknown" and fake.calls == 2


def test_confirmation_without_attempt_mark_is_refused(env):
    """Прямой POST `confirm=1` без отметки попытки (или с чужой) — подтвердить заново."""
    _on()
    fake = _wappi(env, "timeout", "ok")
    c = _client()
    _send(c)
    mid = _last().id
    for data in ({"confirm": "1"}, {"confirm": "1", "seen": "00000000.0"}):
        r = c.post(f"/admin/conversation/{UID}/resend/{mid}", data=data)
        assert r.headers["X-Action-Outcome"] == "confirm_required"
    assert fake.calls == 1 and _last().status == "unknown"


def test_failed_message_still_retries_without_confirmation(env):
    _on()
    fake = _wappi(env, "402", "ok")
    c = _client()
    _send(c)
    r = c.post(f"/admin/conversation/{UID}/resend/{_last().id}")
    assert r.headers["X-Action-Outcome"] == "sent" and fake.calls == 2


# ------------------ 200 без id у текста (ревью pdf, п. 2) ------------------

@pytest.mark.parametrize("mode", ["noid", "errbody", "nojson"])
def test_text_200_without_id_is_unknown_when_flag_on(env, mode):
    """Как у `send_file`: Wappi ответил 2xx, но id нет — мог принять, мог отклонить."""
    _on()
    fake = _wappi(env, mode, "ok")
    c = _client()
    r = _send(c)
    assert (r.headers["X-Action-Outcome"], _last().status) == ("unknown", "unknown")
    assert _last().provider_msg_id in ("", None)
    r = c.post(f"/admin/conversation/{UID}/resend/{_last().id}")
    assert r.headers["X-Action-Outcome"] == "confirm_required" and fake.calls == 1
    r = c.post(f"/admin/conversation/{UID}/resend/{_last().id}", data=_confirm(c, _last().id))
    assert r.headers["X-Action-Outcome"] == "sent" and fake.calls == 2


@pytest.mark.parametrize("mode", ["noid", "errbody", "nojson"])
def test_text_200_without_id_flag_off_is_sent_as_before(env, mode):
    _wappi(env, mode)
    r = _send(_client())
    assert (r.headers["X-Action-Outcome"], _last().status) == ("sent", "sent")


def test_confirmed_resend_200_without_id_stays_unknown(env):
    _on()
    fake = _wappi(env, "timeout", "noid")
    c = _client()
    _send(c)
    r = c.post(f"/admin/conversation/{UID}/resend/{_last().id}", data=_confirm(c, _last().id))
    assert r.headers["X-Action-Outcome"] == "unknown" and fake.calls == 2


# ------------- CancelledError посреди отправки (ревью pdf, п. 3) -------------

def _send_cancelled(c):
    async def go():
        transport = httpx.ASGITransport(app=main.app)
        async with REAL_ASYNC_CLIENT(transport=transport, base_url="https://testserver",
                                     cookies=c.cookies) as ac:
            await ac.post(f"/admin/conversation/{UID}/send", data={"text": "Подойти можно с 10:00"})
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(go())


def test_cancelled_send_is_unknown_not_eternal_pending(env):
    _on()
    fake = _wappi(env, "cancel", "ok")
    c = _client()
    _send_cancelled(c)
    assert _last().sender == "manager" and _last().status == "unknown"
    r = c.post(f"/admin/conversation/{UID}/resend/{_last().id}", data=_confirm(c, _last().id))
    assert r.headers["X-Action-Outcome"] == "sent" and fake.calls == 2


def test_cancelled_send_flag_off_as_before(env):
    _wappi(env, "cancel")
    _send_cancelled(_client())
    assert _last().sender == "manager" and _last().status == "pending"


# ---------------------------- права ----------------------------

def test_foreign_direction_manager_gets_404(env):
    _on()
    fake = _wappi(env, "timeout", "ok")
    _send(_client())
    r = _client("aisina").post(f"/admin/conversation/{UID}/resend/{_last().id}",
                               data={"confirm": "1"})
    assert r.status_code == 404 and fake.calls == 1


def test_colleague_cannot_confirm_owners_message_when_ownership_enforced(env):
    _on()
    asyncio.run(flags.set_flag("authz_enforce_enabled", True))
    import tempfile
    from pathlib import Path
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import NullPool
    tmp = Path(tempfile.mkdtemp()) / "d.db"
    url = f"sqlite+aiosqlite:///{tmp.as_posix()}"

    async def _init():
        eng = create_async_engine(url)
        async with eng.begin() as conn:
            from app.domain.models import DomainBase
            await conn.run_sync(DomainBase.metadata.create_all)
        await eng.dispose()
    asyncio.run(_init())
    sm = async_sessionmaker(create_async_engine(url, poolclass=NullPool), expire_on_commit=False)
    env.setattr(admin_router, "_domain_sessionmaker", lambda: sm)
    fake = _wappi(env, "timeout", "ok")
    _send(_client("medina"))                              # Медина — владелец
    assert _last().status == "unknown"
    eliza = _client("eliza")
    r = eliza.post(f"/admin/conversation/{UID}/resend/{_last().id}",
                   data=_confirm(eliza, _last().id))
    assert r.headers["X-Action-Outcome"] == "denied" and fake.calls == 1
    assert _last().status == "unknown"


def test_file_message_unknown_is_never_resent(env):
    _on()
    fake = _wappi(env, "ok")
    c = _client()
    msg_id = asyncio.run(get_conversation_store().add_message(
        UID, "manager", "📎 паспорт.pdf", status="unknown"))
    html = c.get(f"/admin/conversation/{UID}").text
    assert "Отправить ещё раз" not in html
    r = c.post(f"/admin/conversation/{UID}/resend/{msg_id}", data={"confirm": "1"})
    assert r.headers["X-Action-Outcome"] == "denied" and fake.calls == 0


# ---------------------------- классификатор ----------------------------

def test_classifier_table():
    req = httpx.Request("POST", "https://wappi.invalid/x")
    resp = lambda code: httpx.Response(code, request=req)   # noqa: E731
    assert send_unknown.classify(httpx.ConnectTimeout("x", request=req)) == "failed"
    assert send_unknown.classify(httpx.PoolTimeout("x", request=req)) == "failed"
    assert send_unknown.classify(httpx.WriteTimeout("x", request=req)) == "unknown"
    assert send_unknown.classify(httpx.ReadError("x", request=req)) == "unknown"
    assert send_unknown.classify(httpx.HTTPStatusError("x", request=req, response=resp(401))) == "failed"
    assert send_unknown.classify(httpx.HTTPStatusError("x", request=req, response=resp(502))) == "unknown"
    assert send_unknown.classify(RuntimeError("канал не настроен")) == "failed"
    assert send_unknown.classify(ValueError("нет адаптера")) == "failed"
    assert send_unknown.classify(asyncio.CancelledError()) == "unknown"
