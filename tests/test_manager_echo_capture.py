import asyncio

from fastapi.testclient import TestClient

import app.core.orchestrator as orch
import app.main as main
from app.channels.wappi import WappiAdapter
from app.config import BotConfig
from app.core.own_outbound import _reset_for_tests, mark_own
from app.core.orchestrator import Orchestrator
from app.core.state import get_state_store, state_store
from app.integrations.panel import store as panel_store

PROFILE = "manager-capture-profile"
BOT_ID = "getvisa"
PHONE = "996500494009"


def _clear() -> None:
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    panel_store._memory_store._mid = 0
    state_store._store.clear()
    main._seen_wappi_ids.clear()
    _reset_for_tests()


def _echo(msg_id: str = "manager-echo-1", body: str = "manager reply") -> dict:
    return {
        "id": msg_id,
        "profile_id": PROFILE,
        "wh_type": "incoming_message",
        "body": body,
        "type": "chat",
        "from": "996706660009@c.us",
        "to": f"{PHONE}@c.us",
        "chatId": f"{PHONE}@c.us",
        "is_me": True,
        "chat_type": "dialog",
    }


def _incoming(msg_id: str = "client-in-1", body: str = "need visa") -> dict:
    return {
        "id": msg_id,
        "profile_id": PROFILE,
        "wh_type": "incoming_message",
        "body": body,
        "type": "chat",
        "from": f"{PHONE}@c.us",
        "to": "996706660009@c.us",
        "chatId": f"{PHONE}@c.us",
        "is_me": False,
        "chat_type": "dialog",
    }


def _wrapped(*events: dict) -> dict:
    return {"messages": list(events)}


def _wire(monkeypatch):
    _clear()

    class FakeFunnel:
        async def handle(self, msg, state):
            return f"bot:{msg.text}"

    monkeypatch.setattr(orch, "get_funnel", lambda name: FakeFunnel())
    bot = BotConfig(id=BOT_ID, scenario="visa", wappi_profile_id=PROFILE)

    class RecordingWappi(WappiAdapter):
        def __init__(self, bot):
            super().__init__(bot=bot)
            self.sent = []

        async def send(self, chat_id, text, **kw):
            self.sent.append((chat_id, text))
            return f"provider-{len(self.sent)}"

    channel = RecordingWappi(bot)
    monkeypatch.setattr(main, "_wappi_orchestrators", {PROFILE: Orchestrator(channel=channel, bot=bot)})
    return channel


def test_manager_echo_flag_off_keeps_old_ignore_behavior(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", False)
    client = TestClient(main.app)

    resp = client.post("/webhook/wappi", json=_wrapped(_echo()))

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "handled": 0}
    conv = asyncio.run(panel_store.get_conversation_store().get(f"{BOT_ID}:{PHONE}"))
    assert conv is None


def test_manager_echo_flag_on_saves_manager_and_intercepts(monkeypatch):
    channel = _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    client = TestClient(main.app)

    resp = client.post("/webhook/wappi", json=_wrapped(_echo(body="hello from manager")))

    assert resp.status_code == 200
    assert channel.sent == []
    key = f"{BOT_ID}:{PHONE}"
    conv = asyncio.run(panel_store.get_conversation_store().get(key))
    assert conv is not None
    assert conv.messages[-1].sender == "manager"
    assert conv.messages[-1].text == "hello from manager"
    assert conv.intercepted is True
    assert conv.assigned_to == "whatsapp"
    assert asyncio.run(get_state_store().load(key)).intercepted is True


def test_manager_echo_flag_on_skips_own_provider_id(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    mark_own("own-id")
    client = TestClient(main.app)

    resp = client.post("/webhook/wappi", json=_wrapped(_echo(msg_id="own-id")))

    assert resp.status_code == 200
    conv = asyncio.run(panel_store.get_conversation_store().get(f"{BOT_ID}:{PHONE}"))
    assert conv is None


def test_manager_echo_retry_is_deduped(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    client = TestClient(main.app)
    event = _echo(msg_id="retry-id")

    assert client.post("/webhook/wappi", json=_wrapped(event)).status_code == 200
    assert client.post("/webhook/wappi", json=_wrapped(event)).status_code == 200

    conv = asyncio.run(panel_store.get_conversation_store().get(f"{BOT_ID}:{PHONE}"))
    assert conv is not None
    assert [m.sender for m in conv.messages] == ["manager"]


def test_client_incoming_still_routes_with_capture_enabled(monkeypatch):
    channel = _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    client = TestClient(main.app)

    resp = client.post("/webhook/wappi", json=_wrapped(_incoming(body="need visa now")))

    assert resp.json() == {"ok": True, "handled": 1}
    assert channel.sent == [(f"{PHONE}@c.us", "bot:need visa now")]


def test_echo_capture_error_does_not_block_next_client_event(monkeypatch):
    channel = _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)

    async def fail_echo(raw):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "_handle_manager_echo", fail_echo)
    client = TestClient(main.app)

    resp = client.post(
        "/webhook/wappi",
        json=_wrapped(_echo(msg_id="bad-echo"), _incoming(msg_id="after-echo", body="need visa now")),
    )

    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "handled": 1}
    assert channel.sent == [(f"{PHONE}@c.us", "bot:need visa now")]
