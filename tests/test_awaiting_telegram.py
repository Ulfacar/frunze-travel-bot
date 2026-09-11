# -*- coding: utf-8 -*-
"""Сторож «клиент ждёт живого человека» должен иметь адресата.

Замер 11.09 на проде: `alert_whatsapp_to` пуст, `alert_bot_id` пуст — джоба выходит
первой же строкой и не сработала НИ РАЗУ. При этом прямо сейчас 196 диалогов, где
последним говорил клиент, бот заглушён перехватом, и никто не ответил; за сутки
набегает ~10 новых.

Доставляем владельцу диалога в личный телеграм — тем же каналом, что и мгновенная
заявка (по нему медиана реакции 19 минут на замере за 28 дней).

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core import awaiting

NOW = datetime(2026, 9, 11, 12, 0, tzinfo=timezone.utc)


def conv(**kw):
    base = dict(user_id="996700000001", phone="996700000001", funnel="tours",
                stage="manager", intercepted=True, archived=False, outcome=None,
                last_sender="client", last_message_at=NOW - timedelta(minutes=40),
                assigned_to="aisina", qualification={})
    base.update(kw)
    return SimpleNamespace(**base)


class Cfg(SimpleNamespace):
    pass


def cfg(**kw):
    base = dict(alert_awaiting_minutes=10, alert_cooldown_minutes=60,
                awaiting_telegram_enabled=False, awaiting_max_age_hours=24,
                alert_whatsapp_to="", alert_bot_id="")
    base.update(kw)
    return Cfg(**base)


def test_fresh_waiting_client_is_selected():
    got = awaiting.select_telegram_targets([conv()], NOW, cfg())
    assert [c.user_id for c in got] == ["996700000001"]


def test_old_backlog_is_not_chased():
    """Лид недельной давности будить менеджера не должен — он уже мёртв."""
    old = conv(last_message_at=NOW - timedelta(days=7))
    assert awaiting.select_telegram_targets([old], NOW, cfg()) == []


def test_answered_dialog_is_not_selected():
    assert awaiting.select_telegram_targets([conv(last_sender="manager")], NOW, cfg()) == []


def test_too_fresh_is_not_selected():
    young = conv(last_message_at=NOW - timedelta(minutes=3))
    assert awaiting.select_telegram_targets([young], NOW, cfg()) == []


def test_finished_dialog_is_not_selected():
    assert awaiting.select_telegram_targets([conv(outcome="won")], NOW, cfg()) == []


def test_burst_is_capped():
    """Первое включение не имеет права высыпать менеджеру весь накопленный хвост."""
    many = [conv(user_id=f"99670000{i:04d}") for i in range(40)]
    got = awaiting.select_telegram_targets(many, NOW, cfg())
    assert len(got) <= awaiting.TELEGRAM_CAP


@pytest.mark.asyncio
async def test_flag_off_sends_nothing(monkeypatch):
    sent = []
    monkeypatch.setattr(awaiting, "_push_owner", lambda *a, **k: sent.append(a))
    monkeypatch.setattr(awaiting, "_all_conversations", lambda: _fake([conv()]))
    assert await awaiting.run_telegram(now=NOW, cfg=cfg(awaiting_telegram_enabled=False)) == 0
    assert sent == []


@pytest.mark.asyncio
async def test_flag_on_pushes_to_the_owner(monkeypatch):
    sent = []

    async def push(login, text, conv_obj):
        sent.append((login, text))
        return True

    monkeypatch.setattr(awaiting, "_push_owner", push)
    monkeypatch.setattr(awaiting, "_all_conversations", lambda: _fake([conv()]))
    awaiting._alerted.clear()
    n = await awaiting.run_telegram(now=NOW, cfg=cfg(awaiting_telegram_enabled=True))
    assert n == 1
    assert sent and sent[0][0] == "aisina"
    assert "ждёт" in sent[0][1]


@pytest.mark.asyncio
async def test_cooldown_blocks_the_second_ping(monkeypatch):
    sent = []

    async def push(login, text, conv_obj):
        sent.append(login)
        return True

    monkeypatch.setattr(awaiting, "_push_owner", push)
    monkeypatch.setattr(awaiting, "_all_conversations", lambda: _fake([conv()]))
    awaiting._alerted.clear()
    c = cfg(awaiting_telegram_enabled=True)
    await awaiting.run_telegram(now=NOW, cfg=c)
    await awaiting.run_telegram(now=NOW + timedelta(minutes=5), cfg=c)
    assert len(sent) == 1


def _fake(items):
    async def _inner():
        return items
    return _inner()
