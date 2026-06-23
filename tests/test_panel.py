"""Тесты админ-панели: лог диалогов (store), логирование оркестратором,
перехват (бот замолкает), эндпоинты доски + авторизация.
"""
import asyncio

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.main as main
from app.channels.base import Message
from app.config import BotConfig
from app.core.orchestrator import Orchestrator
from app.integrations.crm.db import init_models
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import PostgresConversationStore


def _clear_memory():
    """Очистить процесс-глобальные in-memory стораджи между тестами."""
    panel_store._memory_store._conv.clear()
    from app.core.state import state_store
    state_store._store.clear()


class _FakeChannel:
    channel = "whatsapp"

    def __init__(self):
        self.sent = []

    async def send(self, chat_id, text, **kw):
        self.sent.append((chat_id, text))


def _msg(user_id, text):
    return Message(channel="whatsapp", user_id=user_id, chat_id=user_id, text=text)


# ---------------- store (Postgres на SQLite) ----------------
def test_postgres_conversation_store_round_trip():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://",
                                     connect_args={"check_same_thread": False}, poolclass=StaticPool)
        await init_models(engine)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        store = PostgresConversationStore(sessionmaker=sm)

        await store.add_message("996700111", "client", "виза в США", channel="whatsapp", bot_id="getvisa")
        await store.update_meta("996700111", funnel="visa", stage="qualification",
                                qualification={"name": "Саодат"})
        await store.add_message("996700111", "bot", "Как могу к вам обращаться?")

        cards = await store.list_cards("visa")
        assert len(cards) == 1
        assert cards[0].user_id == "996700111"
        assert cards[0].last_text == "Как могу к вам обращаться?"
        assert cards[0].qualification["name"] == "Саодат"

        conv = await store.get("996700111")
        assert [m.sender for m in conv.messages] == ["client", "bot"]
        assert conv.last_sender == "bot"  # последним писал бот
        await engine.dispose()

    asyncio.run(scenario())


def test_card_model_flags_client_waiting():
    """Карточка с последней репликой клиента → сигнал ожидания (waiting)."""
    from datetime import datetime, timedelta, timezone
    from app.admin.router import _card_model
    from app.integrations.panel.store import ConversationView

    now = datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc)
    conv = ConversationView(user_id="996700777", funnel="visa", stage="qualification",
                            qualification={"name": "Айгуль"}, last_sender="client",
                            last_text="а виза за сколько дней?",
                            last_message_at=now - timedelta(minutes=25))
    m = _card_model(conv, now)
    assert m["initials"] == "АЙ"
    assert m["wait_level"] == "hot"       # ждёт 25 мин (> 20)
    assert "мин" in m["wait_label"]
    assert m["last_sender"] == "client"


def test_board_maps_follow_up_stage():
    """Follow-up is its own column: these leads need a repeat touch, not a fresh greeting."""
    from datetime import datetime, timezone
    from app.admin.router import _build_board
    from app.integrations.panel.store import ConversationView

    conv = ConversationView(user_id="996700888", funnel="visa", stage="follow_up")
    columns, _ = _build_board([conv], datetime(2026, 6, 22, 12, 0, tzinfo=timezone.utc))

    follow_up = next(c for c in columns if c["key"] == "follow_up")
    assert follow_up["cards"][0]["user_id"] == "996700888"


# ---------------- логирование оркестратором ----------------
def test_orchestrator_logs_client_and_bot(monkeypatch):
    _clear_memory()
    monkeypatch.setattr("app.agent.llm.settings.openrouter_api_key", "")
    ch = _FakeChannel()
    bot = BotConfig(id="frunze_tours_1", scenario="tours")
    asyncio.run(Orchestrator(channel=ch, bot=bot).handle(_msg("u-log-1", "хочу тур")))

    conv = asyncio.run(panel_store.get_conversation_store().get("u-log-1"))
    assert conv is not None
    assert conv.funnel == "tours"
    assert [m.sender for m in conv.messages] == ["client", "bot"]
    assert conv.messages[0].text == "хочу тур"
    assert "Лид на тур" in conv.ai_summary
    assert conv.manager_next_step
    assert conv.lead_temperature in {"new", "warm", "hot"}
    assert ch.sent  # бот ответил


