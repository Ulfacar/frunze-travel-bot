"""Тесты мотора готовности (app/core/readiness.py) — детерминированный тир, ноль LLM."""
from app.core.readiness import (compute_readiness, compute_tier, ghost_downgrade,
                                _estimate_value)
from app.core.state import DialogState


def _state(funnel="tours", qualification=None, user_texts=()):
    history = [{"role": "user", "content": t} for t in user_texts]
    return DialogState(user_id="u", funnel=funnel,
                       qualification=dict(qualification or {}), history=history)


def _sig(**over):
    base = {k: False for k in (
        "explicit_payment_intent", "explicit_booking_request", "manager_requested",
        "deadline_mentioned", "budget_stated", "contact_shared", "destination_confirmed",
        "travel_dates_narrowed", "pax_count_stated", "country_in_scope",
        "travel_purpose_stated", "document_readiness_mentioned",
        "price_objection_only", "info_only_browsing", "comparing_multiple_agencies",
        "single_word_replies_only", "keyword_safety_trigger_matched")}
    base["message_count_client"] = 3
    base.update(over)
    return base


# ---------- compute_tier: ветки и приоритет ----------

def test_tier_safety_trigger_wins_even_with_one_message():
    assert compute_tier(_sig(keyword_safety_trigger_matched=True, message_count_client=1)) == "green"


def test_tier_insufficient_when_too_few_messages():
    assert compute_tier(_sig(message_count_client=1)) == "insufficient"


def test_tier_insufficient_when_no_signals_at_all():
    assert compute_tier(_sig(message_count_client=5)) == "insufficient"


def test_tier_green_on_strong_positive():
    assert compute_tier(_sig(explicit_payment_intent=True)) == "green"
    assert compute_tier(_sig(explicit_booking_request=True)) == "green"
    assert compute_tier(_sig(manager_requested=True)) == "green"


def test_tier_green_on_combo():
    assert compute_tier(_sig(deadline_mentioned=True, budget_stated=True,
                             destination_confirmed=True)) == "green"


def test_tier_noise_on_two_negatives_zero_positive():
    assert compute_tier(_sig(price_objection_only=True,
                             comparing_multiple_agencies=True)) == "noise"


def test_tier_warm_is_the_fallback():
    # один позитив, нет сильного сигнала и комбо → тёплый
    assert compute_tier(_sig(destination_confirmed=True)) == "warm"


def test_tier_positive_beats_noise():
    # есть позитив → не шум, даже с негативами
    assert compute_tier(_sig(destination_confirmed=True, price_objection_only=True,
                             comparing_multiple_agencies=True)) == "warm"


# ---------- _estimate_value ----------

def test_estimate_value_dollars():
    assert _estimate_value({"budget": "$800"}) == (800.0, "$")


def test_estimate_value_range_averages():
    val, cur = _estimate_value({"budget": "800-1000 долларов"})
    assert val == 900.0 and cur == "$"


def test_estimate_value_thousands_som():
    assert _estimate_value({"budget": "до 100 тыс сом"}) == (100000.0, "сом")


def test_estimate_value_empty():
    assert _estimate_value({}) == (None, "")
    assert _estimate_value({"budget": ""}) == (None, "")


def test_estimate_value_no_currency_marker_is_blank_not_guessed():
    # spec: валюту не выдумываем — нет маркера → пусто (а не «$» по эвристике)
    assert _estimate_value({"budget": "3000"}) == (3000.0, "")


# ---------- compute_readiness: интеграция по DialogState ----------

def test_readiness_insufficient_on_bare_greeting():
    r = compute_readiness(_state(user_texts=["привет"]))
    assert r["readiness_tier"] == "insufficient"
    assert r["readiness_reason"]


def test_readiness_green_on_payment_question():
    r = compute_readiness(_state(user_texts=["привет", "а как оплатить тур?"]))
    assert r["readiness_tier"] == "green"
    assert "оплат" in r["readiness_reason"].lower()
    assert r["readiness_signals"]["keyword_safety_trigger_matched"] is True


def test_readiness_green_on_full_qualification_combo():
    r = compute_readiness(_state(
        qualification={"destination": "Анталья", "dates": "15 июля", "budget": "$900", "tourists": "2"},
        user_texts=["хочу тур", "да, подходит"]))
    assert r["readiness_tier"] == "green"
    assert r["estimated_value"] == 900.0 and r["estimated_value_currency"] == "$"


def test_readiness_noise_on_price_shopping():
    r = compute_readiness(_state(user_texts=["сколько стоит", "дорого, у других дешевле"]))
    assert r["readiness_tier"] == "noise"


def test_readiness_warm_partial_data():
    r = compute_readiness(_state(qualification={"destination": "Дубай"},
                                 user_texts=["хочу в Дубай", "а что есть"]))
    assert r["readiness_tier"] == "warm"


# ---------- ghost_downgrade (застойный неготовый → noise) ----------

def test_ghost_stale_nonready_becomes_noise():
    assert ghost_downgrade("insufficient", {}, 30, "bot") == "noise"
    assert ghost_downgrade("warm", {}, 48, "bot") == "noise"


def test_ghost_client_waiting_is_not_ghost():
    # последним писал клиент → мяч у нас, это не «пропал»
    assert ghost_downgrade("insufficient", {}, 99, "client") == "insufficient"


def test_ghost_never_touches_green():
    assert ghost_downgrade("green", {}, 999, "bot") == "green"


def test_ghost_protects_sticky_buyer():
    assert ghost_downgrade("warm", {"explicit_payment_intent": True}, 99, "bot") == "warm"


def test_ghost_recent_untouched():
    assert ghost_downgrade("warm", {}, 3, "bot") == "warm"   # 3ч < порога 24ч


def test_readiness_green_is_sticky_after_hesitation():
    """Регресс (codex-reviewer MAJOR): покупатель показал намерение платить, потом
    усомнился вслух — НЕ должен слететь в шум. Позитивы стики по всей истории."""
    state = _state(user_texts=[
        "хочу тур в Анталью", "а как оплатить?", "ой, дороговато, я пока просто смотрю"])
    r = compute_readiness(state)
    assert r["readiness_tier"] == "green"          # safety-триггер «оплатить» стики
    assert r["readiness_signals"]["explicit_payment_intent"] is True


# ---------- Разговор, который ведут мимо нас (19.08.2026) ----------
#
# Если менеджер отвечает клиенту с телефона, а эхо ответа до нас не долетает, в истории
# остаются одни клиентские реплики. Мотор готовности видит «человек пишет, позитивных
# сигналов нет» и опускает лид в «Шум» — то есть прячет из ленты клиента, с которым уже
# работают. Судить о готовности по половине разговора нельзя: честный ответ — «мало данных».

def _state_led_past_us():
    return _state(user_texts=("здравствуйте, можно подробнее про визу",
                              "а в другом агентстве как",
                              "дорого, просто смотрю пока"))


def test_readiness_does_not_call_it_noise_when_our_replies_are_missing():
    result = compute_readiness(_state_led_past_us())

    assert result["readiness_tier"] == "insufficient"


def test_readiness_still_calls_it_noise_when_we_actually_replied():
    state = _state_led_past_us()
    state.history.insert(1, {"role": "assistant", "content": "Здравствуйте! Какая страна?"})

    assert compute_readiness(state)["readiness_tier"] == "noise"
