# -*- coding: utf-8 -*-
"""Воронка FrunzeTravel — только для туров.

`read_back_once` перебирает лиды, ставшие «Подписан», и сопоставляет их с нашими
диалогами по `bitrix_lead_id` — БЕЗ проверки воронки. Визовые менеджеры двигают лиды
в «Подписан» сотнями в месяц, и каждый такой лид помечал наш визовый диалог продажей,
а при включённом `bitrix_autodeal_enabled` заводил сделку в CATEGORY_ID=27, то есть
в туровой воронке.

Проверено на проде 13.09: флаг в рантайме включён, один визовый диалог уже помечен
как продажа. Загрязняется ровно та статистика, ради которой всё и делается.

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

LEAD = "190001"
STAGE_MAP = {"qualified": "UC_S0NTF8", "offer_sent": "UC_PNSIIB"}


class FakeAdapter:
    def __init__(self):
        self.lead = {"ID": LEAD, "STATUS_ID": "CONVERTED", "COMMENTS": ""}
        self.deals: list[dict] = []
        self.stage_calls: list[tuple[str, str]] = []

    async def list_converted_leads(self, since):
        await asyncio.sleep(0)
        return [dict(self.lead)]

    async def get_lead(self, lead_id):
        await asyncio.sleep(0)
        return dict(self.lead)

    async def update_stage_status(self, lead_id, status_id):
        self.stage_calls.append((str(lead_id), status_id))

    async def update_comments(self, lead_id, text):
        pass

    async def add_note(self, lead_id, text):
        pass

    async def find_deal_by_lead(self, lead_id):

        return getattr(self, "portal_deal", "")  # сделка, заведённая конвертацией в портале


    async def create_deal(self, fields):
        await asyncio.sleep(0)
        self.deals.append(dict(fields))
        return str(6000 + len(self.deals))


def run(coro):
    return asyncio.run(coro)


def _conv(bot_id: str, funnel: str):
    key = f"{bot_id}:996700333444"
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id=bot_id))
    run(store.update_meta(key, bitrix_lead_id=LEAD, funnel=funnel))
    return store, key


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bp.settings, "bitrix_stage_map", dict(STAGE_MAP), raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_deal_category_id", "27", raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_deal_stage_id", "C27:NEW", raising=False)
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    run(flags.set_flag("bitrix_autodeal_enabled", True))
    yield
    flags.reset()


def test_visa_sale_does_not_create_a_tour_deal():
    """Главный случай: визовый лид «Подписан» — в туровой воронке ничего не появляется."""
    fake = FakeAdapter()
    _conv("getvisa", "visa")
    run(bp.read_back_once(adapter=fake))
    assert fake.deals == [], "визовая продажа не имеет права попасть в воронку туров"


def test_visa_sale_does_not_mark_the_dialog_won():
    """И исход визового диалога трогать нельзя — по нему считают туровую конверсию."""
    fake = FakeAdapter()
    store, key = _conv("getvisa", "visa")
    stats = run(bp.read_back_once(adapter=fake))
    conv = run(store.get(key))
    assert (conv.outcome or "") != "won"
    assert stats.get("won", 0) == 0


def test_tour_sale_still_works():
    """Ложное срабатывание дороже: туровая продажа обязана доехать как прежде."""
    fake = FakeAdapter()
    store, key = _conv("frunze_tours", "tours")
    stats = run(bp.read_back_once(adapter=fake))
    conv = run(store.get(key))
    assert (conv.outcome or "") == "won"
    assert stats.get("won", 0) == 1
    assert len(fake.deals) == 1
    assert fake.deals[0].get("CATEGORY_ID") == "27"


def test_unknown_funnel_is_not_counted_as_a_tour():
    """Пустая воронка — не повод считать продажу туровой."""
    fake = FakeAdapter()
    store, key = _conv("frunze_tours", "")
    run(bp.read_back_once(adapter=fake))
    conv = run(store.get(key))
    assert (conv.outcome or "") != "won"
    assert fake.deals == []
