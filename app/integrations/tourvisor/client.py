"""Клиент TourVisor API (XML-шлюз, формат JSON).

Протокол асинхронный:
  1) search.php  → возвращает requestid
  2) result.php?requestid=... → опрашиваем, пока state != "finished"
  3) парсим отели/туры в читаемые строки для агента

Справочники (list.php: departure/country/operator) работают сразу.
Модуль поиска (search.php) на аккаунте Frunze Travel АКТИВИРОВАН и отдаёт живые отели с
ценами (проверено 27.06.2026: search.php → requestid, result.php → отели). Док: http://tourvisor.ru/xml/
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote_plus

import httpx

from app.config import settings

logger = logging.getLogger("tourvisor")

BASE_URL = "http://tourvisor.ru/xml"

# Опрос результата. Замер 31.07.2026: поиск по Египту досчитывался 53 с — прежние 20 с
# обрывали его на 30% и превращали живую выдачу в «ничего не нашлось». Держим потолок выше,
# но как только отели есть, ждать «до конца» смысла нет: клиент в WhatsApp ждёт ответа.
POLL_INTERVAL = 1.5
POLL_TIMEOUT = 35.0
POLL_ENOUGH_AFTER = 15.0

# Ретрай обрывов связи с tourvisor.ru (см. _call).
NETWORK_RETRIES = 2
NETWORK_BACKOFF = 0.7

# Города вылета Frunze Travel. Из Бишкека TourVisor продаёт малую часть направлений,
# из Алматы — практически всё; правило «нет из Бишкека → предложи Алматы» идёт от менеджеров
# (см. branding.FRUNZE_DESTINATIONS).
BISHKEK_ID = "80"
ALMATY_ID = "60"


@dataclass
class TourSearch:
    """Результат подбора вместе с причиной — агент не должен домысливать её сам."""

    lines: list[str]
    found: int
    reason: str  # ok | no_destination | nothing_found
    departure: str = ""
    fallback_departure: bool = False
    min_price: str = ""
    query: dict | None = None

# Дефолты, если из текста не удалось распарсить
DEFAULT_NIGHTS = (7, 10)
DEFAULT_ADULTS = 2
# TourVisor ТРЕБУЕТ возраст КАЖДОГО ребёнка (childage1..N) — без него поиск с детьми
# возвращает 0 отелей. Если возраст неизвестен — подставляем дефолт, чтобы не сломать выдачу.
DEFAULT_CHILD_AGE = 7
MAX_CHILDREN = 4  # лимит TourVisor (childage1..childage4)


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
        # Единственная точка выхода в API — здесь и считаем суточную квоту (3000/сутки).
        # Учитываем ДО запроса: провайдер тратит квоту и на ошибочные вызовы.
        from app.integrations.tourvisor import quota
        query = {"authlogin": self._login, "authpass": self._pass, "format": "json", **params}

        # Связь с tourvisor.ru рвётся: за один сеанс диагностики 31.07.2026 httpx.ReadError
        # прилетал трижды, и каждый раз со второй попытки запрос проходил. Без ретрая одна
        # такая осечка роняет ВЕСЬ подбор, и живой клиент слышит «поиск временно недоступен»
        # вместо своих туров. Ретраим только обрывы транспорта: ошибки самого API (неверные
        # параметры, кончившаяся квота) повторять бессмысленно.
        for attempt in range(NETWORK_RETRIES + 1):
            await quota.note_call()
            try:
                resp = await client.get(f"{BASE_URL}/{path}", params=query)
                resp.raise_for_status()
                break
            except httpx.TransportError:
                if attempt == NETWORK_RETRIES:
                    raise
                logger.info("TourVisor: обрыв связи на %s, повтор %s", path, attempt + 1)
                await asyncio.sleep(NETWORK_BACKOFF * (attempt + 1))

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

    async def _all_regions(self, client: httpx.AsyncClient) -> list[dict]:
        """Справочник ВСЕХ курортов мира одним вызовом (на проде 676 записей).

        Каждая запись несёт id своей страны — поэтому названный клиентом курорт сам
        определяет страну, и «Пхукет» перестаёт быть запросом без country."""
        if "region:all" in self._ref_cache:
            return self._ref_cache["region:all"]
        data = await self._call(client, "list.php", {"type": "region"})
        items = _as_list((data.get("lists", {}).get("regions", {}) or {}).get("region"))
        self._ref_cache["region:all"] = items
        return items

    @staticmethod
    def _match_region(regions: list[dict], text: str, country: str | None = None) -> dict | None:
        """Кусок свободного текста → запись курорта. Страна, если известна, сужает пул."""
        t = (text or "").strip().lower()
        if len(t) < 3:
            return None
        pool = [r for r in regions if str(r.get("country")) == str(country)] if country else []
        for items in (pool, regions):
            for r in items:
                if str(r.get("name", "")).lower() == t:
                    return r
            for r in items:
                name = str(r.get("name", "")).lower()
                # Порог длины — чтобы короткие названия не ловились подстрокой наугад.
                if len(name) >= 4 and name in t:
                    return r
        return None

    async def resolve_destination(
        self, client: httpx.AsyncClient, destination: str, region_text: str = ""
    ) -> tuple[str | None, str | None]:
        """Свободный текст → (id страны, «id курортов через запятую»).

        Клиент называет курорт («Пхукет», «Хургада», «Дубай») минимум так же часто, как
        страну. Раньше страна искалась только по списку стран → не находилась → запрос уходил
        БЕЗ country, и TourVisor искал по всему миру (боевой случай: просили Пхукет, получили
        Шарм-эль-Шейх). Теперь курорт восстанавливает страну сам.
        """
        parts = [
            p.strip()
            for chunk in (destination or "", region_text or "")
            for p in re.split(r"[,/;]|\sи\s", chunk)
            if p.strip()
        ]
        if not parts:
            return None, None

        countries = await self._ref(client, "country", "countries", "country")
        country = self._match_id(countries, destination or "") or next(
            (cid for p in parts if (cid := self._match_id(countries, p))), None
        )

        regions = await self._all_regions(client)
        hits: list[dict] = []
        for part in parts:
            hit = self._match_region(regions, part, country)
            if hit and hit not in hits:
                hits.append(hit)

        if not country and hits:
            country = str(hits[0].get("country") or "") or None
        if not country:
            return None, None

        ids = [str(r.get("id")) for r in hits if str(r.get("country")) == str(country)]
        return country, (",".join(ids) or None)

    # ---------- поиск ----------
    async def search(self, params: dict) -> list[str]:
        """Совместимый вход: только строки вариантов (без диагностики)."""
        return (await self.search_detailed(params)).lines

    async def search_detailed(self, params: dict) -> TourSearch:
        """Подбор туров с ДИАГНОЗОМ: что искали, сколько нашли и почему пусто.

        Раньше наверх уходил голый список строк, и на пустой выдаче агент не знал причины —
        поэтому выдумывал её («август дорогой, поднимите бюджет»), а клиент впустую поднимал
        бюджет. Теперь причина машинная, и агент обязан назвать именно её.
        """
        if not self.configured:
            # Демо-режим без доступов — чтобы прогонять диалог офлайн.
            dest = params.get("destination", "направление")
            return TourSearch(
                lines=[f"{dest}: отель 4*, 7 ночей, ~демо-цена (оператор A)",
                       f"{dest}: отель 5*, 10 ночей, ~демо-цена (оператор B)"],
                found=2, reason="ok", departure="", fallback_departure=False,
            )

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                query = await self._build_query(client, params)
                if not query.get("country"):
                    # Поиск без страны TourVisor выполняет по всему миру — именно так на
                    # «Пхукет» клиенту прилетал Шарм-эль-Шейх. Лучше честно переспросить.
                    return TourSearch([], 0, "no_destination", "", False)

                departure = str(query.get("departure") or BISHKEK_ID)
                hotels = await self._search_once(client, query)

                # Из Бишкека продаётся малая часть направлений (Египет/Таиланд/Кипр — ноль).
                # Правило менеджеров (branding.FRUNZE_DESTINATIONS): нет из Бишкека — смотрим
                # из Алматы. Раньше этого не делал никто, и живые заявки уходили в пустоту.
                fallback = False
                if not hotels and departure == BISHKEK_ID:
                    hotels = await self._search_once(client, {**query, "departure": ALMATY_ID})
                    if hotels:
                        departure, fallback = ALMATY_ID, True

                names = await self._ref(client, "departure", "departures", "departure")
                dep_name = next((d.get("name", "") for d in names if str(d.get("id")) == departure), "")
                if not hotels:
                    return TourSearch([], 0, "nothing_found", dep_name, False, query=query)
                return TourSearch(
                    lines=_format_hotels(hotels),
                    found=len(hotels),
                    reason="ok",
                    departure=dep_name,
                    fallback_departure=fallback,
                    min_price=_min_price_label(hotels),
                    query=query,
                )
            except TourVisorError as e:
                logger.warning("TourVisor API: %s", e)
                # Пробрасываем понятный маркер наверх — агент сообщит, что подбор временно недоступен.
                raise

    async def _search_once(self, client: httpx.AsyncClient, query: dict) -> list[dict]:
        """Один полный проход: запустить поиск и дождаться результата."""
        started = await self._call(client, "search.php", query)
        request_id = str(started.get("result", {}).get("requestid") or started.get("requestid", ""))
        if not request_id:
            logger.warning("TourVisor: пустой requestid, ответ=%s", started)
            return []
        return await self._poll(client, request_id)

    async def _build_query(self, client: httpx.AsyncClient, params: dict) -> dict:
        """Свободный текст квалификации → параметры search.php."""
        query: dict[str, str | int] = {}

        dep = await self.resolve_departure(client, params.get("departure_city", "") or params.get("departure", ""))
        query["departure"] = dep or "80"  # дефолт — Бишкек

        country, regions = await self.resolve_destination(
            client, params.get("destination", ""), params.get("region", "")
        )
        if country:
            query["country"] = country
            if regions:
                query["regions"] = regions

        meal = _parse_meal(" ".join(t for t in (params.get("meal", ""), params.get("destination", "")) if t))
        if meal:
            query["meal"] = meal  # TourVisor ищет указанное питание и лучше

        date_from, date_to, span = _parse_date_range(params.get("dates", ""))
        if date_from:
            query["datefrom"] = date_from.strftime("%d.%m.%Y")
            query["dateto"] = (date_to or date_from).strftime("%d.%m.%Y")

        # Явно названные ночи важнее вычисленных из диапазона дат.
        nights = _explicit_nights(f"{params.get('dates', '')} {params.get('nights', '')}")
        if nights is None and span:
            nights = (span, span)
        query["nightsfrom"], query["nightsto"] = nights or DEFAULT_NIGHTS

        adults, child_ages = _parse_tourists(
            params.get("tourists", ""), params.get("children_ages", "")
        )
        query["adults"] = adults
        if child_ages:
            query["child"] = len(child_ages)
            for i, age in enumerate(child_ages, 1):
                query[f"childage{i}"] = age  # TourVisor: возраст обязателен для каждого ребёнка

        stars = _parse_stars(str(params.get("hotel_stars", "") or params.get("stars", "")))
        if stars:
            query["stars"] = stars

        # Бюджет СОЗНАТЕЛЬНО не уходит в запрос. TourVisor отдаёт выдачу по возрастанию цены,
        # а его priceto — в валюте оператора (на деле EUR). Клиент называет сумму в сомах или
        # «на человека», и жёсткий потолок превращал живой запрос в пустой: боевой случай
        # «500 тыс. сом» → priceto=500 EUR → ноль вариантов и выдуманное «август дорогой».
        # Теперь бюджет размечает готовую выдачу у нас (см. _format_hotels), а не режет её.
        return query

    async def _poll(self, client: httpx.AsyncClient, request_id: str) -> list[dict]:
        """Опрашивать result.php до завершения поиска, таймаута или «уже достаточно».

        Клиент ждёт ответа в мессенджере, поэтому досчитывать поиск до 100% ради шестого
        отеля незачем: как только набралось достаточно вариантов, отдаём их.
        """
        waited = 0.0
        while waited < POLL_TIMEOUT:
            data = await self._call(client, "result.php", {"requestid": request_id})
            block = data.get("data", {})
            state = (block.get("status", {}) or {}).get("state", "")
            hotels = _as_list((block.get("result", {}) or {}).get("hotel"))
            if state == "finished":
                return hotels
            if state in ("error", "no search results"):
                return []
            if hotels and waited >= POLL_ENOUGH_AFTER:
                return hotels
            await asyncio.sleep(POLL_INTERVAL)
            waited += POLL_INTERVAL
        # таймаут — отдаём, что успело прийти
        data = await self._call(client, "result.php", {"requestid": request_id})
        return _as_list(((data.get("data", {}).get("result", {})) or {}).get("hotel"))


# ---------- парсеры свободного текста ----------
# Месяцы словами. Порядок важен: более длинные основы проверяются первыми, иначе «мар»
# перехватит «мая». Живые логи показывают, что LLM пишет даты именно так («10-16 августа»,
# «август 2026»), а не в dd.mm — раньше такие строки молча выпадали из запроса целиком.
_RU_MONTHS: tuple[tuple[str, int], ...] = (
    ("январ", 1), ("феврал", 2), ("март", 3), ("апрел", 4), ("мая", 5), ("мае", 5),
    ("май", 5), ("июн", 6), ("июл", 7), ("август", 8), ("сентябр", 9), ("октябр", 10),
    ("ноябр", 11), ("декабр", 12),
)

# Диапазон дат шире этого считаем не поездкой, а окном поиска — ночи из него не выводим.
_MAX_TRIP_SPAN_DAYS = 30


def _roll_to_future(d1: date, d2: date) -> tuple[date, date]:
    """Прошедшая дата → ближайший будущий год. TourVisor на прошлые даты отвечает bad format."""
    today = date.today()
    while d1 < today:
        try:
            d1, d2 = d1.replace(year=d1.year + 1), d2.replace(year=d2.year + 1)
        except ValueError:  # 29 февраля в невисокосный год
            d1, d2 = d1 + timedelta(days=365), d2 + timedelta(days=365)
    return d1, d2


def _month_from_text(text: str) -> int | None:
    for stem, num in _RU_MONTHS:
        if stem in text:
            return num
    return None


def _last_day(year: int, month: int) -> int:
    return (date(year + (month == 12), (month % 12) + 1, 1) - timedelta(days=1)).day


def _parse_date_range(text: str) -> tuple[date | None, date | None, int | None]:
    """Свободный текст → (дата с, дата по, ночей из диапазона).

    Третий элемент заполняется, ТОЛЬКО когда клиент назвал обе границы поездки — тогда из
    них выводится длительность («10-16 августа» = 6 ночей). Для синтезированного окна
    (одна дата, целый месяц) он None, чтобы не выдать ширину окна за длительность тура.
    """
    t = (text or "").strip().lower()
    if not t:
        return None, None, None

    # 1) Числовой формат dd.mm[.yyyy]. Разделитель только «.» или «/» — чтобы «7-10 ночей»
    #    не принять за 07.10.
    found = re.findall(r"(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?", t)
    if found:
        def to_date(m) -> date:
            d, mo, y = int(m[0]), int(m[1]), int(m[2]) if m[2] else date.today().year
            return date(y + 2000 if y < 100 else y, mo, d)

        try:
            d1 = to_date(found[0])
            explicit_end = len(found) > 1
            d2 = to_date(found[1]) if explicit_end else d1 + timedelta(days=14)
        except ValueError:
            return None, None, None
        d1, d2 = _roll_to_future(d1, d2)
        span = (d2 - d1).days if explicit_end else None
        return d1, d2, (span if span and 0 < span <= _MAX_TRIP_SPAN_DAYS else None)

    # 2) Месяц словами: «10-16 августа», «8-10 сентября», «август 2026», «в августе».
    month = _month_from_text(t)
    if not month:
        return None, None, None

    year_m = re.search(r"\b(20\d{2})\b", t)
    year = int(year_m.group(1)) if year_m else date.today().year

    # Числа ДО названия месяца — это дни («с 10 по 16 августа»). Год стоит после и сюда
    # не попадает.
    head = t[: t.index(next(s for s, n in _RU_MONTHS if s in t and n == month))]
    days = [int(n) for n in re.findall(r"\b(\d{1,2})\b", head) if 1 <= int(n) <= 31]

    try:
        if len(days) >= 2:
            d1, d2 = date(year, month, days[-2]), date(year, month, days[-1])
        elif len(days) == 1:
            d1 = date(year, month, days[0])
            d2 = d1 + timedelta(days=14)
        else:  # месяц целиком
            d1 = date(year, month, 1)
            d2 = date(year, month, _last_day(year, month))
    except ValueError:
        return None, None, None

    if d2 < d1:
        d1, d2 = d2, d1
    d1, d2 = _roll_to_future(d1, d2)
    span = (d2 - d1).days if len(days) >= 2 else None
    return d1, d2, (span if span and 0 < span <= _MAX_TRIP_SPAN_DAYS else None)


def _parse_dates(text: str) -> tuple[str | None, str | None]:
    """Обёртка для совместимости: даты в формате TourVisor (dd.mm.yyyy)."""
    d1, d2, _ = _parse_date_range(text)
    if not d1:
        return None, None
    return d1.strftime("%d.%m.%Y"), (d2 or d1).strftime("%d.%m.%Y")


def _explicit_nights(text: str) -> tuple[int, int] | None:
    """Ночи, ЯВНО названные в тексте. None — не названы (тогда считаем из дат)."""
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
    return None


def _parse_nights(text: str) -> tuple[int, int]:
    return _explicit_nights(text) or DEFAULT_NIGHTS


def _parse_tourists(text: str, ages_text: str = "") -> tuple[int, list[int]]:
    """«2 взрослых, дети 10 и 5» → (2, [10, 5]). Возвращает (взрослые, возрасты_детей).

    Возрасты детей ОБЯЗАТЕЛЬНЫ для TourVisor. Источники в порядке приоритета:
      1) отдельное поле инструмента `children_ages` (напр. «10, 8, 5»);
      2) числа после слова «дети/ребёнок» в свободном тексте;
      3) если известно только число детей без возрастов — подставляем DEFAULT_CHILD_AGE.
    Так поиск с детьми перестаёт возвращать пусто.
    """
    t = (text or "").lower()

    adults_m = re.search(r"(\d+)\s*взросл", t)
    adults = int(adults_m.group(1)) if adults_m else DEFAULT_ADULTS

    # Кол-во детей: число ПЕРЕД словом «дети/ребёнок» («3 детей», «1 ребёнок»).
    kids_m = re.search(r"(\d+)\s*(?:дет|реб)", t)
    kids_count = int(kids_m.group(1)) if kids_m else 0

    # Явные возрасты из отдельного поля имеют приоритет.
    ages = [int(n) for n in re.findall(r"\d+", ages_text or "")]
    if not ages:
        # Возрасты из свободного текста: числа ПОСЛЕ слова «дети/ребёнок/малыш»
        # («дети 10, 12 и 2 года»). Число-счётчик стоит до слова и сюда не попадает.
        kw = re.search(r"(?:дет\w*|реб[её]\w*|малыш\w*)", t)
        if kw:
            ages = [int(n) for n in re.findall(r"\d+", t[kw.end():])]

    # Нет ни взрослых, ни детей по ключевым словам — старое поведение «первое число = взрослые».
    if not adults_m and not kids_m and not ages:
        nums = [int(n) for n in re.findall(r"\d+", t)]
        return (nums[0] if nums else DEFAULT_ADULTS), []

    n = min(max(kids_count, len(ages)), MAX_CHILDREN)
    if n == 0:
        return adults, []
    ages = (ages + [DEFAULT_CHILD_AGE] * n)[:n]  # дополняем дефолтом / обрезаем под кол-во
    return adults, ages


def _parse_stars(text: str) -> int | None:
    """«5», «5*», «5 звёзд», «4-5*» → минимальная звёздность (TourVisor ищет её и выше).

    Голое число тоже принимаем: поле приходит из отдельного параметра инструмента, а не из
    общего текста, поэтому спутать его не с чем."""
    t = (text or "").strip().lower()
    m = (re.search(r"([1-5])\s*\*", t)
         or re.search(r"([1-5])\s*звёзд", t)
         or re.search(r"([1-5])\s*звезд", t)
         or re.fullmatch(r"\s*([1-5])\s*", t))
    return int(m.group(1)) if m else None


def _parse_meal(text: str) -> int | None:
    """Тип питания → код TourVisor (2 RO, 3 BB, 4 HB, 5 FB, 7 AI, 9 UAI)."""
    t = (text or "").lower()
    if "ультра" in t or "uai" in t:
        return 9
    if "всё включ" in t or "все включ" in t or "all incl" in t or re.search(r"\bai\b", t):
        return 7
    if "полный пансион" in t or "fb" in t:
        return 5
    if "полупансион" in t or "hb" in t or ("завтрак" in t and "ужин" in t):
        return 4
    if "завтрак" in t or "bb" in t:
        return 3
    if "без питания" in t or "room only" in t or re.search(r"\bro\b", t):
        return 2
    return None


def _parse_budget(text: str) -> tuple[int | None, int | None]:
    nums = [int(n.replace(" ", "")) for n in re.findall(r"\d[\d\s]{2,}", text or "")]
    if not nums:
        return None, None
    if len(nums) >= 2:
        return min(nums), max(nums)
    return None, nums[0]


# ---------- форматирование результата ----------
def _hotel_price(h: dict) -> int:
    """Числовая цена лучшего тура отеля — для сортировки «самые дешёвые». Нечитаемое → +∞."""
    best = (_as_list((h.get("tours", {}) or {}).get("tour")) or [{}])[0]
    try:
        return int(str(best.get("price", "")).replace(" ", ""))
    except (TypeError, ValueError):
        return 10**9


def _min_price_label(hotels: list[dict]) -> str:
    """«10525 USD» по самому дешёвому туру — чтобы агент называл честную минимальную цену."""
    if not hotels:
        return ""
    best_hotel = min(hotels, key=_hotel_price)
    best = (_as_list((best_hotel.get("tours", {}) or {}).get("tour")) or [{}])[0]
    price, currency = best.get("price", ""), best.get("currency", "")
    return f"{price} {currency}".strip()


def _format_hotels(hotels: list[dict], limit: int = 5) -> list[str]:
    out: list[str] = []
    for h in hotels[:limit]:
        tours = _as_list((h.get("tours", {}) or {}).get("tour"))
        best = tours[0] if tours else {}
        name = h.get("hotelname", "Отель")
        stars = h.get("hotelstars", "")
        region = h.get("regionname", "") or h.get("countryname", "")
        flydate = best.get("flydate", "")
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
        # Дата вылета — обязательна. Без неё ни клиент, ни бот не замечали, что показаны
        # туры на совсем другие числа (боевой случай: просили 10–16.08, показывали 03–06.08).
        if flydate:
            tail.append(f"вылет {flydate}")
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
            line += ". " + ", ".join(tail)
        out.append(line)
    return out


def _hotel_link(name: str, region: str = "") -> str:
    """Ссылку на отель бот больше НЕ даёт. Оставлено пустым намеренно.

    Раньше сюда подставлялся поиск в Google по названию отеля — заглушка, потому что XML
    TourVisor не отдаёт публичный URL карточки. На живом диалоге 03.08 стало видно, чем это
    оборачивается: мы платим за рекламу, доводим клиента до подбора и на последнем шаге сами
    отправляем его в выдачу, где рядом стоят Booking и цены конкурентов на тот же отель.

    Менеджеры так не делают: они шлют карточку тура (`tourcart.ru/?tvcard=…`), которая ведёт
    в нашу воронку и уже содержит даты, состав и бронь. Собрать такую ссылку из XML мы пока
    не умеем — до тех пор бот называет отель словами, а карточку присылает человек.
    """
    return ""
