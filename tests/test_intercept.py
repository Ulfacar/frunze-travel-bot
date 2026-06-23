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


def test_handoff_to_manager_auto_intercepts(monkeypatch):
    """Когда воронка переводит стадию в manager, бот шлёт прощальную реплику и
    автоматически глушится — следующее сообщение клиента уже без ответа бота."""
    import app.core.orchestrator as orch
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

    class HandoffFunnel:
        async def handle(self, msg, state):
            state.stage = "manager"
            return "Передаю менеджеру 🙏"

    monkeypatch.setattr(orch, "get_funnel", lambda name: HandoffFunnel())

    state = asyncio.run(state_store.load("handoff-user"))
    state.funnel = "visa"
    state.intercepted = False

    orchestrator = Orchestrator(channel=FakeChannel())
    msg = Message(channel="telegram", user_id="handoff-user", chat_id="77", text="хочу к менеджеру")
    asyncio.run(orchestrator.handle(msg))

    # Прощальная реплика этого хода ушла...
    assert sent == [("77", "Передаю менеджеру 🙏")]
    # ...и бот теперь заглушен.
    saved = asyncio.run(state_store.load("handoff-user"))
    assert saved.intercepted is True

    # Следующее сообщение клиента — бот молчит.
    sent.clear()
    msg2 = Message(channel="telegram", user_id="handoff-user", chat_id="77", text="ещё вопрос")
    asyncio.run(orchestrator.handle(msg2))
    assert sent == []
