"""ГЕЙТ: карточка передачи менеджеру по формату приложения Б.4.

Написан ДО реализации и исполнителем НЕ редактируется.

Карточка — единственное, что получает человек от въездного бота. Бот сознательно не
доводит сделку: он квалифицирует и отдаёт. Значит потеря строки в карточке означает, что
менеджер начнёт разговор с клиентом заново, и клиент это заметит.

Отдельно закреплены два честных отказа, которые обязаны быть ВИДНЫ в карточке, а не
молча пусты: цены не называются по решению владельца, а остаток дней не считается, потому
что ТЗ это запрещает.
"""
import pytest

from app.core import entry_card
from app.knowledge.entry_regime import EntryQuery, EntryVerdict, RegistrationTerm, UnitRef, evaluate, resolve_citizenship

# Двенадцать подписей строк из PDF, с. 88.
REQUIRED_LABELS = (
    "ЛИД", "Клиент:", "Гражданство:", "Цель:", "Режим:", "Регистрация:",
    "Основание:", "Приглашающая сторона:", "Семья/группа:", "Риски/флаги:",
    "Ориентир стоимости:", "Причина передачи:",
)


@pytest.fixture()
def filled():
    return {
        "name": "Rajesh",
        "phone": "996700111222",
        "channel": "whatsapp",
        "kg_entry": {
            "citizenship": "IND", "document_type": "ordinary",
            "purpose": "business_meeting", "location": "abroad",
            "entry_on": "2026-11-10", "exit_on": "2026-11-20",
            "applicants_count": 1, "language": "en", "client_type": "B2C",
            "inviter": "ОсОО «Пример», ИНН 123",
            "flags": ["Срочно"], "handoff_reason": "квалификация завершена",
        },
    }


def _verdict(country):
    iso = resolve_citizenship(country)
    return evaluate(EntryQuery(citizenship_iso3=iso))


# --- A. Все двенадцать строк на месте ------------------------------------------

def test_every_line_of_appendix_b4_is_present(filled):
    card = entry_card.render(filled, _verdict("Индия"))
    missing = [label for label in REQUIRED_LABELS if label not in card]
    assert missing == [], f"из карточки Б.4 пропали строки: {missing}"


def test_card_works_on_an_empty_dialog():
    """Клиент написал одну реплику и замолчал — карточка всё равно читаемая."""
    card = entry_card.render({}, None)
    assert all(label in card for label in REQUIRED_LABELS)
    assert "не выяснено" in card


# --- B. Данные клиента попадают в карточку -------------------------------------

def test_client_data_is_rendered(filled):
    card = entry_card.render(filled, _verdict("Индия"))
    assert "Rajesh" in card and "996700111222" in card
    assert "IND" in card
    assert "деловая встреча" in card, "цель не переведена на человеческий язык"
    assert "за рубежом" in card
    assert "2026-11-10" in card and "2026-11-20" in card
    assert "Срочно" in card


def test_document_type_is_human_readable():
    data = {"kg_entry": {"document_type": "un_lp"}}
    assert "документ ООН" in entry_card.render(data, None)


# --- C. Режим и регистрация из движка ------------------------------------------

def test_visa_free_regime_shows_limit_and_permit(filled):
    card = entry_card.render(filled, _verdict("Россия"))
    assert "безвиз" in card
    assert "90/180" in card
    assert "без Единого разрешения" in card


def test_visa_required_regime_shows_the_procedure(filled):
    card = entry_card.render(filled, _verdict("Нигерия"))
    assert "виза" in card
    assert "ГКНБ" in card, "не указано согласование ГКНБ для общего порядка"


def test_registration_term_is_rendered(filled):
    assert "освобождение 30 дн" in entry_card.render(filled, _verdict("Россия"))
    assert "5 раб. дн" in entry_card.render(filled, _verdict("Узбекистан"))


def test_uzbekistan_shows_both_deadline_and_term(filled):
    """Узбекистан: учёт за 5 рабочих дней, а оформляется регистрация на 60 дней."""
    card = entry_card.render(filled, _verdict("Узбекистан"))
    assert "5 раб. дн" in card and "60 дн" in card


# --- D. Основание обязательно (Б.2 п.4) ----------------------------------------

def test_basis_names_units_sections_and_pages(filled):
    card = entry_card.render(filled, _verdict("Россия"))
    assert "KG.VF.EAEU" in card
    assert "с. " in card, "в основании нет страницы ТЗ"
    assert "не подтверждено" in card, \
        "менеджер не видит, что правило ещё не прошло приёмку"


def test_source_label_is_visible_to_the_manager(filled):
    """Таджикистан помечен `verify` — менеджер обязан это видеть в карточке."""
    card = entry_card.render(filled, _verdict("Таджикистан"))
    assert "метка verify" in card


# --- E. Честные отказы видны, а не пусты ---------------------------------------

def test_prices_are_explicitly_not_quoted(filled):
    card = entry_card.render(filled, _verdict("Россия"))
    assert "не называется" in card
    assert "$" not in card


def test_withheld_reasons_reach_the_manager(filled):
    """Чего бот НЕ сказал клиенту — важнее того, что сказал."""
    card = entry_card.render(filled, _verdict("Россия"))
    assert "Не сказано клиенту:" in card
    assert "not_confirmed" in card


# --- F. Производные формы ------------------------------------------------------

def test_dossier_lines_drop_the_lead_header(filled):
    lines = entry_card.dossier_lines(filled, _verdict("Россия"))
    assert lines and not lines[0].startswith("ЛИД")
    assert any("Режим:" in line for line in lines)


def test_request_line_is_one_short_line(filled):
    line = entry_card.request_line(filled, _verdict("Россия"))
    assert "\n" not in line and len(line) < 160
    assert "въезд в КР" in line and "IND" in line
