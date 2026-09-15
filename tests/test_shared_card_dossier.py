# -*- coding: utf-8 -*-
"""Досье на ОБЩЕЙ карточке Открытой линии подписано, и чужие сводки не затираются.

## Откуда задача (прод, замер 11.09.2026)

Открытая линия сажает на одну карточку нескольких наших клиентов: таких карточек 74, на
худшей — 19 человек и 73 телефона внутри. Досье бот писал перезаписью всего комментария,
без подписи, — и менеджер читал сводку последнего написавшего как сводку про всю карточку.
Поля портала мы там не трогали и раньше (`bitrix_lead_fields_enabled`, 14.09), а вот
комментарий трогали.

## Что закрепляем

1. Флаг `dossier_shared_cards_enabled` выключен — поведение ровно прежнее.
2. Включён: наша секция подписана номером клиента, чужие секции остаются на месте.
3. Своя секция обновляется, а не задваивается; свежие клиенты сверху; потолок 10.
4. Обычной карточки (один клиент) подпись не касается.
5. Правило 21.08 не ослаблено: строку менеджера «Клиент: перезвонить...» не затираем.
6. Поля портала на общей карточке по-прежнему не заполняются.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.core import flags
from app.integrations.crm import bitrix_pipeline as bp
from app.integrations.panel import store as ps

LEAD = "188271"
KEY = "frunze_tours:996700111222"
OTHER_KEY = "frunze_tours:996555333444"
COUNTRY = "UF_CRM_1650440002892"
FACTS = {"destination": "Турция", "region": "Анталия", "dates": "05.10.2026-12.10.2026",
         "tourists": "2", "name": "Азамат"}
MARKER = "Досье бота:"


class FakeAdapter:
    def __init__(self, comments=""):
        self.lead = {"ID": LEAD, "STATUS_ID": "UC_Y4VY7B", "COMMENTS": comments}
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


def _conv(key=KEY, *, lead=LEAD, facts=None, minutes_ago=0):
    """Диалог на карточке `lead`. Несколько таких с разными номерами = общая карточка."""
    store = ps.get_conversation_store()
    run(store.ensure(key, bot_id=key.partition(":")[0]))
    run(store.update_meta(key, bitrix_lead_id=lead, funnel="tours",
                          qualification=dict(FACTS if facts is None else facts),
                          bitrix_dossier_by_bot=True))
    conv = run(store.get(key))
    conv.phone = key.rsplit(":", 1)[-1]
    conv.last_message_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return key


def _shared(**kw):
    """Наш диалог плюс сосед по той же карточке — этим карточка и становится общей."""
    key = _conv(**kw)
    _conv(OTHER_KEY, minutes_ago=180)
    return key


def _sections(text):
    return [line for line in text.splitlines() if line.startswith("Клиент:")]


# ---------------- 1. тумблер выключен = прежнее поведение ------------------------------
def test_flag_off_keeps_old_unsigned_behaviour():
    fake = FakeAdapter()
    assert run(bp.sync_dossier(_shared(), adapter=fake)) is True
    assert _sections(fake.comment_writes[-1]) == []
    assert "Направление: Турция, Анталия" in fake.comment_writes[-1]


# ---------------- 2. подпись и чужие секции -------------------------------------------
def test_our_section_is_signed_with_the_client_phone():
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    fake = FakeAdapter()
    assert run(bp.sync_dossier(_shared(), adapter=fake)) is True
    written = fake.comment_writes[-1]
    assert written.startswith(MARKER)
    assert "Клиент: 996700111222, Азамат" in written
    assert "Направление: Турция, Анталия" in written


def test_other_clients_sections_survive():
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    old = (f"{MARKER}\n\nКлиент: 996555333444\nНаправление: ОАЭ\n"
           "Последнее сообщение: 13.09.2026 10:00")
    fake = FakeAdapter(comments=old)
    run(bp.sync_dossier(_shared(), adapter=fake))
    written = fake.comment_writes[-1]
    assert "Клиент: 996555333444" in written and "Направление: ОАЭ" in written
    assert "Клиент: 996700111222, Азамат" in written


def test_our_section_is_replaced_not_duplicated():
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    fake = FakeAdapter()
    key = _shared()
    run(bp.sync_dossier(key, adapter=fake))
    run(bp.sync_dossier(key, adapter=fake))
    assert _sections(fake.comment_writes[-1]).count("Клиент: 996700111222, Азамат") == 1


def test_fresh_clients_come_first():
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    old = (f"{MARKER}\n\nКлиент: 996555333444\nПоследнее сообщение: 01.09.2026 10:00\n\n"
           "Клиент: 996777000111\nПоследнее сообщение: 12.09.2026 10:00")
    fake = FakeAdapter(comments=old)
    run(bp.sync_dossier(_shared(), adapter=fake))
    assert _sections(fake.comment_writes[-1]) == [
        "Клиент: 996700111222, Азамат",
        "Клиент: 996777000111",
        "Клиент: 996555333444",
    ]


def test_legacy_unsigned_dossier_is_adopted_by_its_own_client():
    """Сводка без подписи носит номер владельца в ссылке на диалог — по нему и подписываем."""
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    old = (f"{MARKER}\nНаправление: ОАЭ\n"
           "Диалог: [url=https://frunzetravel.kg/admin?open=frunze_tours%3A996555333444]"
           "https://frunzetravel.kg/admin?open=frunze_tours%3A996555333444[/url]\n"
           "Последнее сообщение: 13.09.2026 10:00")
    fake = FakeAdapter(comments=old)
    run(bp.sync_dossier(_shared(), adapter=fake))
    written = fake.comment_writes[-1]
    assert "Клиент: 996555333444" in written and "Направление: ОАЭ" in written


def test_adopted_legacy_of_our_own_client_does_not_double():
    """Старая сводка — наша же: секция перезаписывается, а не встаёт второй раз."""
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    old = (f"{MARKER}\nНаправление: Египет\n"
           "Диалог: https://frunzetravel.kg/admin?open=frunze_tours%3A996700111222\n"
           "Последнее сообщение: 13.09.2026 10:00")
    fake = FakeAdapter(comments=old)
    run(bp.sync_dossier(_shared(), adapter=fake))
    written = fake.comment_writes[-1]
    assert len(_sections(written)) == 1
    assert "Египет" not in written and "Направление: Турция, Анталия" in written


def test_same_client_written_with_a_plus_is_still_one_section():
    """Формат номера («+996…» против «996…») не должен плодить вторую секцию."""
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    old = (f"{MARKER}\n\nКлиент: +996 700 111 222, Азамат\nНаправление: Египет\n"
           "Последнее сообщение: 13.09.2026 10:00")
    fake = FakeAdapter(comments=old)
    run(bp.sync_dossier(_shared(), adapter=fake))
    assert len(_sections(fake.comment_writes[-1])) == 1


def test_long_card_is_capped_and_says_how_many_are_hidden():
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    others = "\n\n".join(
        f"Клиент: 9967770001{i:02d}\nПоследнее сообщение: 12.09.2026 10:{i:02d}"
        for i in range(14))
    fake = FakeAdapter(comments=f"{MARKER}\n\n{others}")
    run(bp.sync_dossier(_shared(), adapter=fake))
    written = fake.comment_writes[-1]
    assert len(_sections(written)) == bp.MAX_SHARED_SECTIONS
    assert "Ещё клиентов: 5" in written


# ---------------- 3. обычная карточка не меняется --------------------------------------
def test_single_client_card_has_no_signature():
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    fake = FakeAdapter()
    run(bp.sync_dossier(_conv(), adapter=fake))
    assert _sections(fake.comment_writes[-1]) == []


# ---------------- 4. рука человека по-прежнему главнее ---------------------------------
def test_manager_line_with_the_same_label_is_not_overwritten():
    """«Клиент: перезвонить после обеда» — это человек, а не наша секция."""
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    fake = FakeAdapter(comments=f"{MARKER}\nКлиент: перезвонить после обеда")
    run(bp.sync_dossier(_shared(), adapter=fake))
    assert fake.comment_writes == []


def test_manager_free_text_still_stops_us():
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    fake = FakeAdapter(comments="клиент передумал, летят из Оша")
    run(bp.sync_dossier(_shared(), adapter=fake))
    assert fake.comment_writes == []


# ---------------- 5. поля портала на общей карточке ------------------------------------
def test_portal_fields_stay_empty_on_a_shared_card():
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    run(flags.set_flag("bitrix_lead_fields_enabled", True))
    fake = FakeAdapter()
    run(bp.sync_dossier(_shared(), adapter=fake))
    assert fake.field_writes == []


def test_portal_fields_still_filled_on_a_normal_card():
    run(flags.set_flag("dossier_shared_cards_enabled", True))
    run(flags.set_flag("bitrix_lead_fields_enabled", True))
    fake = FakeAdapter()
    run(bp.sync_dossier(_conv(), adapter=fake))
    assert fake.field_writes and fake.field_writes[-1][COUNTRY] == "Турция, Анталия"
