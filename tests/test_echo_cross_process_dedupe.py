"""Эхо ответа, отправленного ДРУГИМ процессом (CRM на данных бота), не пишется второй раз.

`is_own` живёт в памяти процесса, а отправка из crm.frunzetravel.kg идёт из отдельного
контейнера: бот её id не знает. Вторая защита `_is_bot_echo` сравнивает только с репликами
бота. Без этой проверки каждое сообщение менеджера из CRM появлялось бы в истории дважды
и дважды уходило бы в Bitrix (предаудит B1, блокер B4, 14.10.2026).
"""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app.main as main
from app.integrations.panel import store as panel_store
from tests.test_manager_echo_capture import BOT_ID, PHONE, _echo, _wire, _wrapped

KEY = f"{BOT_ID}:{PHONE}"


def _store():
    return panel_store.get_conversation_store()


def _crm_wrote(text: str, provider_id: str, *, age: timedelta = timedelta(0)) -> None:
    """Так пишет панель CRM: pending, затем sent с id провайдера."""
    store = _store()
    mid = asyncio.run(store.add_message(KEY, "manager", text, channel="whatsapp", bot_id=BOT_ID,
                                        chat_id=f"{PHONE}@c.us", status="pending", phone=PHONE))
    if provider_id:
        asyncio.run(store.mark_message_status(message_id=mid, status="sent",
                                              set_provider_msg_id=provider_id))
    if age:
        conv = asyncio.run(store.get(KEY))
        for m in panel_store._memory_store._conv[KEY].messages:
            if m.id == mid:
                m.created_at = datetime.now(timezone.utc) - age
        assert conv is not None


def _mirror_calls(monkeypatch):
    calls = []
    from app.integrations.crm import bitrix_mirror
    monkeypatch.setattr(bitrix_mirror, "fire", lambda *a, **k: calls.append((a, k)))
    return calls


def _manager_texts():
    conv = asyncio.run(_store().get(KEY))
    return [m.text for m in conv.messages if m.sender == "manager"]


def test_echo_of_message_saved_by_other_process_is_skipped(monkeypatch):
    _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    mirror = _mirror_calls(monkeypatch)
    _crm_wrote("ваш паспорт готов", "wappi-777")

    resp = TestClient(main.app).post("/webhook/wappi",
                                     json=_wrapped(_echo(msg_id="wappi-777", body="ваш паспорт готов")))

    assert resp.status_code == 200
    assert _manager_texts() == ["ваш паспорт готов"]
    assert mirror == []


def test_echo_racing_ahead_of_provider_id_is_skipped(monkeypatch):
    """Эхо пришло раньше, чем CRM записала id провайдера: сообщение ещё pending."""
    _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    _crm_wrote("запись на 21 октября", "")

    TestClient(main.app).post("/webhook/wappi",
                              json=_wrapped(_echo(msg_id="wappi-778", body="запись  на 21 октября")))

    assert _manager_texts() == ["запись на 21 октября"]


def test_same_text_long_ago_is_still_a_new_manager_reply(monkeypatch):
    """Менеджер повторил свою же фразу через сутки — это новое сообщение."""
    _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    _crm_wrote("добрый день", "", age=timedelta(days=1))

    TestClient(main.app).post("/webhook/wappi",
                              json=_wrapped(_echo(msg_id="wappi-779", body="добрый день")))

    assert _manager_texts() == ["добрый день", "добрый день"]


def test_different_text_from_phone_is_recorded(monkeypatch):
    """Ответ с телефона или из Bitrix (нет в базе) пишется, как раньше."""
    _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    _crm_wrote("ваш паспорт готов", "wappi-777")

    TestClient(main.app).post("/webhook/wappi",
                              json=_wrapped(_echo(msg_id="wappi-780", body="заберите в 15:00")))

    assert _manager_texts() == ["ваш паспорт готов", "заберите в 15:00"]


def test_failed_crm_row_does_not_swallow_phone_reply_with_same_text(monkeypatch):
    """CRM не смогла отправить (failed) — менеджер отправил тот же текст с телефона. Это
    настоящий ответ клиенту: он обязан появиться в панели и уйти в Bitrix."""
    _wire(monkeypatch)
    monkeypatch.setattr(main.settings, "capture_manager_echo", True)
    mirror = _mirror_calls(monkeypatch)
    store = _store()
    mid = asyncio.run(store.add_message(KEY, "manager", "ваш паспорт готов", channel="whatsapp",
                                        bot_id=BOT_ID, chat_id=f"{PHONE}@c.us", status="pending",
                                        phone=PHONE))
    asyncio.run(store.mark_message_status(message_id=mid, status="failed"))

    TestClient(main.app).post("/webhook/wappi",
                              json=_wrapped(_echo(msg_id="wappi-781", body="ваш паспорт готов")))

    assert _manager_texts() == ["ваш паспорт готов", "ваш паспорт готов"]
    assert len(mirror) == 1
