"""ГЕЙТ: пять ремней безопасности для въездной ветки.

Написан ДО реализации и исполнителем НЕ редактируется.

Промпт — это просьба, а не гарантия. Модель под давлением клиента («ну скажите хоть
примерно сколько») соскальзывает в точные цифры, обещания и ссылки на закон, которого
не читала. Поэтому запреты ТЗ стоят на выходе, кодом, и срабатывают независимо от того,
что было в промпте.

Ремни ровно по приложению Б.7 («нельзя / можно») и Б.1 («бот не делает»), плюс решение
владельца 21.10 «бот цен не называет вообще».

Отличие от выездной ветки существенное и намеренное: там гарантии и цены только
ЛОГИРУЮТСЯ, здесь — ПОДМЕНЯЮТСЯ. Выездной бот продаёт услугу по официальному прайсу,
въездной излагает закон чужой страны человеку, который на этом законе может потерять
деньги и получить запрет на въезд.
"""
import pytest

from app.agent.validator import validate_reply

PROFILE = "kg_entry"


def _check(text, **kw):
    return validate_reply(text, "visa", profile=PROFILE, **kw)


# --- A. Профиль не задан — ничего не меняется ----------------------------------

@pytest.mark.parametrize("funnel", ["tours", "visa", "tickets", None])
def test_without_profile_behaviour_is_unchanged(funnel):
    """Старые воронки не должны почувствовать появление профиля."""
    text = "Виза стоит $50, гарантируем одобрение."
    assert validate_reply(text, funnel) == validate_reply(text, funnel, profile=None)


# --- B. Ремень 1: цены ---------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Консульский сбор составит $50, наши услуги 50 долларов.",
    "Это будет стоить 5000 сом.",
    "Пошлина — 1 113 сом за регистрацию.",
])
def test_prices_are_replaced_not_just_logged(text):
    clean, violations = _check(text)
    assert "kg_entry_price_blocked" in violations
    assert "$" not in clean and "сом" not in clean.lower(), \
        f"сумма дошла до клиента: {clean!r}"


def test_price_free_text_survives_untouched():
    text = "Для поездки в Кыргызстан понадобится загранпаспорт."
    clean, violations = _check(text)
    assert clean == text
    assert "kg_entry_price_blocked" not in violations


# --- C. Ремень 2: гарантии (Б.7) ------------------------------------------------

@pytest.mark.parametrize("text", [
    "Гарантируем одобрение визы.",
    "Визу точно дадут, не переживайте.",
    "Одобрение 100%.",
])
def test_guarantees_are_replaced(text):
    clean, violations = _check(text)
    assert "kg_entry_guarantee_blocked" in violations
    assert "100" not in clean
    assert "гаранти" not in clean.lower() or "не гаранти" in clean.lower()


def test_honest_wording_about_the_decision_is_allowed():
    text = "Решение принимает МИД Кыргызстана, мы отвечаем за подготовку документов."
    clean, violations = _check(text)
    assert clean == text and "kg_entry_guarantee_blocked" not in violations


# --- D. Ремень 3: неподтверждённое правило --------------------------------------

@pytest.mark.parametrize("text", [
    "Вы можете находиться 90 дней без визы.",
    "Безвизовый срок — 60 дней в каждом периоде 120 дней.",
    "You can stay 30 days without a visa.",
    "Вам нужна виза в общем порядке.",
    "Виза не нужна.",
])
def test_rules_are_blocked_when_nothing_is_confirmed(text):
    """Пусто в `allowed_claims` ⇒ ни одно правило произнести нельзя."""
    clean, violations = _check(text, allowed_claims=frozenset())
    assert "kg_entry_unconfirmed_claim_blocked" in violations, \
        f"неподтверждённое правило дошло до клиента: {text!r}"
    assert clean != text


def test_rules_pass_when_the_matching_field_is_confirmed():
    text = "Вы можете находиться 90 дней без визы."
    clean, violations = _check(text, allowed_claims=frozenset({"regime", "stay_limit"}))
    assert "kg_entry_unconfirmed_claim_blocked" not in violations
    assert clean == text


