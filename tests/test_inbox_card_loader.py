"""Карточный загрузчик инбокса равен полному — по решениям детекторов, а не по тексту.

Зачем этот тест. 20.10.2026 панель упёрлась в 100% CPU: `_all_models` на каждый опрос
(инбокс 10 с, счётчик 12 с, доска 15 с) грузила все диалоги вместе со всей историей —
3488 диалогов и 52 812 сообщений. Лечение — отдавать карточкам агрегат вместо истории.
Опасность лечения ровно одна: `is_noise` и `is_silent` читают историю, а на их ответах
висят массовый архив рекламы и автодожим. Поэтому здесь закреплено РАВЕНСТВО решений
на полной истории и на заглушках, а не «загрузчик что-то вернул».
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.config import settings
from app.core.leadstate import UNSEEN_MIN_CLIENT_MSGS, is_noise, is_silent
from app.integrations.panel.store import MessageView, PostgresConversationStore

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)
OLD = NOW - timedelta(days=9)


class _Stub:
    """Минимальный диалог: поля, которые читают детекторы."""

    def __init__(self, **kw):
        self.user_id = kw.get("user_id", "getvisa:996700000001")
        self.stage = kw.get("stage", "greeting")
        self.intercepted = kw.get("intercepted", False)
        self.assigned_to = kw.get("assigned_to", "")
        self.qualification = kw.get("qualification", {})
        self.last_text = kw.get("last_text", "привет")
        self.last_sender = kw.get("last_sender", "client")
        self.last_message_at = kw.get("last_message_at", OLD)
        self.outcome = kw.get("outcome", "")
        self.followup_count = kw.get("followup_count", 0)
        self.followup_sent = kw.get("followup_sent", False)
        self.messages = kw.get("messages", [])


def _msgs(clients: int, ours: int = 0, other: int = 0) -> list[MessageView]:
    out = [MessageView(sender="client", text="текст клиента") for _ in range(clients)]
    out += [MessageView(sender="bot", text="ответ бота") for _ in range(ours)]
    out += [MessageView(sender="system", text="служебное") for _ in range(other)]
    return out


def _stubs_like_loader(messages: list[MessageView]) -> list[MessageView]:
    """Ровно та свёртка, которую делает `all_conversations_for_cards` в Postgres."""
    total = len(messages)
    clients = sum(1 for m in messages if m.sender == "client")
    ours = sum(1 for m in messages if m.sender in ("bot", "manager"))
    stubs = [MessageView(sender="client", text="") for _ in range(min(clients, UNSEEN_MIN_CLIENT_MSGS))]
    if ours:
        stubs.append(MessageView(sender="bot", text=""))
    if total and not stubs:
        stubs.append(MessageView(sender="", text=""))
    return stubs


# Истории, которые ведут детекторы по разным веткам: пусто, один клиент, «ведут без нас»
# (порог UNSEEN), наша реплика, только служебные отправители, длинный разговор.
HISTORIES = [
    [],
    _msgs(1),
    _msgs(UNSEEN_MIN_CLIENT_MSGS - 1),
    _msgs(UNSEEN_MIN_CLIENT_MSGS),
    _msgs(UNSEEN_MIN_CLIENT_MSGS + 7),
    _msgs(1, ours=1),
    _msgs(UNSEEN_MIN_CLIENT_MSGS + 2, ours=3),
    _msgs(0, ours=2),
    _msgs(0, other=2),
]
CASES = [
    {},
    {"last_text": "https://instagram.com/p/Cxyz посмотрите"},
    {"last_text": "фото"},
    {"stage": "qualification"},
    {"intercepted": True},
    {"assigned_to": "medina"},
    {"qualification": {"name": "Азамат"}},
    {"last_sender": "bot"},
    {"last_message_at": NOW - timedelta(minutes=30)},
    {"outcome": "won"},
    {"followup_count": 2},
    {"followup_sent": True},
]


@pytest.mark.parametrize("history", HISTORIES)
@pytest.mark.parametrize("case", CASES)
def test_detectors_decide_the_same_on_stubs_as_on_full_history(history, case):
    full = _Stub(messages=list(history), **case)
    light = _Stub(messages=_stubs_like_loader(history), **case)
    assert is_noise(full, NOW, settings) == is_noise(light, NOW, settings), case
    assert is_silent(full, NOW, settings) == is_silent(light, NOW, settings), case


def test_loader_never_carries_message_text():
    """Текст истории в карточку не едет: инбокс отдавал 2,1 МБ на каждый опрос."""
    stubs = _stubs_like_loader(_msgs(40, ours=12))
    assert stubs and all(m.text == "" for m in stubs)
    assert len(stubs) <= UNSEEN_MIN_CLIENT_MSGS + 1


def test_postgres_store_exposes_the_card_loader():
    """Маршрут инбокса зовёт именно его — опечатка в имени уронила бы панель в рантайме."""
    assert callable(getattr(PostgresConversationStore, "all_conversations_for_cards", None))


@pytest.mark.asyncio
async def test_memory_store_card_loader_returns_live_conversations():
    from app.integrations.panel.store import MemoryConversationStore
    store = MemoryConversationStore()
    await store.add_message("getvisa:996700000001", "client", "привет", bot_id="getvisa")
    cards = await store.all_conversations_for_cards()
    assert [c.user_id for c in cards] == ["getvisa:996700000001"]


# ---------------- боевой путь: Postgres-бэкенд на SQLite ----------------
# 21.10: первый выпуск этого загрузчика упал на проде с ImportError — имя модели в
# `app.integrations.crm.db` оказалось `ConvMessage`, а не `Message`. Тесты этого не
# поймали: все они работали на MemoryConversationStore, а ветка Postgres НИ РАЗУ не
# исполнялась. Поэтому здесь метод именно ВЫЗЫВАЕТСЯ на живом движке.
@pytest.mark.asyncio
async def test_postgres_card_loader_runs_and_folds_history():
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from app.integrations.crm.db import init_models

    engine = create_async_engine("sqlite+aiosqlite://",
                                 connect_args={"check_same_thread": False}, poolclass=StaticPool)
    await init_models(engine)
    store = PostgresConversationStore(sessionmaker=async_sessionmaker(engine, expire_on_commit=False))

    # клиент пишет трижды, наших реплик нет — это «ведут без нас»
    alone = "getvisa:996700000011"
    for _ in range(UNSEEN_MIN_CLIENT_MSGS):
        await store.add_message(alone, "client", "вы работаете?", channel="whatsapp", bot_id="getvisa")
    # обычный диалог: клиент и наш ответ
    answered = "getvisa:996700000012"
    await store.add_message(answered, "client", "здравствуйте", channel="whatsapp", bot_id="getvisa")
    await store.add_message(answered, "bot", "здравствуйте, чем помочь?", channel="whatsapp", bot_id="getvisa")

    cards = {c.user_id: c for c in await store.all_conversations_for_cards()}
    assert set(cards) == {alone, answered}

    senders = lambda key: [m.sender for m in cards[key].messages]
    assert senders(alone) == ["client"] * UNSEEN_MIN_CLIENT_MSGS
    assert "bot" in senders(answered) and "client" in senders(answered)
    # текста истории в карточке нет — ради этого всё и затевалось
    assert all(m.text == "" for c in cards.values() for m in c.messages)

    full = {c.user_id: c for c in await store.all_conversations()}
    for key in cards:
        assert is_noise(cards[key], NOW, settings) == is_noise(full[key], NOW, settings), key
        assert is_silent(cards[key], NOW, settings) == is_silent(full[key], NOW, settings), key
