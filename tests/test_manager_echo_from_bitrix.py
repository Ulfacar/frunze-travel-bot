"""ГЕЙТ: ответы менеджера ИЗ БИТРИКСА доходят до нашей панели, а бот не глушит сам себя.

Написан ДО правки, исполнителем не редактируется.

## Что нашли 11.08

Замер: за 14 дней у визового канала 36 сообщений менеджеров против 845 и 732 у туровых —
при том, что клиентских сообщений столько же. Причина: туровые отвечают с телефона
(`outgoing_message_phone`, слушаем), а визовые пишут из Контакт-центра Битрикса.

Поддержка Wappi 11.08 дословно: ответ оператора идёт по цепочке «Открытая линия Bitrix24 →
Wappi API → WhatsApp → ваш webhook», тип события — **`outgoing_message_api`**.

А у нас в `wappi.py` стояло: «Тип `outgoing_message_api` СОЗНАТЕЛЬНО не слушаем: это эхо
отправок самого бота». Под одним типом смешаны две разные вещи, и мы отбросили обе.

## Чем это опасно включить наивно

Ответ менеджера в панели означает, что человек вмешался. Если бот примет СВОЮ реплику за
ответ менеджера, он сам себя перехватит и замолчит на этом клиенте. Защита `is_own` живёт
15 минут и только в памяти процесса — после рестарта или задержки эха она не спасёт.

Поэтому вторая линия обороны: сверка с последними репликами бота в этом же диалоге. Совпал
текст — это наше эхо, а не менеджер.
"""
from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

import app.main as main
from app.config import BotConfig
from app.core.orchestrator import Orchestrator
from app.core.own_outbound import _reset_for_tests, mark_own
from app.channels.wappi import WappiAdapter, is_outgoing_echo
from app.core.state import state_store
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

PROFILE = "echo-api-profile"
BOT_ID = "getvisa"
PHONE = "996500494009"
KEY = f"{BOT_ID}:{PHONE}"


def _clear() -> None:
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    panel_store._memory_store._mid = 0
    state_store._store.clear()
    main._seen_wappi_ids.clear()
    _reset_for_tests()


def _api_echo(msg_id="api-echo-1", body="Здравствуйте, отправила вам подборку") -> dict:
    """Ровно та форма, что описала поддержка: ответ оператора из Битрикса."""
    return {
        "id": msg_id,
        "profile_id": PROFILE,
        "wh_type": "outgoing_message_api",
        "body": body,
        "type": "chat",
        "from": "996706660009@c.us",
        "to": f"{PHONE}@c.us",
        "chatId": f"{PHONE}@c.us",
        "is_me": True,
        "chat_type": "dialog",
    }


def _install_bot(monkeypatch):
    """Приём эха живёт за флагом `capture_manager_echo` (на проде включён)."""
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    bot = BotConfig(id=BOT_ID, scenario="visa", wappi_profile_id=PROFILE)
    monkeypatch.setitem(main._wappi_orchestrators, PROFILE,
                        Orchestrator(channel=WappiAdapter(bot=bot), bot=bot))


def _post(payload: dict) -> None:
    """Wappi шлёт события пачкой: {"messages": [...]}."""
    with TestClient(main.app) as client:
        client.post("/webhook/wappi", json={"messages": [payload]})


def _messages() -> list:
    async def _get():
        return (await get_conversation_store().get(KEY)) or None
    conv = asyncio.run(_get())
    return list(getattr(conv, "messages", []) or []) if conv else []


def _seed_bot_reply(text: str) -> None:
    async def _add():
        await get_conversation_store().add_message(KEY, "bot", text, channel="whatsapp",
                                                   bot_id=BOT_ID)
    asyncio.run(_add())


# --- главное: ответ менеджера из Битрикса виден у нас -----------------------------

def test_api_echo_is_recognised_as_echo():
    assert is_outgoing_echo(_api_echo()) is True


def test_manager_reply_from_bitrix_lands_in_panel(monkeypatch):
    _clear()
    _install_bot(monkeypatch)
    _post(_api_echo(body="Добрый день! Виза США делается 3 недели"))
    senders = [(m.sender, m.text) for m in _messages()]
    assert ("manager", "Добрый день! Виза США делается 3 недели") in senders


# --- защита: бот не должен принять свою реплику за менеджера ------------------------

def test_own_message_by_id_is_ignored(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: id помечен как наш — это эхо бота, не менеджер."""
    _clear()
    _install_bot(monkeypatch)
    mark_own("api-echo-own")
    _post(_api_echo(msg_id="api-echo-own", body="Здравствуйте! Я Медина, ваш визовый эксперт"))
    assert [m for m in _messages() if m.sender == "manager"] == []


def test_own_message_by_text_is_ignored_after_restart(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ И САМЫЙ ВАЖНЫЙ.

    Рестарт стёр память `is_own`, эхо пришло позже. Без сверки по тексту бот записал бы
    собственную реплику как ответ менеджера и заглушил бы себя на этом клиенте.
    """
    _clear()
    _install_bot(monkeypatch)
    reply = "Здравствуйте! Я Медина, ваш личный визовый эксперт Frunze Travel"
    _seed_bot_reply(reply)
    _post(_api_echo(msg_id="api-echo-after-restart", body=reply))
    assert [m for m in _messages() if m.sender == "manager"] == []


def test_similar_but_different_text_is_a_manager(monkeypatch):
    """Похожая, но другая фраза — это человек. Глушить её нельзя."""
    _clear()
    _install_bot(monkeypatch)
    _seed_bot_reply("Здравствуйте! Я Медина, ваш личный визовый эксперт Frunze Travel")
    _post(_api_echo(body="Здравствуйте! Это Медина, подскажу по срокам"))
    assert [m.text for m in _messages() if m.sender == "manager"] == [
        "Здравствуйте! Это Медина, подскажу по срокам"]


# --- прежнее поведение не тронуто ---------------------------------------------------

def test_phone_echo_still_works(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: ответы туровых с телефона как работали, так и работают."""
    _clear()
    _install_bot(monkeypatch)
    raw = _api_echo(msg_id="phone-1", body="Азыр чалып коройунчу")
    raw["wh_type"] = "outgoing_message_phone"
    _post(raw)
    assert [m.text for m in _messages() if m.sender == "manager"] == ["Азыр чалып коройунчу"]


def test_group_and_reaction_are_ignored(monkeypatch):
    _clear()
    _install_bot(monkeypatch)
    group = _api_echo(msg_id="grp-1")
    group["chat_type"] = "group"
    reaction = _api_echo(msg_id="rct-1")
    reaction["type"] = "reaction"
    _post(group)
    _post(reaction)
    assert [m for m in _messages() if m.sender == "manager"] == []


def test_client_incoming_is_untouched(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: обычное входящее клиента не должно стать «менеджером»."""
    _clear()
    _install_bot(monkeypatch)
    raw = _api_echo(msg_id="in-1", body="нужна виза")
    raw.update({"wh_type": "incoming_message", "is_me": False,
                "from": f"{PHONE}@c.us", "to": "996706660009@c.us"})
    _post(raw)
    assert [m for m in _messages() if m.sender == "manager"] == []
