# -*- coding: utf-8 -*-
"""Дожим включается по воронкам порознь: туры можно, визы — только с ведома Гриши.

## Откуда задача (замер прода 15.09.2026)

Тумблер `followup_enabled` был один на всё. В очереди на дожим стояло 119 диалогов:
77 визовых (номер GetVisa, заказчик Гриша) и 42 туровых. Включение «чтобы карточки
поехали дальше по воронке» означало 77 сообщений чужим клиентам без ведома заказчика —
и всё это порциями по 20 каждые 5 минут, то есть за полчаса.

## Что закрепляем

1. `followup_enabled:<воронка>` включает дожим только этой воронке; дефолт — общий флаг,
   поэтому у тех, кто ничего не переключал, поведение прежнее.
2. Фильтр по воронке стоит ДО порции: иначе включённые туры получали бы остаток порции,
   занятой выключенными визами.
3. Пока не включена ни одна воронка, джоба не ходит ни в базу, ни в портал.
4. Тумблер с двоеточием в ключе переключается кнопкой в админке.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import flags, followup
from app.core.followup import enabled_funnels, select_followup_targets

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


class Cfg:
    followup_enabled = False
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
    def __init__(self, key, *, funnel="tours", hours_silent=48):
        self.user_id = key
        self.phone = key.split(":")[-1]
        self.channel = "whatsapp"
        self.chat_id = key.split(":")[-1]
        self.bot_id = key.split(":")[0]
        self.funnel = funnel
        self.stage = "qualify"
        self.intercepted = False
        self.archived = False
        self.outcome = ""
        self.followup_count = 0
        self.followup_sent = False
        self.last_message_at = NOW - timedelta(hours=hours_silent)
        self.last_sender = "client"
        self.qualification = {"destination": "Турция"}
        self.messages = [1, 2, 3]
        self.bitrix_lead_id = ""


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean():
    flags.reset()
    yield
    flags.reset()


def _mixed(tours=5, visa=5):
    return ([Conv(f"frunze_tours:9967000000{i:02d}") for i in range(tours)]
            + [Conv(f"getvisa:9967060000{i:02d}", funnel="visa") for i in range(visa)])


# ---------------- 1. отбор по воронке --------------------------------------------------
def test_only_allowed_funnel_is_selected():
    picked = select_followup_targets(_mixed(), NOW, Cfg, {"tours"})
    assert picked and all(c.funnel == "tours" for c in picked)


def test_no_allowed_funnels_means_nobody():
    assert select_followup_targets(_mixed(), NOW, Cfg, set()) == []


def test_none_keeps_old_behaviour():
    """Прежний вызов без ограничения по воронкам берёт всех, как и раньше."""
    assert len(select_followup_targets(_mixed(), NOW, Cfg, None)) == 10


def test_disabled_funnel_does_not_eat_the_batch():
    """Порция целиком уходит включённой воронке, а не делится с выключенной."""
    class Small(Cfg):
        followup_batch_limit = 5

    picked = select_followup_targets(_mixed(tours=20, visa=20), NOW, Small, {"tours"})
    assert len(picked) == 5 and all(c.funnel == "tours" for c in picked)


# ---------------- 2. тумблеры ----------------------------------------------------------
def test_per_funnel_flag_beats_the_global_one():
    run(flags.set_flag("followup_enabled:tours", True))
    assert run(enabled_funnels(Cfg)) == {"tours"}


def test_global_flag_is_the_default_for_every_funnel():
    run(flags.set_flag("followup_enabled", True))
    assert run(enabled_funnels(Cfg)) == {"tours", "visa", "tickets"}


def test_funnel_can_be_switched_off_while_global_is_on():
    run(flags.set_flag("followup_enabled", True))
    run(flags.set_flag("followup_enabled:visa", False))
    assert run(enabled_funnels(Cfg)) == {"tours", "tickets"}


# ---------------- 3. джоба молчит, пока всё выключено ------------------------------------
def test_job_touches_nothing_while_disabled(monkeypatch):
    called = []
    monkeypatch.setattr(followup, "_send_followups",
                        lambda *a, **kw: called.append(a) or asyncio.sleep(0))
    run(followup.run())
    assert called == []


def test_job_runs_for_the_enabled_funnel(monkeypatch):
    run(flags.set_flag("followup_enabled:tours", True))
    seen = {}

    async def fake_send(now, cfg, allowed=None):
        seen["allowed"] = allowed
        return 0

    monkeypatch.setattr(followup, "_send_followups", fake_send)
    monkeypatch.setattr(followup, "is_quiet_hour", lambda *a, **kw: False)
    run(followup.run())
    assert seen["allowed"] == {"tours"}


# ---------------- 4. кнопка в админке ----------------------------------------------------
def test_colon_key_is_switched_by_a_real_button():
    """Ключ с двоеточием уходит в путь URL — проверяем настоящим запросом, не словарём."""
    from fastapi.testclient import TestClient

    from app import main
    from app.integrations.panel import store as panel_store

    panel_store._memory_store._conv.clear()
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login",
                       data={"login": "admin", "password": "frunze"}).status_code == 200
    r = client.post("/admin/flags/followup_enabled:tours", data={"on": "1"})
    assert r.status_code == 200
    assert run(flags.get_flag("followup_enabled:tours", False)) is True
    assert run(enabled_funnels(Cfg)) == {"tours"}
    client.post("/admin/flags/followup_enabled:tours", data={"on": "0"})
    assert run(flags.get_flag("followup_enabled:tours", True)) is False
