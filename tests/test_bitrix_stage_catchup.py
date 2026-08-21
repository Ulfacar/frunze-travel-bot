"""Карточка едет по фактам, даже когда диалог ведёт менеджер (тумблер, дефолт OFF).

## Замер, из которого выросла задача (прод, 21.08.2026)

Заказчик: «нужно, чтобы битрикс карточки работали по турам». Что нашлось в проде:

* туровых диалогов за август — 333, лид заведён у 326, а стадию бот двинул **0 раз**
  (на тест-боте `frunze_tours_tg` — 8 из 10, то есть механизм исправен);
* порог `_is_qualified` проходят 72 диалога, но не перехвачены из них лишь **8**:
  перехвачено 69% диалогов на `frunze_tours` и 88% на `frunze_tours_sezim`;
* в живом портале 45 из 59 туровых лидов стоят в `NEW`, 7 в `JUNK`, 7 в `UC_Y4VY7B` —
  менеджеры карточки почти не двигают, поэтому «бот перетрёт ручное» — риск бумажный;
* `run_turn` при перехвате выходит первой строкой, значит `_sync_qualified_if_ready`
  для таких диалогов не вызывается НИКОГДА — одного тумблера мало, нужен догоняющий
  проход по уже накопленным фактам.

## Что закрепляем

Перехват означает «менеджер ПИШЕТ клиенту», а не «менеджер ДВИГАЛ карточку». Второе
по-прежнему свято: `frozen_manual`, терминальные статусы и движение только вперёд
остаются нетронутыми — и проверяются здесь же.

Правило гейта 17.08 (`test_intercepted_dialog_is_not_moved`) НЕ отменено: при снятом
тумблере оно действует дословно, и тот файл не редактировался.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

LEAD = "186055"
STAGE_MAP = {
    "qualified": "UC_S0NTF8",
    "offer_sent": "UC_PNSIIB",
    "touch_1": "UC_1I1YV0",
    "touch_2": "UC_T9AEO4",
}
# Полный набор фактов по турам — ровно то, что требует `runner._is_qualified`.
FULL_FACTS = {"destination": "Турция", "dates": "октябрь", "tourists": "2 взрослых"}


class FakeAdapter:
    """Портал с ОТДЕЛЬНЫМ состоянием на каждый лид.

    Общий на всех лид — ловушка: первая же сдвинутая карточка «продвигала» и все
    остальные, и проход выглядел сломанным там, где сломан был фейк.
    """

    def __init__(self, status="NEW"):
        self.default_status = status
        self.leads: dict[str, dict] = {}
        self.stage_calls: list[tuple[str, str]] = []

    def _lead(self, lead_id):
        return self.leads.setdefault(
            str(lead_id), {"ID": str(lead_id), "STATUS_ID": self.default_status, "COMMENTS": ""})

    @property
    def lead(self):
        return self._lead(LEAD)

    async def get_lead(self, lead_id):
        await asyncio.sleep(0)
        return dict(self._lead(lead_id))

    async def update_stage_status(self, lead_id, status_id):
        await asyncio.sleep(0)
        self.stage_calls.append((str(lead_id), status_id))
        self._lead(lead_id)["STATUS_ID"] = status_id

    async def update_comments(self, lead_id, text):
        await asyncio.sleep(0)

    async def add_note(self, lead_id, text):
        await asyncio.sleep(0)

    async def list_converted_leads(self, since):
        await asyncio.sleep(0)
        return []

    @property
    def writes(self):
        return len(self.stage_calls)


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
    yield
    flags.reset()


def _conv(*, key="frunze_tours:996700111222", lead=LEAD, intercepted=False,
          qualification=None, stage_by_bot="", funnel="tours", age_days=1):
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id="frunze_tours"))
    run(store.add_message(key, sender="client", text="хочу в Анталью"))
    run(store.update_meta(key, bitrix_lead_id=lead, intercepted=intercepted,
                          funnel=funnel,
                          qualification=dict(qualification or {})))
    if stage_by_bot:
        run(store.update_meta(key, bitrix_stage_by_bot=stage_by_bot))
    conv = run(store.get(key))
    conv.last_message_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    return key


def _catchup(fake):
    return run(bp.catchup_once(adapter=fake))


# ---------------- тумблер снят: гейт 17.08 действует дословно -----------------------
def test_off_by_default_intercepted_dialog_still_frozen():
    fake = FakeAdapter()
    key = _conv(intercepted=True, qualification=FULL_FACTS)

    assert run(bp.advance(key, "qualified", adapter=fake)) == ""
    assert fake.writes == 0


def test_off_by_default_catchup_touches_nothing():
    fake = FakeAdapter()
    _conv(intercepted=True, qualification=FULL_FACTS)

    stats = _catchup(fake)

    assert fake.writes == 0
    assert stats["moved"] == 0


# ---------------- тумблер включён: карточка догоняет факты ---------------------------
def _enable():
    run(flags.set_flag("bitrix_stage_catchup_enabled", True))


def test_intercepted_dialog_with_full_facts_moves():
    _enable()
    fake = FakeAdapter(status="NEW")
    key = _conv(intercepted=True, qualification=FULL_FACTS)

    assert run(bp.advance(key, "qualified", adapter=fake)) == "UC_S0NTF8"
    assert fake.stage_calls == [(LEAD, "UC_S0NTF8")]


def test_catchup_moves_the_backlog():
    """Тот самый случай: факты собраны, менеджер ведёт диалог, карточка стоит в NEW."""
    _enable()
    fake = FakeAdapter(status="NEW")
    _conv(intercepted=True, qualification=FULL_FACTS)

    stats = _catchup(fake)

    assert stats["moved"] == 1
    assert fake.stage_calls == [(LEAD, "UC_S0NTF8")]


def test_catchup_skips_dialogs_without_enough_facts():
    _enable()
    fake = FakeAdapter(status="NEW")
    _conv(intercepted=True, qualification={"destination": "Турция"})   # ни дат, ни туристов

    stats = _catchup(fake)

    assert stats["moved"] == 0
    assert fake.writes == 0


def test_catchup_skips_dialogs_without_lead():
    _enable()
    fake = FakeAdapter(status="NEW")
    _conv(lead="", intercepted=True, qualification=FULL_FACTS)

    assert _catchup(fake)["moved"] == 0
    assert fake.writes == 0


def test_catchup_ignores_dialogs_older_than_window():
    _enable()
    fake = FakeAdapter(status="NEW")
    _conv(intercepted=True, qualification=FULL_FACTS, age_days=90)

    assert _catchup(fake)["moved"] == 0
    assert fake.writes == 0


def test_catchup_does_not_repeat_itself():
    """Второй проход по той же карточке не должен снова дёргать портал."""
    _enable()
    fake = FakeAdapter(status="NEW")
    _conv(intercepted=True, qualification=FULL_FACTS)

    _catchup(fake)
    before = fake.writes
    _catchup(fake)

    assert fake.writes == before


# ---------------- ручное по-прежнему важнее бота -------------------------------------
def test_manual_move_still_freezes_the_bot():
    """Стадию меняли руками (она не совпала с нашей отметкой) — бот не вмешивается."""
    _enable()
    fake = FakeAdapter(status="UC_Y4VY7B")            # менеджер увёл карточку сам
    key = _conv(intercepted=True, qualification=FULL_FACTS, stage_by_bot="UC_S0NTF8")

    assert run(bp.advance(key, "offer_sent", adapter=fake)) == ""
    assert fake.writes == 0


def test_terminal_status_is_never_touched():
    _enable()
    for status in ("CONVERTED", "JUNK", "UC_R8BD0W"):
        ps._memory_store._conv.clear()
        fake = FakeAdapter(status=status)
        key = _conv(intercepted=True, qualification=FULL_FACTS)

        assert run(bp.advance(key, "qualified", adapter=fake)) == ""
        assert fake.writes == 0


def test_stage_never_goes_backwards():
    """Карточка уже дальше по воронке — назад не тянем даже с включённым тумблером."""
    _enable()
    fake = FakeAdapter(status="UC_PNSIIB")            # «Предложение отправлено»
    key = _conv(intercepted=True, qualification=FULL_FACTS)

    assert run(bp.advance(key, "qualified", adapter=fake)) == ""
    assert fake.writes == 0


def test_catchup_never_claims_offer_sent():
    """«Подборку отдали» знает только живой ход — задним числом не выдумываем."""
    _enable()
    fake = FakeAdapter(status="NEW")
    _conv(intercepted=True, qualification=FULL_FACTS)

    _catchup(fake)

    assert [s for _, s in fake.stage_calls] == ["UC_S0NTF8"]
    assert "UC_PNSIIB" not in [s for _, s in fake.stage_calls]


def test_catchup_respects_per_tick_limit(monkeypatch):
    """Портал не любит залпов: за тик двигаем не больше лимита."""
    _enable()
    monkeypatch.setattr(bp.settings, "bitrix_stage_catchup_limit", 2, raising=False)
    fake = FakeAdapter(status="NEW")
    for n in range(5):
        _conv(key=f"frunze_tours:99670011122{n}", lead=f"18605{n}",
              intercepted=True, qualification=FULL_FACTS)

    assert _catchup(fake)["moved"] == 2
