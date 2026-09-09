"""ГЕЙТ: карточку, которую ведёт человек, очередь больше не перебирает.

Написан ДО правки, по замеру прода 09.09.2026 (четвёртый слой одной и той же болезни).

## Замер

После перевода карточек в честную стадию очередь пошла вниз и встала на 43 при нулевом
движении. Разбор остатка по реальным статусам портала:

    человек двинул (UC_Y4VY7B)   22
    человек двинул (UC_1I1YV0)    3

Это `frozen_manual`: стадия в портале не совпадает с нашей отметкой, значит карточку
трогал человек, и бот замирает. Замирает правильно — но результат снова НИГДЕ НЕ
ЗАПОМИНАЕТСЯ, и на следующем прогоне эти же карточки первыми занимают слоты лимита.
Очередь стоит, до живых карточек дело не доходит.

Тот же корень, что у терминальных и у «уже дальше цели»: сходили в портал, получили
«трогать нельзя» и забыли об этом.

## Правило

1. Узнав, что карточку ведёт человек, контроллер запоминает это и больше её не
   запрашивает — слот достаётся тому, кто ждёт.
2. Само правило «человек главнее» не меняется ни на йоту: бот по-прежнему НЕ пишет в
   портал по такой карточке. Гейты 17.08 (`test_manual_move_freezes_bot_forever`) и
   21.08 (`test_manual_move_still_freezes_the_bot`) остаются в силе и не редактируются.
3. Отметка живёт неделю: за это время карточка обычно закрывается, а если нет — стоит
   посмотреть на неё заново, вдруг человек её отпустил.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import flags
from app.core import pipeline_metrics as pm
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

STAGE_MAP = {"dialog_started": "UC_Y4VY7B", "qualified": "UC_S0NTF8", "offer_sent": "UC_PNSIIB"}


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
    pm._reset_for_tests()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bp.settings, "bitrix_stage_map", dict(STAGE_MAP), raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_stage_catchup_days", 30, raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_stage_catchup_limit", 2, raising=False)
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    run(flags.set_flag("bitrix_stage_catchup_enabled", True))
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    yield
    flags.reset()
    pm._reset_for_tests()


def _conv(key, lead, *, stage_by_bot=""):
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id="frunze_tours"))
    run(store.add_message(key, sender="client", text="хочу в Анталью"))
    run(store.update_meta(key, bitrix_lead_id=str(lead), intercepted=True, funnel="tours",
                          qualification={}, bitrix_dossier_by_bot=True))
    if stage_by_bot:
        run(store.update_meta(key, bitrix_stage_by_bot=stage_by_bot))
    conv = run(store.get(key))
    conv.last_message_at = datetime.now(timezone.utc) - timedelta(hours=2)
    return key


# ---------------- карточка под человеком выбывает из перебора -----------------------
def test_human_led_card_is_not_requested_twice():
    """22 такие карточки держали очередь на месте, запрашиваясь каждый прогон."""
    fake = FakeAdapter()
    _conv("frunze_tours:996700000001", 301, stage_by_bot="UC_S0NTF8")
    fake.add(301, status="UC_1I1YV0")           # человек унёс карточку сам
    run(bp.catchup_once(adapter=fake))
    first = len(fake.get_calls)
    run(bp.catchup_once(adapter=fake))
    assert len(fake.get_calls) == first, "второй раз за той же карточкой не ходим"


def test_slot_goes_to_the_one_who_waits():
    fake = FakeAdapter()
    for i in range(2):
        _conv(f"frunze_tours:99670000000{i}", 310 + i, stage_by_bot="UC_S0NTF8")
        fake.add(310 + i, status="UC_1I1YV0")
    _conv("frunze_tours:996700009999", 399)
    fake.add(399, status="NEW")
    run(bp.catchup_once(adapter=fake))          # первый прогон упирается в «человеческие»
    run(bp.catchup_once(adapter=fake))          # второй обязан дойти до живой
    assert ("399", "UC_Y4VY7B") in fake.stage_calls


def test_queue_stops_counting_human_led_cards():
    fake = FakeAdapter()
    for i in range(4):
        _conv(f"frunze_tours:9967000001{i:02d}", 320 + i, stage_by_bot="UC_S0NTF8")
        fake.add(320 + i, status="UC_1I1YV0")
    run(bp.catchup_once(adapter=fake))
    run(bp.catchup_once(adapter=fake))
    assert run(bp.catchup_once(adapter=fake))["waiting"] == 0


# ---------------- правило «человек главнее» не тронуто ------------------------------
def test_bot_still_writes_nothing_to_such_a_card():
    """Ложноположительный, обязан пройти: заморозка остаётся заморозкой."""
    fake = FakeAdapter()
    _conv("frunze_tours:996700000002", 302, stage_by_bot="UC_S0NTF8")
    fake.add(302, status="UC_1I1YV0")
    run(bp.catchup_once(adapter=fake))
    run(bp.catchup_once(adapter=fake))
    assert fake.stage_calls == []


def test_advance_itself_is_unchanged():
    """Прямой вызов `advance` по такой карточке ведёт себя ровно как раньше."""
    fake = FakeAdapter()
    key = _conv("frunze_tours:996700000003", 303, stage_by_bot="UC_S0NTF8")
    fake.add(303, status="UC_A492DB")
    assert run(bp.advance(key, "offer_sent", adapter=fake)) == ""
    assert fake.stage_calls == []


def test_normal_card_is_untouched_by_the_new_rule():
    """Ложноположительный: обычная карточка едет как ехала."""
    fake = FakeAdapter()
    _conv("frunze_tours:996700000004", 304)
    fake.add(304, status="NEW")
    assert run(bp.catchup_once(adapter=fake))["moved"] == 1
