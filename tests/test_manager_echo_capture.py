import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app.core.orchestrator as orch
import app.main as main
from app.channels.base import Message
from app.channels.wappi import WappiAdapter
from app.config import BotConfig
from app.core.own_outbound import _reset_for_tests, mark_own
from app.core.intercept import set_intercept
from app.core.orchestrator import Orchestrator
from app.core.state import DialogState, get_state_store, state_store
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
    assert conv.assigned_to == ""
    state = asyncio.run(get_state_store().load(key))
    assert state.intercepted is True
    assert state.auto_intercept_until is not None


def test_auto_intercept_before_ttl_keeps_bot_silent(monkeypatch):
    channel = _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    started = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)
    clock = {"now": started}
    monkeypatch.setattr("app.core.intercept._utcnow", lambda: clock["now"])
    client = TestClient(main.app)

    client.post("/webhook/wappi", json=_wrapped(_echo(msg_id="echo-before-ttl")))
    clock["now"] = started + timedelta(hours=2, minutes=59)
    client.post("/webhook/wappi", json=_wrapped(
        _incoming(msg_id="in-before-ttl", body="are you there?")))

    assert channel.sent == []
    assert asyncio.run(get_state_store().load(f"{BOT_ID}:{PHONE}")).intercepted is True


def test_expired_auto_intercept_answers_and_clears_panel(monkeypatch):
    channel = _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    started = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)
    clock = {"now": started}
    monkeypatch.setattr("app.core.intercept._utcnow", lambda: clock["now"])
    client = TestClient(main.app)

    client.post("/webhook/wappi", json=_wrapped(_echo(msg_id="echo-expiring")))
    clock["now"] = started + timedelta(hours=3)
    client.post("/webhook/wappi", json=_wrapped(
        _incoming(msg_id="in-after-ttl", body="need visa again")))

    assert channel.sent == [(f"{PHONE}@c.us", "bot:need visa again")]
    key = f"{BOT_ID}:{PHONE}"
    state = asyncio.run(get_state_store().load(key))
    conv = asyncio.run(panel_store.get_conversation_store().get(key))
    assert state.intercepted is False
    assert state.auto_intercept_until is None
    assert conv is not None and conv.intercepted is False


def test_new_manager_echo_extends_silence_window(monkeypatch):
    channel = _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    started = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)
    clock = {"now": started}
    monkeypatch.setattr("app.core.intercept._utcnow", lambda: clock["now"])
    client = TestClient(main.app)
    key = f"{BOT_ID}:{PHONE}"

    client.post("/webhook/wappi", json=_wrapped(_echo(msg_id="echo-first")))
    first_deadline = asyncio.run(get_state_store().load(key)).auto_intercept_until
    clock["now"] = started + timedelta(hours=2)
    client.post("/webhook/wappi", json=_wrapped(_echo(msg_id="echo-second")))
    second_deadline = asyncio.run(get_state_store().load(key)).auto_intercept_until
    clock["now"] = started + timedelta(hours=3, minutes=1)
    client.post("/webhook/wappi", json=_wrapped(
        _incoming(msg_id="in-after-old-ttl", body="still waiting")))

    assert second_deadline is not None and first_deadline is not None
    assert second_deadline > first_deadline
    assert channel.sent == []


def test_manual_intercept_never_expires(monkeypatch):
    channel = _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    started = datetime(2026, 7, 29, 6, tzinfo=timezone.utc)
    clock = {"now": started}
    monkeypatch.setattr("app.core.intercept._utcnow", lambda: clock["now"])
    key = f"{BOT_ID}:{PHONE}"
    asyncio.run(set_intercept(key, True, now=started))
    client = TestClient(main.app)
    client.post("/webhook/wappi", json=_wrapped(
        _echo(msg_id="echo-after-manual")))
    clock["now"] = started + timedelta(days=1)

    client.post("/webhook/wappi", json=_wrapped(
        _incoming(msg_id="in-manual-year-later", body="hello")))

    state = asyncio.run(get_state_store().load(key))
    assert state.intercepted is True
    assert state.auto_intercept_until is None
    assert channel.sent == []


def test_manager_echo_keeps_auto_handoff_permanent(monkeypatch):
    channel = _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    key = f"{BOT_ID}:{PHONE}"
    state = asyncio.run(get_state_store().load(key))
    state.stage = "manager"
    state.intercepted = True
    asyncio.run(get_state_store().save(state))

    client = TestClient(main.app)
    client.post("/webhook/wappi", json=_wrapped(
        _echo(msg_id="echo-after-handoff")))

    saved = asyncio.run(get_state_store().load(key))
    assert saved.intercepted is True
    assert saved.auto_intercept_until is None
    assert channel.sent == []


def test_midflight_auto_intercept_deadline_survives_copying_store(monkeypatch):
    deadline = datetime(2026, 7, 29, 9, tzinfo=timezone.utc).timestamp()

    class CopyingStore:
        def __init__(self):
            self.saved = DialogState(user_id=PHONE, funnel="visa")

        async def load(self, user_id):
            return DialogState.from_json(self.saved.to_json())

        async def save(self, state):
            self.saved = DialogState.from_json(state.to_json())

    store = CopyingStore()

    class MidflightFunnel:
        async def handle(self, msg, state):
            fresh = await store.load(BOT_ID + ":" + PHONE)
            fresh.intercepted = True
            fresh.auto_intercept_until = deadline
            await store.save(fresh)
            return "reply that must be dropped"

    class Channel:
        async def send(self, chat_id, text, **kwargs):
            raise AssertionError("intercepted mid-flight reply must not be sent")

    monkeypatch.setattr(orch, "get_state_store", lambda: store)
    monkeypatch.setattr(orch, "get_funnel", lambda name: MidflightFunnel())
    orchestrator = Orchestrator(
        channel=Channel(), bot=BotConfig(id=BOT_ID, scenario="visa"))
    monkeypatch.setattr(orchestrator, "_bots_on", lambda: _async_value(True))
    monkeypatch.setattr(orchestrator, "_maybe_persona_greeting",
                        lambda *args: _async_value(False))
    monkeypatch.setattr(orchestrator, "_maybe_faq_reply",
                        lambda *args: _async_value(None))
    monkeypatch.setattr(orchestrator, "_sync_card",
                        lambda *args: _async_value(None))

    asyncio.run(orchestrator._run_turn(Message(
        channel="whatsapp", user_id=PHONE,
        chat_id=f"{PHONE}@c.us", text="need visa")))

    assert store.saved.intercepted is True
    assert store.saved.auto_intercept_until == deadline


