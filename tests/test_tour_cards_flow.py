"""ГЕЙТ: карточки доезжают до клиента целыми и только когда надо.

Написан ДО реализации, исполнителем НЕ редактируется. ТЗ: `docs/task-tours-cards-v1.md`.

Главная защищаемая мысль: блок карточек дописывается ПОСЛЕ `validate_reply`. Валидатор
существует не зря — он режет выдуманные моделью URL и markdown; но карточки собирает КОД, они
не выдуманы, и их WhatsApp-разметку (`*жирный*`) валидатор бы уничтожил. Поэтому обе стороны
должны сосуществовать: диалог валидируется как раньше, карточки идут мимо.

Второе: флаг по умолчанию ВЫКЛЮЧЕН, и при выключенном флаге ход обязан быть побайтово таким
же, как сегодня на проде.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.agent import runner
from app.agent.validator import validate_reply
from app.core import flags
from app.core.state import DialogState
from app.integrations.tourvisor.client import TourSearch, TourVisorError

OFFER_URL = "https://frunzetravel.kg/t/testslug"
CARDS = [
    "🏠 *FIRST CLASS HOTEL 5⭐️*\n✈️ Бишкек ➡️ Турция, Аланья\n📅 20 авг, 🌙 8нч\n"
    "🛌 standard room land view, 3взр 1реб\n🍽️ Все Включено\n🏷️ 2 765 eur",
    "🏠 *MC BEACH RESORT 5⭐️*\n✈️ Бишкек ➡️ Турция, Аланья\n📅 20 авг, 🌙 8нч\n"
    "🛌 superior room, 2взр 2реб\n🍽️ Ультра Все Включено\n🏷️ 3 409 eur",
]


class FakeBlock:
    def __init__(self, type, text=None, name=None, input=None, id=None):
        self.type, self.text, self.name = type, text, name
        self.input, self.id = input or {}, id

    def model_dump(self):
        return {"type": self.type, "text": self.text, "name": self.name,
                "input": self.input, "id": self.id}


class FakeResp:
    def __init__(self, stop_reason, content):
        self.stop_reason, self.content, self.usage = stop_reason, content, None


def _tool_use(inp=None, id="t1"):
    return FakeResp("tool_use", [FakeBlock("tool_use", name="search_tours",
                                           input=inp or {"destination": "Турция",
                                                         "nights": "7"}, id=id)])


def _text(text="Нашёл варианты в ваш бюджет, что понравится?"):
    return FakeResp("end_turn", [FakeBlock("text", text=text)])


def _patch_client(monkeypatch, *responses):
    fake = AsyncMock()
    fake.messages.create = AsyncMock(side_effect=list(responses))
    monkeypatch.setattr(runner, "client", lambda: fake)
    return fake


def _found(**over) -> TourSearch:
    kwargs = dict(lines=["FIRST CLASS HOTEL 5* Аланья. вылет 20.08.2026, 8 ноч., AI, от 2765 EUR"],
                  found=25, reason="ok", departure="Бишкек")
    kwargs.update(over)
    return TourSearch(**kwargs)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    flags.reset()
    monkeypatch.setattr(runner, "_offer_url", AsyncMock(return_value=OFFER_URL), raising=False)
    monkeypatch.setattr(runner._tourvisor, "search_detailed",
                        AsyncMock(return_value=_found()))
    monkeypatch.setattr(runner, "_render_cards_for_state",
                        lambda found, state: list(CARDS), raising=False)
    yield
    flags.reset()


def _run(monkeypatch, *responses, state=None, cards_on=True):
    state = state or DialogState(user_id="frunze_tours:996700000001", funnel="tours",
                                 bot_id="frunze_tours")
    if cards_on:
        asyncio.run(flags.set_flag("tours_cards_enabled", True))
    _patch_client(monkeypatch, *responses)
    text = asyncio.run(runner.run_tours_turn(state, "хочу в Турцию, 2 взрослых 2 детей"))
    return text, state


# --- флаг ------------------------------------------------------------------------

def test_flag_off_keeps_todays_behaviour(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: дефолт = то, что на проде сейчас. Ни карточек, ни ссылки."""
    text, state = _run(monkeypatch, _tool_use(), _text("Вот варианты"), cards_on=False)
    assert text == "Вот варианты"
    assert "🏠" not in text and "frunzetravel.kg/t/" not in text
    assert not getattr(state, "pending_tour_cards", [])


def test_flag_on_attaches_cards_and_link(monkeypatch):
    text, _ = _run(monkeypatch, _tool_use(), _text("Нашёл варианты"))
    assert text.startswith("Нашёл варианты")
    assert text.count("🏠") == 2
    assert "🛌 standard room land view, 3взр 1реб" in text
    # Ссылка на месте, но замыкает сообщение призыв к действию (правка 14.08): раньше клиент
    # дочитывал пятый отель и упирался в пустоту.
    assert OFFER_URL in text
    assert text.rstrip().endswith("проверю наличие и точную цену.")


