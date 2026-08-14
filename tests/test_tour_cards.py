"""ГЕЙТ: подборка туров выглядит так же, как её присылают менеджеры.

Написан ДО реализации, исполнителем НЕ редактируется. ТЗ: `docs/task-tours-cards-v1.md`.

## Зачем

Бот присылает клиенту ОДИН отель одной строкой. Со встречи 11.08 дословно: «Блин, почему
только один он показывает?». Менеджеры в тот же день показали свой шаблон — карточки с
эмодзи, типом номера, составом и ценой.

## Откуда взяты данные

Из живого ответа TourVisor (разведка `scripts/tourvisor_probe.py` на проде 11.08, запрос
Бишкек→Турция/Аланья 17–25.08, 2 взр + дети 7 и 12). Поля `room`, `placement`, `adults`,
`child`, `tourid`, `picturelink` заполнены у 100% записей — то есть тип номера и состав НЕ
надо угадывать из запроса клиента, они приходят от оператора.

Ключевой факт, который легко потерять: на запрос «2 взрослых + дети 7 и 12» TourVisor
вернул `adults=3, child=1` — двенадцатилетний считается взрослым. В карточке обязан стоять
СОСТАВ ТУРА, а не то, что просил клиент: иначе цена не сойдётся с размещением.
"""
from __future__ import annotations

import pytest

from app.integrations.tourvisor.cards import TOUR_CARDS_LIMIT, render_block, render_cards

EXPECTED = (
    "🏠 *THE NORA HOTELS FAMILY CLUB 5⭐️*\n"
    "✈️ Бишкек ➡️ Турция, Аланья\n"
    "📅 17 авг, 🌙 6нч\n"
    "🛌 economy pool room, 2взр 2реб\n"
    "🍽️ Все Включено\n"
    "🏖️ до моря 50 м\n"
    "🏷️ 2 364 eur за 2взр+2реб"
)


def _tour(**over) -> dict:
    """Тур ровно в той форме, в какой его отдаёт живой TourVisor."""
    tour = {
        "price": 2364,
        "nights": 6,
        "operatorcode": 90,
        "operatorname": "Kompas (KZ)",
        "flydate": "17.08.2026",
        "placement": "DBL + 2 CHD",
        "adults": 2,
        "child": 2,
        "room": "economy pool room",
        "tourname": "TR: Анталия из Бишкека",
        "mealcode": 7,
        "mealrussian": "AI - Все Включено",
        "meal": "AI",
        "tourid": "90264112887701",
        "currency": "EUR",
    }
    tour.update(over)
    return tour


def _hotel(name="THE NORA HOTELS FAMILY CLUB", *, tours=None, **over) -> dict:
    hotel = {
        "hotelcode": 1188,
        "hotelname": name,
        "hotelstars": 5,
        "hotelrating": "3.5",
        "picturelink": "https://static.tourvisor.ru/hotel_pics/main400/1188.jpg",
        "countryname": "Турция",
        "regionname": "Аланья",
        "seadistance": 50,
        "currency": "EUR",
        "tours": {"tour": tours if tours is not None else [_tour()]},
    }
    hotel.update(over)
    return hotel


def _one(hotel: dict) -> str:
    cards = render_cards([hotel], departure="Бишкек")
    assert len(cards) == 1
    return cards[0]


# --- эталон ---------------------------------------------------------------------

def test_card_matches_manager_template():
    """Главный тест: карточка совпадает с шаблоном менеджеров посимвольно."""
    assert _one(_hotel()) == EXPECTED


def test_composition_comes_from_the_tour_not_from_the_request():
    """Состав берём у оператора: он решает размещение, и по нему посчитана цена."""
    card = _one(_hotel(tours=[_tour(adults=3, child=1, placement="TRPL + 1 CHD")]))
    assert "3взр 1реб" in card


def test_adults_only_has_no_children_part():
    card = _one(_hotel(tours=[_tour(adults=2, child=0)]))
    assert "🛌 economy pool room, 2взр\n" in card + "\n"
    assert "реб" not in card


# --- деградация: чего нет, о том молчим ------------------------------------------

def test_no_room_keeps_the_line_with_composition():
    card = _one(_hotel(tours=[_tour(room="")]))
    assert "🛌 2взр 2реб" in card
    assert "None" not in card and ", ," not in card


def test_no_room_and_no_composition_drops_the_line():
    card = _one(_hotel(tours=[_tour(room="", adults=0, child=0)]))
    assert "🛌" not in card


def test_no_meal_no_line():
    card = _one(_hotel(tours=[_tour(mealrussian="", meal="")]))
    assert "🍽️" not in card
    assert "\n\n" not in card, "пустая строка вместо питания — дыра в карточке"


