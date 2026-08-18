"""Факты клиента записываются, когда он их назвал, а не когда бот решил поискать.

До сегодня `qualification` наполнялась ТОЛЬКО из аргументов вызова `search_tours`
(`runner.py:360`). Замеры 18.08.2026 на боевом портале показали цену этого:

* лид 186243 — семь ходов, клиент назвал всё, бот четыре раза подряд спрашивал про
  питание и поиск не вызвал: карточка осталась пустой, стадия `NEW`;
* лид 186247 — клиент ушёл на Дубай и вернулся в Анталью, бот согласился словами, но
  поиск не перезапустил: **в карточке остался Дубай**. Это хуже пустоты — карточка
  противоречит разговору, а менеджер подтверждает заявку по ней.

Разбор детерминированный (закон 1 `docs/venom-v2.md`). Числа режем разборщиками, которые
уже обкатаны боем в `app/integrations/tourvisor/client.py`, — но ТОЛЬКО после сторожей
ниже. Те разборщики писались для аргументов инструмента, где текст уже отобран моделью,
поэтому они щедрые: на «457838 Аширбаев Равшан маратович» `_parse_budget` честно вернёт
457838 USD. В свободной реплике клиента такая щедрость превращается в враньё в карточке.

Три сторожа, каждый — с боевой фразой за спиной:

1. **Маркер обязателен.** Число становится бюджетом только рядом со словом о деньгах,
   составом — только рядом со словом о людях. Иначе «2 с багажом 1 ручная» (про билеты)
   превращается в двух туристов, а номер паспорта — в бюджет.
2. **Прошедшее время — не факт о поездке.** «У нас в прошлом году на двоих в 5 звезд
   отель вышло 1200 с завтраком» — это рассказ, а не запрос. Молчим целиком.
3. **Отрицание перед городом.** «Не из Бишкека, а из Алматы» — берём город ПОСЛЕ
   противопоставления, а не первый найденный.

Пропустить факт дешевле, чем соврать: пустая карточка заставит менеджера прочитать
диалог, карточка с чужим бюджетом — обманет его.

Гейт: `tests/test_tour_facts.py`. ТЗ: `docs/task-tour-facts.md`.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("agent.facts")

FIELDS: tuple[str, ...] = (
    "destination", "region", "departure_city", "budget", "dates",
    "tourists", "children_ages",
)

# ---------- словари ----------

# Города вылета, с которыми работает Frunze (`branding.FRUNZE_DEPARTURE_CITIES`) плюс те,
# что клиенты называют сами. Основа — с границами слова: «ош» иначе найдётся в «хорошая».
_DEPARTURE_CITIES: tuple[tuple[str, str], ...] = (
    (r"бишкек\w*", "Бишкек"),
    (r"алмат\w*|алма-ат\w*", "Алматы"),
    (r"ош[аеу]?\b", "Ош"),
    (r"ташкент\w*", "Ташкент"),
)

# Направления, которые реально продаются из Бишкека и Алматы. Чего в списке нет —
# направлением не считаем: «>Сеул >Нагоя» из билетного диалога не должно уехать в
# туровую карточку.
_COUNTRIES: tuple[tuple[str, str], ...] = (
    (r"турци\w*|турцию|турция", "Турция"),
    (r"оаэ|эмират\w*", "ОАЭ"),
    (r"египт\w*|египет", "Египет"),
    (r"мальдив\w*", "Мальдивы"),
    (r"азербайджан\w*", "Азербайджан"),
    (r"грузи\w*", "Грузия"),
    (r"таиланд\w*|тайланд\w*", "Таиланд"),
    (r"вьетнам\w*", "Вьетнам"),
    (r"кипр\w*", "Кипр"),
)

# Курорт тянет за собой страну: клиент чаще называет «Анталья», а не «Турция».
_RESORTS: tuple[tuple[str, str, str], ...] = (
    (r"анталь\w*|анталия", "Анталья", "Турция"),
    (r"кемер\w*", "Кемер", "Турция"),
    (r"аланья|аланию|алании", "Аланья", "Турция"),
    (r"сиде\b", "Сиде", "Турция"),
    (r"белек\w*", "Белек", "Турция"),
    (r"мармарис\w*", "Мармарис", "Турция"),
    (r"бодрум\w*", "Бодрум", "Турция"),
    (r"дуба[ий]\w*", "Дубай", "ОАЭ"),
    (r"абу-даби|абу даби", "Абу-Даби", "ОАЭ"),
    (r"шардж\w*", "Шарджа", "ОАЭ"),
    (r"хургад\w*", "Хургада", "Египет"),
    (r"шарм\w*", "Шарм-эль-Шейх", "Египет"),
    (r"пхукет\w*", "Пхукет", "Таиланд"),
    (r"нячанг\w*", "Нячанг", "Вьетнам"),
    (r"батуми\w*", "Батуми", "Грузия"),
)

# ---------- сторожа ----------

# Рассказ о прошлой поездке. Замер: «У нас в прошлом году на двоих в 5 звезд отель вышло
# 1200 с завтраком еще» — и сумма, и состав относятся к прошлому.
_PAST = re.compile(
    r"в прошл\w+|в прошлый раз|прошлогодн\w+|ездил\w*|летал\w*|был[иа]\s+в\b|"
    r"вышл[оа]\b|обошл\w+|в позапрошл\w+",
    re.IGNORECASE,
)

# Слово о ДЕНЬГАХ рядом с числом. Замер по 500 боевым сообщениям: маркера «до N» здесь
# быть не должно — на нём «После 25 августа до 1 сентября» превращалось в бюджет 25 USD,
# а «срок действия до 6 месяцев» из пересланного визового чек-листа — в 60000 USD.
_BUDGET_MARKER = re.compile(
    r"бюджет\w*|уложит\w*|уклад\w*|\$|€|долл\w*|\busd\b|\beur\b|евро|"
    r"\bсом\b|\bсома\b|\bсомов\b|\bkgs\b|тыс\.?|тысяч\w*|рубл\w*",
    re.IGNORECASE,
)

# Ссылки и длинные цифровые хвосты. Тот же замер: из
# `https://wa.me/wamo/status/preview/996707660009/120254348253680357` разбор доставал
# «даты» 09.12.2026-23.12.2026 — числа из URL превращались в поездку.
_URL = re.compile(r"https?://\S+|\bwa\.me/\S+|\b\S+\.(?:kg|com|ru|net|org)/\S*", re.IGNORECASE)
_LONG_DIGITS = re.compile(r"\d{7,}")

_MONTHS_RE = (r"январ|феврал|март|апрел|\bмая\b|\bмай\b|июн|июл|август|сентябр|октябр|"
              r"ноябр|декабр")
# Кусок «25 августа», «с 1 по 8 октября» — это дата, а не деньги.
_DATEISH = re.compile(r"\d{1,2}\s*(?:[-–—]|по|до)?\s*\d{0,2}\s*(?:" + _MONTHS_RE + r")\w*",
                      re.IGNORECASE)

# Рассылки, прайсы и чек-листы, которые клиенты пересылают в чат. Из них разбор доставал
# «бюджет 30 USD» (виза на Хайнань) и «Таиланд» как направление тура.
_BROADCAST = re.compile(r"📢|❗|ВАЖНО!|документы для визы|список документов|"
                        r"условия акции", re.IGNORECASE)
_MAX_LEN = 400

# Слово о людях рядом с числом. Без него «2 с багажом 1 ручная» станет двумя туристами.
_PARTY_MARKER = re.compile(
    r"нас\s+будет|нас\s+\d|взросл\w*|дет[ейи]\w*|реб[её]н\w*|малыш\w*|человек\w*|"
    r"\bчел\b|вдво[её]м|втро[её]м|вчетвер\w*|двое|трое|четверо|пятеро|семь[яёе]\w*",
    re.IGNORECASE,
)

_WORD_NUMBERS: dict[str, int] = {
    "один": 1, "одного": 1, "одна": 1,
    "двое": 2, "двоих": 2, "вдвоём": 2, "вдвоем": 2, "два": 2, "две": 2, "двух": 2,
    "трое": 3, "троих": 3, "втроём": 3, "втроем": 3, "три": 3, "трёх": 3, "трех": 3,
    "четверо": 4, "четверых": 4, "вчетвером": 4, "четыре": 4, "четырёх": 4, "четырех": 4,
    "пятеро": 5, "пятерых": 5, "пять": 5, "пяти": 5,
    "шестеро": 6, "шесть": 6,
}

_MAX_CHILD_AGE = 17
_MAX_PARTY = 12


def _found(patterns, text: str):
    """Первое совпадение из словаря: (позиция, каноническое значение, …хвост)."""
    best = None
    for pattern, *values in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match and (best is None or match.start() < best[0]):
            best = (match.start(), *values)
    return best


def _departure_city(text: str) -> str:
    """Город вылета. «Не из Бишкека, а из Алматы» → Алматы, а не Бишкек."""
    contrast = re.search(r"не\s+из\s+\S+.{0,20}?\bа?\s*(?:из|с)\s+(\S+)", text, re.IGNORECASE)
    scope = contrast.group(1) if contrast else text
    if not contrast and not re.search(r"вылет\w*|выезж\w*|\bиз\b|летим|полетим", text,
                                      re.IGNORECASE):
        return ""            # город без слова о вылете — это может быть что угодно
    hit = _found(_DEPARTURE_CITIES, scope)
    return hit[1] if hit else ""


def _place(text: str) -> tuple[str, str]:
    """(страна, курорт). Курорт подставляет свою страну, если её не назвали отдельно."""
    country = _found(_COUNTRIES, text)
    resort = _found(_RESORTS, text)
    if resort:
        return (country[1] if country else resort[2]), resort[1]
    return (country[1] if country else ""), ""


def _party(text: str) -> tuple[str, str]:
    """(сколько человек, возрасты детей). Пусто, если нет слова о людях."""
    if not _PARTY_MARKER.search(text):
        return "", ""

    def number_before(word_pattern: str) -> int:
        match = re.search(r"(\d+|[а-яё]+)\s+" + word_pattern, text, re.IGNORECASE)
        if not match:
            return 0
        token = match.group(1).lower()
        return int(token) if token.isdigit() else _WORD_NUMBERS.get(token, 0)

    ages: list[int] = []
    kids_word = re.search(r"дет[ейи]\w*|реб[её]н\w*|малыш\w*", text, re.IGNORECASE)
    if kids_word:
        ages = [int(n) for n in re.findall(r"\d+", text[kids_word.end():])
                if int(n) <= _MAX_CHILD_AGE]

    adults = number_before(r"взросл")
    kids_count = number_before(r"(?:дет|реб|малыш)")

    total = 0
    explicit = re.search(r"нас\s+(?:будет\s+)?(\d+|[а-яё]+)", text, re.IGNORECASE)
    if explicit:
        token = explicit.group(1).lower()
        total = int(token) if token.isdigit() else _WORD_NUMBERS.get(token, 0)
    if not total and not adults and not kids_count and not ages:
        # «тоже двое», «вдвоём» — состав назван одним словом.
        for word, value in _WORD_NUMBERS.items():
            if re.search(rf"\b{word}\b", text, re.IGNORECASE):
                total = value
                break
    if not total:
        total = adults + max(kids_count, len(ages))

    if not total or total > _MAX_PARTY:
        return "", ""
    ages = ages[:max(kids_count, len(ages))]
    return str(total), ", ".join(str(a) for a in ages)


# Клиент, НАЗЫВАЮЩИЙ свой бюджет, и клиент, ПЕРЕСПРАШИВАЮЩИЙ цену — разные вещи.
# Замер: «В смысле 7455 $?» и «Отель 4 тысячи долларов?» — это реакция на нашу же цену,
# а «легковая машина $80, минивен $100» — прайс на трансфер. Бюджетом это не является.
_BUDGET_INTENT = re.compile(
    r"бюджет\w*|уложит\w*|уклад\w*|в пределах|рассчитыва\w*|максимум|не больше|"
    r"есть\s+\d|готов\w*\s+потрат", re.IGNORECASE,
)
_SHORT_MONEY = 32          # «1700 долларов», «До 1000$» — сумма и есть всё сообщение


def _budget(text: str) -> str:
    """Бюджет — только из текста, очищенного от ссылок, дат и длинных цифровых хвостов."""
    clean = _DATEISH.sub(" ", _LONG_DIGITS.sub(" ", _URL.sub(" ", text)))
    if not _BUDGET_MARKER.search(clean):
        return ""
    if not _BUDGET_INTENT.search(clean):
        # Короткая реплика без вопроса, где сумма — это и есть ответ («1700 долларов»).
        if len(clean.strip()) > _SHORT_MONEY or "?" in clean:
            return ""
    from app.integrations.tourvisor.client import _parse_budget
    amount, currency = _parse_budget(clean)
    if not amount:
        return ""
    return f"{int(amount)} {currency}".strip()


def _dates(text: str) -> str:
    """Даты клиента. Окно, уехавшее почти на год вперёд, в карточку не пускаем.

    Замер: «Турция на двоих мама с дочь в августе с 21 чисел» 18.08.2026 разбирается в
    01.08.2027-31.08.2027. Виноват не разбор месяца, а `_roll_to_future` в клиенте
    TourVisor: он двигает ВЕСЬ месячный интервал в следующий год, если его первое число
    уже прошло, хотя 21 августа ещё впереди. Чинить это надо в самом разборщике — там же
    строится и поисковый запрос, — но отдельной задачей и со своим гейтом.

    Здесь просто не врём менеджеру: месяц, оказавшийся дальше 10 месяцев, отбрасываем.
    Пропущенная дата дешевле неверного года в карточке.
    """
    from datetime import date, datetime
    from app.integrations.tourvisor.client import _parse_dates
    start, end = _parse_dates(_LONG_DIGITS.sub(" ", _URL.sub(" ", text)))
    if not start:
        return ""
    try:
        begins = datetime.strptime(start, "%d.%m.%Y").date()
        if (begins - date.today()).days > 310:
            return ""
    except ValueError:
        return ""
    return f"{start}-{end}" if end and end != start else start


def extract(text: str) -> dict:
    """Факты из одной реплики клиента. Ничего не нашли — пустой словарь, не исключение."""
    raw = str(text or "").strip()
    if len(raw) < 2:
        return {}
    try:
        if _PAST.search(raw):
            return {}          # рассказ о прошлой поездке фактом о будущей не считается
        if len(raw) > _MAX_LEN or _BROADCAST.search(raw):
            return {}          # пересланная рассылка или чек-лист — не запрос клиента

        country, resort = _place(raw)
        tourists, ages = _party(raw)
        result = {
            "destination": country,
            "region": resort,
            "departure_city": _departure_city(raw),
            "budget": _budget(raw),
            "dates": _dates(raw),
            "tourists": tourists,
            "children_ages": ages,
        }
        return {key: value for key, value in result.items() if value}
    except Exception:  # noqa: BLE001 — разбор никогда не роняет ход диалога
        log.warning("facts: разбор реплики не удался", exc_info=True)
        return {}


def merge(known: dict, found: dict) -> dict:
    """Слить найденное с уже известным. Пустое НЕ затирает известное (урок cb7f427)."""
    merged = dict(known or {})
    for key in FIELDS:
        value = (found or {}).get(key)
        if value not in (None, "", [], {}):
            merged[key] = value
    return merged
