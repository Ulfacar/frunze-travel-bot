# -*- coding: utf-8 -*-
"""Напоминать можно дважды, а не бесконечно.

Замер за первые сутки работы: 279 напоминаний на 36 диалогов. Ограничение
«не чаще раза в час» ограничивает ЧАСТОТУ, но не ОБЩЕЕ число: клиент, которому
менеджер так и не ответил, генерирует ~24 сообщения в сутки. Рекорд — 23
напоминания по одному диалогу.

Эффект при этом настоящий: менеджер пришёл в 16 случаях из 36, медиана 14 минут.
То есть работает первое-второе напоминание, а не двадцатое. Дальше это уже не
напоминание, а то самое «лишь бы их это не доставало».

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.core import awaiting

NOW = datetime(2026, 9, 12, 12, 0, tzinfo=timezone.utc)


def conv(**kw):
    base = dict(user_id="996700000001", phone="996700000001", funnel="tours",
                stage="manager", intercepted=True, archived=False, outcome=None,
                last_sender="client", last_message_at=NOW - timedelta(minutes=40),
                assigned_to="aisina", qualification={}, last_text="а на 5 ночей есть?",
                awaiting_pinged_at=None, awaiting_ping_count=0)
    base.update(kw)
    return SimpleNamespace(**base)


def cfg(**kw):
    base = dict(alert_awaiting_minutes=10, alert_cooldown_minutes=60,
                awaiting_telegram_enabled=True, awaiting_max_age_hours=24,
                awaiting_max_pings=2)
    base.update(kw)
    return SimpleNamespace(**base)


def test_first_reminder_goes():
    assert awaiting.select_telegram_targets([conv()], NOW, cfg()) != []


def test_second_reminder_goes():
    c = conv(awaiting_ping_count=1, awaiting_pinged_at=NOW - timedelta(hours=2))
    assert awaiting.select_telegram_targets([c], NOW, cfg()) != []


def test_third_reminder_does_not():
    """Бюджет исчерпан — дальше это уже не напоминание.

    ПОПРАВКА К ГЕЙТУ (12.09, автор — исполнитель, и это оговаривается специально).
    В первой редакции тут стояли дефолтные `last_message_at = NOW-40м` при
    `awaiting_pinged_at = NOW-2ч`, то есть клиент написал ПОСЛЕ последнего напоминания.
    Это ровно тот случай, который следующий тест объявляет сбросом бюджета — два теста
    описывали одну ситуацию с противоположными ожиданиями, и виноват был гейт, а не код.
    Настоящее «третье напоминание» — это молчащий клиент: его последняя реплика СТАРШЕ
    последнего пуша.
    """
    c = conv(awaiting_ping_count=2,
             awaiting_pinged_at=NOW - timedelta(hours=2),
             last_message_at=NOW - timedelta(hours=5))
    assert awaiting.select_telegram_targets([c], NOW, cfg()) == []


def test_budget_is_configurable():
    c = conv(awaiting_ping_count=2,
             awaiting_pinged_at=NOW - timedelta(hours=2),
             last_message_at=NOW - timedelta(hours=5))
    assert awaiting.select_telegram_targets([c], NOW, cfg(awaiting_max_pings=3)) != []


def test_new_client_message_resets_the_budget():
    """Клиент написал снова после напоминаний — это новое ожидание, считаем заново."""
    c = conv(awaiting_ping_count=2,
             awaiting_pinged_at=NOW - timedelta(hours=5),
             last_message_at=NOW - timedelta(minutes=40))   # написал ПОСЛЕ последнего пуша
    assert awaiting.select_telegram_targets([c], NOW, cfg()) != []


def test_budget_holds_while_client_is_silent():
    """Клиент молчит с прошлого раза — бюджет не восстанавливается."""
    c = conv(awaiting_ping_count=2,
             awaiting_pinged_at=NOW - timedelta(hours=2),
             last_message_at=NOW - timedelta(hours=5))
    assert awaiting.select_telegram_targets([c], NOW, cfg()) == []


@pytest.mark.asyncio
async def test_counter_grows_on_a_successful_send(monkeypatch):
    written = {}

    async def push(login, text, conv_obj):
        return True

    async def remember(user_id, moment, count):
        written[user_id] = count

    monkeypatch.setattr(awaiting, "_push_owner", push)
    monkeypatch.setattr(awaiting, "_remember_ping", remember)
    monkeypatch.setattr(awaiting, "_all_conversations",
                        lambda: _fake([conv(awaiting_ping_count=1,
                                            awaiting_pinged_at=NOW - timedelta(hours=2),
                                            last_message_at=NOW - timedelta(hours=5))]))
    awaiting._alerted.clear()
    assert await awaiting.run_telegram(now=NOW, cfg=cfg()) == 1
    assert written.get("996700000001") == 2


def _fake(items):
    async def _inner():
        return items
    return _inner()
