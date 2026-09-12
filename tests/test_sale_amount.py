# -*- coding: utf-8 -*-
"""Сумма в сделке — это оплата, названная менеджером, а не бюджет из разговора.

Замер 13.09: в воронке FrunzeTravel 7 туровых сделок за 2,5 месяца. У тех, что
менеджеры завели руками, суммы стоят (58 000, 45 000, 36 305 сом). У сделки, созданной
нашим конвейером, — ноль, потому что назвать сумму менеджеру негде: на странице
подтверждения одна кнопка и ни одного поля ввода.

При этом `deal_fields` кладёт в `OPPORTUNITY` разобранный `budget` из анкеты, то есть
«сколько клиент хотел потратить», причём диапазоны усредняются. В отчёте о выручке это
не число, а пожелание.

Гейт написан ДО правки и исполнителем НЕ редактируется.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.core import flags, sale_check
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

BOT = "frunze_tours"
KEY = f"{BOT}:996700555666"
LEAD = "191001"


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix_deal_category_id", "27", raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_deal_stage_id", "C27:NEW", raising=False)
    yield
    flags.reset()


def _conv(**meta):
    store = ps.get_conversation_store()
    run(store.ensure(KEY, bot_id=BOT))
    run(store.update_meta(KEY, bitrix_lead_id=LEAD, funnel="tours", **meta))
    return run(store.get(KEY))


LEAD_ROW = {"ID": LEAD, "TITLE": "tours: тест", "ASSIGNED_BY_ID": "155313"}


def test_confirmed_payment_becomes_the_deal_amount():
    conv = _conv(qualification={"destination": "Турция"},
                 sale_amount=120000, sale_currency="KGS")
    fields = bp.deal_fields(conv, LEAD_ROW)
    assert float(fields["OPPORTUNITY"]) == 120000
    assert fields["CURRENCY_ID"] == "KGS"


def test_confirmed_payment_beats_the_budget_from_chat():
    """Клиент говорил про 1500 долларов, заплатил 96 000 сом — в отчёт идёт оплата."""
    conv = _conv(qualification={"budget": "1500 USD"},
                 sale_amount=96000, sale_currency="KGS")
    fields = bp.deal_fields(conv, LEAD_ROW)
    assert float(fields["OPPORTUNITY"]) == 96000
    assert fields["CURRENCY_ID"] == "KGS"


def test_dollars_stay_dollars():
    conv = _conv(sale_amount=1500, sale_currency="USD")
    fields = bp.deal_fields(conv, LEAD_ROW)
    assert float(fields["OPPORTUNITY"]) == 1500
    assert fields["CURRENCY_ID"] == "USD"


def test_without_confirmed_amount_nothing_changes():
    """Ложное срабатывание дороже: без введённой суммы поведение прежнее."""
    conv = _conv(qualification={"budget": "1500 USD"})
    fields = bp.deal_fields(conv, LEAD_ROW)
    assert float(fields.get("OPPORTUNITY") or 0) == 1500
    assert fields.get("CURRENCY_ID") == "USD"


# --- сохранение ответа менеджера ------------------------------------------------

def test_mark_saves_the_amount(monkeypatch):
    _conv(qualification={})
    monkeypatch.setattr(sale_check, "_convert_lead", _noop)
    cid = sale_check.fingerprint(KEY, sale_check.settings) \
        if hasattr(sale_check, "fingerprint") else None
    store = ps.get_conversation_store()
    run(sale_check._save_amount(KEY, "120000", "KGS"))
    conv = run(store.get(KEY))
    assert float(getattr(conv, "sale_amount", 0) or 0) == 120000
    assert getattr(conv, "sale_currency", "") == "KGS"


def test_garbage_amount_is_ignored_but_confirmation_survives():
    """Менеджер набрал ерунду — подтверждение всё равно сохраняется, сумма пустая."""
    _conv(qualification={})
    store = ps.get_conversation_store()
    run(sale_check._save_amount(KEY, "не помню", "KGS"))
    conv = run(store.get(KEY))
    assert not (getattr(conv, "sale_amount", None) or 0)


def test_amount_with_spaces_and_comma_is_understood():
    """«120 000» и «96,5» с телефона — обычное дело."""
    _conv(qualification={})
    store = ps.get_conversation_store()
    run(sale_check._save_amount(KEY, "120 000", "KGS"))
    assert float(getattr(run(store.get(KEY)), "sale_amount", 0) or 0) == 120000


def test_negative_amount_is_refused():
    _conv(qualification={})
    store = ps.get_conversation_store()
    run(sale_check._save_amount(KEY, "-5000", "KGS"))
    assert not (getattr(run(store.get(KEY)), "sale_amount", None) or 0)


async def _noop(*a, **k):
    return None
