"""WP1B: phone-identity normalization. Pure function, no DB / no network."""
import pytest

from app.domain.models import DomainError
from app.domain.phones import normalize_phone


@pytest.mark.parametrize("raw,expected", [
    ("+996700123456", "996700123456"),
    ("996700123456", "996700123456"),
    ("0700123456", "996700123456"),
    ("700123456", "996700123456"),
    ("996700123456@c.us", "996700123456"),
    ("996700123456@s.whatsapp.net", "996700123456"),
    ("+996 (700) 12-34-56", "996700123456"),
    ("  0700 123 456  ", "996700123456"),
])
def test_kg_forms_collapse_to_canonical(raw, expected):
    assert normalize_phone(raw) == expected


def test_full_international_numbers_keep_their_code():
    assert normalize_phone("+7 701 234 56 78") == "77012345678"   # RU, 11 digits
    assert normalize_phone("+1 202 555 0123") == "12025550123"    # US, 11 digits


def test_cross_bot_stability_same_number_same_result():
    # Same subscriber reached via different surface forms → identical identity value,
    # so the same Contact is found regardless of which bot/profile received it.
    forms = ["+996700123456", "996700123456", "0700123456", "700123456",
             "996700123456@c.us"]
    assert len({normalize_phone(f) for f in forms}) == 1


@pytest.mark.parametrize("raw", [
    "", "   ", "@c.us", "0", "12345", "70012345",   # empty / too short
    "77012345678",                                  # international WITHOUT '+' → ambiguous
    "9967001234",                                   # wrong KG length
    "996700123456789",                              # KG too long
    "letters-only",
    None,
])
def test_ambiguous_or_short_rejected(raw):
    with pytest.raises(DomainError):
        normalize_phone(raw)


# --- assume_e164: источник гарантирует формат (WhatsApp отдаёт E.164 без '+') ---


@pytest.mark.parametrize("raw,expected", [
    ("905078174386", "905078174386"),        # Турция — на проде 22 сообщения, был потерян
    ("905078174386@c.us", "905078174386"),   # тот же с whatsapp-суффиксом
    ("77088657170", "77088657170"),          # Казахстан
    ("998943236050", "998943236050"),        # Узбекистан
    ("8801873125190", "8801873125190"),      # Бангладеш, 13 цифр
    ("971552957733", "971552957733"),        # ОАЭ
])
def test_bare_international_accepted_when_source_guarantees_e164(raw, expected):
    assert normalize_phone(raw, assume_e164=True) == expected


def test_assume_e164_does_not_change_any_currently_valid_result():
    """Флаг только ДОБАВЛЯЕТ приём — ни один проходящий сейчас вход не меняет результата."""
    for raw in ["+996700123456", "996700123456", "0700123456", "700123456",
                "996700123456@c.us", "+7 701 234 56 78", "+1 202 555 0123"]:
        assert normalize_phone(raw, assume_e164=True) == normalize_phone(raw)


def test_assume_e164_still_rejects_telegram_id_range():
    """9-10 цифр — диапазон telegram-id: принять его за номер нельзя ни при каких флагах,
    иначе получим выдуманный Contact с реальным владельцем."""
    for raw in ["123456789", "1234567890"]:
        # 9 цифр трактуются как КГ-абонент (старое правило), 10 — отвергаются.
        if len(raw) == 10:
            with pytest.raises(DomainError):
                normalize_phone(raw, assume_e164=True)
        else:
            assert normalize_phone(raw, assume_e164=True) == "996" + raw


def test_whatsapp_and_plus_form_map_to_one_identity():
    """Один человек — один Contact: whatsapp-форма и '+'-форма дают одно значение."""
    assert (normalize_phone("905078174386", assume_e164=True)
            == normalize_phone("+90 507 817 43 86"))
