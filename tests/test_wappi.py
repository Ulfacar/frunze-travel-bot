"""Тесты прямого WhatsApp-канала Wappi: parse/send, фильтр эхо, e2e webhook."""
import asyncio
import json

import httpx
from fastapi.testclient import TestClient

import app.core.orchestrator as orch
import app.main as main
from app.channels.wappi import WappiAdapter, is_incoming_user_message
from app.config import BotConfig
from app.core.bots import BotRegistry
from app.core.orchestrator import Orchestrator

PROFILE = "6a74fb33-16aa"


def _incoming(body="привет", type_="chat", is_me=False):
    return {
        "wh_type": "incoming_message",
        "profile_id": PROFILE,
        "id": "msg1",
        "body": body,
        "type": type_,
        "from": "996700123456@c.us",
        "chatId": "996700123456@c.us",
        "senderName": "Клиент",
        "is_me": is_me,
    }


# ---------------- фильтр входящих ----------------
def test_is_incoming_filters_echo_and_status():
    assert is_incoming_user_message(_incoming()) is True
    assert is_incoming_user_message(_incoming(is_me=True)) is False          # наше эхо
    assert is_incoming_user_message({"wh_type": "message_ack"}) is False     # статус-событие


# ---------------- parse ----------------
def test_parse_text_message():
    msg = asyncio.run(WappiAdapter().parse(_incoming("хочу тур в Турцию")))
    assert msg.channel == "whatsapp"
    assert msg.user_id == "996700123456"             # номер без @c.us
    assert msg.chat_id == "996700123456@c.us"        # отвечаем в этот chatId
    assert msg.text == "хочу тур в Турцию"
    assert msg.kind == "text"


def test_parse_media_is_non_text():
    msg = asyncio.run(WappiAdapter().parse(_incoming(body="", type_="ptt")))
    assert msg.kind == "non_text"
    assert msg.text == ""


# ---------------- send ----------------
def test_send_calls_wappi_api(monkeypatch):
    from app.channels import wappi as mod
    monkeypatch.setattr(mod.settings, "wappi_base_url", "https://wappi.pro")
    monkeypatch.setattr(mod.settings, "wappi_token", "tok-123")

    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"status": "done"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    bot = BotConfig(id="frunze_tours_1", scenario="tours", wappi_profile_id=PROFILE)
    adapter = WappiAdapter(bot=bot, client=client)

    asyncio.run(adapter.send("996700123456@c.us", "Здравствуйте!"))

    assert len(calls) == 1
    req = calls[0]
    assert req.url.path == "/api/sync/message/send"
    assert req.url.params["profile_id"] == PROFILE
    assert req.headers["Authorization"] == "tok-123"
    body = json.loads(req.content)
    assert body == {"recipient": "996700123456", "body": "Здравствуйте!"}


def test_send_skipped_without_credentials(monkeypatch):
    from app.channels import wappi as mod
    monkeypatch.setattr(mod.settings, "wappi_token", "")
    calls = []
    client = httpx.AsyncClient(transport=httpx.MockTransport(
        lambda r: calls.append(r) or httpx.Response(200)))
    adapter = WappiAdapter(bot=BotConfig(id="x", scenario="tours"), client=client)
    asyncio.run(adapter.send("996700123456@c.us", "текст"))
    assert calls == []


# ---------------- e2e webhook ----------------
def _wire_wappi_bot(monkeypatch):
    class FakeFunnel:
        async def handle(self, msg, state):
            return f"echo:{msg.text}"

    monkeypatch.setattr(orch, "get_funnel", lambda name: FakeFunnel())

    bot = BotConfig(id="frunze_tours_1", scenario="tours", wappi_profile_id=PROFILE)

    class RecordingWappi(WappiAdapter):
        def __init__(self, bot):
            super().__init__(bot=bot)
            self.sent = []

        async def send(self, chat_id, text, **kw):
            self.sent.append((chat_id, text))

    channel = RecordingWappi(bot)
    monkeypatch.setattr(main, "registry", BotRegistry([bot]))
    monkeypatch.setattr(main, "_wappi_orchestrators", {PROFILE: Orchestrator(channel=channel, bot=bot)})
    return channel


def test_wappi_webhook_routes_and_replies(monkeypatch):
    channel = _wire_wappi_bot(monkeypatch)
    client = TestClient(main.app)

    resp = client.post("/webhook/wappi", json=_incoming("хочу тур"))

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "bot": "frunze_tours_1"}
    assert channel.sent == [("996700123456@c.us", "echo:хочу тур")]


def test_wappi_webhook_ignores_own_echo(monkeypatch):
    channel = _wire_wappi_bot(monkeypatch)
    client = TestClient(main.app)

    resp = client.post("/webhook/wappi", json=_incoming("это наше сообщение", is_me=True))

    assert resp.json() == {"ok": True, "skipped": "not_incoming"}
    assert channel.sent == []  # на эхо не отвечаем — нет цикла
