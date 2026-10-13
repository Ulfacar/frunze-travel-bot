"""ГЕЙТ: рейсы в карточке тура (просьба Гриши 02.10.2026).

Гриша прислал образец подборки туроператора и попросил слать так же. Бот уже слал этот
формат и ссылку; единственное, чего не хватало, — две строки перелёта:

    ✈️ 29 окт, 06:30 - 10:00, Red Sea Airlines - 20кг
    ✈️ 4 ноя, 20:15 - 05:30 +1, Red Sea Airlines - 20кг

Разведка на проде 02.10 (`scripts/tourvisor_flights_probe.py`) показала, что в поисковой
выдаче рейсов нет, а `actdetail.php` отдаёт их целиком: `departure.time`, `arrival.time`,
`company.name`, `baggage`, и «+1» шлюз проставляет сам внутри времени. Стоит это 12 с на
тур и 18–22 с на подборку — поэтому тумблер `tour_flights_enabled` с дефолтом OFF.

Фикстура ниже — сокращённый НАСТОЯЩИЙ ответ шлюза, снятый разведкой, а не выдуманная
структура: выдуманная разошлась бы со шлюзом молча.
"""
import app.config
from app.integrations.tourvisor import cards

# Реальный ответ actdetail.php (тур 13267327993537, Бишкек → Анталия, 22.10.2026).
FLIGHT = {
    "forward": [{
        "departure": {"date": "22.10.2026", "time": "05:40",
                      "port": {"id": "BSZ", "name": "Кыргызстан, Бишкек"}},
        "arrival": {"date": "22.10.2026", "time": "08:35",
                    "port": {"id": "AYT", "name": "Анталия, Турция"}},
        "company": {"id": "PC", "name": "Pegasus Airlines"},
        "baggage": 20, "carryOn": "8 кг", "number": "PC709",
    }],
    "backward": [{
        "departure": {"date": "29.10.2026", "time": "22:15",
                      "port": {"id": "AYT", "name": "Анталия, Турция"}},
        # Прилёт на следующий день: «+1» приходит ОТ ШЛЮЗА внутри времени.
        "arrival": {"date": "30.10.2026", "time": "06:05 +1",
                    "port": {"id": "BSZ", "name": "Кыргызстан, Бишкек"}},
        "company": {"id": "PC", "name": "Pegasus Airlines"},
        "baggage": 20, "carryOn": "8 кг", "number": "PC708",
    }],
}

HOTEL = {
    "hotelname": "KLEOPATRA SUN LIGHT HOTEL", "hotelstars": "3",
    "countryname": "Турция", "regionname": "Аланья", "seadistance": "250",
    "tours": {"tour": [{
        "tourid": "13267327993537", "flydate": "22.10.2026", "nights": "7",
        "room": "standard room a block", "adults": "2", "child": "0",
        "mealrussian": "AI - Ультра Все Включено", "price": "1499", "currency": "EUR",
    }]},
}


def _card(flights=None) -> str:
    return cards.render_card(HOTEL, departure="Бишкек", flights=flights)


# --- A. Формат строки — дословно по образцу -----------------------------------

def test_outbound_leg_matches_the_operator_template():
    assert "✈️ 22 окт, 05:40 - 08:35, Pegasus Airlines - 20кг" in _card(FLIGHT)


def test_return_leg_keeps_the_gateway_plus_one():
    """«+1» не вычисляем сами: часовые пояса — повод разойтись с оператором."""
    assert "✈️ 29 окт, 22:15 - 06:05 +1, Pegasus Airlines - 20кг" in _card(FLIGHT)


def test_flights_stand_right_after_the_destination():
    """Порядок строк в образце: куда летим → чем летим → когда заселяемся."""
    lines = _card(FLIGHT).splitlines()
    where = next(i for i, l in enumerate(lines) if "➡️" in l)
    legs = [i for i, l in enumerate(lines) if l.startswith("✈️ 2") or l.startswith("✈️ 29")]
    stay = next(i for i, l in enumerate(lines) if l.startswith("📅"))
    assert legs == [where + 1, where + 2], "рейсы стоят не сразу за направлением"
    assert max(legs) < stay, "рейсы попали ниже даты заезда"


# --- B. Деградация: подборка важнее формата -----------------------------------

def test_card_without_flights_is_exactly_the_old_one():
    """Тумблер OFF — текст прежний дословно, иначе это не откат, а другое поведение."""
    assert _card(None) == _card({})
    assert "Pegasus" not in _card(None)
    assert "🏷️ 1 499 eur за двоих" in _card(None)


def test_partial_flight_data_does_not_break_the_card():
    """Шлюз отдал половину — печатаем, что есть, и ничего не выдумываем."""
    only_forward = {"forward": FLIGHT["forward"]}
    card = _card(only_forward)
    assert "05:40 - 08:35" in card
    assert card.count("✈️ 22 окт") == 1
    assert "KLEOPATRA" in card


def test_leg_without_time_is_skipped_not_half_printed():
    broken = {"forward": [{"departure": {"date": "22.10.2026"},
                           "company": {"name": "Pegasus Airlines"}}]}
    card = _card(broken)
    assert "Pegasus" not in card, "строка рейса напечатана без времени"
    assert "🏠 *KLEOPATRA SUN LIGHT HOTEL 3⭐️*" in card


def test_missing_baggage_leaves_the_rest_of_the_line():
    no_bag = {"forward": [dict(FLIGHT["forward"][0], baggage=0)]}
    assert "✈️ 22 окт, 05:40 - 08:35, Pegasus Airlines" in _card(no_bag)
    assert "кг" not in _card(no_bag).split("📅")[0].split("➡️")[1]


# --- C. Пересадка — факт, а не умолчание --------------------------------------

