"""ГЕЙТ: сделка в Битриксе заводится ЗАПОЛНЕННОЙ, а не пустой.

Написан ДО реализации.

## Замер, из которого выросла задача (прод, 11.09.2026)

Прогнали весь путь на живом диалоге владельца: бот довёл карточку, менеджер нажал
«Оплатил», лид уехал в «Подписан», сделка создалась сама. Открыли её — пусто:

    TITLE        «Al - WhatsApp Wappi: GetVisa»   название канала, а не тура
    COMMENTS     «Диалог: /admin/conversation/…»  голый путь, даже не ссылка
    CONTACT_ID   пусто                            телефона в сделке нет
    SOURCE_ID    пусто                            откуда пришёл клиент — неизвестно

Всё содержание разговора лежало рядом, в лиде: направление, курорт, даты, ночи, состав,
город вылета, питание. В сделку не переносилось ничего. Менеджер, открыв такую сделку,
не видит ни куда летит клиент, ни когда, ни сколько человек, ни телефона.

Это невыполненный пункт исходного ТЗ — `docs/bitrix-integration-spec.md`, «Таблица 2.
Поля сделки (что пишет бот)».

## Правило

1. Название сделки говорит о туре, а не о канале: «Тур: Турция, Аланья · 3 чел · 2 октября».
2. Досье бота переносится в сделку целиком — тем же текстом, что и в лид, не второй копией.
3. В сделке есть ссылка на карточку клиента и на переписку.
4. Источник переносится из лида.
5. Сумму бот НЕ трогает: сколько клиент заплатил, он не знает (решение владельца 11.09).
6. Контакт привязывается, только если тумблер включён; выключен — сделка всё равно
   заводится.
7. Ничего из этого не должно уронить создание сделки: пустая анкета, отсутствие телефона
   и сбой портала на контакте оставляют сделку живой.
"""
from __future__ import annotations

import pytest

from app.integrations.crm import bitrix_pipeline


class Conv:
    """Диалог в форме, которую читает сборка полей сделки."""

    def __init__(self, *, qualification=None, phone="996500494009", name="Al"):
        self.user_id = f"frunze_tours:{phone}"
        self.phone = phone
        self.bot_id = "frunze_tours"
        self.funnel = "tours"
        self.qualification = dict(qualification or {})
        self.messages = []
        self.last_message_at = None
        self.estimated_value = None
        self.estimated_value_currency = ""
        self.name = name


FULL = {"destination": "Турция", "region": "Аланья", "dates": "2 октября",
        "nights": "7", "tourists": "3", "departure_city": "Алматы",
        "meal": "всё включено"}

LEAD = {"ID": "181771", "TITLE": "Al - WhatsApp Wappi: GetVisa",
        "SOURCE_ID": "27|2F099BC3-478D", "ASSIGNED_BY_ID": "96451", "NAME": "Al"}


# ---------------- название ------------------------------------------------------------
def test_title_describes_the_tour_not_the_channel():
    """Менеджер должен опознать сделку в списке, не открывая её."""
    title = bitrix_pipeline.deal_title(Conv(qualification=FULL), LEAD)
    assert "Турция" in title
    assert "Аланья" in title
    assert "WhatsApp Wappi" not in title, title


def test_title_falls_back_to_lead_when_nothing_collected():
    """Ложноположительный, обязан пройти: пустая анкета не ломает название."""
    title = bitrix_pipeline.deal_title(Conv(qualification={}), LEAD)
    assert title == LEAD["TITLE"]


def test_title_survives_a_lead_without_title():
    conv = Conv(qualification={})
    title = bitrix_pipeline.deal_title(conv, {})
    assert conv.phone in title


# ---------------- поля сделки ---------------------------------------------------------
def test_dossier_goes_into_the_deal():
    """Досье переносится тем же текстом, что и в лид, — не второй копией."""
    conv = Conv(qualification=FULL)
    fields = bitrix_pipeline.deal_fields(conv, LEAD)
    comments = fields["COMMENTS"]
    for expected in ("Турция", "Аланья", "Алматы", "2 октября"):
        assert expected in comments, comments


def test_deal_links_to_the_client_card_and_to_the_chat(monkeypatch):
    """Обе ссылки кликабельны — при заданных адресах, как на проде."""
    from app.config import settings

    monkeypatch.setattr(settings, "bitrix_portal_url", "https://getvisakg.bitrix24.kz")
    monkeypatch.setattr(settings, "public_base_url", "https://frunzetravel.kg")
    comments = bitrix_pipeline.deal_fields(Conv(qualification=FULL), LEAD)["COMMENTS"]
    assert "/crm/lead/details/181771/" in comments, "нет ссылки на карточку клиента"
    assert "https://frunzetravel.kg" in comments, "нет ссылки на переписку"


