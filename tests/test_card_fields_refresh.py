# -*- coding: utf-8 -*-
"""Карточка в Битриксе заполнена тем, что бот знает, — а не пустая.

## Замер, из которого выросла задача (прод, 14.09.2026, 165 свежих туровых карточек)

* поля портала «Какая страна ?», «Даты поездки ?», «Количество туристов» пусты во ВСЕХ —
  бот писал только текст в комментарий, а менеджер смотрит в поля;
* у 28 из 52 клиентов, чьё направление бот знал, в карточке его не было: досье записалось
  в начале пустым, а молчаливое дочитывание после перехвата клало факты только в нашу базу.

## Что закрепляем

1. Новые факты доезжают в уже записанное досье (флаг `dossier_refresh_enabled`).
2. Туровые поля портала заполняются — только пустые, только туры, не на общих карточках
   (флаг `bitrix_lead_fields_enabled`).
3. Оба флага выключены — в портал не уходит ничего нового.
"""
import asyncio
from datetime import datetime, timezone

import pytest

from app.channels.base import Message
from app.core import flags
from app.core.orchestrator import Orchestrator
from app.core.state import state_store
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

LEAD = "188331"
KEY = "frunze_tours:996700208905"
COUNTRY, DATES, TOURISTS = ("UF_CRM_1650440002892", "UF_CRM_1650441175540",
                            "UF_CRM_1650441245612")
FACTS = {"destination": "Вьетнам", "region": "Фукуок", "dates": "13.10.2026-21.10.2026",
         "tourists": "2"}
EMPTY_DOSSIER = ("Досье бота:\nДиалог: https://frunzetravel.kg/admin?open=x\n"
                 "Последнее сообщение: 13.09.2026 11:46")


class FakeAdapter:
    def __init__(self, comments=EMPTY_DOSSIER, **fields):
        self.lead = {"ID": LEAD, "STATUS_ID": "UC_Y4VY7B", "COMMENTS": comments, **fields}
        self.comment_writes: list[str] = []
        self.field_writes: list[dict] = []

    async def get_lead(self, lead_id):
        await asyncio.sleep(0)
        return dict(self.lead)

    async def update_comments(self, lead_id, text):
        self.comment_writes.append(text)
        self.lead["COMMENTS"] = text

    async def update_lead_fields(self, lead_id, fields):
        self.field_writes.append(dict(fields))
        self.lead.update(fields)

    async def update_stage_status(self, lead_id, status_id):  # pragma: no cover
        raise AssertionError("стадию здесь трогать нельзя")


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    ps._memory_store._conv.clear()
    flags.reset()
    monkeypatch.setattr(bp.settings, "bitrix24_webhook_url", "https://portal/rest/1/tok")
    run(flags.set_flag("bitrix_pipeline_enabled", True))
    run(flags.set_flag("dossier_when_intercepted_enabled", True))
    yield
    flags.reset()


def _conv(key=KEY, *, funnel="tours", lead=LEAD, facts=None):
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id=key.partition(":")[0]))
    run(store.update_meta(key, bitrix_lead_id=lead, intercepted=True, funnel=funnel,
                          qualification=dict(FACTS if facts is None else facts),
                          bitrix_dossier_by_bot=True))
    run(store.get(key)).last_message_at = datetime.now(timezone.utc)
    return key


def _use(monkeypatch, fake):
    monkeypatch.setattr(bp, "_adapter", lambda adapter=None: adapter or fake)


# ---------------- 1. свежие факты доезжают в досье ------------------------------------
def test_refresh_writes_new_facts_into_an_empty_dossier(monkeypatch):
    run(flags.set_flag("dossier_refresh_enabled", True))
    fake = FakeAdapter()
    _use(monkeypatch, fake)
    assert run(bp.refresh_dossier(_conv(), dict(FACTS))) is True
    assert "Направление: Вьетнам, Фукуок" in fake.comment_writes[-1]
    assert "Состав: 2 туриста" in fake.comment_writes[-1]


def test_refresh_is_silent_when_flag_off(monkeypatch):
    fake = FakeAdapter()
    _use(monkeypatch, fake)
    assert run(bp.refresh_dossier(_conv(), dict(FACTS))) is False
    assert fake.comment_writes == [] and fake.field_writes == []