@pytest.mark.parametrize("broken", [{"price": ""}, {"currency": ""}, {"price": "договорная"}])
def test_hotel_without_usable_price_is_dropped(broken):
    """ЛОЖНОПОЛОЖИТЕЛЬНЫЙ: цена без валюты в Бишкеке читается как сомы.

    Показать на один отель меньше дешевле, чем назвать 2364 сома вместо 2364 евро.
    """
    assert render_cards([_hotel(tours=[_tour(**broken)])], departure="Бишкек") == []


def test_hotel_without_name_is_dropped():
    assert render_cards([_hotel(name="")], departure="Бишкек") == []


def test_hotel_without_tours_is_dropped():
    assert render_cards([_hotel(tours=[])], departure="Бишкек") == []


# --- форматирование значений ------------------------------------------------------

@pytest.mark.parametrize("raw,want", [
    (2364, "2 364"), ("2364", "2 364"), (2364.0, "2 364"), ("2 364", "2 364"),
    (900, "900"), (12345, "12 345"),
])
def test_price_grouping(raw, want):
    assert f"🏷️ {want} eur" in _one(_hotel(tours=[_tour(price=raw)]))


def test_currency_is_lowercase_and_not_converted():
    """Валюта как у менеджеров — строчными, и ровно та, что отдал оператор."""
    assert "🏷️ 2 364 usd" in _one(_hotel(tours=[_tour(currency="USD")]))


@pytest.mark.parametrize("raw,want", [
    ("17.08.2026", "17 авг"), ("01.09.2026", "1 сен"), ("31.12.2026", "31 дек"),
    ("завтра", "завтра"), ("", None),
])
def test_flydate_is_humanized(raw, want):
    card = _one(_hotel(tours=[_tour(flydate=raw)]))
    if want is None:
        assert "📅" not in card or "🌙 6нч" in card
    else:
        assert want in card


def test_meal_code_prefix_is_stripped():
    """«AI - Все Включено» → «Все Включено»: код питания клиенту ничего не говорит."""
    assert "🍽️ Все Включено" in _one(_hotel(tours=[_tour(mealrussian="AI - Все Включено")]))
    assert "🍽️ Ультра Все Включено" in _one(
        _hotel(tours=[_tour(mealrussian="UAI - Ультра Все Включено")]))
    assert "🍽️ Все Включено" in _one(_hotel(tours=[_tour(mealrussian="Все Включено")]))


def test_route_line_uses_departure_country_and_region():
    assert "✈️ Бишкек ➡️ Турция, Аланья" in _one(_hotel())


def test_route_survives_missing_region():
    card = _one(_hotel(regionname=""))
    assert "✈️ Бишкек ➡️ Турция" in card and "Турция," not in card


# --- разметка WhatsApp -------------------------------------------------------------

@pytest.mark.parametrize("dirty", [
    "HOTEL *STAR* RESORT", "HOTEL_UNDER", "HOTEL~TILDE", "HOTEL\nBREAK", "HOTEL`TICK",
])
def test_hotel_name_is_sanitized(dirty):
    """Одна звёздочка в названии превратила бы пол-сообщения в жирный."""
    card = _one(_hotel(name=dirty))
    head = card.splitlines()[0]
    assert head.startswith("🏠 *") and head.endswith("*")
    assert head.count("*") == 2
    assert "_" not in head and "~" not in head and "`" not in head


def test_no_line_starts_like_a_bullet():
    """Каждая строка начинается с эмодзи: даже случайно пройдя strip_markdown, карточка
    не превратится в кашу — `_BULLET` эмодзи не трогает."""
    for line in _one(_hotel()).splitlines():
        assert not line.lstrip().startswith(("-", "*", "•"))


# --- подборка целиком ---------------------------------------------------------------

def _many(count: int) -> list[dict]:
    return [_hotel(f"HOTEL {i}", tours=[_tour(price=1000 + i)]) for i in range(count)]


def test_limit_is_five():
    assert TOUR_CARDS_LIMIT == 5
    assert len(render_cards(_many(12), departure="Бишкек")) == 5
    assert len(render_cards(_many(3), departure="Бишкек")) == 3
    assert render_cards([], departure="Бишкек") == []


def test_sorted_by_price_ascending():
    hotels = [_hotel("DEAR", tours=[_tour(price=5000)]),
              _hotel("CHEAP", tours=[_tour(price=1000)]),
              _hotel("MID", tours=[_tour(price=3000)])]
    cards = render_cards(hotels, departure="Бишкек")
    assert ["CHEAP" in cards[0], "MID" in cards[1], "DEAR" in cards[2]] == [True, True, True]


def test_deduplicated_by_hotel_name():
    hotels = [_hotel("SAME", tours=[_tour(price=1000)]),
              _hotel("SAME", tours=[_tour(price=1200)])]
    assert len(render_cards(hotels, departure="Бишкек")) == 1


