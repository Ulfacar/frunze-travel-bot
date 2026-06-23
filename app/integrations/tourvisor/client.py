"""Клиент TourVisor API (XML-шлюз, формат JSON).

Протокол асинхронный:
  1) search.php  → возвращает requestid
  2) result.php?requestid=... → опрашиваем, пока state != "finished"
  3) парсим отели/туры в читаемые строки для агента

Справочники (list.php: departure/country/operator) работают сразу.
ВНИМАНИЕ: на аккаунте Frunze Travel модуль поиска (search.php) пока НЕ активирован
(возвращает "Authorisation Error"); list.php/result.php — доступны. Код готов, заработает
сразу после включения XML-поиска на стороне TourVisor. Док: http://tourvisor.ru/xml/
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date, timedelta

import httpx

from app.config import settings

logger = logging.getLogger("tourvisor")

BASE_URL = "http://tourvisor.ru/xml"

# Опрос результата
POLL_INTERVAL = 1.5
POLL_TIMEOUT = 20.0

# Дефолты, если из текста не удалось распарсить
DEFAULT_NIGHTS = (7, 10)
DEFAULT_ADULTS = 2


class TourVisorError(Exception):
    """Ошибка API TourVisor (в т.ч. Authorisation Error при невключённом модуле поиска)."""


def _as_list(value) -> list:
    """TourVisor отдаёт один элемент объектом, несколько — массивом. Нормализуем в список."""
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


class TourVisorClient:
    def __init__(self) -> None:
        self._login = settings.tourvisor_login
        self._pass = settings.tourvisor_pass
        # Кэш справочников: type -> [{"id","name",...}]
        self._ref_cache: dict[str, list[dict]] = {}

    @property
    def configured(self) -> bool:
        return bool(self._login and self._pass)

    # ---------- низкоуровневый вызов ----------
    async def _call(self, client: httpx.AsyncClient, path: str, params: dict) -> dict:
        resp = await client.get(
            f"{BASE_URL}/{path}",
            params={"authlogin": self._login, "authpass": self._pass, "format": "json", **params},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict) and "error" in data:
            msg = (data["error"] or {}).get("errormessage", "").strip()
            raise TourVisorError(msg or "Unknown TourVisor error")
        return data

    # ---------- справочники ----------
    async def _ref(self, client: httpx.AsyncClient, list_type: str, plural: str, singular: str) -> list[dict]:
        """Загрузить и закэшировать справочник (departure/country/operator…)."""
        if list_type in self._ref_cache:
            return self._ref_cache[list_type]
        data = await self._call(client, "list.php", {"type": list_type})
        items = _as_list((data.get("lists", {}).get(plural, {}) or {}).get(singular))
        self._ref_cache[list_type] = items
        return items

    @staticmethod
    def _match_id(items: list[dict], text: str) -> str | None:
        """Сопоставить свободный текст («Турция», «Бишкек») с id справочника."""
        if not text:
            return None
        t = text.strip().lower()
        # точное совпадение имени
        for it in items:
            if it.get("name", "").lower() == t:
                return it.get("id")
        # вхождение в любую сторону (Анталия ⊂ ?, «из Бишкека» ⊃ Бишкек)
        for it in items:
            name = it.get("name", "").lower()
            if name and (name in t or t in name):
                return it.get("id")
        return None

    async def resolve_departure(self, client: httpx.AsyncClient, text: str) -> str | None:
        return self._match_id(await self._ref(client, "departure", "departures", "departure"), text)

    async def resolve_country(self, client: httpx.AsyncClient, text: str) -> str | None:
        return self._match_id(await self._ref(client, "country", "countries", "country"), text)

    # ---------- поиск ----------
    async def search(self, params: dict) -> list[str]:
        """Подбор туров по параметрам квалификации. Возвращает читаемые строки для агента."""
        if not self.configured:
            # Демо-режим без доступов — чтобы прогонять диалог офлайн.
            dest = params.get("destination", "направление")
            return [
                f"{dest}: отель 4*, 7 ночей, ~демо-цена (оператор A)",
                f"{dest}: отель 5*, 10 ночей, ~демо-цена (оператор B)",
            ]

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                query = await self._build_query(client, params)
                started = await self._call(client, "search.php", query)
                request_id = str(started.get("result", {}).get("requestid") or started.get("requestid", ""))
                if not request_id:
                    logger.warning("TourVisor: пустой requestid, ответ=%s", started)
                    return []
                hotels = await self._poll(client, request_id)
                return _format_hotels(hotels)
            except TourVisorError as e:
                logger.warning("TourVisor API: %s", e)
                # Пробрасываем понятный маркер наверх — агент сообщит, что подбор временно недоступен.
                raise

    async def _build_query(self, client: httpx.AsyncClient, params: dict) -> dict:
        """Свободный текст квалификации → параметры search.php."""
        query: dict[str, str | int] = {}

        dep = await self.resolve_departure(client, params.get("departure_city", "") or params.get("departure", ""))
        query["departure"] = dep or "80"  # дефолт — Бишкек

        country = await self.resolve_country(client, params.get("destination", ""))
        if country:
            query["country"] = country

        date_from, date_to = _parse_dates(params.get("dates", ""))
        if date_from:
            query["datefrom"] = date_from
            query["dateto"] = date_to

        nights_from, nights_to = _parse_nights(params.get("dates", "") + " " + str(params.get("nights", "")))
        query["nightsfrom"], query["nightsto"] = nights_from, nights_to

        adults, kids = _parse_tourists(params.get("tourists", ""))
        query["adults"] = adults
        if kids:
            query["child"] = kids

        stars = _parse_stars(params.get("hotel_stars", ""))
        if stars:
            query["stars"] = stars

        price_from, price_to = _parse_budget(params.get("budget", ""))
        if price_to:
            query["pricetype"] = 0  # цена за тур
            if price_from:
                query["pricefrom"] = price_from
            query["priceto"] = price_to

        return query

    async def _poll(self, client: httpx.AsyncClient, request_id: str) -> list[dict]:
        """Опрашивать result.php, пока поиск не завершится (или таймаут)."""
        waited = 0.0
        while waited < POLL_TIMEOUT:
            data = await self._call(client, "result.php", {"requestid": request_id})
            block = data.get("data", {})
            state = (block.get("status", {}) or {}).get("state", "")
            if state == "finished":
                return _as_list((block.get("result", {}) or {}).get("hotel"))
            if state in ("error", "no search results"):
                return []
            await asyncio.sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL
        # таймаут — отдаём, что успело прийти
        data = await self._call(client, "result.php", {"requestid": request_id})
        return _as_list(((data.get("data", {}).get("result", {})) or {}).get("hotel"))


# ---------- парсеры свободного текста ----------
def _parse_dates(text: str) -> tuple[str | None, str | None]:
    """Ищем dd.mm[.yyyy]. Если нашли одну дату — окно +14 дней; диапазон — как есть.

    Разделитель только «.» или «/» — чтобы «7-10 ночей» не принять за дату 07.10.
    """
    found = re.findall(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", text or "")
    if not found:
        return None, None

    def to_date(m) -> date:
        d, mo, y = int(m[0]), int(m[1]), int(m[2]) if m[2] else date.today().year
        if y < 100:
            y += 2000
        return date(y, mo, d)

    try:
        d1 = to_date(found[0])
        d2 = to_date(found[1]) if len(found) > 1 else d1 + timedelta(days=14)
    except ValueError:
        return None, None
    return d1.strftime("%d.%m.%Y"), d2.strftime("%d.%m.%Y")


def _parse_nights(text: str) -> tuple[int, int]:
    t = text or ""
    # диапазон «7-10 ночей»
    rng = re.search(r"(\d+)\s*[-–—]\s*(\d+)\s*ноч", t, re.IGNORECASE)
    if rng:
        a, b = int(rng.group(1)), int(rng.group(2))
        return min(a, b), max(a, b)
    nums = [int(n) for n in re.findall(r"(\d+)\s*ноч", t, re.IGNORECASE)]
    if len(nums) >= 2:
        return min(nums), max(nums)
    if len(nums) == 1:
        return nums[0], nums[0]
    return DEFAULT_NIGHTS


def _parse_tourists(text: str) -> tuple[int, int]:
    """«2 взрослых 1 ребёнок» → (2,1). Если непонятно — (2,0)."""
    t = (text or "").lower()
    adults_m = re.search(r"(\d+)\s*взросл", t)
    kids_m = re.search(r"(\d+)\s*(?:реб|дет)", t)
    if adults_m or kids_m:
        return (int(adults_m.group(1)) if adults_m else DEFAULT_ADULTS,
                int(kids_m.group(1)) if kids_m else 0)
    nums = [int(n) for n in re.findall(r"\d+", t)]
    if nums:
        return nums[0], 0
    return DEFAULT_ADULTS, 0


def _parse_stars(text: str) -> int | None:
    m = re.search(r"(\d)\s*\*", text or "") or re.search(r"(\d)\s*звёзд", (text or "").lower())
    return int(m.group(1)) if m else None


def _parse_budget(text: str) -> tuple[int | None, int | None]:
    nums = [int(n.replace(" ", "")) for n in re.findall(r"\d[\d\s]{2,}", text or "")]
    if not nums:
        return None, None
    if len(nums) >= 2:
        return min(nums), max(nums)
    return None, nums[0]


# ---------- форматирование результата ----------
def _format_hotels(hotels: list[dict], limit: int = 5) -> list[str]:
    out: list[str] = []
    for h in hotels[:limit]:
        tours = _as_list((h.get("tours", {}) or {}).get("tour"))
        best = tours[0] if tours else {}
        name = h.get("hotelname", "Отель")
        stars = h.get("hotelstars", "")
        region = h.get("regionname", "") or h.get("countryname", "")
        nights = best.get("nights", "")
        meal = best.get("mealrussian") or best.get("meal", "")
        price = best.get("price", "")
        currency = best.get("currency", "")
        operator = best.get("operatorname", "")
        parts = [f"{name}"]
        if stars:
            parts.append(f"{stars}*")
        if region:
            parts.append(region)
        tail = []
        if nights:
            tail.append(f"{nights} ноч.")
        if meal:
            tail.append(str(meal))
        if price:
            tail.append(f"от {price} {currency}".strip())
        if operator:
            tail.append(f"({operator})")
        line = " ".join(parts)
        if tail:
            line += " — " + ", ".join(tail)
        out.append(line)
    return out
