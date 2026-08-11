"""Подборка туров в том виде, в каком её присылают менеджеры.

Отдельный модуль без сети: формат — это то, что владелец будет править по вкусу, а транспорт
(`client.py`) — нет. Чистые функции легко прогнать на исторических данных перед продом.

Почему карточки собирает код, а не модель. До 11.08 весь текст клиенту сочинял LLM, и три
силы подряд не давали ему стать подборкой: промпт «1–2 фразы, максимум ~300 знаков, БЕЗ
markdown и списков» (`prompts/common.py`), лимит `llm_max_tokens=512` и валидатор, срезающий
жирный и буллеты. В 300 знаков влезает ровно один отель — клиент его и получал.

Разметка здесь — **WhatsApp**, а не markdown: одиночные `*` дают жирный. Поэтому блок
карточек дописывается ПОСЛЕ `validate_reply` (см. `runner.run_turn`) — иначе `strip_markdown`
съел бы звёздочки, а `_SPACED_DASH` порезал бы строки.

Данные — из живого ответа TourVisor (разведка 11.08): `room`, `placement`, `adults`, `child`
приходят у 100% туров, поэтому тип номера и состав НЕ угадываются из запроса клиента.
"""
from __future__ import annotations

import re

# Решение владельца 11.08: у менеджеров в шаблоне 8 карточек, но в мессенджере это простыня.
TOUR_CARDS_LIMIT = 5

_MONTHS = ("янв", "фев", "мар", "апр", "май", "июн",
           "июл", "авг", "сен", "окт", "ноя", "дек")

# Разметка WhatsApp: эти символы в названии отеля превратили бы пол-сообщения в жирный/курсив.
_MARKUP = re.compile(r"[*_~`]+")
_MEAL_CODE = re.compile(r"^[A-Z]{2,5}\s*-\s*")
_SPACES = re.compile(r"\s+")


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _clean_name(raw) -> str:
    """Имя отеля без разметки и переводов строк."""
    return _SPACES.sub(" ", _MARKUP.sub("", str(raw or ""))).strip()


def _price(raw) -> int | None:
    """Цена числом. Пусто и мусор → None: отель без цены в подборку не идёт."""
    text = _SPACES.sub("", str(raw or "").replace(" ", ""))
    if not text:
        return None
    try:
        value = float(text.replace(",", "."))
    except ValueError:
        return None
    return int(value) if value > 0 else None


def _money(value: int) -> str:
    """2364 → «2 364»: как в сообщениях менеджеров."""
    return f"{value:,}".replace(",", " ")


def _date(raw) -> str:
    """«17.08.2026» → «17 авг». Не распарсилось — отдаём как есть, не выдумываем."""
    text = str(raw or "").strip()
    match = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})", text)
    if not match:
        return text
    day, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        return text
    return f"{day} {_MONTHS[month - 1]}"


def _meal(tour: dict) -> str:
    """«AI - Все Включено» → «Все Включено»: код питания клиенту ничего не говорит."""
    raw = str(tour.get("mealrussian") or tour.get("meal") or "").strip()
    return _MEAL_CODE.sub("", raw).strip()


def _people(tour: dict) -> str:
    """Состав ТУРА, а не запроса клиента.

    На «2 взрослых + дети 7 и 12» TourVisor вернул `adults=3, child=1` — двенадцатилетний
    считается взрослым, и цена посчитана именно так. Покажем запрошенное — клиент не сойдётся
    с менеджером по цене.
    """
    def _num(key: str) -> int:
        try:
            return int(str(tour.get(key) or 0).strip() or 0)
        except ValueError:
            return 0

    adults, child = _num("adults"), _num("child")
    parts = []
    if adults > 0:
        parts.append(f"{adults}взр")
    if child > 0:
        parts.append(f"{child}реб")
    return " ".join(parts)


def _best_tour(hotel: dict) -> tuple[dict, int] | None:
    """Самый дешёвый тур отеля с пригодной ценой. Нет такого — отеля в подборке нет."""
    best: tuple[dict, int] | None = None
    for tour in _as_list((hotel.get("tours") or {}).get("tour")):
        if not isinstance(tour, dict):
            continue
        price = _price(tour.get("price"))
        # Валюту берём ИЗ ТОГО ЖЕ тура, а не с уровня отеля: цена и валюта обязаны приехать
        # из одной записи, иначе однажды покажем евровую цену с сомовой подписью.
        currency = str(tour.get("currency") or "").strip()
        if price is None or not currency:
            continue
        if best is None or price < best[1]:
            best = (tour, price)
    return best