# --- карточки не проходят валидатор ------------------------------------------------

def test_cards_bypass_the_validator(monkeypatch):
    """Сердце конструкции. Валидатор рвёт карточку — значит она обязана идти мимо него."""
    text, _ = _run(monkeypatch, _tool_use(), _text("Нашёл варианты"))
    assert "*FIRST CLASS HOTEL 5⭐️*" in text, "жирный WhatsApp обязан дожить до клиента"
    assert OFFER_URL in text, "ссылка от кода не должна вырезаться как выдуманная моделью"

    # ...и доказываем, что без обхода было бы иначе.
    damaged, _ = validate_reply("\n\n".join(CARDS) + f"\n\nПодробнее здесь:\n{OFFER_URL}",
                                "tours")
    assert "*FIRST CLASS HOTEL 5⭐️*" not in damaged or OFFER_URL not in damaged


def test_model_text_is_still_validated(monkeypatch):
    """Диалог остаётся под валидатором: выдуманный моделью URL по-прежнему вырезается."""
    text, _ = _run(monkeypatch, _tool_use(),
                   _text("Смотрите тут https://booking.com/hotel и выбирайте"))
    assert "booking.com" not in text
    assert text.count("🏠") == 2


# --- деградация --------------------------------------------------------------------

def test_nothing_found_has_no_cards(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: пусто — значит пусто, без висящих хвостов."""
    runner._tourvisor.search_detailed = AsyncMock(
        return_value=_found(lines=[], found=0, reason="nothing_found"))
    monkeypatch.setattr(runner, "_render_cards_for_state", lambda found, state: [],
                        raising=False)
    text, _ = _run(monkeypatch, _tool_use(), _text("На эти даты туров нет"))
    assert text == "На эти даты туров нет"
    assert "Подробнее" not in text and not text.endswith("\n")


def test_tourvisor_error_has_no_cards(monkeypatch):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: API упал — заявка важнее карточек, ход не ломается."""
    runner._tourvisor.search_detailed = AsyncMock(side_effect=TourVisorError("boom"))
    text, _ = _run(monkeypatch, _tool_use(), _text("Подбор временно недоступен"))
    assert text == "Подбор временно недоступен"
    assert "🏠" not in text


def test_offer_link_failure_keeps_cards(monkeypatch):
    """Страница не создалась — карточки всё равно уходят, просто без ссылки."""
    monkeypatch.setattr(runner, "_offer_url", AsyncMock(return_value=""), raising=False)
    text, _ = _run(monkeypatch, _tool_use(), _text("Нашёл варианты"))
    assert text.count("🏠") == 2
    assert "Подробнее" not in text


# --- жизненный цикл карточек ---------------------------------------------------------

def test_cards_do_not_survive_into_the_next_turn(monkeypatch):
    text, state = _run(monkeypatch, _tool_use(), _text("Нашёл варианты"))
    assert "🏠" in text
    _patch_client(monkeypatch, _text("Да, конечно"))
    second = asyncio.run(runner.run_tours_turn(state, "а можно подешевле?"))
    assert second == "Да, конечно"
    assert "🏠" not in second


def test_stale_cards_from_a_crashed_turn_are_dropped(monkeypatch):
    """Ход упал после поиска — карточки осели в state. К следующей реплике они не липнут."""
    state = DialogState(user_id="frunze_tours:996700000002", funnel="tours",
                        bot_id="frunze_tours")
    state.pending_tour_cards = list(CARDS)
    _patch_client(monkeypatch, _text("Здравствуйте!"))
    asyncio.run(flags.set_flag("tours_cards_enabled", True))
    text = asyncio.run(runner.run_tours_turn(state, "здравствуйте"))
    assert text == "Здравствуйте!"
    assert not state.pending_tour_cards


def test_two_searches_in_one_turn_keep_only_the_last(monkeypatch):
    calls = {"n": 0}

    def _cards(found, state):
        calls["n"] += 1
        return [CARDS[0]] if calls["n"] == 1 else [CARDS[1]]

    monkeypatch.setattr(runner, "_render_cards_for_state", _cards, raising=False)
    text, _ = _run(monkeypatch, _tool_use(id="t1"), _tool_use(id="t2"), _text("Уточнил"))
    assert text.count("🏠") == 1
    assert "MC BEACH RESORT" in text


# --- контракт с моделью ---------------------------------------------------------------

def test_report_without_cards_mode_is_unchanged():
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: старый текст для модели не должен поехать."""
    report = runner._tours_search_report(_found())
    assert "Цены называй ровно как в строках" in report
    assert "Найдено вариантов: 25" in report


def test_report_with_cards_mode_forbids_relisting():
    report = runner._tours_search_report(_found(), cards_mode=True)
    assert "Цены называй ровно как в строках" not in report
    assert "не перечисляй" in report.lower()