def test_connection_is_named_out_loud():
    """Клиент, купивший «прямой» рейс с пересадкой, вернётся к менеджеру с претензией."""
    via = {"forward": [
        dict(FLIGHT["forward"][0],
             arrival={"date": "22.10.2026", "time": "07:00", "port": {"name": "Стамбул"}}),
        {"departure": {"date": "22.10.2026", "time": "09:00", "port": {"name": "Стамбул"}},
         "arrival": {"date": "22.10.2026", "time": "11:30", "port": {"name": "Анталия"}},
         "company": {"name": "Pegasus Airlines"}, "baggage": 20},
    ]}
    line = next(l for l in _card(via).splitlines() if l.startswith("✈️ 22 окт"))
    assert "05:40 - 11:30" in line, "маршрут не склеен от первого вылета до последнего прилёта"
    assert "1 пересадка" in line


# --- D. Спрашиваем рейсы только по тем турам, что увидит клиент ---------------

def test_only_shown_tours_are_actualized():
    """Актуализация стоит 12 с за тур: лишние запросы — это ожидание клиента впустую."""
    many = [dict(HOTEL, hotelname=f"HOTEL {i}",
                 tours={"tour": [dict(HOTEL["tours"]["tour"][0],
                                      tourid=f"id{i}", price=str(1000 + i))]})
            for i in range(9)]
    ids = cards.picked_tour_ids(many)
    assert len(ids) == cards.TOUR_CARDS_LIMIT == 5
    assert ids == ["id0", "id1", "id2", "id3", "id4"], "взяты не пять самых дешёвых"


def test_cards_match_flights_by_tour_id():
    """Рейсы раскладываются по своим турам, а не по порядку в списке."""
    other = dict(HOTEL, hotelname="SECOND HOTEL",
                 tours={"tour": [dict(HOTEL["tours"]["tour"][0], tourid="second", price="900")]})
    rendered = cards.render_cards([HOTEL, other], departure="Бишкек",
                                  flights={"13267327993537": FLIGHT})
    with_flights = [c for c in rendered if "Pegasus" in c]
    assert len(with_flights) == 1
    assert "KLEOPATRA" in with_flights[0], "рейсы приклеились к чужому отелю"


# --- E. Тумблер ---------------------------------------------------------------

def test_flag_defaults_to_off():
    """Ожидание выросло бы в шесть раз — такое не включается деплоем."""
    assert app.config.settings.tour_flights_enabled is False


def test_flag_is_switchable_without_deploy():
    from app.admin.router import FEATURE_FLAGS
    assert "tour_flights_enabled" in FEATURE_FLAGS


# --- F. Рейсы не переживают свой ход ------------------------------------------

def test_flights_are_cleared_with_the_rest_of_the_turn():
    """Рейсы прошлого поиска, приклеенные к следующей реплике, — это чужие данные
    в чужом ответе. Чистятся там же, где карточки: и на выдаче, и на входе хода."""
    import inspect
    from app.agent import runner
    from app.core.state import DialogState

    assert DialogState(user_id="frunze_tours:996700000001").pending_tour_flights == {}
    attach = inspect.getsource(runner._attach_tour_cards)
    enter = inspect.getsource(runner.run_tours_turn)
    assert "pending_tour_flights = {}" in attach, "рейсы не сбрасываются после выдачи"
    assert "pending_tour_flights = {}" in enter, "рейсы не сбрасываются на входе хода"


# --- G. Частичный ответ лучше пустого ----------------------------------------

def test_slow_tours_do_not_cancel_the_ones_that_answered():
    """Шлюз отвечает по 12 с на тур. Если ждать всех одним `gather`, один залипший
    тур обнуляет рейсы и у четырёх ответивших. Берём успевших."""
    import asyncio
    from app.integrations.tourvisor import client as tv_client

    calls = []

    async def fake_call(self, http, path, params):
        tour_id = params["tourid"]
        calls.append(tour_id)
        if tour_id == "slow":
            await asyncio.sleep(5)           # дольше таймаута ниже
        return {"flights": [{"forward": FLIGHT["forward"], "backward": FLIGHT["backward"]}]}

    original_call, original_timeout = tv_client.TourVisorClient._call, tv_client.FLIGHTS_TIMEOUT
    tv_client.TourVisorClient._call = fake_call
    tv_client.FLIGHTS_TIMEOUT = 0.4
    try:
        got = asyncio.run(tv_client.TourVisorClient().flights_for(["fast1", "slow", "fast2"]))
    finally:
        tv_client.TourVisorClient._call = original_call
        tv_client.FLIGHTS_TIMEOUT = original_timeout

    assert set(got) == {"fast1", "fast2"}, "успевшие туры потеряны из-за одного залипшего"
    assert "slow" not in got


def test_broken_tour_does_not_sink_the_others():
    import asyncio
    from app.integrations.tourvisor import client as tv_client

    async def fake_call(self, http, path, params):
        if params["tourid"] == "boom":
            raise RuntimeError("шлюз ответил мусором")
        return {"flights": [{"forward": FLIGHT["forward"]}]}

    original = tv_client.TourVisorClient._call
    tv_client.TourVisorClient._call = fake_call
    try:
        got = asyncio.run(tv_client.TourVisorClient().flights_for(["ok1", "boom", "ok2"]))
    finally:
        tv_client.TourVisorClient._call = original
    assert set(got) == {"ok1", "ok2"}


def test_no_tour_ids_means_no_calls_at_all():
    import asyncio
    from app.integrations.tourvisor import client as tv_client
    assert asyncio.run(tv_client.TourVisorClient().flights_for([])) == {}
    assert asyncio.run(tv_client.TourVisorClient().flights_for(["", "  "])) == {}
