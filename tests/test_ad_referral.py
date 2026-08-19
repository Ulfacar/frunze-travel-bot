"""Тесты фичи «источник лида из Click-to-WhatsApp Ads» (referral):
парсер Wappi → Message.referral → персист источника в панель (write-once) →
контекстное приветствие → показ в карточке. Всё оффлайн, без сети.

⚠ Реальный JSON-формат referral от Wappi не подтверждён на живом трафике (нет в
фикстурах) — форматы ниже best-guess (Cloud API `referral` + web `externalAdReply`).
Парсер защитный: неизвестный формат → {} и фича деградирует в «как было».
"""
import asyncio

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

import app.core.orchestrator as orch
import app.main as main
from app.channels.base import Message
from app.channels.wappi import WappiAdapter, extract_ad_referral
from app.config import BotConfig
from app.core.bots import BotRegistry
from app.core.branding import ad_greeting, persona_greeting
from app.core.orchestrator import Orchestrator
from app.core.state import DialogState
from app.integrations.crm.db import init_models
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import PostgresConversationStore

PROFILE = "6a74fb33-16aa"


def _clear_memory():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core.state import state_store
    state_store._store.clear()
    from app.core import flags
    flags.reset()


def _incoming(body="здравствуйте", referral=None, extra=None):
    ev = {
        "wh_type": "incoming_message",
        "profile_id": PROFILE,
        "id": "msg-ad-1",
        "body": body,
        "type": "chat",
        "from": "996700123456@c.us",
        "chatId": "996700123456@c.us",
        "senderName": "Клиент",
        "is_me": False,
        "chat_type": "dialog",
    }
    if referral is not None:
        ev["referral"] = referral
    if extra:
        ev.update(extra)
    return ev


_CLOUD_REFERRAL = {
    "source_type": "ad",
    "source_id": "123456789",
    "source_url": "https://fb.me/abcd",
    "ctwa_clid": "clid-xyz",
    "headline": "Тур в Дубай 5 ночей всё включено",
    "body": "От 800$ на двоих, вылет из Бишкека",
    "media_type": "image",
}


# ---------------- парсер ----------------
def test_extract_referral_cloud_api_format():
    out = extract_ad_referral({"referral": _CLOUD_REFERRAL})
    assert out["source_type"] == "ad"
    assert out["source_id"] == "123456789"
    assert out["ctwa_clid"] == "clid-xyz"
    assert out["headline"].startswith("Тур в Дубай")
    assert out["source_url"] == "https://fb.me/abcd"


def test_extract_referral_camelcase_nested_external_ad_reply():
    raw = {"contextInfo": {"externalAdReply": {
        "sourceId": "ad-99", "sourceUrl": "https://instagram.com/p/x",
        "title": "Виза в США под ключ", "sourceType": "ad"}}}
    out = extract_ad_referral(raw)
    assert out["source_id"] == "ad-99"
    assert out["headline"] == "Виза в США под ключ"
    assert out["source_type"] == "ad"


def test_extract_referral_absent_or_garbage():
    assert extract_ad_referral(_incoming()) == {}          # обычное сообщение
    assert extract_ad_referral({"referral": "строка"}) == {}
    assert extract_ad_referral({"referral": {}}) == {}
    assert extract_ad_referral({"referral": {"foo": 1}}) == {}   # нет опознавательных полей
    assert extract_ad_referral("не dict") == {}
    assert extract_ad_referral({"contextInfo": "плохо"}) == {}


def test_extract_referral_truncates_long_fields():
    out = extract_ad_referral({"referral": {"source_id": "x", "headline": "д" * 999}})
    assert len(out["headline"]) <= 300


def test_parse_sets_message_referral():
    ad = asyncio.run(WappiAdapter().parse(_incoming(referral=_CLOUD_REFERRAL)))
    assert ad.referral and ad.referral["source_id"] == "123456789"
    plain = asyncio.run(WappiAdapter().parse(_incoming()))
    assert plain.referral == {}


def test_parse_referral_on_media_message():
    """Рекламный клик может прийти с картинкой объявления (non_text) — referral всё равно ловим."""
    msg = asyncio.run(WappiAdapter().parse(_incoming(body="", referral=_CLOUD_REFERRAL,
                                                     extra={"type": "image"})))
    assert msg.kind == "non_text"
    assert msg.referral["source_id"] == "123456789"