def test_refresh_keeps_manager_text(monkeypatch):
    """Менеджер дописал своё — досье не перезаписываем (правило 21.08 не ослабляется)."""
    run(flags.set_flag("dossier_refresh_enabled", True))
    fake = FakeAdapter(comments="Досье бота:\nклиент передумал, летят из Оша")
    _use(monkeypatch, fake)
    run(bp.refresh_dossier(_conv(), dict(FACTS)))
    assert fake.comment_writes == []


# ---------------- 2. поля портала ------------------------------------------------------
def test_fields_filled_when_empty(monkeypatch):
    run(flags.set_flag("bitrix_lead_fields_enabled", True))
    fake = FakeAdapter()
    run(bp.sync_dossier(_conv(), adapter=fake))
    assert fake.field_writes == [{COUNTRY: "Вьетнам, Фукуок",
                                  DATES: "13.10.2026-21.10.2026",
                                  TOURISTS: "2 туриста"}]


def test_manager_value_in_field_wins(monkeypatch):
    run(flags.set_flag("bitrix_lead_fields_enabled", True))
    fake = FakeAdapter(**{COUNTRY: "Турция (со слов в офисе)"})
    run(bp.sync_dossier(_conv(), adapter=fake))
    assert fake.field_writes and COUNTRY not in fake.field_writes[-1]
    assert fake.lead[COUNTRY] == "Турция (со слов в офисе)"


def test_fields_filled_even_if_comment_belongs_to_manager(monkeypatch):
    """Комментарий чужой — его не трогаем, но пустое поле от этого пустым не перестаёт."""
    run(flags.set_flag("bitrix_lead_fields_enabled", True))
    fake = FakeAdapter(comments="позвонить после 18:00")
    run(bp.sync_dossier(_conv(), adapter=fake))
    assert fake.comment_writes == []
    assert fake.field_writes and fake.field_writes[-1][COUNTRY] == "Вьетнам, Фукуок"


def test_fields_not_written_when_flag_off():
    fake = FakeAdapter()
    run(bp.sync_dossier(_conv(), adapter=fake))
    assert fake.field_writes == []


def test_visa_lead_fields_untouched():
    run(flags.set_flag("bitrix_lead_fields_enabled", True))
    fake = FakeAdapter()
    run(bp.sync_dossier(_conv("getvisa:996700208905", funnel="visa"), adapter=fake))
    assert fake.field_writes == []


def test_shared_openline_card_untouched():
    """Одна карточка — несколько клиентов: страна первого была бы враньём про остальных."""
    run(flags.set_flag("bitrix_lead_fields_enabled", True))
    _conv("frunze_tours:996700000001")
    key = _conv("frunze_tours:996700000002")
    fake = FakeAdapter()
    run(bp.sync_dossier(key, adapter=fake))
    assert fake.field_writes == []


def test_nothing_known_nothing_written():
    run(flags.set_flag("bitrix_lead_fields_enabled", True))
    fake = FakeAdapter()
    run(bp.sync_dossier(_conv(facts={}), adapter=fake))
    assert fake.field_writes == []


# ---------------- 3. молчаливое дочитывание зовёт обновление только на новость ----------
class _Channel:
    channel = "telegram"

    async def send(self, chat_id, text, **kwargs):  # pragma: no cover
        raise AssertionError("при перехвате бот клиенту не пишет")


def _intercepted_dialog(user_id):
    state = run(state_store.load(user_id))
    state.funnel, state.intercepted, state.stage, state.bot_id = "tours", True, "manager", "frunze_tours"
    run(state_store.save(state))
    store = ps.get_conversation_store()
    run(store.ensure(user_id, bot_id="frunze_tours"))
    run(store.update_meta(user_id, funnel="tours", stage="manager", intercepted=True))


def _say(user_id, text):
    run(Orchestrator(channel=_Channel()).handle(
        Message(channel="telegram", user_id=user_id, chat_id="42", text=text)))


def test_silent_reading_fires_refresh_only_on_news(monkeypatch):
    run(flags.set_flag("facts_when_silent_enabled", True))
    fired: list[dict] = []
    monkeypatch.setattr(bp, "fire_dossier", lambda key, q: fired.append(dict(q)))
    _intercepted_dialog("refresh-1")
    _say("refresh-1", "Хотели тур на двоих в Турцию с 7 по 14 октября")
    assert len(fired) == 1 and fired[0].get("destination") == "Турция"
    _say("refresh-1", "Да, в Турцию")
    assert len(fired) == 1, "повтор уже известного не должен стоить порталу записи"
