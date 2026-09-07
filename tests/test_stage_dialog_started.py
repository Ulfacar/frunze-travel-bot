"""ГЕЙТ: карточка уходит из «Новый лид», как только с клиентом начали работать.

Написан ДО реализации и исполнителем НЕ редактируется.

## Замер, из которого выросла задача (прод, 07.09.2026)

Заказчик не первый раз говорит «карточки по турам не двигаются». Что в проде:

* **340 из 426 туровых лидов за 30 дней стоят в `NEW`**; у виз наоборот — 708 из 751
  двинуты, но двигают их РУКАМИ менеджеры (Медина 322 перевода, Элиза 242), а у туров
  этой привычки нет: Адеми 13, Айсина 0. Значит по турам двигать должен бот;
* механизм бота исправен — 41 движение за 14 дней, 42 из 47 квалифицированных доехали;
* но двигает он ТОЛЬКО по полной квалификации (направление + даты + туристы), а её
  проходят 11% диалогов: **85% забирает менеджер** раньше, чем бот успеет выяснить.
  Нет фактов → нет движения → карточка навсегда в `NEW`;
* отдельный дефект: 27 карточек, уже уехавших ДАЛЬШЕ цели, каждый тик занимали все 25
  слотов лимита (`moved: 0` во всех прогонах за сутки), а 5 реально ждущих не
  обрабатывались вообще.

## Правило

Бот занимает только те стадии, по которым у него есть достоверный факт:

    с клиентом начали работать  → «Выявление потребностей» (UC_S0NTF8)   ← НОВОЕ
    бот отдал подборку          → «Предложение отправлено» (UC_PNSIIB)   (уже работало)
    «Переписка/Недозвоны», касания → не трогаем, это ручные статусы менеджеров
    CONVERTED / JUNK / «не квалифицирован» → ставят только люди

«Начали работать» = менеджер перехватил, ИЛИ диалог закреплён за менеджером, ИЛИ собран
хотя бы один факт, ИЛИ кто-то ответил клиенту. Ни одного признака — карточка остаётся
в `NEW`, и это честно: с лидом действительно никто не работал.

Порядок стадий в портале жёсткий и бот двигает только вперёд:
`NEW(10) → Выявление(20) → Переписка/Недозвоны(30) → касания(40-60) → Предложение(70)`.
Поэтому «Переписку» бот не ставит: она ПОЗЖЕ «Выявления», и заняв её, мы закрыли бы
«Выявление» навсегда.

За флагом `bitrix_stage_dialog_started_enabled`, дефолт OFF — при снятом тумблере
поведение обязано остаться ровно прежним.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

LEAD = "186777"
STAGE_MAP = {
    "dialog_started": "UC_S0NTF8",
    "qualified": "UC_S0NTF8",
    "offer_sent": "UC_PNSIIB",
    "touch_1": "UC_1I1YV0",
    "touch_2": "UC_T9AEO4",
}
FULL_FACTS = {"destination": "Турция", "dates": "октябрь", "tourists": "2 взрослых"}
PARTIAL_FACTS = {"destination": "Турция"}


class FakeAdapter:
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
    run(flags.set_flag("bitrix_stage_catchup_enabled", True))
    yield
    flags.reset()


def _conv(*, key="frunze_tours:996700111222", lead=LEAD, intercepted=False,
          qualification=None, stage_by_bot="", assigned_to="", replies=(),
          age_days=1):
    """Диалог в памяти. `replies` — кто отвечал клиенту после его сообщения."""
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id=key.split(":")[0]))
    run(store.add_message(key, sender="client", text="хочу в Анталью"))
    for sender in replies:
        run(store.add_message(key, sender=sender, text="добрый день"))
    run(store.update_meta(key, bitrix_lead_id=lead, intercepted=intercepted,
                          funnel="tours", qualification=dict(qualification or {})))
    if stage_by_bot:
        run(store.update_meta(key, bitrix_stage_by_bot=stage_by_bot))
    if assigned_to:
        run(store.update_meta(key, assigned_to=assigned_to))
    conv = run(store.get(key))
    conv.last_message_at = datetime.now(timezone.utc) - timedelta(days=age_days)
    return key


def _catchup(fake):
    return run(bp.catchup_once(adapter=fake))


def _stage_of(key):
    return bp._catchup_stage(run(ps.get_conversation_store().get(key)))


# ---------------- новое: диалог начался → «Выявление потребностей» ------------------
def test_intercepted_dialog_without_facts_starts_moving():
    """Главный случай: 85% туровых диалогов забирает менеджер, фактов у бота нет."""
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    key = _conv(intercepted=True)
    fake = FakeAdapter()
    stats = _catchup(fake)
    assert stats["moved"] == 1
    assert fake.lead["STATUS_ID"] == "UC_S0NTF8"
    assert key


def test_answered_dialog_starts_moving():
    """Клиенту ответили — с лидом работают, даже если фактов ещё нет."""
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    _conv(replies=("bot",))
    fake = FakeAdapter()
    assert _catchup(fake)["moved"] == 1
    assert fake.lead["STATUS_ID"] == "UC_S0NTF8"


def test_partial_facts_are_enough_to_leave_new():
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    _conv(qualification=PARTIAL_FACTS)
    fake = FakeAdapter()
    assert _catchup(fake)["moved"] == 1


def test_assigned_dialog_starts_moving():
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    _conv(assigned_to="Адеми")
    fake = FakeAdapter()
    assert _catchup(fake)["moved"] == 1


# ---------------- граница: с лидом никто не работал → карточка остаётся в NEW -------
def test_untouched_lead_stays_in_new():
    """Клиент написал, никто не ответил, менеджер не брал, фактов нет — это и есть NEW."""
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    key = _conv()
    fake = FakeAdapter()
    assert _stage_of(key) == ""
    assert _catchup(fake)["moved"] == 0
    assert fake.lead["STATUS_ID"] == "NEW"


# ---------------- квалификация не деградировала -------------------------------------
def test_full_facts_still_report_qualified():
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    key = _conv(qualification=FULL_FACTS, intercepted=True)
    assert _stage_of(key) == "qualified"


def test_full_facts_move_the_card_as_before():
    key = _conv(qualification=FULL_FACTS, intercepted=True)
    fake = FakeAdapter()
    assert _catchup(fake)["moved"] == 1
    assert fake.lead["STATUS_ID"] == "UC_S0NTF8"
    assert key


# ---------------- починка застревания на лимите -------------------------------------
def test_card_already_further_than_target_is_not_queued():
    """27 таких карточек занимали все 25 слотов лимита и не двигались никогда."""
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    _conv(qualification=FULL_FACTS, stage_by_bot="UC_PNSIIB")
    fake = FakeAdapter(status="UC_PNSIIB")
    stats = _catchup(fake)
    assert stats["eligible"] == 0, "карточка уже дальше цели — её незачем брать в работу"
    assert fake.writes == 0


def test_stuck_cards_do_not_starve_the_ones_that_wait():
    """Ложноположительный: ждущая карточка получает слот, даже если рядом «застрявшие»."""
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    for i in range(30):
        _conv(key=f"frunze_tours:99670000{i:04d}", lead=f"9000{i}",
              qualification=FULL_FACTS, stage_by_bot="UC_PNSIIB")
    _conv(key="frunze_tours:996700999999", lead="777001", intercepted=True)
    fake = FakeAdapter()
    fake.leads["777001"] = {"ID": "777001", "STATUS_ID": "NEW", "COMMENTS": ""}
    for i in range(30):
        fake.leads[f"9000{i}"] = {"ID": f"9000{i}", "STATUS_ID": "UC_PNSIIB", "COMMENTS": ""}
    stats = _catchup(fake)
    assert stats["moved"] == 1
    assert fake.leads["777001"]["STATUS_ID"] == "UC_S0NTF8"


# ---------------- ложноположительные: при снятом тумблере ничего не изменилось ------
def test_flag_off_keeps_todays_behaviour():
    key = _conv(intercepted=True)
    fake = FakeAdapter()
    assert _stage_of(key) == "", "без тумблера диалог без фактов стадии не получает"
    assert _catchup(fake)["moved"] == 0
    assert fake.lead["STATUS_ID"] == "NEW"


def test_flag_off_still_moves_qualified():
    """Снятый тумблер не должен ломать то, что работало до него."""
    _conv(qualification=FULL_FACTS, intercepted=True)
    fake = FakeAdapter()
    assert _catchup(fake)["moved"] == 1


# ---------------- инварианты «человек главнее» остаются в силе ----------------------
def test_manual_move_still_freezes_the_bot():
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    _conv(intercepted=True, stage_by_bot="UC_S0NTF8")
    fake = FakeAdapter(status="UC_1I1YV0")      # менеджер унёс карточку сам
    _catchup(fake)
    assert fake.writes == 0


def test_terminal_status_is_never_touched():
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    _conv(intercepted=True)
    fake = FakeAdapter(status="JUNK")
    _catchup(fake)
    assert fake.writes == 0


def test_stage_never_goes_backwards():
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    _conv(intercepted=True)
    fake = FakeAdapter(status="UC_T9AEO4")
    _catchup(fake)
    assert fake.writes == 0


def test_bot_never_sets_perepiska_or_touch_stages():
    """«Переписка/Недозвоны» и касания — ручные статусы менеджеров, бот их не занимает."""
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    _conv(intercepted=True)
    fake = FakeAdapter()
    _catchup(fake)
    assert all(status not in ("UC_Y4VY7B", "UC_1I1YV0", "UC_T9AEO4", "UC_A492DB")
               for _, status in fake.stage_calls)


def test_per_bot_flag_does_not_leak_to_visas():
    """Заказчик просил трогать только туры: визы включать не просили."""
    run(flags.set_flag("bitrix_stage_dialog_started_enabled:frunze_tours", True))
    _conv(key="getvisa:996700333444", lead="555001", intercepted=True)
    fake = FakeAdapter()
    fake.leads["555001"] = {"ID": "555001", "STATUS_ID": "NEW", "COMMENTS": ""}
    _catchup(fake)
    assert fake.writes == 0


def test_dialog_without_lead_is_not_an_error():
    run(flags.set_flag("bitrix_stage_dialog_started_enabled", True))
    _conv(lead="", intercepted=True)
    fake = FakeAdapter()
    assert _catchup(fake)["errors"] == 0