# ---------------- персист источника в панель (write-once) ----------------
def test_orchestrator_persists_source_to_panel_write_once():
    _clear_memory()
    bot = BotConfig(id="frunze_tours", scenario="tours")
    orc = Orchestrator(channel=None, bot=bot)
    msg = Message(channel="whatsapp", user_id="996700123456", chat_id="996700123456@c.us",
                  text="здравствуйте", referral=_CLOUD_REFERRAL)
    asyncio.run(orc._log_in(msg, msg.text))

    conv = asyncio.run(panel_store._memory_store.get("frunze_tours:996700123456"))
    assert conv.source == "ad"
    assert conv.source_headline.startswith("Тур в Дубай")
    assert conv.source_id == "123456789"

    # Второе касание с другим объявлением НЕ перетирает первое (write-once).
    msg2 = Message(channel="whatsapp", user_id="996700123456", chat_id="996700123456@c.us",
                   text="ещё вопрос", referral={"source_id": "999", "headline": "Другой оффер"})
    asyncio.run(orc._log_in(msg2, msg2.text))
    conv2 = asyncio.run(panel_store._memory_store.get("frunze_tours:996700123456"))
    assert conv2.source_id == "123456789"  # осталось первое касание


def test_post_source_type_maps_to_post():
    _clear_memory()
    bot = BotConfig(id="frunze_tours", scenario="tours")
    orc = Orchestrator(channel=None, bot=bot)
    msg = Message(channel="whatsapp", user_id="u-post", chat_id="c",
                  text="hi", referral={"source_type": "post", "source_id": "p1", "headline": "Пост"})
    asyncio.run(orc._log_in(msg, msg.text))
    conv = asyncio.run(panel_store._memory_store.get("frunze_tours:u-post"))
    assert conv.source == "post"


# ---------------- store roundtrip на SQLite (Postgres-бэкенд) ----------------
def test_store_source_roundtrip_sqlite_and_write_once():
    async def scenario():
        engine = create_async_engine("sqlite+aiosqlite://",
                                     connect_args={"check_same_thread": False}, poolclass=StaticPool)
        await init_models(engine)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        store = PostgresConversationStore(sessionmaker=sm)

        await store.add_message("frunze_tours:996700999", "client", "здравствуйте",
                                channel="whatsapp", bot_id="frunze_tours")
        await store.update_meta("frunze_tours:996700999", funnel="tours",
                                source="ad", source_id="A1", source_headline="Тур в Турцию",
                                source_url="https://fb.me/z", source_payload=_CLOUD_REFERRAL)
        # write-once: повторный источник не перетирает
        await store.update_meta("frunze_tours:996700999", source="ad", source_id="A2",
                                source_headline="Другое")

        conv = await store.get("frunze_tours:996700999")
        assert conv.source == "ad"
        assert conv.source_id == "A1"
        assert conv.source_headline == "Тур в Турцию"
        assert conv.source_payload["ctwa_clid"] == "clid-xyz"

        cards = await store.list_cards("tours")
        assert cards[0].source == "ad"

    asyncio.run(scenario())


def test_old_conversation_without_source_is_safe():
    """Диалог без источника: _view/get отдаёт пустой source, карточка не падает."""
    from datetime import datetime, timezone
    from app.admin.router import _card_model
    _clear_memory()
    conv = asyncio.run(panel_store._memory_store.ensure("frunze_tours:u-old", bot_id="frunze_tours"))
    assert conv.source == ""
    card = _card_model(conv, datetime.now(timezone.utc))
    assert card["source"] == ""
    assert card["source_headline"] == ""


# ---------------- контекстное приветствие ----------------
def test_ad_greeting_uses_headline_and_falls_back():
    g = ad_greeting("tours", "Адеми", "Тур в Дубай всё включено")
    assert g and "Дубай" in g and "Адеми" in g
    # Нет заголовка → None (fallback на обычное персона-приветствие)
    assert ad_greeting("tours", "Адеми", "") is None
    assert ad_greeting("tours", "Адеми", "   ") is None
    # visa/tickets тоже дают контекст
    assert "визовый" in ad_greeting("visa", "Медина", "Виза в США").lower()
    assert ad_greeting("tickets", "Адеми", "Билеты в Дубай") is not None


def test_maybe_persona_greeting_uses_ad_greeting(monkeypatch):
    sent = []

    async def fake_reply(self, msg, text):
        sent.append(text)

    async def fake_sync(self, msg, state):
        pass

    monkeypatch.setattr(Orchestrator, "_reply", fake_reply)
    monkeypatch.setattr(Orchestrator, "_sync_card", fake_sync)

    class FakeStore:
        async def save(self, state):
            pass

    state = DialogState(user_id="u-ad", funnel="tours", manager_name="Адеми",
                        ad_referral={"headline": "Тур в Дубай"})
    msg = Message(channel="whatsapp", user_id="u-ad", chat_id="c", text="здравствуйте")
    handled = asyncio.run(Orchestrator(channel=None)._maybe_persona_greeting(msg, state, FakeStore()))
    assert handled is True
    assert "Дубай" in sent[0]
    # без referral — обычное приветствие
    assert "Дубай" not in persona_greeting("tours", "Адеми")


# ---------------- LLM-контекст рекламы ----------------
def test_ad_context_message_for_runner():
    from app.agent.runner import _ad_context_message
    assert _ad_context_message({}) is None
    m = _ad_context_message({"headline": "Тур в Дубай", "body": "от 800$"})
    assert m["role"] == "user"
    assert "Дубай" in m["content"] and "рекламе" in m["content"]