def render_card(hotel: dict, *, departure: str = "") -> str:
    """Одна карточка. Пустая строка — отель показывать нельзя."""
    name = _clean_name(hotel.get("hotelname"))
    picked = _best_tour(hotel)
    if not name or picked is None:
        return ""
    tour, price = picked
    currency = str(tour.get("currency") or "").strip().lower()

    stars = str(hotel.get("hotelstars") or "").strip()
    head = f"{name} {stars}⭐️" if stars else name
    lines = [f"🏠 *{head}*"]

    where = ", ".join(x for x in (str(hotel.get("countryname") or "").strip(),
                                  str(hotel.get("regionname") or "").strip()) if x)
    if where:
        lines.append(f"✈️ {departure} ➡️ {where}" if departure else f"✈️ {where}")

    when = [x for x in (_date(tour.get("flydate")),) if x]
    nights = str(tour.get("nights") or "").strip()
    if nights:
        when.append(f"🌙 {nights}нч")
    if when:
        lines.append("📅 " + ", ".join(when) if when[0] != f"🌙 {nights}нч" else when[0])

    stay = ", ".join(x for x in (str(tour.get("room") or "").strip(), _people(tour)) if x)
    if stay:
        lines.append(f"🛌 {stay}")

    meal = _meal(tour)
    if meal:
        lines.append(f"🍽️ {meal}")

    lines.append(f"🏷️ {_money(price)} {currency}")
    return "\n".join(lines)


def pick(hotels: list[dict], *, limit: int = TOUR_CARDS_LIMIT) -> list[tuple[dict, dict, int]]:
    """Что показываем: дешёвые сверху, по одному туру на отель, не больше `limit`.

    Отбор один на всех — и для карточек в чате, и для страницы подборки. Иначе клиент,
    перейдя по ссылке «Подробнее», увидел бы другой набор отелей, чем в сообщении.
    """
    chosen: list[tuple[dict, dict, int]] = []
    seen: set[str] = set()
    for hotel in hotels or []:
        if not isinstance(hotel, dict):
            continue
        key = _clean_name(hotel.get("hotelname")).upper()
        best = _best_tour(hotel)
        if not key or key in seen or best is None:
            continue
        seen.add(key)
        chosen.append((hotel, best[0], best[1]))
    chosen.sort(key=lambda item: item[2])
    return chosen[:limit]


def render_cards(hotels: list[dict], *, departure: str = "",
                 limit: int = TOUR_CARDS_LIMIT) -> list[str]:
    """Подборка карточками для мессенджера."""
    cards = [render_card(hotel, departure=departure)
             for hotel, _, _ in pick(hotels, limit=limit)]
    return [card for card in cards if card]


def offer_items(hotels: list[dict], *, departure: str = "",
                limit: int = TOUR_CARDS_LIMIT) -> list[dict]:
    """Те же отели, но структурой — для страницы подборки.

    Здесь берём и то, чего нет в карточке мессенджера: фото, описание, рейтинг, расстояние
    до моря. Разведка 11.08 показала, что всё это приходит у 100% отелей — именно из этих
    полей страница и становится похожей на то, что менеджеры шлют вручную.
    """
    items: list[dict] = []
    for hotel, tour, price in pick(hotels, limit=limit):
        items.append({
            "name": _clean_name(hotel.get("hotelname")),
            "stars": str(hotel.get("hotelstars") or "").strip(),
            "rating": str(hotel.get("hotelrating") or "").strip(),
            "picture": str(hotel.get("picturelink") or "").strip(),
            "description": str(hotel.get("hoteldescription") or "").strip(),
            "country": str(hotel.get("countryname") or "").strip(),
            "region": str(hotel.get("regionname") or "").strip(),
            "seadistance": str(hotel.get("seadistance") or "").strip(),
            "departure": departure,
            "flydate": _date(tour.get("flydate")),
            "nights": str(tour.get("nights") or "").strip(),
            "room": str(tour.get("room") or "").strip(),
            "people": _people(tour),
            "meal": _meal(tour),
            "operator": str(tour.get("operatorname") or "").strip(),
            "price": _money(price),
            "currency": str(tour.get("currency") or "").strip().lower(),
        })
    return items


def render_block(cards: list[str], *, offer_url: str = "") -> str:
    """Готовый хвост сообщения. Пустая подборка — пустая строка, без висящих заголовков."""
    if not cards:
        return ""
    block = "\n\n".join(cards)
    if offer_url:
        block += f"\n\nПодробнее здесь:\n{offer_url}"
    return block
