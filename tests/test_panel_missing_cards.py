"""Экран «нет карточки в Bitrix»: диалоги, которые остались только у нас.

Зачем он есть. Карточка в портале создаётся зеркалом по ходу разговора, и она НЕ
появляется, когда зеркало выключено, портал ответил отказом (ночные 403) или бот молчал
из-за внешнего сбоя. Замер прода 21.10.2026: **811 диалогов без карточки, 355 из них не в
архиве, 343 с настоящим разговором**. При переносе учёта такой клиент теряется бесследно,
поэтому номера надо видеть и уметь забрать файлом.

Экран только читает. В Bitrix он ничего не создаёт — это принципиально: Гриша попросил
«сохранить номера», а не «досоздать карточки», и массовое создание лидов в портале
задним числом ударило бы по очереди Открытых линий.
"""
import asyncio

from fastapi.testclient import TestClient

import app.config
import app.main as main
from app.config import ManagerConfig
from app.integrations.panel import store as panel_store
from app.integrations.panel.store import get_conversation_store

FLAG = "panel_missing_cards_enabled"
NO_CARD = ("getvisa:996700000011", "getvisa:996700000012")
WITH_CARD = "getvisa:996700000013"
TOURS_NO_CARD = "frunze_tours:996700000021"


def _clear():
    panel_store._memory_store._conv.clear()
    panel_store._memory_store._audit.clear()
    from app.core import flags
    flags.reset()


def _managers(monkeypatch):
    """Админ и визовый менеджер: второй нужен для проверки скоупа."""
    monkeypatch.setattr(app.config.settings, "managers", [
        ManagerConfig(login="admin", name="Админ", password="frunze", admin=True),
        ManagerConfig(login="grisha", name="Гриша", password="visa-only", admin=False),
    ], raising=False)


def _on(monkeypatch, value=True):
    monkeypatch.setattr(app.config.settings, FLAG, value, raising=False)


def _seed():
    """Два визовых диалога без карточки, один с карточкой, один туровый без карточки."""
    store = get_conversation_store()

    async def _s():
        for user in NO_CARD:
            await store.add_message(user, "client", "здравствуйте, нужна виза",
                                    channel="whatsapp", bot_id="getvisa",
                                    phone=user.split(":")[1])
            await store.update_meta(user, funnel="visa")
        await store.add_message(WITH_CARD, "client", "виза в США", channel="whatsapp",
                                bot_id="getvisa", phone=WITH_CARD.split(":")[1])
        await store.update_meta(WITH_CARD, funnel="visa", bitrix_lead_id="4455")
        await store.add_message(TOURS_NO_CARD, "client", "хочу тур", channel="whatsapp",
                                bot_id="frunze_tours", phone=TOURS_NO_CARD.split(":")[1])
        await store.update_meta(TOURS_NO_CARD, funnel="tours")
    asyncio.run(_s())


def _login(login="admin", password="frunze"):
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login",
                       data={"login": login, "password": password}).status_code == 200
    return client


# --- A. Что экран показывает ---------------------------------------------------

def test_lists_only_dialogs_without_a_card(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch); _seed()
    body = _login().get("/admin/no-card").text
    assert "996700000011" in body and "996700000012" in body
    # Диалог с карточкой в списке не нужен: его не потеряли.
    assert "996700000013" not in body


def test_screen_does_not_write_to_bitrix(monkeypatch):
    """Ни одного обращения к порталу: экран читающий, иначе он создаст лиды задним числом."""
    _clear(); _managers(monkeypatch); _on(monkeypatch); _seed()
    calls = []
    import app.integrations.crm.bitrix_mirror as mirror
    monkeypatch.setattr(mirror, "fire", lambda *a, **k: calls.append(a), raising=False)
    assert _login().get("/admin/no-card").status_code == 200
    assert calls == []


# --- B. Выгрузка ---------------------------------------------------------------

def test_csv_carries_numbers_with_bom_and_is_audited(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch); _seed()
    resp = _login().get("/admin/no-card.csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]
    # BOM обязателен: без него Excel в русской Windows ломает кириллицу.
    assert resp.text.startswith("﻿")
    assert "996700000011" in resp.text and "996700000013" not in resp.text
    assert any(a["action"] == "export" and "no_card_csv" in (a.get("detail") or "")
               for a in panel_store._memory_store._audit), "выгрузка не записана в аудит"


# --- C. Флаг ------------------------------------------------------------------

def test_flag_off_hides_screen_export_and_link(monkeypatch):
    """Дефолт OFF: пока не включили, экрана не существует и ссылки на него нет."""
    _clear(); _managers(monkeypatch); _on(monkeypatch, False); _seed()
    client = _login()
    assert client.get("/admin/no-card").status_code == 404
    assert client.get("/admin/no-card.csv").status_code == 404
    assert "/admin/no-card" not in client.get("/admin").text


def test_flag_on_shows_link_in_navigation(monkeypatch):
    _clear(); _managers(monkeypatch); _on(monkeypatch); _seed()
    assert "/admin/no-card" in _login().get("/admin").text


# --- D. Права -----------------------------------------------------------------

def test_manager_sees_only_his_direction(monkeypatch):
    """Скоуп менеджера действует и здесь, иначе экран стал бы обходом прав.

    Ровно эту ошибку независимый аудит нашёл 21.10 в календаре: задачи фильтровались по
    владельцу, а данные карточки брались из диалога без проверки доступа.
    """
    _clear(); _managers(monkeypatch); _on(monkeypatch); _seed()
    body = _login("grisha", "visa-only").get("/admin/no-card").text
    assert "996700000011" in body
    assert "996700000021" not in body, "визовый менеджер увидел туровый номер"


def test_csv_respects_the_same_scope(monkeypatch):
    """Выгрузка — тот же список: иначе файл станет дырой в правах."""
    _clear(); _managers(monkeypatch); _on(monkeypatch); _seed()
    text = _login("grisha", "visa-only").get("/admin/no-card.csv").text
    assert "996700000011" in text
    assert "996700000021" not in text
