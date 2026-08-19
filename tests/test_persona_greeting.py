import asyncio

from app.channels.base import Message
from app.config import BotConfig
from app.core.faq import is_bare_greeting
from app.core.orchestrator import Orchestrator
from app.core.state import DialogState, state_store


class FakeChannel:
    channel = "telegram"

    async def parse(self, raw):  # pragma: no cover
        ...

    async def send(self, chat_id, text, **kwargs):
        ...


class FakeStore:
    def __init__(self) -> None:
        self.saved = []

    async def save(self, state):
        self.saved.append(state)


def _msg(text: str = "здравствуйте") -> Message:
    return Message(channel="telegram", user_id="u-persona", chat_id="42", text=text)


def test_is_bare_greeting_full_string_only():
    assert is_bare_greeting("здравствуйте")
    assert is_bare_greeting("привет")
    assert is_bare_greeting("салам алейкум")
    assert is_bare_greeting("здравствуйте можно узнать подробнее")
    assert is_bare_greeting("/start")

    assert not is_bare_greeting("здравствуйте хочу тур в турцию")
    assert not is_bare_greeting("здравствуйте расскажите про визу сша")
    assert not is_bare_greeting("когда рейсы")


def test_maybe_persona_greeting_tours_ademi_without_llm(monkeypatch):
    sent = []

    async def fake_reply(self, msg, text):
        sent.append(text)

    async def fake_sync(self, msg, state):
        pass

    monkeypatch.setattr(Orchestrator, "_reply", fake_reply)
    monkeypatch.setattr(Orchestrator, "_sync_card", fake_sync)

    state = DialogState(user_id="u-ademi", funnel="tours", manager_name="Адеми")
    store = FakeStore()

    handled = asyncio.run(
        Orchestrator(channel=FakeChannel())._maybe_persona_greeting(_msg(), state, store)
    )

    assert handled is True
    assert sent and "Адеми" in sent[0]
    assert "направление" in sent[0]
    assert len(state.history) == 2
    assert state.history[0] == {"role": "user", "content": "здравствуйте"}
    assert state.history[1] == {"role": "assistant", "content": sent[0]}
    assert store.saved == [state]


def test_maybe_persona_greeting_visa_medina(monkeypatch):
    sent = []

    async def fake_reply(self, msg, text):
        sent.append(text)

    async def fake_sync(self, msg, state):
        pass

    monkeypatch.setattr(Orchestrator, "_reply", fake_reply)
    monkeypatch.setattr(Orchestrator, "_sync_card", fake_sync)

    state = DialogState(user_id="u-medina", funnel="visa", manager_name="Медина")
    handled = asyncio.run(
        Orchestrator(channel=FakeChannel())._maybe_persona_greeting(_msg(), state, FakeStore())
    )

    assert handled is True
    assert "Медина" in sent[0]
    assert "Как могу к вам обращаться" in sent[0]


def test_maybe_persona_greeting_tours_sezim(monkeypatch):
    sent = []

    async def fake_reply(self, msg, text):
        sent.append(text)

    async def fake_sync(self, msg, state):
        pass

    monkeypatch.setattr(Orchestrator, "_reply", fake_reply)
    monkeypatch.setattr(Orchestrator, "_sync_card", fake_sync)

    state = DialogState(user_id="u-sezim", funnel="tours", manager_name="Сезим")
    handled = asyncio.run(
        Orchestrator(channel=FakeChannel())._maybe_persona_greeting(_msg(), state, FakeStore())
    )

    assert handled is True
    assert "Сезим" in sent[0]


def test_maybe_persona_greeting_does_not_intercept_greeting_with_intent(monkeypatch):
    async def fail_reply(self, msg, text):  # pragma: no cover
        raise AssertionError("persona greeting should not reply")

    monkeypatch.setattr(Orchestrator, "_reply", fail_reply)

    state = DialogState(user_id="u-intent", funnel="tours", manager_name="Адеми")
    handled = asyncio.run(
        Orchestrator(channel=FakeChannel())._maybe_persona_greeting(
            _msg("здравствуйте, хочу тур в турцию"), state, FakeStore()
        )
    )

    assert handled is False
    assert state.history == []


def test_maybe_persona_greeting_does_not_intercept_second_message(monkeypatch):
    async def fail_reply(self, msg, text):  # pragma: no cover
        raise AssertionError("persona greeting should not reply")

    monkeypatch.setattr(Orchestrator, "_reply", fail_reply)

    state = DialogState(
        user_id="u-second",
        funnel="tours",
        manager_name="Адеми",
        history=[{"role": "user", "content": "уже писал"}],
    )
    handled = asyncio.run(
        Orchestrator(channel=FakeChannel())._maybe_persona_greeting(
            _msg("привет"), state, FakeStore()
        )
    )

    assert handled is False
    assert len(state.history) == 1


def test_run_turn_persona_greeting_before_funnel_handle(monkeypatch):
    import app.core.orchestrator as orch

    sent = []

    async def bots_on(self):
        return True

    async def fake_reply(self, msg, text):
        sent.append(text)

    async def fake_sync(self, msg, state):
        pass

    def fail_get_funnel(name):  # pragma: no cover
        raise AssertionError("bare persona greeting must not reach funnel/LLM path")

    monkeypatch.setattr(Orchestrator, "_bots_on", bots_on)
    monkeypatch.setattr(Orchestrator, "_reply", fake_reply)
    monkeypatch.setattr(Orchestrator, "_sync_card", fake_sync)
    monkeypatch.setattr(orch, "get_funnel", fail_get_funnel)

    bot = BotConfig(id="frunze_tours", scenario="tours", manager_name="Адеми")
    msg = Message(
        channel="telegram",
        user_id="persona-run-turn",
        chat_id="42",
        text="здравствуйте",
    )

    asyncio.run(Orchestrator(channel=FakeChannel(), bot=bot)._run_turn(msg))

    saved = asyncio.run(state_store.load("frunze_tours:persona-run-turn"))
    assert sent and "Адеми" in sent[0]
    assert len(saved.history) == 2


# ---------- Английский клиент (19.08.2026) ----------
#
# «Hello» и «hi» проходят как голое приветствие, то есть ответ собирается БЕЗ LLM — и до
# сегодня всегда был русским, сколько бы правил о языке ни лежало в системном промпте.

def test_persona_greeting_answers_english_client_in_english():
    from app.core.branding import persona_greeting

    visa = persona_greeting("visa", "Медина", english=True)
    tours = persona_greeting("tours", "Адеми", english=True)

    assert "Hello" in visa and "Frunze Travel" in visa
    assert "Hello" in tours
    assert "Здравствуйте" not in visa and "Здравствуйте" not in tours


def test_persona_greeting_stays_russian_by_default():
    from app.core.branding import persona_greeting

    assert "Здравствуйте" in persona_greeting("visa", "Медина")
    assert "Здравствуйте" in persona_greeting("tours", "Адеми")
