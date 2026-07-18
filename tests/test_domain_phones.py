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
