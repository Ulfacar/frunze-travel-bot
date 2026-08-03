"""Пуш «заявка готова» уходит со ВСЕХ путей, а не только из основного хода.

Разбор прода 03.08: за неделю пуш ушёл по 18 заявкам из 31, и у всех тринадцати
«молчаливых» владелец был на месте. Причина оказалась не в правах и не в телеге:
стадию `manager` ставят четыре разные ветки, а `maybe_notify` звали только из одной
(`_run_turn`). Остальные три выходят через `return` — заявка оседала в панели.

Живые примеры, ради которых написан файл:
* голос: два подряд → авто-хендофф (`_handle_non_text`) — самый частый путь бота;
* FAQ `handoff_only`: 02.08 виза США, бот сказал «передаю менеджеру», Медина
  закреплена, пуша не было, сутки тишины;
* визовый self-service: повторный вопрос по своей визе тоже уводит к человеку.

Проверяем факт вызова, а не текст пуша — содержимое карточки закрыто
test_instant_handoff.py.
"""
import asyncio

import pytest

from app.channels.base import Message
from app.config import BotConfig
from app.core import instant_handoff
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


class _Calls:
    """Ловит вызовы maybe_notify: (ключ диалога, что бот пообещал клиенту)."""

    def __init__(self):
        self.seen: list[tuple[str, str]] = []

    async def __call__(self, user_id, *, promised="", sessionmaker=None,
                       waited_since=None):
        self.seen.append((user_id, promised))
        return True


@pytest.fixture
def calls(monkeypatch):
    spy = _Calls()
    monkeypatch.setattr(instant_handoff, "maybe_notify", spy)
    return spy


def _voice(uid):
    return Message(channel="telegram", user_id=uid, chat_id=uid, text="", kind="non_text")


def _text(uid, body):
    return Message(channel="telegram", user_id=uid, chat_id=uid, text=body, kind="text")


def test_voice_handoff_pushes_the_lead(calls):
    """Два голосовых подряд = заявка у менеджера. Клиент ждёт звонка, а не тишины."""
    orch = Orchestrator(channel=FakeChannel())
    asyncio.run(orch.handle(_voice("u_voice")))          # первое — фолбэк, пуша нет
    assert calls.seen == []
    asyncio.run(orch.handle(_voice("u_voice")))          # второе — хендофф
    assert [uid for uid, _ in calls.seen] == ["u_voice"]
    assert calls.seen[0][1] == NON_TEXT_HANDOFF          # менеджер видит, что обещано
    state = asyncio.run(get_state_store().load("u_voice"))
    assert state.stage == "manager"


def test_single_voice_is_not_a_lead(calls):
    """Одно голосовое — ещё не заявка: пуш по нему был бы ложной тревогой."""
    ch = FakeChannel()
    asyncio.run(Orchestrator(channel=ch).handle(_voice("u_one")))
    assert ch.sent == [("u_one", NON_TEXT_FALLBACK)]
    assert calls.seen == []


def test_faq_handoff_only_pushes_the_lead(calls, monkeypatch):
    """Случай Акбара (02.08, виза США): бот сказал «передаю менеджеру» — и всё."""
    from app.core import faq

    entry = faq.FaqEntryView(
        id=1, funnel="tours", enabled=True, priority=0, title="чужая страна",
        patterns=["бразилия"], negative_terms=[], answer="Передаю менеджеру — подскажет.",
        handoff_only=True, allow_during_qualification=False)
    monkeypatch.setattr(faq, "match_faq", lambda *a, **kw: entry)

    orch = Orchestrator(channel=FakeChannel(),
                        bot=BotConfig(id="frunze_tours", scenario="tours"))
    asyncio.run(orch.handle(_text("u_faq", "а Бразилия?")))

    # Ключ диалога у бота с id — с префиксом: пуш адресуется той же карточке.
    assert [uid for uid, _ in calls.seen] == ["frunze_tours:u_faq"]
    assert calls.seen[0][1] == entry.answer
    state = asyncio.run(get_state_store().load("frunze_tours:u_faq"))
    assert state.stage == "manager" and state.intercepted is True


def test_ordinary_faq_answer_pushes_nothing(calls, monkeypatch):
    """Обычный FAQ (адрес, часы работы) заявкой не является — менеджера не дёргаем."""
    from app.core import faq

    entry = faq.FaqEntryView(
        id=2, funnel="tours", enabled=True, priority=0, title="адрес",
        patterns=["адрес"], negative_terms=[], answer="Мы на Фрунзе 1.",
        handoff_only=False, allow_during_qualification=True)
    monkeypatch.setattr(faq, "match_faq", lambda *a, **kw: entry)

    orch = Orchestrator(channel=FakeChannel(),
                        bot=BotConfig(id="frunze_tours", scenario="tours"))
    asyncio.run(orch.handle(_text("u_addr", "какой адрес?")))

    assert calls.seen == []
