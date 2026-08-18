"""ГЕЙТ: досье живёт и тогда, когда стадия больше не меняется.

Найдено приёмочным прогоном 18.08.2026 (лид 186259, сценарий `drip`). После включения
разбора фактов карточка перестала быть пустой — но обновилась ОДИН раз и застыла:

    ход 3  Направление: Турция · Анталья | Вылет: Бишкек | Даты: 05.09-11.09 | Состав: 2
    ход 4  клиент уходит на Дубай            → в карточке по-прежнему Анталья
    ход 5  клиент говорит «нас четверо»      → в карточке по-прежнему 2
    ход 7  клиент меняет вылет на Ош         → в карточке по-прежнему Бишкек

Причина: бот не дошёл до подборки, поэтому весь ход зовётся только `qualified`. Первый
такой вызов ставит стадию «Выявление потребностей», а каждый следующий упирается в
ранний выход `_advance_and_sync` («стадия уже та») и НЕ доходит до записи досье.

Раньше дефект не проявлялся: в сценарии с подборкой чередовались две разные стадии, и
одна из них всегда проходила мимо раннего выхода. Стоило остаться одной — карточка
замерзает.

Правило, которое здесь закрепляется: **ранний выход относится к стадии, а не к досье.**
Стадию второй раз не двигаем, факты — дописываем. Но только когда они изменились: лишний
вызов портала на каждую реплику нам не нужен.
"""
from __future__ import annotations

import asyncio

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

BOT = "frunze_tours"
KEY = f"{BOT}:996700000091"
LEAD = "186259"
STAGE_MAP = {"qualified": "UC_S0NTF8", "offer_sent": "UC_PNSIIB"}

ANTALYA = {"destination": "Турция", "region": "Анталья", "departure_city": "Бишкек",
           "dates": "05.09.2026-11.09.2026", "tourists": "2"}
DUBAI = dict(ANTALYA, destination="ОАЭ", region="Дубай")


class FakeAdapter:
    def __init__(self, status="UC_S0NTF8", comments=""):
        self.lead = {"ID": LEAD, "STATUS_ID": status, "COMMENTS": comments}
        self.stage_calls: list[tuple[str, str]] = []
        self.comment_calls: list[tuple[str, str]] = []
        self.reads = 0

    async def get_lead(self, lead_id):
        await asyncio.sleep(0)
        self.reads += 1
        return dict(self.lead)

    async def update_stage_status(self, lead_id, status_id):
        await asyncio.sleep(0)
        self.stage_calls.append((str(lead_id), status_id))
        self.lead["STATUS_ID"] = status_id

    async def update_comments(self, lead_id, text):
        await asyncio.sleep(0)
        self.comment_calls.append((str(lead_id), text))
        self.lead["COMMENTS"] = text


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bp.settings, "bitrix_stage_map", dict(STAGE_MAP), raising=False)
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    yield
    flags.reset()


def _conv(*, qualification, stage_by_bot="UC_S0NTF8"):
    store = ps.get_conversation_store()
    run(store.ensure(KEY, bot_id=BOT))
    run(store.add_message(KEY, sender="client", text="хочу в Анталью"))
    run(store.update_meta(KEY, bitrix_lead_id=LEAD, qualification=dict(qualification),
                          assigned_to="ademi"))
    if stage_by_bot:
        run(store.update_meta(KEY, bitrix_stage_by_bot=stage_by_bot))
    return store


def _turn(fake, quali, monkeypatch):
    """Один ход: тот же путь, которым идёт бот (`fire` → `_advance_and_sync`)."""
    monkeypatch.setattr(bp, "_adapter", lambda adapter=None: fake)
    return run(bp._advance_and_sync(KEY, "qualified", dict(quali)))


def test_dossier_updates_when_stage_already_set(monkeypatch):
    """Стадия та же, факты новые — карточка обязана догнать разговор."""
    fake = FakeAdapter()
    _conv(qualification=ANTALYA)
    _turn(fake, DUBAI, monkeypatch)
    assert fake.comment_calls, "досье не переписали при уже выставленной стадии"
    assert "ОАЭ" in fake.comment_calls[-1][1]


def test_stage_is_not_moved_twice(monkeypatch):
    """Инвариант: стадию второй раз не трогаем — правило «только вперёд» цело."""
    fake = FakeAdapter()
    _conv(qualification=ANTALYA)
    _turn(fake, DUBAI, monkeypatch)
    assert fake.stage_calls == []


def test_unchanged_facts_do_not_touch_portal(monkeypatch):
    """Факты не менялись — ни чтения, ни записи: портал не дёргаем на каждую реплику."""
    fake = FakeAdapter()
    _conv(qualification=ANTALYA)
    _turn(fake, ANTALYA, monkeypatch)
    assert fake.comment_calls == []
    assert fake.reads == 0


def test_each_change_reaches_the_card(monkeypatch):
    """Три хода подряд с новыми фактами — три записи, а не одна."""
    fake = FakeAdapter()
    store = _conv(qualification=ANTALYA)
    for quali in (DUBAI,
                  dict(DUBAI, tourists="4", children_ages="7, 10"),
                  dict(DUBAI, tourists="4", children_ages="7, 10", departure_city="Ош")):
        _turn(fake, quali, monkeypatch)
        run(store.update_meta(KEY, qualification=dict(quali)))   # как делает оркестратор
    assert len(fake.comment_calls) == 3
    assert "Ош" in fake.comment_calls[-1][1]
