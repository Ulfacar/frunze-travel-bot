"""Юнит-тесты агентного цикла «Туры» с мок-Claude (без сети и без API-ключа).

Мокаем app.agent.runner.client (Anthropic) и runner._tourvisor.search, проверяя:
- round-trip tool_use → tool_result → финальный текст;
- guard по максимуму итераций;
- graceful degrade инструмента search_tours при ошибке TourVisor.
"""
import asyncio
from unittest.mock import AsyncMock

from app.agent import runner
from app.core.state import DialogState
from app.integrations.crm import get_crm
from app.integrations.tourvisor.client import TourVisorError


# ---- фейковые ответы Claude (форма, которую ждёт runner) ----
class FakeBlock:
    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type = type
        self.text = text
        self.name = name
        self.input = input or {}
        self.id = id

    def model_dump(self):
        return {"type": self.type, "text": self.text, "name": self.name,
                "input": self.input, "id": self.id}


class FakeResp:
    def __init__(self, stop_reason, content):
        self.stop_reason = stop_reason
        self.content = content


def _tool_use(name="search_tours", inp=None, id="t1"):
    return FakeResp("tool_use", [FakeBlock("tool_use", name=name,
                                           input=inp or {"destination": "Турция"}, id=id)])


def _text(text="Готово"):
    return FakeResp("end_turn", [FakeBlock("text", text=text)])


def _patch_client(monkeypatch, *responses, repeat_last=False):
    fake = AsyncMock()
    if repeat_last:
        fake.messages.create = AsyncMock(return_value=responses[-1])
    else:
        fake.messages.create = AsyncMock(side_effect=list(responses))
    monkeypatch.setattr(runner, "client", lambda: fake)
    return fake


def test_tool_use_then_text(monkeypatch):
    """search_tours отрабатывает, затем Claude отдаёт финальный текст."""
    state = DialogState(user_id="u1", funnel="tours")
    fake = _patch_client(monkeypatch, _tool_use(), _text("Вот варианты"))
    monkeypatch.setattr(runner._tourvisor, "search", AsyncMock(return_value=["Отель X 5*"]))

    reply = asyncio.run(runner.run_tours_turn(state, "хочу тур в Турцию"))

    assert reply == "Вот варианты"
    runner._tourvisor.search.assert_awaited()
    assert state.deal_id is not None  # лид создан по ходу search_tours
    assert fake.messages.create.await_count == 2


def test_max_iterations_guard(monkeypatch):
    """Если Claude бесконечно зовёт инструменты — выходим по лимиту с безопасным ответом."""
    state = DialogState(user_id="u2", funnel="tours")
    fake = _patch_client(monkeypatch, _tool_use(), repeat_last=True)
    monkeypatch.setattr(runner._tourvisor, "search", AsyncMock(return_value=["X"]))

    reply = asyncio.run(runner.run_tours_turn(state, "тур"))

    assert reply  # не пусто — есть запасная фраза
    assert fake.messages.create.await_count == runner.MAX_TOOL_ITERATIONS


def test_search_tool_graceful_degrade(monkeypatch):
    """Ошибка TourVisor не валит диалог — инструмент возвращает понятное сообщение."""
    state = DialogState(user_id="u3", funnel="tours")
    crm = get_crm()
    monkeypatch.setattr(runner._tourvisor, "search", AsyncMock(side_effect=TourVisorError("auth")))

    out = asyncio.run(runner._tours_exec_tool("search_tours", {"destination": "Турция"}, state, crm))

    assert "менеджер" in out.lower()


def test_visa_turn_scores_and_replies(monkeypatch):
    """Воронка «Визы» на общем run_turn: score_visa отрабатывает → финальный текст."""
    state = DialogState(user_id="v1", funnel="visa")
    fake = _patch_client(
        monkeypatch,
        _tool_use(name="score_visa", inp={"country": "Германия", "prior_visas": "да"}, id="v"),
        _text("Ваши шансы — высокие. Приглашаю на консультацию."),
    )
    reply = asyncio.run(runner.run_visa_turn(state, "нужна виза в Германию"))

    assert reply and "консультаци" in reply.lower()
    assert state.deal_id is not None  # лид по визе создан
    assert fake.messages.create.await_count == 2


def test_visa_category_thresholds():
    """Категории шансов по порогам."""
    from app.funnels.visa import visa_category
    assert visa_category(80) == "высокие"
    assert visa_category(50) == "средние"
    assert visa_category(20) == "низкие"


def test_tickets_turn_submits_request(monkeypatch):
    """Воронка «Билеты»: submit_request фиксирует заявку и создаёт лид."""
    state = DialogState(user_id="b1", funnel="tickets")
    fake = _patch_client(
        monkeypatch,
        _tool_use(name="submit_request",
                  inp={"route": "Бишкек-Москва", "dates": "10.07", "passengers": "2"}, id="b"),
        _text("Заявка принята, менеджер свяжется с вами."),
    )
    reply = asyncio.run(runner.run_tickets_turn(state, "нужен билет в Москву"))

    assert reply and "менеджер" in reply.lower()
    assert state.deal_id is not None
    assert state.qualification.get("route") == "Бишкек-Москва"
    assert fake.messages.create.await_count == 2