def test_lead_number_survives_without_portal_url(monkeypatch):
    """Ложноположительный: адрес портала не задан — связь с карточкой всё равно видна."""
    from app.config import settings

    monkeypatch.setattr(settings, "bitrix_portal_url", "")
    comments = bitrix_pipeline.deal_fields(Conv(qualification=FULL), LEAD)["COMMENTS"]
    assert "181771" in comments


def test_source_and_assignee_come_from_the_lead():
    fields = bitrix_pipeline.deal_fields(Conv(qualification=FULL), LEAD)
    assert fields["SOURCE_ID"] == LEAD["SOURCE_ID"]
    assert fields["ASSIGNED_BY_ID"] == LEAD["ASSIGNED_BY_ID"]


def test_amount_goes_with_its_currency():
    """Сумма уезжает вместе с валютой — иначе «2500 USD» ляжет как 2500 сом.

    ПОПРАВКА 11.09: сначала я написал здесь «сумму бот не трогает вовсе» — неверно.
    Действующий гейт tests/test_deal_currency.py (замер портала 18.08) требует обратного,
    и он прав: это оценка из разговора, а менеджер правит её в карточке. «Не трогаем»
    относилось к тому, что мы не СПРАШИВАЕМ сумму у менеджера кнопкой, а не к полю.
    """
    conv = Conv(qualification={**FULL, "budget": "2500 USD"})
    fields = bitrix_pipeline.deal_fields(conv, LEAD)
    assert fields["OPPORTUNITY"] == "2500.0"
    assert fields["CURRENCY_ID"] == "USD"


def test_no_amount_when_it_cannot_be_parsed():
    """Ложноположительный: «минимальный» — не сумма. Пустое поле лучше выдуманного."""
    conv = Conv(qualification={**FULL, "budget": "минимальный"})
    assert "OPPORTUNITY" not in bitrix_pipeline.deal_fields(conv, LEAD)


def test_category_and_stage_are_set():
    fields = bitrix_pipeline.deal_fields(Conv(qualification=FULL), LEAD)
    assert fields["CATEGORY_ID"]
    assert fields["STAGE_ID"]


def test_empty_qualification_still_produces_a_valid_deal():
    """Ложноположительный: разговор был пустым — сделка всё равно заводится."""
    fields = bitrix_pipeline.deal_fields(Conv(qualification={}), LEAD)
    assert fields["TITLE"]
    assert fields["CATEGORY_ID"] and fields["STAGE_ID"]


def test_lead_id_is_not_written_directly():
    """`LEAD_ID` в сделке доступен только для чтения — портал отвергнет запись."""
    fields = bitrix_pipeline.deal_fields(Conv(qualification=FULL), LEAD)
    assert "LEAD_ID" not in fields


# ======================================================================================
# ПРОГОН ПО 734 ЖИВЫМ ДИАЛОГАМ 11.09 — состав в названии искажался.
# «Тур: Турция, Анталья · 2 взрослых, 1 ребенок чел · сентябрь» — слово «чел»
# дописывалось всегда, даже когда состав записан фразой и слово там уже есть.
# ======================================================================================

def test_bare_number_of_tourists_gets_the_word():
    title = bitrix_pipeline.deal_title(Conv(qualification={**FULL, "tourists": "3"}), LEAD)
    assert "3 чел" in title, title


@pytest.mark.parametrize("tourists", [
    "2 взрослых, 1 ребенок",
    "2 взрослых",
    "семья из 5 человек",
])
def test_phrase_composition_is_taken_as_is(tourists):
    """Состав фразой берём как есть: «2 взрослых чел» — это мусор в названии."""
    title = bitrix_pipeline.deal_title(Conv(qualification={**FULL, "tourists": tourists}), LEAD)
    assert tourists in title, title
    assert f"{tourists} чел" not in title, title


def test_no_composition_block_when_unknown():
    """Ложноположительный: состава нет — название собирается без него и не ломается."""
    q = {k: v for k, v in FULL.items() if k != "tourists"}
    title = bitrix_pipeline.deal_title(Conv(qualification=q), LEAD)
    assert title.startswith("Тур: ")
    assert "чел" not in title, title
