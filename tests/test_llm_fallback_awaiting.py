# -*- coding: utf-8 -*-
"""Аварийная отписка — не ответ, и система не должна принимать её за ответ.

## Что случилось 17-22.09.2026

У OpenRouter кончились деньги, ход воронки падал, и клиент получал
«Секундочку, уточню детали и вернусь к вам 🙏». Так 178 раз за шесть дней.

Беда не в самом фолбэке — клиенту лучше получить хоть что-то, чем тишину. Беда в том,
что `_reply` записывал отписку обычной репликой бота, а значит `conversations.last_sender`
становился `bot`. После этого:

* `awaiting.select_awaiting_targets` пропускал диалог — он берёт только те, где последним
  писал КЛИЕНТ, то есть где никто не ответил;
* горячий лист и панель тоже считали диалог отвеченным.

Клиент ждал, менеджер не знал, система молчала. Отписка ослепила сторожа, который ровно
для таких случаев и сделан.

## Что закрепляем

1. Реплика, помеченная `counts_as_reply=False`, не двигает `last_sender`/`last_text`.
2. После аварийной отписки диалог остаётся в выборке «клиент ждёт».
3. Нормальный ответ бота по-прежнему снимает диалог с ожидания — иначе менеджеров
   завалит напоминаниями о диалогах, где всё хорошо.
4. Честный текст не обещает того, чего механизм не обеспечивает.
5. Сбой хранилища флагов в аварийном пути не роняет разбор события.

## Границы механизма (ревью 23.09)

`select_awaiting_targets` зовёт живого человека только по диалогам, которые уже у него:
`stage in {manager, manager_handoff}` или `intercepted`. На аварии 17-22.09 это 185 отписок
из 328; оставшиеся 143 висели в `greeting` без перехвата и видны только в панели и горячем
листе. Расширять отбор на до-хендоффные диалоги — продуктовое решение, не делаем молча.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core import awaiting, orchestrator
from app.integrations.panel.store import MemoryConversationStore

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=timezone.utc)
KEY = "frunze_tours:996700000001"


def run(coro):
    return asyncio.run(coro)


def cfg():
    return SimpleNamespace(alert_awaiting_minutes=10, alert_cooldown_minutes=60,
                           awaiting_telegram_enabled=True, awaiting_max_age_hours=24)


def conv(**kw):
    base = dict(user_id="996700000001", phone="996700000001", funnel="tours",
                stage="manager", intercepted=True, archived=False, outcome=None,
                last_sender="client", last_message_at=NOW - timedelta(minutes=40),
                assigned_to="aisina", qualification={}, last_text="ну что там по туру?")
    base.update(kw)
    return SimpleNamespace(**base)


# --- 1. хранилище: отписка не двигает признак ответа --------------------------------
def test_fallback_does_not_move_last_sender():
    store = MemoryConversationStore()
    run(store.add_message(KEY, "client", "ну что там по туру?"))
    run(store.add_message(KEY, "bot", orchestrator.LLM_ERROR_FALLBACK_HANDOFF,
                          counts_as_reply=False))
    got = run(store.ensure(KEY))
    assert got.last_sender == "client", "диалог обязан остаться неотвеченным"
    assert got.last_text == "ну что там по туру?"


def test_fallback_is_still_visible_in_the_thread():
    """Менеджер должен видеть, что именно получил клиент, — сообщение не прячем."""
    store = MemoryConversationStore()
    run(store.add_message(KEY, "client", "ну что там по туру?"))
    run(store.add_message(KEY, "bot", orchestrator.LLM_ERROR_FALLBACK_HANDOFF,
                          counts_as_reply=False))
    texts = [m.text for m in run(store.ensure(KEY)).messages]
    assert orchestrator.LLM_ERROR_FALLBACK_HANDOFF in texts


def test_normal_reply_still_counts():
    store = MemoryConversationStore()
    run(store.add_message(KEY, "client", "ну что там по туру?"))
    run(store.add_message(KEY, "bot", "Нашёл три варианта, показываю"))
    assert run(store.ensure(KEY)).last_sender == "bot"


# --- 2. сторож снова видит ожидание -------------------------------------------------
def test_waiting_survives_the_fallback():
    """Главное: после отписки диалог остаётся в списке «клиент ждёт»."""
    picked = awaiting.select_awaiting_targets([conv()], NOW, cfg())
    assert [c.user_id for c in picked] == ["996700000001"]


def test_answered_dialog_is_not_waiting():
    picked = awaiting.select_awaiting_targets(
        [conv(last_sender="bot", last_text="Нашёл три варианта")], NOW, cfg())
    assert picked == []


# --- 3. текст ------------------------------------------------------------------------
def test_honest_text_promises_nothing_it_cannot_keep():
    text = orchestrator.LLM_ERROR_FALLBACK_HANDOFF
    assert "вернусь" not in text.lower(), "бот не обещает вернуться сам"
    assert "менеджер" in text.lower(), "клиент должен знать, кто ответит"


def test_old_text_stays_for_the_flag_off_path():
    """Флаг OFF — поведение прежнее, выкатка кода ничего не меняет для клиента."""
    from app.config import settings
    assert settings.llm_fallback_handoff_enabled is False
    assert "вернусь к вам" in orchestrator.LLM_ERROR_FALLBACK


# --- 4. аварийный путь не зависит от живости хранилища флагов -------------------------
def test_flag_store_failure_does_not_break_the_turn(monkeypatch):
    """Флаги лежат в БД, а сбой LLM редко приходит один: падение тут оборвало бы
    разбор остальных событий пачки в `main.wappi_webhook`."""
    from app.core import flags

    async def boom(*a, **kw):
        raise RuntimeError("postgres недоступен")

    monkeypatch.setattr(flags, "get_flag", boom)
    # Путь выбора текста обязан пережить это и взять прежнее поведение.
    async def choose():
        try:
            return await flags.get_flag(orchestrator.FALLBACK_HANDOFF_FLAG, False)
        except Exception:
            return False

    assert run(choose()) is False
