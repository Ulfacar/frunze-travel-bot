"""Не-текст (голос/фото/медиа): бот честно отвечает, а не молчит.

Тестируем поведение оркестратора (без импорта telegram-адаптера, который тянет aiogram).
"""
import asyncio

from app.channels.base import Message
from app.core.orchestrator import NON_TEXT_FALLBACK, NON_TEXT_HANDOFF, Orchestrator
from app.core.state import get_state_store


class FakeChannel:
    channel = "telegram"

    def __init__(self):
        self.sent = []

    async def parse(self, raw):  # pragma: no cover
        ...

    async def send(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


def _voice(uid):
    return Message(channel="telegram", user_id=uid, chat_id=uid, text="", kind="non_text")


def _text(uid, body):
    return Message(channel="telegram", user_id=uid, chat_id=uid, text=body, kind="text")


def test_voice_message_gets_fallback():
    ch = FakeChannel()
    msg = Message(channel="telegram", user_id="u1", chat_id="1", text="", kind="non_text")
    asyncio.run(Orchestrator(channel=ch).handle(msg))
    assert ch.sent == [("1", NON_TEXT_FALLBACK)]


def test_two_consecutive_voices_hand_off_to_manager():
    ch = FakeChannel()
    orch = Orchestrator(channel=ch)
    asyncio.run(orch.handle(_voice("u_two")))
    asyncio.run(orch.handle(_voice("u_two")))
    # 1-е — фолбэк, 2-е — хендофф менеджеру.
    assert ch.sent == [("u_two", NON_TEXT_FALLBACK), ("u_two", NON_TEXT_HANDOFF)]
    state = asyncio.run(get_state_store().load("u_two"))
    assert state.stage == "manager"
    assert state.intercepted is True


def test_text_between_voices_resets_counter():
    ch = FakeChannel()
    orch = Orchestrator(channel=ch)
    asyncio.run(orch.handle(_voice("u_reset")))      # counter → 1, фолбэк
    asyncio.run(orch.handle(_text("u_reset", "привет")))  # текст сбрасывает счётчик
    asyncio.run(orch.handle(_voice("u_reset")))      # снова 1-е подряд → фолбэк, НЕ хендофф
    assert ch.sent[-1] == ("u_reset", NON_TEXT_FALLBACK)
    assert NON_TEXT_HANDOFF not in [t for _, t in ch.sent]
    state = asyncio.run(get_state_store().load("u_reset"))
    assert state.intercepted is False


def test_empty_update_ignored():
    ch = FakeChannel()
    msg = Message(channel="telegram", user_id="", chat_id="", text="", kind="text")
    asyncio.run(Orchestrator(channel=ch).handle(msg))
    assert ch.sent == []  # служебный апдейт — молчим


def test_telegram_parse_detects_voice():
    from app.channels.telegram import TelegramAdapter
    raw = {"message": {"from": {"id": 7}, "chat": {"id": 7}, "voice": {"file_id": "x"}}}
    adapter = TelegramAdapter.__new__(TelegramAdapter)  # без реального Bot/токена
    adapter.channel = "telegram"
    msg = asyncio.run(TelegramAdapter.parse(adapter, raw))
    assert msg.kind == "non_text" and msg.text == ""


def test_telegram_parse_text_is_text():
    from app.channels.telegram import TelegramAdapter
    raw = {"message": {"from": {"id": 7}, "chat": {"id": 7}, "text": "привет"}}
    adapter = TelegramAdapter.__new__(TelegramAdapter)
    adapter.channel = "telegram"
    msg = asyncio.run(TelegramAdapter.parse(adapter, raw))
    assert msg.kind == "text" and msg.text == "привет"
