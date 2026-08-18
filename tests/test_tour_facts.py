"""ГЕЙТ задачи «факты клиента доходят до карточки без поиска».

Написан ДО реализации и исполнителем НЕ редактируется. Кажется, что тест неверный —
остановись и спроси, не правь. ТЗ: `docs/task-tour-facts.md`.

## Зачем (три замера 18.08.2026 на боевом портале)

Факты попадают в состояние диалога ТОЛЬКО из аргументов вызова `search_tours`
(`app/agent/runner.py:360`). Нет поиска — карточка пустая или врёт:

1. Лид 186243: семь ходов, клиент назвал направление, даты, состав, бюджет и город
   вылета. Бот четыре раза подряд спрашивал про питание и поиск не вызвал ни разу.
   `qualification = {}`, стадия `NEW`, досье пустое. Воспроизведено 2 прогона из 2.
2. Лид 186247: клиент ушёл на Дубай, потом вернулся в Анталью. Бот согласился словами
   («Окей, возвращаемся в Анталью 👍») и ответил ценами по Анталье, но поиск не
   перезапустил — **в карточке остался Дубай**. Менеджер подтвердил бы не ту страну.
3. По базе: `qualification` заполнена у 120 туровых диалогов из 698 (17%) на канале
   Адеми и у 39 из 289 (13%) на канале Айсины.

## Требуется от реализации

    app/agent/facts.py
        FIELDS: tuple[str, ...]
        def extract(text: str) -> dict          # только уверенно найденное, иначе {}
        def merge(known: dict, found: dict) -> dict   # пустое НЕ затирает известное

Извлечение детерминированное (закон 1 `docs/venom-v2.md`): разбор идёт кодом, а не
моделью. Готовые разборщики уже есть в `app/integrations/tourvisor/client.py`
(`_parse_dates`, `_parse_tourists`, `_parse_budget`) — переиспользовать, а не писать
заново.

Ложноположительные фразы ниже взяты из БОЕВОЙ переписки, а не выдуманы: на них
регулярка без маркеров ошибается, и цена ошибки — враньё в карточке менеджера.
"""
from __future__ import annotations

import pytest


class _Missing:
    """Модуля ещё нет — тест обязан УПАСТЬ, а не сорвать сбор всего прогона.

    Красный гейт не должен мешать остальным 1130 тестам: импорт на уровне модуля
    превратил бы отсутствие `app/agent/facts.py` в ошибку коллекции.
    """

    def __getattr__(self, name):
        raise AssertionError("app/agent/facts.py ещё не написан — см. docs/task-tour-facts.md")


def _mod():
    try:
        from app.agent import facts as module
        return module
    except ImportError:
        return _Missing()


facts = _mod()


# --- положительные: фразы, ради которых всё затевается ------------------------

@pytest.mark.parametrize("text,field,expected", [
    # Ловушка «не из X, а из Y»: наивный разбор возьмёт первый город и ошибётся.
    ("И вылетать будем не из Бишкека, а из Алматы", "departure_city", "Алматы"),
    ("И вылетать будем не из Бишкека, а из Оша", "departure_city", "Ош"),
    ("Вылет из Бишкека, с 5 по 11 сентября, двое взрослых", "departure_city", "Бишкек"),
])
def test_departure_city_extracted(text, field, expected):
    assert facts.extract(text).get(field) == expected


def test_budget_with_marker():
    """«Бюджет тогда поднимем до 2500 долларов» — 2500, а не 2500 сом и не пусто."""
    got = facts.extract("Бюджет тогда поднимем до 2500 долларов")
    assert "2500" in str(got.get("budget", ""))


def test_budget_in_soms():
    got = facts.extract("Здравствуйте! Хочу в Анталью в сентябре, двое взрослых, "
                        "бюджет до 100 тысяч сом")
    assert got.get("budget")
    assert "100" in str(got["budget"])


def test_party_with_children_ages():
    """Возраст детей обязателен для поиска: без него TourVisor отдаёт пусто."""
    got = facts.extract("И нас будет четверо: двое взрослых и двое детей, 7 и 10 лет")
    assert str(got.get("tourists")) == "4"
    ages = str(got.get("children_ages", ""))
    assert "7" in ages and "10" in ages


