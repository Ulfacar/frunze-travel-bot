from app.agent.validator import SAFE_FLIGHT_REPLY, SAFE_WORKVISA_REPLY, validate_reply
from app.core.branding import PRICE_DISCLAIMER


def test_tours_direct_flight_claim_is_replaced():
    clean, violations = validate_reply(
        "Да, есть прямой рейс Бишкек–Египет в июле. Подберу отель.",
        "tours",
    )

    assert SAFE_FLIGHT_REPLY in clean
    assert "есть прямой рейс" not in clean.lower()
    assert "Подберу отель" in clean
    assert "direct_flight_claim_blocked" in violations


def test_tours_negated_direct_flight_claim_is_not_changed():
    text = "Прямых рейсов нет, скорее всего с пересадкой."
    clean, violations = validate_reply(text, "tours")

    assert clean == text
    assert "direct_flight_claim_blocked" not in violations


def test_tours_price_disclaimer_still_appended_without_flight_claims():
    clean, violations = validate_reply("Отель 5*, 7 ночей от 1000$.", "tours")

    assert PRICE_DISCLAIMER in clean
    assert "tours_price_disclaimer_added" in violations
    assert "direct_flight_claim_blocked" not in violations


def test_flight_claim_not_blocked_outside_tours():
    text = "Да, есть прямой рейс Бишкек–Египет в июле."
    clean, violations = validate_reply(text, "tickets")

    assert clean == text
    assert "direct_flight_claim_blocked" not in violations


def test_multiple_direct_flight_claims_get_one_safe_reply():
    clean, violations = validate_reply(
        "Есть прямой рейс. Чартер тоже есть. Отель подберем.",
        "tours",
    )

    assert clean.count(SAFE_FLIGHT_REPLY) == 1
    assert "Отель подберем" in clean
    assert "direct_flight_claim_blocked" in violations


def test_visa_work_visa_offer_is_replaced():
    clean, violations = validate_reply(
        "Да, оформляем рабочую визу за 2 недели. Можем начать сегодня.",
        "visa",
    )

    assert SAFE_WORKVISA_REPLY in clean
    assert "оформляем рабочую визу" not in clean.lower()
    assert "Можем начать сегодня" in clean
    assert "work_visa_offer_blocked" in violations


def test_visa_work_visa_refusal_is_not_changed():
    text = "К сожалению, рабочими визами не занимаемся."
    clean, violations = validate_reply(text, "visa")

    assert clean == text
    assert "work_visa_offer_blocked" not in violations


def test_work_visa_claim_not_blocked_outside_visa():
    text = "Да, оформляем рабочую визу за 2 недели."
    clean, violations = validate_reply(text, "tours")

    assert clean == text
    assert "work_visa_offer_blocked" not in violations
