# -*- coding: utf-8 -*-
"""Сторож всплеска сбоев: он молчал, и это надо было заметить раньше.

## Замер прода 15.09.2026

`ALERT_WHATSAPP_TO` и `ALERT_BOT_ID` пусты — `watchdog.run` выходил первой же строкой.
То есть сторож, который должен кричать про сбои LLM и отправки, не работал вообще, при
живом Telegram-канале (2 получателя, токен на месте), куда уже ходят сторож баланса и
сторож карточек. Тестов у модуля не было ни одного.

## Что закрепляем

1. Нет адресата и тумблер выключен — молчим (прежнее поведение, ничего не сломано).
2. Тумблер включён и WhatsApp не настроен — алерт уходит в Telegram.
3. WhatsApp настроен — приоритет у него, Telegram не трогаем.
4. **Ночью про тишину вебхуков не пишем.** Порог 30 минут при cooldown в час дал бы до
   десяти сообщений за ночь, когда клиенты просто спят. Шумного сторожа выключают.
5. Всплеск сбоев ночью НЕ глушим: это реальные ошибки, а не отсутствие трафика.
"""
import asyncio

import pytest

from app.core import flags, watchdog


class Cfg:
    alert_silence_minutes = 30
    alert_fail_threshold = 5
    alert_cooldown_minutes = 60
    channel_heartbeat_quiet_from = 22
    channel_heartbeat_quiet_to = 9
    alert_whatsapp_to = ""
    alert_bot_id = ""
    watchdog_telegram_enabled = False


NOW = 1_000_000.0


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    flags.reset()
    watchdog._state.update({"alert_silence_ts": 0.0, "alert_fail_ts": 0.0,
                            "fail_baseline": 0.0})
    yield
    flags.reset()


# ---------------- 1. решение: что вообще считается поводом ------------------------------
def test_silence_alert_fires_in_daytime():
    alerts = watchdog.decide(NOW, 60 * 60, {}, dict(watchdog._state), Cfg, night=False)
    assert [reason for reason, _ in alerts] == ["silence"]


def test_silence_is_quiet_at_night():
    """Ночью клиенты не пишут — тишина не повод будить человека."""
    alerts = watchdog.decide(NOW, 60 * 60, {}, dict(watchdog._state), Cfg, night=True)
    assert alerts == []


def test_failures_alert_fires_even_at_night():
    """Сбои — это ошибки, а не отсутствие трафика: ночью они тем более важны."""
    snap = {"llm_failures": 7, "send_failures": 1}
    alerts = watchdog.decide(NOW, None, snap, dict(watchdog._state), Cfg, night=True)
    assert [reason for reason, _ in alerts] == ["failures"]


def test_cooldown_holds_the_second_alert():
    state = dict(watchdog._state)
    first = watchdog.decide(NOW, 60 * 60, {}, state, Cfg)
    second = watchdog.decide(NOW + 60, 60 * 60, {}, state, Cfg)
    assert first and second == []


# ---------------- 2. доставка ------------------------------------------------------------
def _patch_cfg(monkeypatch, **kw):
    for key, value in kw.items():
        monkeypatch.setattr(watchdog.settings, key, value, raising=False)


def test_silent_when_no_recipient_configured(monkeypatch):
    """Прежнее поведение: адресата нет, тумблер выключен — ни одной отправки."""
    _patch_cfg(monkeypatch, alert_whatsapp_to="", alert_bot_id="",
               watchdog_telegram_enabled=False)
    sent = []
    monkeypatch.setattr(watchdog.observ, "last_inbound_ago", lambda: 60 * 60)
    monkeypatch.setattr(watchdog.observ, "snapshot", lambda: {})
    monkeypatch.setattr(watchdog.outbound, "send_to_client",
                        lambda *a, **kw: sent.append(a) or asyncio.sleep(0))
    run(watchdog.run())
    assert sent == []


def test_telegram_used_when_whatsapp_is_not_configured(monkeypatch):
    _patch_cfg(monkeypatch, alert_whatsapp_to="", alert_bot_id="")
    run(flags.set_flag("watchdog_telegram_enabled", True))
    monkeypatch.setattr(watchdog.observ, "last_inbound_ago", lambda: None)
    monkeypatch.setattr(watchdog.observ, "snapshot",
                        lambda: {"llm_failures": 9, "send_failures": 0})

    pushed = []
    from app.core import ops_alert

    async def fake_send(text, *, key="", **kw):
        pushed.append((key, text))
        return True

    monkeypatch.setattr(ops_alert, "send", fake_send)
    run(watchdog.run())
    assert pushed and pushed[0][0] == "watchdog:failures"
    assert "сбоев" in pushed[0][1]


def test_whatsapp_keeps_priority_when_configured(monkeypatch):
    _patch_cfg(monkeypatch, alert_whatsapp_to="996700000000", alert_bot_id="frunze_tours")
    run(flags.set_flag("watchdog_telegram_enabled", True))
    monkeypatch.setattr(watchdog.observ, "last_inbound_ago", lambda: None)
    monkeypatch.setattr(watchdog.observ, "snapshot",
                        lambda: {"llm_failures": 9, "send_failures": 0})
    sent = []

    async def fake_wa(channel, bot_id, to, text):
        sent.append((channel, to))
        return "msg-1"

    monkeypatch.setattr(watchdog.outbound, "send_to_client", fake_wa)
    from app.core import ops_alert
    monkeypatch.setattr(ops_alert, "send",
                        lambda *a, **kw: pytest.fail("Telegram не нужен, когда есть WhatsApp"))
    run(watchdog.run())
    assert sent == [("whatsapp", "996700000000")]


def test_master_switch_still_wins(monkeypatch):
    """`alerts_enabled` выключен — молчим независимо от адресата."""
    _patch_cfg(monkeypatch, alert_whatsapp_to="", alert_bot_id="")
    run(flags.set_flag("watchdog_telegram_enabled", True))
    run(flags.set_flag("alerts_enabled", False))
    from app.core import ops_alert
    monkeypatch.setattr(ops_alert, "send",
                        lambda *a, **kw: pytest.fail("алерты выключены рубильником"))
    run(watchdog.run())


# ---------------- 3. граница ночи ---------------------------------------------------------
def test_night_window_wraps_midnight():
    assert watchdog._is_night(23, Cfg) and watchdog._is_night(3, Cfg)
    assert not watchdog._is_night(12, Cfg)
    assert watchdog._is_night(22, Cfg) and not watchdog._is_night(9, Cfg)