def test_registration_claim_needs_its_own_permission():
    """Подтверждённый режим не разрешает говорить про срок регистрации."""
    text = "Зарегистрироваться нужно в течение 5 рабочих дней."
    _, violations = _check(text, allowed_claims=frozenset({"regime", "stay_limit"}))
    assert "kg_entry_unconfirmed_claim_blocked" in violations


def test_neutral_numbers_are_not_mistaken_for_rules():
    """Число в ответе не всегда правило: «2 фотографии» — не срок и не лимит."""
    text = "Понадобятся 2 фотографии на белом фоне."
    clean, violations = _check(text, allowed_claims=frozenset())
    assert "kg_entry_unconfirmed_claim_blocked" not in violations
    assert clean == text


# --- E. Ремень 4: сканы до согласия (Б.1) ---------------------------------------

@pytest.mark.parametrize("text", [
    "Пришлите, пожалуйста, скан паспорта.",
    "Отправьте фото паспорта и адрес проживания.",
    "Please send your passport scan.",
    "Загрузите копию паспорта.",
])
def test_documents_are_not_requested_before_consent(text):
    clean, violations = _check(text, consent_given=False)
    assert "kg_entry_scan_before_consent_blocked" in violations, \
        f"бот попросил документы до согласия на обработку данных: {text!r}"
    assert clean != text


def test_documents_may_be_requested_after_consent():
    text = "Пришлите, пожалуйста, скан паспорта."
    clean, violations = _check(text, consent_given=True)
    assert "kg_entry_scan_before_consent_blocked" not in violations
    assert clean == text


# --- F. Ремень 5: запрещённые формулировки Б.7 ----------------------------------

@pytest.mark.parametrize("text,must_go", [
    ("Можно немного поработать по туристической визе.", "поработать по туристической"),
    ("Регистрация продлит ваш безвизовый срок.", "продлит"),
    ("Штраф заплатите в аэропорту при выезде.", "аэропорту"),
    ("Туристическую визу мы вам продлим.", "продлим"),
    ("Ускорим по знакомству.", "по знакомству"),
    ("Можете оставаться в стране, пока заявку рассматривают.", "оставаться"),
])
def test_forbidden_wordings_from_appendix_b7(text, must_go):
    clean, violations = _check(text, allowed_claims=frozenset(dict.fromkeys(
        ("regime", "stay_limit", "registration", "unified_permit"))))
    assert any(v.startswith("kg_entry_forbidden_") for v in violations), \
        f"запрещённая формулировка Б.7 прошла: {text!r}"
    assert must_go not in clean.lower()


def test_allowed_counterparts_survive():
    """«Можно» из той же таблицы Б.7 проходить обязано, иначе бот онемеет."""
    for text in ("Работать по туристической визе нельзя — для работы нужно Единое разрешение.",
                 "Регистрация не продлевает безвизовый срок.",
                 "Штраф оплачивается только через ОВД до выезда.",
                 "Туристическая виза не продлевается."):
        clean, violations = _check(text, allowed_claims=frozenset(
            {"regime", "stay_limit", "registration", "unified_permit"}))
        assert not any(v.startswith("kg_entry_forbidden_") for v in violations), \
            f"правильная формулировка заблокирована: {text!r}"


# --- G. Мягкие сигналы ----------------------------------------------------------

def test_two_or_three_questions_are_allowed_here():
    """Б.2 п.1 разрешает 2-3 вопроса за сообщение, в отличие от общего правила."""
    text = "Какое у вас гражданство? Какая цель поездки? Когда планируете въезд?"
    _, violations = _check(text, allowed_claims=frozenset())
    assert "multiple_questions" not in violations


def test_four_questions_are_flagged():
    text = "Гражданство? Цель? Даты? Паспорт? Приглашение?"
    _, violations = _check(text, allowed_claims=frozenset())
    assert "too_many_questions" in violations
