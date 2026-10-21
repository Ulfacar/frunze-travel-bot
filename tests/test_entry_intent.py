"""ГЕЙТ: распознавание темы на визовом номере.

Написан ДО реализации и исполнителем НЕ редактируется.

На номере GetVisa два разных бизнеса: выездные визы для граждан КР (работает, приносит
деньги) и въездные визы в КР для иностранцев (новое). Ошибка распознавания стоит дорого
в обе стороны, но несимметрично:

- увели выездного клиента во въездную ветку → он получает чужие факты про безвиз и
  регистрацию вместо ответа про собеседование в посольстве. **Это регрессия работающего.**
- не распознали въездного → он получает прежнее поведение, то есть передачу менеджеру.
  Неидеально, но безопасно.

Поэтому дефолт у неоднозначного — `unknown`, то есть прежнее поведение целиком.
"""
import pytest

from app.core.entry_intent import detect, looks_english


# --- A. Выездное остаётся выездным ---------------------------------------------

@pytest.mark.parametrize("text", [
    "хочу визу в США",
    "нужен шенген",
    "виза в Польшу",
    "запишите на собеседование в посольство",
    "мне отказали в визе, что делать",
    "сколько стоит виза в Канаду",
    "нужна виза в Великобританию для туризма",
    "помогите с DS-160",
    "когда слоты в визовый центр",
])
def test_outbound_stays_outbound(text):
    assert detect(text) == "outbound", f"выездной клиент уехал бы не туда: {text!r}"


def test_outbound_veto_beats_an_entry_word(text="виза в Польшу, живу в Бишкеке"):
    """Упоминание Бишкека как места жительства не делает разговор въездным."""
    assert detect(text) == "outbound"


# --- B. Въездное распознаётся ---------------------------------------------------

@pytest.mark.parametrize("text", [
    "нужна виза в Кыргызстан",
    "I need a visa to Kyrgyzstan",
    "do I need a visa for Kyrgyzstan?",
    "how long can I stay in Kyrgyzstan without a visa",
    "как сделать регистрацию иностранца",
    "что такое единое разрешение на работу",
    "хочу оформить резидент-карту",
    "e-visa кыргызстан",
    "I am in Bishkek, my passport expires soon",
])
def test_entry_is_recognized(text):
    assert detect(text) == "kg_entry", f"въездной клиент не распознан: {text!r}"


def test_english_visa_question_without_an_outbound_country_is_entry():
    """Клиентура выездного GetVisa пишет по-русски; английский визовый вопрос — въезд."""
    assert detect("hello, I want to apply for a visa") == "kg_entry"


def test_english_question_about_an_outbound_country_is_not_entry():
    assert detect("I need a Schengen visa") == "outbound"


# --- C. Сомнение = прежнее поведение -------------------------------------------

@pytest.mark.parametrize("text", [
    "виза",
    "здравствуйте",
    "добрый день, можно узнать подробнее?",
    "",
    "   ",
    "сколько стоит",
    "а документы какие нужны",
])
def test_ambiguous_keeps_the_old_behaviour(text):
    assert detect(text) == "unknown", f"неоднозначная реплика забрана новой веткой: {text!r}"


# --- D. Липкость: режим не переобувается посреди диалога -----------------------

def test_sticky_mode_wins_over_text():
    assert detect("а в посольстве спрашивают?", sticky="kg_entry") == "kg_entry"
    assert detect("нужна виза в Кыргызстан", sticky="outbound") == "outbound"


def test_sticky_garbage_is_ignored():
    assert detect("нужна виза в Кыргызстан", sticky="") == "kg_entry"
    assert detect("нужна виза в Кыргызстан", sticky="nonsense") == "kg_entry"


# --- E. Определение языка -------------------------------------------------------

@pytest.mark.parametrize("text,english", [
    ("I need a visa", True),
    ("hello", True),
    ("нужна виза", False),
    ("виза to Kyrgyzstan", False),      # смешанная — считаем русской, клиент местный
    ("", False),
    ("12345", False),
])
def test_language_detection(text, english):
    assert looks_english(text) is english
