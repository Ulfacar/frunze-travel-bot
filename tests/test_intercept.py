"""Нативный перехват: когда менеджер взял диалог (state.intercepted=True), бот молчит."""
import asyncio
from unittest.mock import AsyncMock

from app.agent import runner
from app.core.state import DialogState


def test_runner_silent_when_intercepted(monkeypatch):
    """run_tours_turn не зовёт Claude и ничего не отвечает при перехвате."""
    state = DialogState(user_id="u1", funnel="tours")
    state.intercepted = True
    fake = AsyncMock()
    fake.messages.create = AsyncMock()
    monkeypatch.setattr(runner, "client", lambda: fake)

    reply = asyncio.run(runner.run_tours_turn(state, "привет"))

    assert reply is None
    fake.messages.create.assert_not_called()
    assert state.history == []  # история не тронута


def test_orchestrator_silent_when_intercepted(monkeypatch):
    """Оркестратор не отвечает ни в одной воронке, пока менеджер ведёт диалог."""
    from app.channels.base import Message
    from app.core.orchestrator import Orchestrator
    from app.core.state import state_store

    sent = []

    class FakeChannel:
        channel = "telegram"

        async def parse(self, raw):  # pragma: no cover
            ...

        async def send(self, chat_id, text, **kwargs):
            sent.append((chat_id, text))

    state = asyncio.run(state_store.load("intercepted-user"))
    state.funnel = "tours"
    state.intercepted = True

    msg = Message(channel="telegram", user_id="intercepted-user", chat_id="42", text="есть туры?")
    asyncio.run(Orchestrator(channel=FakeChannel()).handle(msg))

    assert sent == []  # бот промолчал