def test_cheapest_tour_of_the_hotel_wins():
    hotel = _hotel(tours=[_tour(price=3000, room="suite"), _tour(price=2364)])
    assert "🏷️ 2 364 eur" in _one(hotel)


# --- склейка сообщения ----------------------------------------------------------------

def test_block_separates_cards_with_one_blank_line():
    block = render_block(render_cards(_many(3), departure="Бишкек"))
    assert "\n\n\n" not in block
    assert block.count("🏠") == 3


def test_block_appends_offer_link():
    """Ссылка на месте, но последнее слово — за призывом к действию (правка 14.08).

    Раньше блок заканчивался ссылкой, и клиент, дочитав пятый отель, упирался в пустоту:
    названия прочитаны, делать с ними нечего. Вопрос модели «какой курорт нравится?» стоит
    ДО подборки и к этому моменту уже забыт.
    """
    block = render_block(render_cards(_many(2), departure="Бишкек"),
                         offer_url="https://frunzetravel.kg/t/abc123")
    assert "https://frunzetravel.kg/t/abc123" in block
    assert "Фото и подробности:" in block
    assert block.rstrip().endswith("проверю наличие и точную цену.")


def test_block_without_link_has_no_dangling_tail():
    block = render_block(render_cards(_many(2), departure="Бишкек"))
    assert "Фото и подробности" not in block
    assert not block.endswith("\n")


def test_block_of_nothing_is_empty():
    assert render_block([]) == ""
    assert render_block([], offer_url="https://frunzetravel.kg/t/abc") == ""


# ---------------- цена и различители (замер живой подборки 14.08) ----------------
def test_price_says_for_whom_it_is():
    """К цене приписано, на скольких она посчитана.

    В живой подборке 14.08 рядом стояли «2взр» и «1 361 eur», и человек, который не покупал
    туры онлайн, читает это как цену за человека: умножает на два, получает вдвое дороже
    рынка и уходит молча. Мы даже не узнаем, что потеряли его на арифметике, а не на цене.
    """
    assert "🏷️ 2 364 eur за 2взр+2реб" in _one(_hotel())
    assert "за двоих" in _one(_hotel(tours=[_tour(adults=2, child=0)]))
    assert "за одного" in _one(_hotel(tours=[_tour(adults=1, child=0)]))


def test_sea_distance_is_the_thing_that_distinguishes_hotels():
    """Расстояние до моря — единственное, чем отличаются пять одинаковых троек.

    Замер 14.08: подборка из пяти отелей 3⭐ в одном курорте, на одни даты, всё включено,
    разброс цены 5%. Выбором это не является. Поле приходит у 100% отелей и до 14.08 жило
    только на странице подборки, в WhatsApp не доходило.
    """
    assert "🏖️ до моря 50 м" in _one(_hotel())
    assert "до моря" not in _one(_hotel(seadistance=0)), "нулевое расстояние не показываем"
    assert "до моря" not in _one(_hotel(seadistance="")), "пустое поле строки не добавляет"


def test_block_ends_with_a_next_step():
    """После карточек клиенту сказано, что делать дальше.

    Вопрос модели («какой курорт больше нравится?») стоит ДО подборки, и человек, дочитав
    пятый отель, упирается в пустоту: названия прочитаны, действия нет.
    """
    from app.integrations.tourvisor.cards import render_block

    block = render_block(["карточка"], offer_url="https://frunzetravel.kg/t/abc")
    assert block.rstrip().endswith("проверю наличие и точную цену.")
    assert block.index("https://") < block.index("Какой отель"), "ссылка выше призыва"
    assert render_block([]) == "", "пустая подборка не тянет за собой призыв"


def test_model_is_told_only_the_places_that_reached_the_cards():
    """Модель узнаёт, какие курорты реально ушли клиенту, а не что было найдено.

    В карточки идут пять самых дешёвых, а найдено бывает больше и по другим курортам. Живой
    случай 14.08: подводка обещала «варианты по Кемеру и Аланье», во всех пяти карточках была
    Аланья. Расхождение клиент замечает мгновенно, и недоверие достаётся ценам — которые как
    раз верные.
    """
    from app.integrations.tourvisor.cards import picked_places

    hotels = [
        _hotel("ALANYA A", tours=[_tour(price=1000)], regionname="Аланья"),
        _hotel("ALANYA B", tours=[_tour(price=1100)], regionname="Аланья"),
        _hotel("KEMER PRICEY", tours=[_tour(price=9000)], regionname="Кемер"),
    ]
    assert picked_places(hotels, limit=2) == ["Турция, Аланья"], "дорогой Кемер в карточки не попал"
    assert picked_places(hotels, limit=3) == ["Турция, Аланья", "Турция, Кемер"]
    assert picked_places([]) == []
