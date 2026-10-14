# -*- coding: utf-8 -*-
"""`read_back_once` не ходит в портал, когда ходить некуда или незачем.

Долг из docs/migr-1-bitrix-inventory.md: джоба дёргает портал каждые 10 минут без
проверки флагов. После отключения Bitrix это вечные предупреждения в логе.

Но это сейчас единственный автоматический учёт продаж, поэтому рубильник
`bitrix_read_back_enabled` по умолчанию ВКЛЮЧЁН. Закрыть read-back глобальным
`bitrix_pipeline_enabled` нельзя: на проде (14.10) глобального ключа в `app_flags`
нет, дефолт False — включены только ключи по ботам. Такой гейт молча остановил бы
учёт продаж.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

LEAD = "190001"


class FakeAdapter:
    def __init__(self):
        self.calls = 0

    async def list_converted_leads(self, since):
        self.calls += 1
        return [{"ID": LEAD, "STATUS_ID": "CONVERTED"}]

    async def find_deal_by_lead(self, lead_id):
        return ""

    async def create_deal(self, fields):
        return "6001"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    yield
    flags.reset()


def _tour_conv():
    key = "frunze_tours:996700333444"
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id="frunze_tours"))
    run(store.update_meta(key, bitrix_lead_id=LEAD, funnel="tours"))
    return store, key


def test_empty_webhook_url_skips_portal(monkeypatch):
    """Портал не настроен — клиента не создаём и в сеть не идём, ошибок нет."""
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "")

    def _no_client():
        raise AssertionError("read-back не должен создавать клиента Bitrix без URL")

    monkeypatch.setattr(bp, "_adapter", lambda adapter=None: adapter or _no_client())
    stats = run(bp.read_back_once())
    assert stats["errors"] == 0
    assert stats["checked"] == 0


def test_flag_off_skips_portal():
    fake = FakeAdapter()
    _tour_conv()
    run(flags.set_flag("bitrix_read_back_enabled", False))
    stats = run(bp.read_back_once(adapter=fake))
    assert fake.calls == 0
    assert stats["won"] == 0 and stats["errors"] == 0


def test_default_keeps_sales_accounting_without_global_pipeline_flag():
    """Как на проде: глобального `bitrix_pipeline_enabled` нет, рубильник не трогали —
    продажа обязана засчитаться, как и раньше."""
    fake = FakeAdapter()
    store, key = _tour_conv()
    stats = run(bp.read_back_once(adapter=fake))
    assert fake.calls == 1
    assert stats["won"] == 1
    assert (run(store.get(key)).outcome or "") == "won"
