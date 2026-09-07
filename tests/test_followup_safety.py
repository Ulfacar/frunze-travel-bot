"""ГЕЙТ: дожим не превращается в веерную рассылку по всей базе.

Написан ДО реализации и исполнителем НЕ редактируется.

## Замер, из которого выросла задача (прод, 07.09.2026, сухой прогон)

Дожим не включали ни разу за всю жизнь бота: `followup_count = 0` у всех 2955 диалогов.
Сухой прогон `select_followup_targets` на боевых данных показал, почему это было
правильно:

    ВСЕГО получили бы касание: 818
       getvisa             589
       frunze_tours_sezim  153
       frunze_tours         76

Первое же включение отправило бы 818 сообщений залпом — по всей базе, накопленной за
месяцы. Клиент, замолчавший в июле, получил бы «вы ещё думаете над поездкой?».
Это спам, жалобы и реальный риск блокировки номеров в WhatsApp — а канал у нас один
на весь бизнес.

В коде на тот момент не было ни одного ограничителя:

* `is_silent` проверяет «молчит ДОЛЬШЕ N часов» и не имеет верхней границы — под дожим
  попадал и трёхмесячный труп;
* `_send_followups` шлёт всем отобранным за один проход, без лимита на прогон.

## Правило

1. За один прогон уходит не больше `followup_batch_limit` сообщений. Очередь разбирается
   порциями, а не залпом.
2. Клиент, молчащий дольше `followup_max_age_days`, не дожимается вообще: он уже не
   вернётся, а сообщение через три месяца читается как спам.
3. Первыми дожимаем тех, кто замолчал недавно — у них шанс вернуться выше.
4. Оба ограничителя работают и в авто-режиме, и по кнопке «дожать» в админке.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core.followup import select_followup_targets

NOW = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)


class Cfg:
    followup_after_hours = 24
    followup_max_pings = 2
    followup_interval_hours = 84
    followup_quiet_from = 22
    followup_quiet_to = 9
    followup_batch_limit = 20
    followup_max_age_days = 14
    noise_max_client_messages = 1
    noise_window_hours = 48


class Conv:
    """Минимальный диалог в форме, которую читают `is_silent` и рассылка."""

    def __init__(self, key, *, hours_silent=48, pings=0, bot="frunze_tours"):
        self.user_id = key
        self.phone = key.split(":")[-1]
        self.channel = "whatsapp"
        self.chat_id = key.split(":")[-1]
        self.bot_id = bot
        self.funnel = "tours"
        self.stage = "qualify"
        self.intercepted = False
        self.archived = False
        self.outcome = ""
        self.followup_count = pings
        self.followup_sent = pings > 0
        self.last_message_at = NOW - timedelta(hours=hours_silent)
        self.last_sender = "client"
        self.qualification = {"destination": "Турция"}
        self.messages = [1, 2, 3]
        self.bitrix_lead_id = ""


def _many(count, **kw):
    return [Conv(f"frunze_tours:99670000{i:04d}", **kw) for i in range(count)]


# ---------------- порционность ------------------------------------------------------
def test_batch_is_capped_per_run():
    """818 целей на проде не должны уйти одним залпом."""
    targets = select_followup_targets(_many(100), NOW, Cfg)
    assert len(targets) <= Cfg.followup_batch_limit


def test_cap_is_configurable():
    class Small(Cfg):
        followup_batch_limit = 5

    assert len(select_followup_targets(_many(50), NOW, Small)) == 5


def test_everyone_gets_their_turn_across_runs():
    """Ложноположительный: лимит не должен насовсем отсекать хвост очереди.

    Отобранные в первом прогоне получают отметку и уходят из выборки — следующий прогон
    берёт следующих. Здесь проверяем именно это: выборка не залипает на одних и тех же.
    """
    convs = _many(30)
    first = select_followup_targets(convs, NOW, Cfg)
    for c in first:                       # имитируем успешную отправку
        c.followup_count = 1
        c.last_message_at = NOW
    second = select_followup_targets(convs, NOW + timedelta(hours=100), Cfg)
    assert second and {c.user_id for c in second} != {c.user_id for c in first}


# ---------------- окно свежести -----------------------------------------------------
def test_long_dead_dialog_is_never_pinged():
    """Клиент, молчащий три месяца, дожиму не подлежит: это спам, а не касание."""
    assert select_followup_targets([Conv("frunze_tours:1", hours_silent=24 * 90)], NOW, Cfg) == []


def test_edge_of_the_window_still_counts():
    inside = Conv("frunze_tours:2", hours_silent=24 * 13)
    outside = Conv("frunze_tours:3", hours_silent=24 * 15)
    picked = {c.user_id for c in select_followup_targets([inside, outside], NOW, Cfg)}
    assert "frunze_tours:2" in picked
    assert "frunze_tours:3" not in picked


def test_window_is_configurable():
    class Wide(Cfg):
        followup_max_age_days = 60

    assert select_followup_targets([Conv("frunze_tours:4", hours_silent=24 * 30)], NOW, Wide)


# ---------------- порядок: свежие первыми -------------------------------------------
def test_fresher_dialogs_go_first():
    old = Conv("frunze_tours:old", hours_silent=24 * 10)
    fresh = Conv("frunze_tours:fresh", hours_silent=30)
    middle = Conv("frunze_tours:mid", hours_silent=24 * 4)
    picked = select_followup_targets([old, fresh, middle], NOW, Cfg)
    assert [c.user_id for c in picked][0] == "frunze_tours:fresh"


# ---------------- прежние правила не сломаны ----------------------------------------
def test_ping_limit_still_holds():
    """Ложноположительный: исчерпавший лимит касаний не дожимается независимо от прочего."""
    assert select_followup_targets([Conv("frunze_tours:5", pings=2)], NOW, Cfg) == []


def test_intercepted_is_never_touched():
    conv = Conv("frunze_tours:6")
    conv.intercepted = True
    assert select_followup_targets([conv], NOW, Cfg) == []


def test_silent_less_than_threshold_is_not_touched():
    assert select_followup_targets([Conv("frunze_tours:7", hours_silent=2)], NOW, Cfg) == []


def test_non_whatsapp_is_not_touched():
    conv = Conv("tg:8")
    conv.channel = "telegram"
    assert select_followup_targets([conv], NOW, Cfg) == []
