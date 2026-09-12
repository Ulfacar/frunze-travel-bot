# -*- coding: utf-8 -*-
"""Счётчик «не чаще раза в час» обязан переживать рестарт.

Поймано живым прогоном 11.09: напоминания ушли из отдельного процесса, а
`_alerted` — словарь в памяти. У планировщика он свой и пустой, значит те же
восемь человек получили бы вторую пачку через пять минут. И каждый деплой
сбрасывал бы счётчик так же — у нас их по несколько в день.

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
                assigned_to="aisina", qualification={}, last_text="а на 5 ночей есть?",
                awaiting_pinged_at=None)
    base.update(kw)
    return SimpleNamespace(**base)


def cfg():
    return SimpleNamespace(alert_awaiting_minutes=10, alert_cooldown_minutes=60,
                           awaiting_telegram_enabled=True, awaiting_max_age_hours=24)


def test_recent_ping_is_read_from_the_record_not_from_memory():
    """Память пуста (как после рестарта), но в записи стоит отметка 5 минут назад."""
    awaiting._alerted.clear()
    recent = conv(awaiting_pinged_at=NOW - timedelta(minutes=5))
    assert awaiting.select_telegram_targets([recent], NOW, cfg()) == []


def test_old_ping_does_not_block_forever():
    awaiting._alerted.clear()
    old = conv(awaiting_pinged_at=NOW - timedelta(hours=5))
    assert awaiting.select_telegram_targets([old], NOW, cfg()) != []


def test_never_pinged_is_selected():
    awaiting._alerted.clear()
    assert awaiting.select_telegram_targets([conv()], NOW, cfg()) != []


@pytest.mark.asyncio
async def test_successful_send_is_written_to_the_record(monkeypatch):
    written = {}

    async def push(login, text, conv_obj):
        return True

    async def remember(user_id, moment, count):   # сигнатура выросла: счётчик
        written[user_id] = moment

    monkeypatch.setattr(awaiting, "_push_owner", push)
    monkeypatch.setattr(awaiting, "_remember_ping", remember)
    monkeypatch.setattr(awaiting, "_all_conversations", lambda: _fake([conv()]))
    awaiting._alerted.clear()
    assert await awaiting.run_telegram(now=NOW, cfg=cfg()) == 1
    assert written.get("996700000001") == NOW


@pytest.mark.asyncio
async def test_failed_send_is_not_written(monkeypatch):
    """Не дошло — отметку не ставим, иначе клиент выпадет на час молча."""
    written = {}

    async def push(login, text, conv_obj):
        return False

    async def remember(user_id, moment, count):   # сигнатура выросла: счётчик
        written[user_id] = moment

    monkeypatch.setattr(awaiting, "_push_owner", push)
    monkeypatch.setattr(awaiting, "_remember_ping", remember)
    monkeypatch.setattr(awaiting, "_all_conversations", lambda: _fake([conv()]))
    awaiting._alerted.clear()
    assert await awaiting.run_telegram(now=NOW, cfg=cfg()) == 0
    assert written == {}


def _fake(items):
    async def _inner():
        return items
    return _inner()
