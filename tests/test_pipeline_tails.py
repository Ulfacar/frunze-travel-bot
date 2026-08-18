"""ГЕЙТ двух хвостов конвейера карточек, найденных 18.08.2026.

Написан ДО правки и исполнителем НЕ редактируется. Кажется, что тест неверный —
остановись и спроси, не правь.

## Хвост 1 — продажу видно только у сотни самых старых карточек

Замер на проде: карточек с лидом, попадающих в окно обратного чтения (45 дней), — **1001**,
а `READ_BACK_LIMIT` = 100. Сортировки в запросе нет вовсе, порядок физический, то есть
проверяются самые СТАРЫЕ. Живая проверка: перевёл тестовый лид 186245 в «Подписан» —
обратное чтение не заметило его ни на потолке 100, ни на 400.

Это бьёт в саму цель конвейера («учесть все продажи»): менеджер отмечает сделку на свежем
лиде, а мы её не видим никогда.

Чинится не потолком, а вопросом к порталу: вместо 1001 запроса `crm.lead.get` — один
список `crm.lead.list` с фильтром «статус Подписан, изменён после такого-то». Спрашивать
надо о том, что изменилось, а не опрашивать каждую карточку (тот же закон, что со сторожем
каналов: спрашиваем Wappi, а не гадаем по тишине).

## Хвост 2 — стадии касаний всегда пустые

`BITRIX_STAGE_MAP` содержит `touch_1` → «1 касание» и `touch_2` → «2 касание», но их не
вызывает НИКТО: в коде есть только `qualified` и `offer_sent`. Карточка прыгает с
«Выявление потребностей» сразу в «Предложение отправлено», а колонки касаний в воронке
стоят пустыми — и по ним кажется, что бот не дожимает.

Касание — это отправленный пинг дожима (`app/core/followup.py`), других касаний у бота нет.

## Требуется от реализации

    app/integrations/crm/bitrix24.py
        async list_converted_leads(since: datetime) -> list[dict]   # ID/TITLE/ASSIGNED_BY_ID

    app/integrations/crm/bitrix_pipeline.py
        read_back_once  — спрашивает портал списком, без потолка на наши диалоги

    app/core/followup.py
        после успешного пинга — bitrix_pipeline.fire(..., "touch_1" | "touch_2", ...)
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import flags, followup
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

BOT = "frunze_tours"
STAGE_MAP = {"qualified": "UC_S0NTF8", "offer_sent": "UC_PNSIIB",
             "touch_1": "UC_1I1YV0", "touch_2": "UC_T9AEO4"}


def run(coro):
    return asyncio.run(coro)


class FakeAdapter:
    """Портал: отвечает списком конвертированных и считает ВСЕ обращения к нему."""

    def __init__(self, converted: list[str] | None = None):
        self.converted = converted or []
        self.get_lead_calls = 0
        self.list_calls = 0
        self.deals: list[dict] = []
        self.stage_calls: list[tuple[str, str]] = []
        self.comment_calls: list[tuple[str, str]] = []
        self.leads: dict[str, dict] = {}

    async def list_converted_leads(self, since):
        await asyncio.sleep(0)
        self.list_calls += 1
        return [{"ID": lid, "TITLE": f"tours: {lid}", "ASSIGNED_BY_ID": "96451"}
                for lid in self.converted]

    async def get_lead(self, lead_id):
        await asyncio.sleep(0)
        self.get_lead_calls += 1
        return self.leads.get(str(lead_id),
                              {"ID": lead_id, "STATUS_ID": "UC_S0NTF8", "COMMENTS": ""})

    async def update_stage_status(self, lead_id, status_id):
        await asyncio.sleep(0)
        self.stage_calls.append((str(lead_id), status_id))
        self.leads.setdefault(str(lead_id), {"ID": lead_id, "COMMENTS": ""})["STATUS_ID"] = status_id

    async def update_comments(self, lead_id, text):
        await asyncio.sleep(0)
        self.comment_calls.append((str(lead_id), text))

    async def create_deal(self, fields):
        await asyncio.sleep(0)
        self.deals.append(dict(fields))
        return str(7000 + len(self.deals))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    monkeypatch.setattr(bp.settings, "bitrix_stage_map", dict(STAGE_MAP), raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_deal_category_id", "27", raising=False)
    monkeypatch.setattr(bp.settings, "bitrix_deal_stage_id", "C27:NEW", raising=False)
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    yield
    flags.reset()


def _many_convs(count: int, *, converted_key: str, lead: str) -> None:
    """Много диалогов, интересный — ПОСЛЕДНИЙ: он самый свежий и раньше не проверялся."""
    store = ps.get_conversation_store()
    for i in range(count):
        key = f"{BOT}:99670011{i:04d}"
        run(store.ensure(key, bot_id=BOT))
        run(store.add_message(key, sender="client", text="хочу тур"))
        run(store.update_meta(key, bitrix_lead_id=str(180000 + i),
                              qualification={"budget": "1500 USD"}))
    run(store.ensure(converted_key, bot_id=BOT))
    run(store.add_message(converted_key, sender="client", text="беру"))
    run(store.update_meta(converted_key, bitrix_lead_id=lead,
                          qualification={"budget": "2500 USD"}))


# --- хвост 1: продажу видно на любой карточке, не только на старых -------------

def test_conversion_on_the_freshest_lead_is_seen():
    """Тот самый случай 186245: продажа на самом свежем диалоге из тысячи."""
    key, lead = f"{BOT}:996700000081", "186245"
    _many_convs(150, converted_key=key, lead=lead)
    fake = FakeAdapter(converted=[lead])
    stats = run(bp.read_back_once(adapter=fake))
    assert stats["won"] == 1
    conv = run(ps.get_conversation_store().get(key))
    assert (getattr(conv, "outcome", "") or "") == "won"


def test_portal_is_asked_by_list_not_by_polling_every_card():
    """1001 карточка в окне — столько же `crm.lead.get` мы делать не имеем права."""
    key, lead = f"{BOT}:996700000081", "186245"
    _many_convs(150, converted_key=key, lead=lead)
    fake = FakeAdapter(converted=[lead])
    run(bp.read_back_once(adapter=fake))
    assert fake.list_calls == 1
    assert fake.get_lead_calls <= 1, f"портал опрошен покарточно: {fake.get_lead_calls} раз"


def test_unknown_converted_lead_is_ignored():
    """Портал вернул продажу по чужой карточке — это не наш диалог, молча пропускаем."""
    _many_convs(5, converted_key=f"{BOT}:996700000081", lead="186245")
    fake = FakeAdapter(converted=["999999"])
    stats = run(bp.read_back_once(adapter=fake))
    assert stats["won"] == 0 and stats["errors"] == 0


def test_won_is_counted_once():
    key, lead = f"{BOT}:996700000081", "186245"
    _many_convs(5, converted_key=key, lead=lead)
    fake = FakeAdapter(converted=[lead])
    assert run(bp.read_back_once(adapter=fake))["won"] == 1
    assert run(bp.read_back_once(adapter=fake))["won"] == 0


def test_deal_is_created_with_currency():
    key, lead = f"{BOT}:996700000081", "186245"
    _many_convs(5, converted_key=key, lead=lead)
    run(flags.set_flag("bitrix_autodeal_enabled", True))
    fake = FakeAdapter(converted=[lead])
    run(bp.read_back_once(adapter=fake))
    assert fake.deals and fake.deals[-1]["CURRENCY_ID"] == "USD"
    assert float(fake.deals[-1]["OPPORTUNITY"]) == 2500


def test_autodeal_off_keeps_dry_run():
    key, lead = f"{BOT}:996700000081", "186245"
    _many_convs(5, converted_key=key, lead=lead)
    fake = FakeAdapter(converted=[lead])
    stats = run(bp.read_back_once(adapter=fake))
    assert fake.deals == [] and stats["deals_dry_run"] == 1


# --- хвост 2: касания доезжают до воронки -------------------------------------

def _silent_conv(key: str, *, lead: str, pings: int = 0, stage_by_bot: str = "UC_S0NTF8",
                 silent_hours: int = 30):
    """Молчащий клиент. Часы важны: первый пинг уходит после 24 часов тишины, повторный —
    после 84 (`followup_interval_hours`, ритм ~2 раза в неделю)."""
    store = ps.get_conversation_store()
    run(store.add_message(key, "bot", "вопрос?", channel="whatsapp",
                          bot_id=BOT, chat_id="996700111222@c.us"))
    run(store.update_meta(key, funnel="tours", stage="qualification",
                          bitrix_lead_id=lead, followup_count=pings,
                          bitrix_stage_by_bot=stage_by_bot))
    conv = run(store.get(key))
    conv.last_message_at = datetime.now(timezone.utc) - timedelta(hours=silent_hours)
    return store


def _run_followup(monkeypatch, fired: list):
    async def fake_send(channel, bot_id, chat_id, text):
        return "pmid"

    monkeypatch.setattr(followup.outbound, "send_to_client", fake_send)
    monkeypatch.setattr(followup.settings, "followup_enabled", True)
    monkeypatch.setattr(followup.settings, "followup_after_hours", 24)
    monkeypatch.setattr(followup.settings, "followup_quiet_from", 0)
    monkeypatch.setattr(followup.settings, "followup_quiet_to", 0)
    monkeypatch.setattr(bp, "fire", lambda key, stage, quali: fired.append((key, stage)))
    run(followup.run())


def test_first_ping_moves_card_to_touch_1(monkeypatch):
    key = f"{BOT}:996700111222"
    _silent_conv(key, lead="186300", pings=0)
    fired: list = []
    _run_followup(monkeypatch, fired)
    assert (key, "touch_1") in fired, f"стадия касания не поставлена: {fired}"


def test_second_ping_moves_card_to_touch_2(monkeypatch):
    key = f"{BOT}:996700111222"
    _silent_conv(key, lead="186300", pings=1, silent_hours=100)
    fired: list = []
    _run_followup(monkeypatch, fired)
    assert (key, "touch_2") in fired


def test_third_ping_moves_nothing(monkeypatch):
    """Стадии «3 касание» в карте нет — молчим, а не выдумываем."""
    key = f"{BOT}:996700111222"
    _silent_conv(key, lead="186300", pings=2, silent_hours=100)
    fired: list = []
    _run_followup(monkeypatch, fired)
    assert not [f for f in fired if f[1].startswith("touch")]


def test_ping_without_lead_fires_nothing(monkeypatch):
    """Карточки нет — двигать нечего."""
    key = f"{BOT}:996700111222"
    _silent_conv(key, lead="", pings=0)
    fired: list = []
    _run_followup(monkeypatch, fired)
    assert not [f for f in fired if f[1].startswith("touch")]


def test_touch_never_moves_card_backwards():
    """Инвариант: после «Предложение отправлено» касание НЕ откатывает стадию назад."""
    key = f"{BOT}:996700111222"
    store = _silent_conv(key, lead="186300", pings=0, stage_by_bot="UC_PNSIIB")
    fake = FakeAdapter()
    fake.leads["186300"] = {"ID": "186300", "STATUS_ID": "UC_PNSIIB", "COMMENTS": ""}
    assert run(bp.advance(key, "touch_1", adapter=fake)) == ""
    assert fake.stage_calls == []
    assert store is not None