def test_return_to_previous_destination():
    """Случай лида 186247: возврат в Анталью обязан доехать до карточки."""
    got = facts.extract("Хотя нет, всё-таки вернёмся к Турции, Анталья")
    assert got.get("destination") == "Турция"
    assert got.get("region") == "Анталья"


def test_resort_and_dates_in_one_question():
    got = facts.extract("А Кемер на 1-8 октября что стоит? тоже двое, всё включено")
    assert got.get("region") == "Кемер"
    assert got.get("dates")
    assert str(got.get("tourists")) == "2"


def test_dates_shift():
    got = facts.extract("А даты сдвинем на 12-18 сентября")
    assert got.get("dates")


# --- ложноположительные: боевые фразы, на которых ошибаться нельзя -------------

@pytest.mark.parametrize("text,forbidden", [
    # Номер документа в анкете на визу/тур — не бюджет.
    ("457838 Аширбаев Равшан маратович", "budget"),
    # Два телефона менеджеру — ни бюджет, ни состав.
    ("0555255273 - Нурзада  0555255364 - Каныкей", "budget"),
    ("0555255273 - Нурзада  0555255364 - Каныкей", "tourists"),
    # Кыргызский: «через 40 минут подойду». Не бюджет и не состав.
    ("40 мин барып калам 🫣", "budget"),
    ("40 мин барып калам 🫣", "tourists"),
    # ПРОШЛЫЙ опыт клиента: и 1200, и «на двоих» относятся к позапрошлой поездке.
    ("У нас в прошлом году на двоих в 5 звезд отель вышло 1200 с завтраком еще", "budget"),
    ("У нас в прошлом году на двоих в 5 звезд отель вышло 1200 с завтраком еще", "tourists"),
    # Про багаж в билетах, а не про число туристов.
    ("2 с багажом  1 ручная", "tourists"),
    # Голая цифра без маркера — гадать нельзя.
    ("3800 выходит", "budget"),
])
def test_no_false_positive(text, forbidden):
    assert not facts.extract(text).get(forbidden)


def test_question_without_facts_is_empty():
    assert facts.extract("Когда там хорошая погода") == {}


def test_ticket_route_is_not_a_tour_destination():
    """«Вылет 25 сент с Алматы >Сеул >Нагоя» — билеты. Сеул нам не направление туров."""
    got = facts.extract("Вылет 25 сент с Алматы >Сеул >Нагоя")
    assert not got.get("destination")
    assert not got.get("region")


def test_empty_and_garbage_never_raise():
    for text in ("", "   ", "😊", "?", "ок"):
        assert facts.extract(text) == {}


# --- слияние: главный источник наших прошлых аварий ----------------------------

def test_merge_keeps_known_when_nothing_found():
    known = {"destination": "Турция", "dates": "5-11 сентября"}
    assert facts.merge(known, {}) == known


def test_merge_never_overwrites_with_empty():
    """Пустое поле из разбора не должно стирать названную клиентом дату (урок cb7f427)."""
    known = {"dates": "5-11 сентября", "budget": "1500 USD"}
    merged = facts.merge(known, {"dates": "", "budget": None})
    assert merged["dates"] == "5-11 сентября"
    assert merged["budget"] == "1500 USD"


def test_merge_applies_new_value():
    merged = facts.merge({"region": "Дубай"}, {"region": "Анталья"})
    assert merged["region"] == "Анталья"


def test_merge_does_not_mutate_input():
    known = {"region": "Дубай"}
    facts.merge(known, {"region": "Анталья"})
    assert known == {"region": "Дубай"}


def test_merge_drops_unknown_keys():
    """В квалификацию попадают только наши поля: мусор в карточку не уезжает."""
    merged = facts.merge({}, {"region": "Анталья", "любимый_цвет": "синий"})
    assert "любимый_цвет" not in merged


def test_fields_cover_what_dossier_shows():
    """Досье показывает направление, вылет, бюджет, даты и состав — всё должно извлекаться."""
    for key in ("destination", "region", "departure_city", "budget", "dates",
                "tourists", "children_ages"):
        assert key in facts.FIELDS