class _CopyingStore:
    def __init__(self):
        self.saved = DialogState(user_id=f"{BOT_ID}:{PHONE}", funnel="visa")

    async def load(self, user_id):
        return DialogState.from_json(self.saved.to_json())

    async def save(self, state):
        self.saved = DialogState.from_json(state.to_json())


class _RecordingChannel:
    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))
        return f"provider-{len(self.sent)}"


def _concurrent_echo_orchestrator(monkeypatch, funnel):
    _clear()
    store = _CopyingStore()
    channel = _RecordingChannel()
    bot = BotConfig(id=BOT_ID, scenario="visa", wappi_profile_id=PROFILE)
    orchestrator = Orchestrator(channel=channel, bot=bot)
    monkeypatch.setattr(orch, "get_state_store", lambda: store)
    monkeypatch.setattr("app.core.intercept.get_state_store", lambda: store)
    monkeypatch.setattr(orch, "get_funnel", lambda name: funnel)
    monkeypatch.setattr(main, "_wappi_orchestrators", {PROFILE: orchestrator})
    monkeypatch.setattr(main.settings, "debounce_seconds", 0)
    monkeypatch.setattr(orchestrator, "_bots_on", lambda: _async_value(True))
    monkeypatch.setattr(orchestrator, "_maybe_persona_greeting",
                        lambda *args: _async_value(False))
    monkeypatch.setattr(orchestrator, "_maybe_faq_reply",
                        lambda *args: _async_value(None))
    monkeypatch.setattr(orchestrator, "_sync_card",
                        lambda *args: _async_value(None))
    return orchestrator, store, channel


def test_handle_drops_reply_when_manager_echo_arrives_midflight(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()

    class SlowFunnel:
        async def handle(self, msg, state):
            entered.set()
            await release.wait()
            return "reply that must be dropped"

    orchestrator, store, channel = _concurrent_echo_orchestrator(
        monkeypatch, SlowFunnel()
    )

    async def scenario():
        turn = asyncio.create_task(orchestrator.handle(Message(
            channel="whatsapp", user_id=PHONE,
            chat_id=f"{PHONE}@c.us", text="need visa"
        )))
        await entered.wait()
        await main._handle_manager_echo(_echo(msg_id="echo-during-handle"))
        release.set()
        await turn

    asyncio.run(scenario())

    assert channel.sent == []
    assert store.saved.intercepted is True
    assert store.saved.auto_intercept_until is not None


def test_auto_handoff_keeps_permanent_deadline_after_midflight_echo(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()

    class HandoffFunnel:
        async def handle(self, msg, state):
            entered.set()
            await release.wait()
            state.stage = "manager"
            return "handoff reply"

    orchestrator, store, _channel = _concurrent_echo_orchestrator(
        monkeypatch, HandoffFunnel()
    )

    async def scenario():
        turn = asyncio.create_task(orchestrator.handle(Message(
            channel="whatsapp", user_id=PHONE,
            chat_id=f"{PHONE}@c.us", text="manager please"
        )))
        await entered.wait()
        await main._handle_manager_echo(_echo(msg_id="echo-during-handoff"))
        release.set()
        await turn

    asyncio.run(scenario())

    assert store.saved.intercepted is True
    assert store.saved.stage == "manager"
    assert store.saved.auto_intercept_until is None


def test_llm_failure_preserves_midflight_manager_echo(monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()

    class FailingFunnel:
        async def handle(self, msg, state):
            entered.set()
            await release.wait()
            raise RuntimeError("fake LLM failure")

    orchestrator, store, _channel = _concurrent_echo_orchestrator(
        monkeypatch, FailingFunnel()
    )

    async def scenario():
        turn = asyncio.create_task(orchestrator.handle(Message(
            channel="whatsapp", user_id=PHONE,
            chat_id=f"{PHONE}@c.us", text="need visa"
        )))
        await entered.wait()
        await main._handle_manager_echo(_echo(msg_id="echo-during-failure"))
        expected_deadline = store.saved.auto_intercept_until
        release.set()
        await turn
        return expected_deadline

    expected_deadline = asyncio.run(scenario())

    assert store.saved.intercepted is True
    assert store.saved.auto_intercept_until == expected_deadline
    assert expected_deadline is not None


async def _async_value(value):
    return value


def test_manager_echo_preserves_existing_owner(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    key = f"{BOT_ID}:{PHONE}"
    asyncio.run(panel_store.get_conversation_store().update_meta(
        key, assigned_to="medina"))

    TestClient(main.app).post("/webhook/wappi", json=_wrapped(
        _echo(msg_id="echo-owned")))

    conv = asyncio.run(panel_store.get_conversation_store().get(key))
    assert conv is not None and conv.assigned_to == "medina"


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
