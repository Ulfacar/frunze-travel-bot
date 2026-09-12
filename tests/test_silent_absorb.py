# -*- coding: utf-8 -*-
"""Бот молчит при перехвате — но обязан продолжать ЧИТАТЬ переписку.

Замер 13.09: из 739 перехваченных туровых диалогов анкета пуста у 591 (80%). Есть
диалог со 131 сообщением клиента и полностью пустой карточкой. Причина —
`orchestrator._run_turn` выходит на `if state.intercepted: … return` ДО того места, где
извлекаются факты, а стадия `manager` ставится одновременно с перехватом, то есть раньше,
чем бот успевает выяснить направление.

Правило заказчика «перехватил менеджер — бот замолкает» при этом железное: читать можно,
писать нельзя. И стадию карточки трогать нельзя тоже — её ведёт человек (решение 16.07).

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
import asyncio

import pytest

from app.channels.base import Message
from app.core import flags
from app.core.orchestrator import Orchestrator
from app.core.state import state_store
from app.integrations.panel import store as ps

BOT = "frunze_tours"


class FakeChannel:
    channel = "telegram"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    async def parse(self, raw):  # pragma: no cover
        ...

    async def send(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    ps._memory_store._conv.clear()
    flags.reset()
    run(flags.set_flag("facts_when_silent_enabled", True))
    yield
    flags.reset()


def _intercepted(user_id: str, funnel: str = "tours", stage: str = "greeting"):
    state = run(state_store.load(user_id))
    state.funnel = funnel
    state.intercepted = True
    state.stage = stage
    state.bot_id = BOT
    run(state_store.save(state))
    store = ps.get_conversation_store()
    run(store.ensure(user_id, bot_id=BOT))
    run(store.update_meta(user_id, funnel=funnel, stage=stage, intercepted=True))
    return state, store


def _say(channel, user_id, text):
    run(Orchestrator(channel=channel).handle(
        Message(channel="telegram", user_id=user_id, chat_id="42", text=text)))


# --- главное: читаем, но молчим ---------------------------------------------------------

def test_facts_are_absorbed_while_the_bot_stays_silent():
    channel = FakeChannel()
    _, store = _intercepted("silent-1")
    _say(channel, "silent-1", "Хотели тур на двоих в Турцию с 7 по 14 октября")
    conv = run(store.get("silent-1"))
    assert channel.sent == [], "бот не имеет права писать клиенту при перехвате"
    assert (conv.qualification or {}).get("destination") == "Турция"
    assert str((conv.qualification or {}).get("tourists")) == "2"


def test_stage_is_not_moved_by_silent_reading():
    """Стадию ведёт человек. Заполнение анкеты не имеет права тащить карточку."""
    channel = FakeChannel()
    _, store = _intercepted("silent-2", stage="office")
    _say(channel, "silent-2", "Хотели тур на двоих в Турцию с 7 по 14 октября")
    assert run(store.get("silent-2")).stage == "office"


def test_flag_off_changes_nothing():
    run(flags.set_flag("facts_when_silent_enabled", False))
    channel = FakeChannel()
    _, store = _intercepted("silent-3")
    _say(channel, "silent-3", "Хотели тур на двоих в Турцию с 7 по 14 октября")
    assert not (run(store.get("silent-3")).qualification or {})
    assert channel.sent == []


def test_visa_dialog_is_not_touched():
    """Только туры: у виз своя анкета и свой смысл полей."""
    channel = FakeChannel()
    _, store = _intercepted("silent-4", funnel="visa")
    _say(channel, "silent-4", "Хотели тур на двоих в Турцию с 7 по 14 октября")
    assert not (run(store.get("silent-4")).qualification or {})


def test_known_facts_are_not_lost():
    channel = FakeChannel()
    _, store = _intercepted("silent-5")
    run(store.update_meta("silent-5", qualification={"budget": "1500 USD"}))
    _say(channel, "silent-5", "Давайте всё-таки Анталью")
    q = run(store.get("silent-5")).qualification or {}
    assert q.get("budget") == "1500 USD"
    assert q.get("region") == "Анталья"


def test_broken_parser_does_not_break_the_turn(monkeypatch):
    from app.agent import facts

    def boom(_text):
        raise RuntimeError("разбор упал")

    monkeypatch.setattr(facts, "extract", boom)
    channel = FakeChannel()
    _intercepted("silent-6")
    _say(channel, "silent-6", "Турция на двоих")   # не должно поднять исключение
    assert channel.sent == []
