"""Панель бота перед переводом визовых менеджеров из Bitrix (14.10.2026).

Две дыры из ревью B1: «Повторить» пересылал клиенту ЛЮБОЕ сообщение диалога по id мимо
проверки владельца; проверка владельца при любом сбое ПРОПУСКАЛА отправку и перехват.
"""
import asyncio

import app.admin.router as admin_router
from app.core import live_authz
from app.integrations.panel.store import get_conversation_store
from tests.test_live_authz import USER_ID, _client, _conv, _setup


def _sent(monkeypatch):
    calls = []

    async def fake(channel, bot_id, chat_id, text):
        calls.append(text)
        return f"wappi-{len(calls)}"
    monkeypatch.setattr(admin_router.outbound, "send_to_client", fake)
    return calls


def _message(sender, text, status):
    store = get_conversation_store()

    async def go():
        mid = await store.add_message(USER_ID, sender, text, channel="whatsapp", bot_id="getvisa",
                                      phone="996700123456", status=status)
        return mid
    return asyncio.run(go())


def _resend(client, mid):
    return client.post(f"/admin/conversation/{USER_ID}/resend/{mid}")


# --- «Повторить» ---

def test_resend_refuses_client_message(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)
    client_msg = _conv().messages[0].id
    r = _resend(_client("medina", "m1"), client_msg)
    assert r.headers["X-Action-Outcome"] == "denied"
    assert sent == []


def test_resend_refuses_bot_and_delivered_messages(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)
    c = _client("medina", "m1")
    assert _resend(c, _message("bot", "ответ бота", "failed")).headers["X-Action-Outcome"] == "denied"
    assert _resend(c, _message("manager", "уже ушло", "sent")).headers["X-Action-Outcome"] == "denied"
    assert sent == []


def test_resend_own_failed_manager_message_goes_out_and_intercepts(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)
    c = _client("medina", "m1")
    c.post(f"/admin/conversation/{USER_ID}/takeover")
    mid = _message("manager", "пришлите паспорт", "failed")
    _resend(c, mid)
    assert sent == ["пришлите паспорт"]
    assert _conv().intercepted is True


def test_resend_in_colleagues_dialog_is_denied(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)
    _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    mid = _message("manager", "текст Медины", "failed")
    r = _resend(_client("eliza", "e1"), mid)
    assert r.headers["X-Action-Outcome"] == "denied"
    assert sent == []


# --- проверка владельца при сбое ---

def test_flag_read_failure_denies_send_but_allows_release(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)

    async def boom():
        raise RuntimeError("db down")
    monkeypatch.setattr(live_authz, "enforcement_enabled", boom)
    c = _client("medina", "m1")
    r = c.post(f"/admin/conversation/{USER_ID}/send", data={"text": "ответ"})
    assert r.headers["X-Action-Outcome"] == "denied"
    assert sent == []
    assert c.post(f"/admin/conversation/{USER_ID}/release").status_code == 200


def test_domain_failure_denies_send_and_claim(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)
    from app.domain import live_assign

    async def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(live_assign, "contact_for_channel", boom)
    c = _client("medina", "m1")
    assert c.post(f"/admin/conversation/{USER_ID}/send", data={"text": "ответ"}).headers["X-Action-Outcome"] == "denied"
    assert c.post(f"/admin/conversation/{USER_ID}/takeover").headers["X-Action-Outcome"] == "denied"
    assert sent == []
    assert _conv().intercepted is False


def test_unknown_direction_denies_send(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)
    monkeypatch.setattr(admin_router, "_authz_direction", lambda conv: "")
    r = _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/send", data={"text": "ответ"})
    assert r.headers["X-Action-Outcome"] == "denied"
    assert sent == []


def test_normal_owner_send_still_works(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)
    r = _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/send", data={"text": "добрый день"})
    assert r.headers["X-Action-Outcome"] == "sent"
    assert sent == ["добрый день"]


# --- ревью 14.10, раунд 1: глобальные действия, release при сбое, гонка повтора ---

