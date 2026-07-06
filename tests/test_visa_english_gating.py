"""Правка со встречи 06.07: по англоязычным странам (США/UK/Канада…) бот НЕ спрашивает
про уровень английского — это личная информация, и для визового офицера незнание языка
не минус. По остальным странам вопрос задаётся как раньше.
"""
import asyncio

from app.channels.base import Message
from app.core.branding import is_english_speaking
from app.core.state import DialogState
from app.funnels.visa import REQUIRED_FIELDS, VisaFunnel, _required_fields, _ask_for

ENGLISH_Q = _ask_for("english_level")


def test_is_english_speaking_matches_common_forms():
    for country in ("США", "сша", "Америка", "USA", "Великобритания", "Англия",
                    "Канада", "Australia", "Ирландия"):
        assert is_english_speaking(country), country


def test_is_english_speaking_false_for_others_and_empty():
    for country in ("Германия", "Шенген", "Китай", "Таиланд", "", None):
        assert not is_english_speaking(country), country


def test_is_english_speaking_no_false_positive_on_ukraine():
    # «Ukraine» латиницей содержит «uk» — не должно ложно матчиться (Украина не англоязычная).
    assert not is_english_speaking("Ukraine")
    assert not is_english_speaking("Украина")


def test_required_fields_drops_english_for_english_speaking():
    fields = _required_fields({"country": "США"})
    assert "english_level" not in fields
    # Остальные поля не потеряны.
    assert set(fields) == set(REQUIRED_FIELDS) - {"english_level"}


def test_required_fields_keeps_english_for_schengen():
    assert "english_level" in _required_fields({"country": "Германия (Шенген)"})


def test_required_fields_keeps_english_when_country_unknown():
    assert "english_level" in _required_fields({})


def _run_offline_visa(monkeypatch, country: str) -> list[str]:
    """Прогнать офлайн-воронку визы, вернуть все реплики бота (вопросы + финал)."""
    monkeypatch.setattr("app.agent.llm.settings.openrouter_api_key", "")
    funnel = VisaFunnel()
    state = DialogState(user_id="offline-visa", funnel="visa")
    # Ответы по порядку полей; страну подставляем нужную. english_level даём на случай Шенгена.
    answers = ["Иван", country, "30", "в браке", "инженер", "Турция",
               "с семьёй", "базово", "август", "нет"]
    replies = []
    for text in ["нужна виза", *answers]:
        msg = Message(channel="console", user_id="offline-visa", chat_id="offline-visa", text=text)
        replies.append(asyncio.run(funnel.handle(msg, state)))
    return [r for r in replies if r]


def test_us_visa_does_not_ask_english(monkeypatch):
    replies = _run_offline_visa(monkeypatch, "США")
    assert all(ENGLISH_Q not in r for r in replies), "по США спросили про английский"


def test_schengen_visa_asks_english(monkeypatch):
    replies = _run_offline_visa(monkeypatch, "Германия")
    assert any(ENGLISH_Q in r for r in replies), "по Шенгену НЕ спросили про английский"