# ---------------- перехват глушит бота ----------------
def test_takeover_mutes_bot_but_logs_client(monkeypatch):
    _clear_memory()
    monkeypatch.setattr("app.agent.llm.settings.openrouter_api_key", "")
    ch = _FakeChannel()
    orch = Orchestrator(channel=ch, bot=BotConfig(id="frunze_tours_1", scenario="tours"))

    asyncio.run(orch.handle(_msg("u-int-1", "здравствуйте")))
    assert len(ch.sent) == 1  # бот ответил на первое

    # Менеджер перехватывает.
    from app.admin.router import _set_intercept
    asyncio.run(_set_intercept("u-int-1", True))

    asyncio.run(orch.handle(_msg("u-int-1", "второе сообщение")))
    assert len(ch.sent) == 1  # бот молчит — нового ответа нет

    conv = asyncio.run(panel_store.get_conversation_store().get("u-int-1"))
    # Но входящее клиента залогировано (менеджер должен видеть).
    assert conv.messages[-1].text == "второе сообщение"
    assert conv.messages[-1].sender == "client"
    assert conv.intercepted is True


# ---------------- эндпоинты доски + авторизация ----------------
def test_board_requires_auth():
    client = TestClient(main.app)
    assert client.get("/admin/board/visa").status_code == 401


def test_board_renders_card_with_auth(monkeypatch):
    _clear_memory()
    store = panel_store.get_conversation_store()
    asyncio.run(store.add_message("996700222", "client", "виза в Канаду", channel="whatsapp"))
    asyncio.run(store.update_meta("996700222", funnel="visa", stage="qualification",
                                  qualification={"name": "Адам"}))

    client = TestClient(main.app)
    resp = client.get("/admin/board/visa", auth=("admin", "frunze"))
    assert resp.status_code == 200
    assert "996700222" in resp.text
    assert "Адам" in resp.text
    assert "Квалификация" in resp.text  # колонка канбана


# ---------------- ответ менеджера из панели (двусторонняя отправка) ----------------
def test_manager_send_replies_and_takes_over(monkeypatch):
    _clear_memory()
    store = panel_store.get_conversation_store()
    asyncio.run(store.add_message("996700333", "client", "здравствуйте", channel="whatsapp",
                                  bot_id="getvisa", chat_id="996700333@c.us"))

    sent = []
    async def fake_send(channel, bot_id, chat_id, text):
        sent.append((channel, bot_id, chat_id, text))
    monkeypatch.setattr("app.channels.outbound.send_to_client", fake_send)

    client = TestClient(main.app)
    resp = client.post("/admin/conversation/996700333/send",
                       data={"text": "Это менеджер Медина, помогу вам"}, auth=("admin", "frunze"))
    assert resp.status_code == 200

    # Адаптер вызван с правильным адресом ответа (chat_id, не user_id).
    assert sent == [("whatsapp", "getvisa", "996700333@c.us", "Это менеджер Медина, помогу вам")]

    conv = asyncio.run(store.get("996700333"))
    assert conv.messages[-1].sender == "manager"
    assert conv.messages[-1].text == "Это менеджер Медина, помогу вам"
    assert conv.intercepted is True  # ручная отправка перехватила диалог


def test_conversation_renders_manager_brief(monkeypatch):
    _clear_memory()
    store = panel_store.get_conversation_store()
    asyncio.run(store.add_message("996700444", "client", "хочу визу в США", channel="whatsapp"))
    asyncio.run(store.update_meta(
        "996700444",
        funnel="visa",
        stage="office",
        qualification={"name": "Алия", "country": "США"},
        ai_summary="Визовый лид. Уже собрано: имя: Алия; страна: США.",
        manager_next_step="Согласовать консультацию в офисе.",
        escalation_reason="Бот ведет клиента к консультации.",
        lead_temperature="warm",
    ))

    client = TestClient(main.app)
    resp = client.get("/admin/conversation/996700444", auth=("admin", "frunze"))

    assert resp.status_code == 200
    assert "AI для менеджера" in resp.text
    assert "Согласовать консультацию" in resp.text
    assert "тёплый" in resp.text


def test_manager_brief_marks_hot_payment_signal():
    from app.core.manager_brief import build_manager_brief
    from app.core.state import DialogState

    state = DialogState(
        user_id="hot-1",
        funnel="tours",
        stage="qualification",
        history=[{"role": "user", "content": "можете бронировать, готов оплатить"}],
    )

    brief = build_manager_brief(state)

    assert brief["lead_temperature"] == "hot"
    assert "Горячий клиент" in brief["manager_next_step"]
    assert "готовность" in brief["escalation_reason"]
