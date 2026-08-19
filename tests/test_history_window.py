"""History windowing for LLM sends keeps full state history intact."""
import asyncio
from unittest.mock import AsyncMock

from app.agent import runner
from app.core.state import DialogState
from app.integrations.tourvisor.client import TourSearch


class FakeBlock:
    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type = type
        self.text = text
        self.name = name
        self.input = input or {}
        self.id = id

    def model_dump(self):
        return {
            "type": self.type,
            "text": self.text,
            "name": self.name,
            "input": self.input,
            "id": self.id,
        }


class FakeResp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content
        self.usage = None


def _tool_use(name="search_tours", inp=None, id="tool-1"):
    return FakeResp(
        "tool_use",
        [FakeBlock("tool_use", name=name, input=inp or {"destination": "Турция"}, id=id)],
    )


def _text(text="Готово"):
    return FakeResp("end_turn", [FakeBlock("text", text=text)])


def _tool_cycle(n: int) -> list[dict]:
    return [
        {"role": "user", "content": f"request {n}"},
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": f"tool-{n}",
                    "name": "search_tours",
                    "input": {"destination": "Турция"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": f"tool-{n}",
                    "content": f"result {n}",
                }
            ],
        },
        {"role": "assistant", "content": f"answer {n}"},
    ]


def test_windowed_history_keeps_short_history_unchanged():
    history = [
        {"role": "user", "content": "one"},
        {"role": "assistant", "content": "two"},
    ]

    assert runner._windowed_history(history, 2) == history
    assert runner._windowed_history(history, 3) == history


def test_windowed_history_max_zero_returns_everything():
    history = _tool_cycle(1) + _tool_cycle(2)

    assert runner._windowed_history(history, 0) == history


def test_windowed_history_starts_on_user_text_boundary_for_long_history():
    history = _tool_cycle(1) + _tool_cycle(2) + _tool_cycle(3)

    window = runner._windowed_history(history, 5)

    assert window[0] == {"role": "user", "content": "request 3"}
    assert len(window) <= 5


def test_windowed_history_never_starts_on_tool_result_for_any_max():
    history = _tool_cycle(1) + _tool_cycle(2) + _tool_cycle(3)

    for max_n in range(1, len(history) + 3):
        window = runner._windowed_history(history, max_n)

        assert window
        assert window[0]["role"] == "user"
        assert isinstance(window[0]["content"], str)
        assert not (
            isinstance(window[0]["content"], list)
            and any(block.get("type") == "tool_result" for block in window[0]["content"])
        )


def test_qual_context_message_only_includes_non_empty_values():
    assert runner._qual_context_message({}) is None
    assert runner._qual_context_message({"destination": "", "date": None}) is None

    msg = runner._qual_context_message({
        "destination": "Турция",
        "date": "июль",
        "budget": 0,
    })

    assert msg["role"] == "user"
    assert "destination=Турция" in msg["content"]
    assert "date=июль" in msg["content"]
    assert "budget=" not in msg["content"]


def test_date_context_message_uses_bishkek_local_date():
    from datetime import datetime, timezone

    # 09.07.2026 06:00 UTC -> Бишкек (UTC+6) 12:00 того же дня.
    msg = runner._date_context_message(datetime(2026, 7, 9, 6, 0, tzinfo=timezone.utc))
    assert msg["role"] == "user"
    assert "09.07.2026" in msg["content"]
    assert "Бишкек" in msg["content"]

    # 09.07.2026 20:00 UTC -> Бишкек 02:00 10.07 — дата должна перекатиться.
    later = runner._date_context_message(datetime(2026, 7, 9, 20, 0, tzinfo=timezone.utc))
    assert "10.07.2026" in later["content"]


def test_run_turn_sends_window_and_qual_each_tool_iteration(monkeypatch):
    monkeypatch.setattr(runner.settings, "llm_history_max_messages", 3)
    state = DialogState(
        user_id="u-window",
        funnel="tours",
        qualification={"destination": "Турция", "date": "июль"},
        history=_tool_cycle(1) + _tool_cycle(2),
    )
    original_history_len = len(state.history)

    fake = AsyncMock()
    fake.messages.create = AsyncMock(side_effect=[_tool_use(), _text("Вот варианты")])
    monkeypatch.setattr(runner, "client", lambda: fake)
    monkeypatch.setattr(runner._tourvisor, "search_detailed",
                        AsyncMock(return_value=TourSearch(["Отель X 5*"], 1, "ok", "Бишкек")))

    reply = asyncio.run(runner.run_tours_turn(state, "актуально?"))

    assert reply == "Вот варианты"
    assert fake.messages.create.await_count == 2

    first_messages = fake.messages.create.await_args_list[0].kwargs["messages"]
    second_messages = fake.messages.create.await_args_list[1].kwargs["messages"]

    assert first_messages[0]["role"] == "user"
    assert first_messages[0]["content"].startswith("[Служебная заметка: сегодня")
    assert first_messages[1]["content"].startswith("[Уже известно от клиента:")
    assert first_messages[2] == {"role": "user", "content": "актуально?"}

    assert second_messages[0]["content"].startswith("[Служебная заметка: сегодня")
    assert second_messages[1]["content"].startswith("[Уже известно от клиента:")
    assert second_messages[2] == {"role": "user", "content": "актуально?"}
    assert second_messages[3]["role"] == "assistant"
    assert second_messages[4]["role"] == "user"
    assert isinstance(second_messages[4]["content"], list)
    assert second_messages[4]["content"][0]["type"] == "tool_result"

    assert len(state.history) == original_history_len + 4
    assert state.history[0] == {"role": "user", "content": "request 1"}


# ---------- Языковая заметка (19.08.2026) ----------

def test_language_note_appears_for_english_client():
    """Клиент по-английски → служебная заметка на этот ход, как с датой и графиком."""
    history = [{"role": "user", "content": "Hello! Can I get more info on this?"}]

    note = runner._language_context_message(history)

    assert note is not None
    assert "English" in note["content"] or "английск" in note["content"]


def test_language_note_absent_for_russian_client():
    history = [{"role": "user", "content": "здравствуйте, нужна виза в Италию"}]

    assert runner._language_context_message(history) is None


def test_language_note_ignores_forwarded_hotel_names():
    """Латинское название отеля от русскоязычного клиента заметку не поднимает."""
    history = [{"role": "user", "content": "*KIMEROS PARK HOLIDAY VILLAGE 5*"}]

    assert runner._language_context_message(history) is None


def test_language_note_follows_the_last_client_message():
    """Клиент перешёл на русский — заметка уходит, бот не залипает на английском."""
    history = [{"role": "user", "content": "Hello! Can I get more info?"},
               {"role": "assistant", "content": "Hello! Which country?"},
               {"role": "user", "content": "давайте по-русски, нужна виза"}]

    assert runner._language_context_message(history) is None