def test_scoped_manager_cannot_run_global_actions(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)
    c = _client("medina", "m1")
    assert c.post("/admin/followup/run").status_code == 403
    assert c.post("/admin/bots/frunze_tours/toggle").status_code == 403      # чужая команда
    assert c.post("/admin/bots/frunze_tours/stt-toggle").status_code == 403
    assert c.get("/admin/faq").status_code == 403
    assert c.post("/admin/faq/save", data={"title": "x"}).status_code == 403
    assert c.post("/admin/faq/1/toggle", data={"enabled": "0"}).status_code == 403
    assert sent == []


def test_release_on_failure_only_for_owner(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/takeover")
    from app.domain import live_assign

    async def boom(*a, **k):
        raise RuntimeError("db down")
    monkeypatch.setattr(live_assign, "contact_for_channel", boom)
    _client("eliza", "e1").post(f"/admin/conversation/{USER_ID}/release")
    assert _conv().intercepted is True and _conv().assigned_to == "medina"
    _client("medina", "m1").post(f"/admin/conversation/{USER_ID}/release")
    assert _conv().intercepted is False


def test_second_resend_of_same_message_does_not_send_again(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch, enforce=True)
    sent = _sent(monkeypatch)
    c = _client("medina", "m1")
    mid = _message("manager", "пришлите паспорт", "failed")
    assert _resend(c, mid).headers["X-Action-Outcome"] == "sent"
    assert _resend(c, mid).headers["X-Action-Outcome"] == "denied"
    assert sent == ["пришлите паспорт"]
    assert _conv().assigned_to == "medina"


def test_resend_filter_holds_even_with_enforcement_off(tmp_path, monkeypatch):
    """Флаг владения OFF не открывает пересылку чужих реплик клиенту."""
    _setup(tmp_path, monkeypatch, enforce=False)
    sent = _sent(monkeypatch)
    r = _resend(_client("medina", "m1"), _conv().messages[0].id)
    assert r.headers["X-Action-Outcome"] == "denied"
    assert sent == []



def test_bot_toggles_are_full_admin_only(tmp_path, monkeypatch):
    """Решение Алана 14.10: даже свой бот и STT переключает только полный админ."""
    _setup(tmp_path, monkeypatch, enforce=True)
    c = _client("medina", "m1")
    assert c.post("/admin/bots/getvisa/toggle", data={"on": "1"}).status_code == 403
    assert c.post("/admin/bots/getvisa/stt-toggle", data={"on": "1"}).status_code == 403
    assert _client("admin", "frunze").post("/admin/bots/getvisa/toggle", data={"on": "1"}).status_code in (200, 404)


def test_three_concurrent_resends_send_once(tmp_path, monkeypatch):
    """Три одновременных «Повторить», первая попытка падает: клиент получает сообщение один раз."""
    import httpx
    import app.main as main
    _setup(tmp_path, monkeypatch, enforce=True)
    calls = []

    async def slow(channel, bot_id, chat_id, text):
        calls.append(text)
        await asyncio.sleep(0.05)
        if len(calls) == 1:          # первая попытка падает — сценарий гонки из ревью r2
            raise RuntimeError("wappi down")
        return f"wappi-{len(calls)}"
    monkeypatch.setattr(admin_router.outbound, "send_to_client", slow)
    mid = _message("manager", "пришлите паспорт", "failed")

    async def run():
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="https://testserver") as c:
            assert (await c.post("/admin/login", data={"login": "medina", "password": "m1"})).status_code in (200, 303)
            return await asyncio.gather(*[c.post(f"/admin/conversation/{USER_ID}/resend/{mid}")
                                          for _ in range(3)])
    responses = asyncio.run(run())
    # A упал, B (ждал ту же блокировку) отправил, C увидел уже `sent`. Третьей отправки нет.
    assert calls == ["пришлите паспорт", "пришлите паспорт"]
    outcomes = sorted(r.headers["X-Action-Outcome"] for r in responses)
    # Третий отсекается до блокировки (уже pending → denied) или внутри неё (duplicate).
    assert outcomes in (["duplicate", "failed", "sent"], ["denied", "failed", "sent"])
