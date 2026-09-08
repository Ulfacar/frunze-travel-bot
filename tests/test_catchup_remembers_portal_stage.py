"""ГЕЙТ: сходив в портал, контроллер обязан запомнить, что там увидел.

Написан ДО правки, по замеру прода 08.09.2026 (третий слой одной и той же болезни).

## Замер

После починки терминальных карточек и переписывания сводок очередь пошла вниз, но
медленно: 278 → 270 → 265, по 5-8 за прогон при лимите 25. Разбор головы очереди
(25 карточек, реальные статусы из портала):

    уже дальше цели (UC_Y4VY7B)   16
    уже дальше цели (UC_S0NTF8)    3
    уже дальше цели (UC_PNSIIB)    3
    реально поедут                 3

22 карточки из 25 уже стоят на целевой стадии или дальше — их двинул человек или наш же
бот раньше. Но `bitrix_stage_by_bot` у них пуст, поэтому очередь считает их ждущими:
контроллер идёт в портал, получает «двигать некуда» и ничего не запоминает. Следующий
прогон повторяет это ровно с теми же карточками.

Общий корень всех трёх слоёв один: **результат похода в портал не сохраняется**, если
он оказался «делать нечего». Терминальные это уже чинили, здесь — та же правка для
«карточка уже дальше цели».

## Правило

Увидев в портале стадию, до которой мы и так собирались довести (или дальше неё),
контроллер записывает её себе и больше эту карточку не запрашивает. Само собой это не
мешает человеку двигать карточку дальше: следующее расхождение поймает `frozen_manual`.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

STAGE_MAP = {"dialog_started": "UC_S0NTF8", "qualified": "UC_S0NTF8", "offer_sent": "UC_PNSIIB"}


class FakeAdapter:
    def __init__(self):
        self.leads: dict[str, dict] = {}
        self.get_calls: list[str] = []
        self.stage_calls: list[tuple[str, str]] = []

    def add(self, lead_id, status="NEW"):
        self.leads[str(lead_id)] = {"ID": str(lead_id), "STATUS_ID": status, "COMMENTS": ""}

    async def get_lead(self, lead_id):
        await asyncio.sleep(0)
        self.get_calls.append(str(lead_id))
        return dict(self.leads.get(str(lead_id), {"ID": str(lead_id), "STATUS_ID": "NEW", "COMMENTS": ""}))

    async def update_stage_status(self, lead_id, status_id):
        await asyncio.sleep(0)
        self.stage_calls.append((str(lead_id), status_id))
        self.leads.setdefault(str(lead_id), {})["STATUS_ID"] = status_id

    async def update_comments(self, lead_id, text):
        await asyncio.sleep(0)

    async def add_note(self, lead_id, text):
        await asyncio.sleep(0)

    async def list_converted_leads(self, since):
        await asyncio.sleep(0)
        return []


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bp.settings, "bitrix_stage_map", dict(STAGE_MAP), raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_stage_catchup_days", 30, raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_stage_catchup_limit", 25, raising=False)
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    run(flags.set_flag("bitrix_stage_catchup_enabled", True))
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    yield
    flags.reset()


def _conv(key, lead):
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id="frunze_tours"))
    run(store.add_message(key, sender="client", text="хочу в Анталью"))
    run(store.update_meta(key, bitrix_lead_id=str(lead), intercepted=True, funnel="tours",
                          qualification={"destination": "Турция"},
                          bitrix_dossier_by_bot=True))
    conv = run(store.get(key))
    conv.last_message_at = datetime.now(timezone.utc) - timedelta(hours=2)
    return key


def _stage_of(key):
    return getattr(run(ps.get_conversation_store().get(key)), "bitrix_stage_by_bot", "")


# ---------------- карточка, уже уехавшая дальше, выбывает из очереди ----------------
def test_card_further_than_target_is_remembered():
    """16 из 25 в голове очереди стояли на «Переписка/Недозвоны» и запрашивались вечно."""
    fake = FakeAdapter()
    key = _conv("frunze_tours:996700000001", 401)
    fake.add(401, status="UC_Y4VY7B")
    run(bp.catchup_once(adapter=fake))
    assert _stage_of(key) == "UC_Y4VY7B", "увидели стадию в портале — запомнили"


def test_remembered_card_is_not_requested_again():
    fake = FakeAdapter()
    _conv("frunze_tours:996700000002", 402)
    fake.add(402, status="UC_Y4VY7B")
    run(bp.catchup_once(adapter=fake))
    first = len(fake.get_calls)
    run(bp.catchup_once(adapter=fake))
    assert len(fake.get_calls) == first, "второй раз в портал за той же карточкой не ходим"


def test_card_exactly_on_target_also_leaves_the_queue():
    fake = FakeAdapter()
    key = _conv("frunze_tours:996700000003", 403)
    fake.add(403, status="UC_S0NTF8")           # ровно цель `dialog_started`
    run(bp.catchup_once(adapter=fake))
    assert _stage_of(key) == "UC_S0NTF8"


def test_queue_drains_to_zero_when_everyone_is_already_there():
    """Очередь из «уже доехавших» обязана опустеть за один проход, а не жить вечно."""
    fake = FakeAdapter()
    for i in range(10):
        _conv(f"frunze_tours:99670000010{i}", 410 + i)
        fake.add(410 + i, status="UC_Y4VY7B")
    run(bp.catchup_once(adapter=fake))
    assert run(bp.catchup_once(adapter=fake))["waiting"] == 0


# ---------------- ложноположительные: ничего не сломали -----------------------------
def test_card_behind_target_still_moves():
    fake = FakeAdapter()
    key = _conv("frunze_tours:996700000004", 404)
    fake.add(404, status="NEW")
    assert run(bp.catchup_once(adapter=fake))["moved"] == 1
    assert _stage_of(key) == "UC_S0NTF8"
    assert ("404", "UC_S0NTF8") in fake.stage_calls


def test_bot_never_writes_a_stage_it_did_not_verify():
    """Запоминаем только то, что реально увидели в портале, а не то, что хотели поставить."""
    fake = FakeAdapter()
    key = _conv("frunze_tours:996700000005", 405)
    fake.add(405, status="UC_PNSIIB")
    run(bp.catchup_once(adapter=fake))
    assert _stage_of(key) == "UC_PNSIIB"
    assert fake.stage_calls == [], "в портал ничего не писали"


def test_human_moving_further_still_freezes_the_bot():
    """Ложноположительный: правило «человек главнее» осталось в силе."""
    fake = FakeAdapter()
    key = _conv("frunze_tours:996700000006", 406)
    fake.add(406, status="UC_S0NTF8")
    run(bp.catchup_once(adapter=fake))          # запомнили UC_S0NTF8
    fake.leads["406"]["STATUS_ID"] = "UC_1I1YV0"   # человек унёс дальше
    run(bp.catchup_once(adapter=fake))
    assert fake.stage_calls == []