# ---------------- state: толерантность к откату + roundtrip ----------------
def test_dialogstate_from_json_tolerates_unknown_and_roundtrips_referral():
    # Незнакомый ключ (например после отката прода) не роняет load.
    st = DialogState.from_json('{"user_id":"u","some_future_key":123}')
    assert st.user_id == "u"
    # ad_referral переживает сериализацию.
    src = DialogState(user_id="u", ad_referral={"headline": "X", "source_id": "1"})
    back = DialogState.from_json(src.to_json())
    assert back.ad_referral == {"headline": "X", "source_id": "1"}


# ---------------- e2e webhook ----------------
def _wire(monkeypatch):
    class FakeFunnel:
        async def handle(self, msg, state):
            return f"echo:{msg.text}"

    monkeypatch.setattr(orch, "get_funnel", lambda name: FakeFunnel())
    bot = BotConfig(id="frunze_tours_1", scenario="tours", wappi_profile_id=PROFILE)

    class RecordingWappi(WappiAdapter):
        def __init__(self, bot):
            super().__init__(bot=bot)
            self.sent = []

        async def send(self, chat_id, text, **kw):
            self.sent.append((chat_id, text))

    channel = RecordingWappi(bot)
    monkeypatch.setattr(main, "registry", BotRegistry([bot]))
    monkeypatch.setattr(main, "_wappi_orchestrators", {PROFILE: Orchestrator(channel=channel, bot=bot)})
    return channel


def test_webhook_ad_referral_persisted_e2e(monkeypatch):
    _clear_memory()
    _wire(monkeypatch)
    client = TestClient(main.app)
    resp = client.post("/webhook/wappi",
                       json={"messages": [_incoming(body="хочу тур", referral=_CLOUD_REFERRAL)]})
    assert resp.status_code == 200
    assert resp.json() == {"ok": True, "handled": 1}
    conv = asyncio.run(panel_store._memory_store.get("frunze_tours_1:996700123456"))
    assert conv.source == "ad"
    assert conv.source_headline.startswith("Тур в Дубай")


# --- Источник из ТЕКСТА сообщения (19.08.2026) ------------------------------------------
#
# Замер прода: `source` пуст у ВСЕХ 1107 диалогов за 30 дней — payload Wappi рекламных полей
# так и не прислал. При этом 168 клиентских сообщений за тот же месяц содержат ссылку
# `fb.me`/Instagram прямо в тексте: реклама подставляет её первой строкой, когда человек
# нажимает «Написать» под объявлением. Источник приходит — просто не там, где мы ждали.

def test_referral_from_text_reads_facebook_short_link():
    from app.channels.wappi import referral_from_text

    ref = referral_from_text("https://fb.me/6hIOycVps Hello! Can I get more info on this?")

    assert ref["source_type"] == "ad"
    assert ref["source_id"] == "6hIOycVps"
    assert ref["source_url"] == "https://fb.me/6hIOycVps"


def test_referral_from_text_reads_instagram_post():
    from app.channels.wappi import referral_from_text

    ref = referral_from_text("https://www.instagram.com/p/DaSTt26MbIg/ Здравствуйте! Можете подробнее?")

    assert ref["source_type"] == "post"
    assert ref["source_id"] == "DaSTt26MbIg"


def test_referral_from_text_ignores_ordinary_text_and_foreign_links():
    from app.channels.wappi import referral_from_text

    assert referral_from_text("здравствуйте, нужна виза в Италию") == {}
    assert referral_from_text("вот отель https://booking.com/hotel/xyz") == {}
    assert referral_from_text("") == {}


def test_parse_falls_back_to_text_referral_when_payload_has_none():
    """Payload пуст — источник берём из текста; это и есть тот случай, что живёт на проде."""
    adapter = WappiAdapter()
    raw = {"chatId": "996700112233@c.us", "from": "996700112233@c.us", "type": "chat",
           "body": "https://fb.me/6hIOycVps Hello! Can I get more info on this?"}

    msg = asyncio.run(adapter.parse(raw))

    assert msg.referral.get("source_id") == "6hIOycVps"


def test_payload_referral_wins_over_text_link():
    """Настоящий CTWA-контекст богаче текстовой ссылки — он и должен победить."""
    adapter = WappiAdapter()
    raw = {"chatId": "996700112233@c.us", "from": "996700112233@c.us", "type": "chat",
           "body": "https://fb.me/6hIOycVps привет",
           "referral": {"source_id": "23851234567890", "source_url": "https://fb.com/ads/1",
                        "headline": "Визы в Европу за 14 дней"}}

    msg = asyncio.run(adapter.parse(raw))

    assert msg.referral["source_id"] == "23851234567890"
    assert msg.referral["headline"] == "Визы в Европу за 14 дней"
