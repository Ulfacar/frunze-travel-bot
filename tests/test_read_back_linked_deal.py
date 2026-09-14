# -*- coding: utf-8 -*-
"""Менеджер сконвертировал лид кнопкой портала — сделка уже есть, вторую не заводим.

Прод 12.09: лид 187095 Адеми перевела в «Подписан» в 13:31, портал сам завёл сделку 5699
на 36 305 и привязал к лиду. Наш обратный проход в 13:41 увидел «Подписан» и завёл
пустую 5701 рядом — в воронке FrunzeTravel одна продажа стала двумя.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps
from tests.test_read_back_tours_only import LEAD, FakeAdapter

KEY = "frunze_tours:996703080916"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    run(flags.set_flag("bitrix_autodeal_enabled", True))
    store = ps.get_conversation_store()
    run(store.ensure(KEY, bot_id="frunze_tours"))
    run(store.update_meta(KEY, funnel="tours", bitrix_lead_id=LEAD))
    yield
    flags.reset()


def test_portal_deal_is_linked_not_duplicated():
    fake = FakeAdapter()
    fake.portal_deal = "5699"
    stats = run(bp.read_back_once(adapter=fake))
    assert fake.deals == [], "вторая сделка поверх сделки менеджера"
    assert stats["deals_linked"] == 1
    assert run(ps.get_conversation_store().get(KEY)).bitrix_deal_id == "5699"


def test_no_portal_deal_still_creates_one():
    """Лид сконвертирован без сделки (кнопкой «Оплатил») — сделку по-прежнему заводим мы."""
    fake = FakeAdapter()
    stats = run(bp.read_back_once(adapter=fake))
    assert len(fake.deals) == 1 and stats["deals_created"] == 1
