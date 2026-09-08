"""ГЕЙТ: очередь контроллера должна двигаться, а не крутиться на одних и тех же.

Написан ДО правки, по замеру прода 08.09.2026.

## Замер

Сутки работы контроллера после включения:

    прогонов 108 | сдвинуто 17 | сводок 1949 | очередь 278 | ошибок 0

Каждый прогон отдавал ОДНО И ТО ЖЕ: `eligible 25, moved 0, dossiers 17, waiting 278`.
Очередь за сутки не сдвинулась: 303 → 303. Разбор логов показал, чем заняты слоты:

* **10 карточек в `JUNK`** дали 815 обращений к порталу за сутки. Терминальный статус
  виден только после запроса, отказ нигде не запоминается — и на следующем прогоне эти
  же десять снова первые в очереди;
* **17 карточек с уже записанной сводкой** переписывались на каждом прогоне: в
  `catchup_once` досье пишется всегда, когда карточка попала в работу, а `dossier_done`
  учитывался только вместе со `stage_done`. Отсюда 1949 записей при 154 карточках —
  по двенадцать переписываний на карточку за сутки.

Итог: 25 слотов лимита заняты теми, кого двигать невозможно или уже нечего делать, и до
278 ждущих очередь не доходит никогда.

## Правило

1. Карточка, про которую портал сказал «терминальная», выбывает из очереди и больше в
   неё не возвращается: двигать её нельзя ни сейчас, ни потом.
2. Сводка пишется, когда её нет. Уже записанную догоняющий проход не переписывает —
   свежие факты в неё доносит живой ход.
3. Слот, освобождённый первыми двумя правилами, достаётся тому, кто реально ждёт.
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
        self.comment_calls: list[str] = []
        self.stage_calls: list[tuple[str, str]] = []

    def add(self, lead_id, status="NEW", comments=""):
        self.leads[str(lead_id)] = {"ID": str(lead_id), "STATUS_ID": status, "COMMENTS": comments}

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
        self.comment_calls.append(str(lead_id))

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
    bp._reset_skip_cache_for_tests()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bp.settings, "bitrix_stage_map", dict(STAGE_MAP), raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_stage_catchup_days", 30, raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_stage_catchup_limit", 3, raising=False)
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    run(flags.set_flag("bitrix_stage_catchup_enabled", True))
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    run(flags.set_flag("dossier_when_intercepted_enabled", True))
    yield
    flags.reset()
    bp._reset_skip_cache_for_tests()


def _conv(key, lead, *, dossier_done=False, stage_by_bot=""):
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id="frunze_tours"))
    run(store.add_message(key, sender="client", text="хочу в Анталью"))
    run(store.update_meta(key, bitrix_lead_id=str(lead), intercepted=True, funnel="tours",
                          qualification={"destination": "Турция"},
                          bitrix_dossier_by_bot=dossier_done))
    if stage_by_bot:
        run(store.update_meta(key, bitrix_stage_by_bot=stage_by_bot))
    conv = run(store.get(key))
    conv.last_message_at = datetime.now(timezone.utc) - timedelta(hours=2)
    return key


# ---------------- терминальные выбывают из очереди ----------------------------------
def test_junk_card_leaves_the_queue_forever():
    """10 карточек в JUNK дали 815 обращений к порталу за сутки — так больше нельзя."""
    fake = FakeAdapter()
    _conv("frunze_tours:996700000001", 501)
    fake.add(501, status="JUNK")
    run(bp.catchup_once(adapter=fake))
    first = len(fake.get_calls)
    run(bp.catchup_once(adapter=fake))
    assert len(fake.get_calls) == first, "терминальную карточку второй раз не запрашиваем"


def test_junk_card_frees_the_slot_for_someone_waiting():
    """Слот, занятый мёртвой карточкой, обязан достаться живой."""
    fake = FakeAdapter()
    for i in range(3):
        _conv(f"frunze_tours:99670000000{i}", 600 + i)
        fake.add(600 + i, status="JUNK")
    _conv("frunze_tours:996700009999", 777)
    fake.add(777, status="NEW")
    run(bp.catchup_once(adapter=fake))      # первый прогон упирается в мёртвых
    run(bp.catchup_once(adapter=fake))      # второй обязан дойти до живой
    assert ("777", "UC_S0NTF8") in fake.stage_calls


# ---------------- сводка не переписывается по кругу ---------------------------------
def test_existing_dossier_is_not_rewritten():
    """1949 записей на 154 карточки — это переписывание одного и того же."""
    fake = FakeAdapter()
    _conv("frunze_tours:996700000010", 801, dossier_done=True)
    fake.add(801, status="NEW")
    run(bp.catchup_once(adapter=fake))
    assert fake.comment_calls == [], "сводка уже записана — переписывать её незачем"


def test_missing_dossier_is_still_written():
    """Ложноположительный, обязан пройти: там, где сводки нет, она появляется."""
    fake = FakeAdapter()
    _conv("frunze_tours:996700000011", 802, dossier_done=False)
    fake.add(802, status="NEW")
    run(bp.catchup_once(adapter=fake))
    assert "802" in fake.comment_calls


# ---------------- очередь реально двигается -----------------------------------------
def test_queue_shrinks_run_after_run():
    """Главный признак здоровья: за несколько прогонов очередь уменьшается."""
    fake = FakeAdapter()
    for i in range(8):
        _conv(f"frunze_tours:9967000001{i:02d}", 900 + i)
        fake.add(900 + i, status="NEW")
    seen = []
    for _ in range(3):
        seen.append(run(bp.catchup_once(adapter=fake))["waiting"])
    assert seen[-1] < seen[0], f"очередь не уменьшается: {seen}"


# ---------------- инварианты не сломаны ---------------------------------------------
def test_terminal_card_is_never_written_to():
    fake = FakeAdapter()
    _conv("frunze_tours:996700000020", 803)
    fake.add(803, status="CONVERTED")
    run(bp.catchup_once(adapter=fake))
    assert fake.stage_calls == [] and fake.comment_calls == []


def test_healthy_card_still_moves():
    fake = FakeAdapter()
    _conv("frunze_tours:996700000021", 804)
    fake.add(804, status="NEW")
    assert run(bp.catchup_once(adapter=fake))["moved"] == 1
