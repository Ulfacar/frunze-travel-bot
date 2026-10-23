"""Ремни безопасности въездной ветки: запреты ТЗ, стоящие на выходе, а не в промпте.

Промпт — это просьба, а не гарантия. Модель под давлением клиента («ну скажите хоть
примерно сколько») соскальзывает в точные цифры, обещания и ссылки на закон, которого не
читала. Поэтому запреты приложения Б.7 и Б.1 проверяются кодом после модели.

Отличие от выездной ветки намеренное: там цены и гарантии только ЛОГИРУЮТСЯ, здесь
подменяются. Выездной бот продаёт услугу по официальному прайсу; въездной излагает
закон чужой страны человеку, который на этом законе может потерять консульский сбор и
получить запрет на въезд.
"""
from __future__ import annotations

import re

# --- Правила: что считается утверждением о законе ------------------------------

# Срок или лимит: число рядом со словом про дни. Отдельно от любых других чисел —
# «2 фотографии» утверждением о законе не является.
_RULE_PERIOD = re.compile(
    r"\b\d{1,3}\s*(?:календарн\w*\s*|рабоч\w*\s*)?"
    r"(?:дн\w*|сут\w*|day|days|month|месяц\w*)",
    re.IGNORECASE)

# Остаток дней по конкретному человеку. Отдельно от лимита, и это принципиально:
# лимит — норма из единицы знаний («90 дней в окне 180»), а остаток считает
# государственная система учёта ЕСУВМ, доступа к ней нет, и политика подсчёта дня
# въезда и выезда в данных не подтверждена. ТЗ 2.9 запрещает «обещать остаток по
# расчёту в уме». Оба утверждения выглядят как «число рядом со словом день», поэтому
# разрешение произносить лимит само по себе открывало дорогу остатку — нужен свой ремень.
#
# Предложение «5 дней в текущем окне» ловится отдельной альтернативой, потому что
# `validate_reply` до профиля чистит markdown и превращает тире в точку: реплика
# «Остаток — 5 дней в текущем окне» распадается на два предложения, и остаток иначе
# выживал бы как разрешённый лимит. Норма из ТЗ («30 дней в каждом 60-дневном
# периоде») слов «текущем окне» не содержит и под эту альтернативу не попадает.
_RULE_REMAINING = re.compile(
    r"(остал\w*\s+(?:ещё\s+)?\d{1,3}\s*(?:календарн\w*\s*|рабоч\w*\s*)?(?:дн\w*|сут\w*)"
    r"|остат\w*[^.!?]{0,24}?\d{1,3}\s*(?:дн\w*|сут\w*)"
    # Слово «ещё» обязательно: без него «можете находиться 90 дней» — это изложение
    # нормы, а не остаток, и такую фразу бот произносить вправе.
    r"|(?:можете|сможете|есть)\s+(?:(?:пробыть|побыть|остава\w*|находи\w*)\s+)?"
    r"ещё\s+(?:(?:пробыть|побыть|остава\w*|находи\w*)\s+)?\d{1,3}\s*(?:дн\w*|сут\w*)"
    r"|в\s+запасе\s+\d{1,3}\s*(?:дн\w*|сут\w*)"
    # Форма слова здесь перечислена, а не `остал\w*`: иначе ремень срабатывал на
    # «остальное» и подменял нормальную реплику («Документы готовим 3 дня, остальное
    # позже») текстом про остаток дней.
    r"|\d{1,3}\s*(?:дн\w*|сут\w*)[^.!?]{0,16}?"
    r"(?:остал(?:ось|ся|ись|ась|о)|в\s+запасе)"
    r"|\d{1,3}\s*(?:дн\w*|сут\w*)[^.!?]{0,12}?(?:текущ\w*|этом|нынешн\w*)\s+окн\w*"
    # Для английского тот же принцип: «left» или «remaining» обязательны, иначе
    # «you have 30 days without a visa» блокировалось бы как остаток.
    r"|\d{1,3}\s+days?\s+(?:left|remaining)"
    r"|(?:you\s+have|there\s+(?:are|is))\s+\d{1,3}\s+days?\s+(?:left|remaining))",
    re.IGNORECASE)

# Утверждение о режиме въезда.
_RULE_REGIME = re.compile(
    r"(безвиз\w*|без\s+визы|виза\s+(?:не\s+)?нужна|нужна\s+виза|"
    r"visa[-\s]free|without\s+a?\s*visa|need\s+a\s+visa|visa\s+(?:is\s+)?required|"
    r"общ\w*\s+порядк\w*|упрощ\w*\s+порядк\w*)",
    re.IGNORECASE)

# Утверждение о регистрации или о Едином разрешении.
_RULE_REGISTRATION = re.compile(
    r"(регистрац\w*|регистрир\w*|зарегистрир\w*|register\w*|registration)",
    re.IGNORECASE)
_RULE_PERMIT = re.compile(r"(единое\s+разрешени\w*|unified\s+permit)", re.IGNORECASE)

# Какое поле разрешения нужно для какого утверждения.
_CLAIM_FIELDS: tuple[tuple[re.Pattern[str], str], ...] = (
    (_RULE_REGISTRATION, "registration"),
    (_RULE_PERMIT, "unified_permit"),
    (_RULE_REGIME, "regime"),
    (_RULE_PERIOD, "stay_limit"),
)

# --- Запросы документов до согласия на обработку данных (Б.1) -------------------

_ASK_DOCS = re.compile(
    r"(скан\w*\s+паспорт|паспорт\w*\s+скан|фото\s+паспорт|копи\w*\s+паспорт|"
    r"пришлите\s+паспорт|отправьте\s+паспорт|загрузите\s+(?:копи|скан|паспорт)|"
    r"passport\s+scan|scan\s+of\s+your\s+passport|send\s+(?:your\s+)?passport|"
    r"upload\s+(?:your\s+)?passport)",
    re.IGNORECASE)

# --- Запрещённые формулировки приложения Б.7 ------------------------------------
# Каждая пара — ровно строка таблицы «нельзя / можно». Отрицания исключены, иначе
# правильный ответ «работать по туристической нельзя» блокировался бы сам.

NEVER = re.compile(r"(?!x)x")   # никогда не совпадает: отрицания не нужны

FORBIDDEN: tuple[tuple[str, re.Pattern[str], re.Pattern[str], str], ...] = (
    ("work_on_tourist",
     re.compile(r"(?<!не )(?:можно|можете)\s+(?:немного\s+)?поработать"
                r"[^.!?]*турист", re.IGNORECASE),
     NEVER,
     "Работать по туристической визе нельзя — для работы нужно Единое разрешение."),
    # Шаблон ловит не только слово «продлить». В живом прогоне 22.10 модель сказала
    # американцу «30 дней без визы, а с регистрацией — до 60 дней всего», и прежний
    # шаблон этого не видел: слов «продлить» и «увеличить» в фразе нет. По ТЗ 30/60
    # означает «30 дней в каждом 60-дневном периоде», регистрация к сроку не добавляет.
    ("registration_extends",
     re.compile(r"(?:регистрац\w*|зарегистрир\w*)[^.!?]*"
                r"(?:продл|увелич|остат\w*ся|оста(?:нет|ть)\w*|пробы\w*|нахо\w*)"
                r"[^.!?]*(?:дольше|больше|до\s+\d|\d{1,3}\s*дн)"
                r"|(?:продл|увелич)\w*[^.!?]*(?:регистрац\w*|зарегистрир\w*)"
                r"|регистрац\w*[^.!?]*(?:продл|увелич)\w*", re.IGNORECASE),
     re.compile(r"не\s+(?:продл|увелич|да[её]т|добавля)", re.IGNORECASE),
     "Регистрация не продлевает безвизовый срок."),
    ("fine_at_airport",
     re.compile(r"штраф\w*[^.!?]*(?:аэропорт|кпп|границ)", re.IGNORECASE),
     re.compile(r"не\s+(?:оплат|заплат|принима)|нельзя", re.IGNORECASE),
     "Штраф оплачивается только через органы внутренних дел до выезда."),
    ("tourist_visa_extended",
     re.compile(r"турист\w*[^.!?]*(?:продлим|продлить|продлева)", re.IGNORECASE),
     re.compile(r"не\s+продл|нельзя\s+продл", re.IGNORECASE),
     "Туристическая виза не продлевается."),
    ("speed_by_acquaintance",
     re.compile(r"(?:ускорим|ускорить|сделаем)\s+(?:по\s+знакомству|по-знакомству|"
                r"без\s+очеред)", re.IGNORECASE),
     NEVER,
     "Официальное ускорение есть: рассмотрение до двух рабочих дней, сбор выше."),
    ("stay_while_pending",
     re.compile(r"(?:можете|можно)\s+остава\w*[^.!?]*(?:рассматрива|рассмотрени)",
                re.IGNORECASE),
     re.compile(r"не\s+(?:можете|можно)|нельзя", re.IGNORECASE),
     "Подаём заранее, чтобы решение пришло до окончания вашего срока пребывания."),
)

# Безопасные подмены для первых трёх ремней.
SAFE_PRICE_REPLY = ("Точную сумму назовёт специалист — она зависит от типа визы и срока, "
                    "и мы подтверждаем её перед оплатой.")
SAFE_GUARANTEE_REPLY = ("Решение принимает МИД Кыргызстана. Мы отвечаем за правильную "
                        "подготовку документов и сроки подачи.")
SAFE_UNCONFIRMED_REPLY = ("Это правило уточнит специалист: условия зависят от вашего "
                          "гражданства и цели поездки.")
SAFE_CONSENT_REPLY = ("Прежде чем просить документы, нам нужно ваше согласие на обработку "
                      "персональных данных — специалист его оформит.")
SAFE_REMAINING_REPLY = ("Точный остаток дней по вашему паспорту считает государственная "
                        "система учёта — его подтвердит специалист по отметкам о въезде "
                        "и выезде.")

# Те же подмены по-английски. Половина клиентов въездной ветки пишет не по-русски, и
# русская вставка в английский ответ — это сломанный бот. Поймано живым прогоном
# 22.10: «…are you traveling alone Это правило уточнит специалист».
SAFE_PRICE_REPLY_EN = ("A specialist will confirm the exact amount — it depends on the "
                       "visa type and duration, and we confirm it before any payment.")
SAFE_GUARANTEE_REPLY_EN = ("The decision is made by the Ministry of Foreign Affairs of "
                           "the Kyrgyz Republic. We are responsible for preparing your "
                           "documents correctly and on time.")
SAFE_UNCONFIRMED_REPLY_EN = ("A specialist will confirm this rule: the conditions depend "
                             "on your citizenship and the purpose of your trip.")
SAFE_CONSENT_REPLY_EN = ("Before we ask for documents we need your consent to process "
                         "personal data — a specialist will arrange it.")
SAFE_REMAINING_REPLY_EN = ("The exact number of days you have left is calculated by the "
                           "state migration system — a specialist will confirm it from "
                           "the entry and exit stamps in your passport.")


# --- Английские ремни въездного профиля ----------------------------------------
# Отдельно от общих `_PRICE` и `_GUARANTEE` валидатора: те работают и для выездной
# воронки, которая живёт по официальному прайсу, и менять их поведение нельзя.
# Здесь — только въездной профиль, где цен нет вообще, а клиент чаще пишет латиницей.

PRICE_EN = re.compile(
    r"\d[\d\s.,]*\s?(?:dollars?|euros?|soms?|somoni)|(?:costs?|fee|price)\s+(?:is\s+)?"
    r"\d[\d\s.,]*", re.IGNORECASE)

GUARANTEE_EN = re.compile(
    r"(100\s?%|guarantee\w*|we\s+promise|definitely\s+(?:get|be\s+approved|approve)|"
    r"sure\s+to\s+(?:get|be\s+approved)|certainly\s+(?:get|be\s+approved))",
    re.IGNORECASE)
GUARANTEE_EN_NEG = re.compile(
    r"(cannot|can't|cant|do\s+not|don't|no|never)\s+(?:\w+\s+){0,2}guarantee|"
    r"not\s+guaranteed", re.IGNORECASE)

# Шесть запретов Б.7 по-английски. Форма та же, что у русских: утвердительный шаблон
# плюс шаблон отрицания, иначе верный ответ («you may NOT work on a tourist visa»)
# блокировал бы сам себя.
FORBIDDEN_EN_RULES: tuple[tuple[str, re.Pattern[str], re.Pattern[str]], ...] = (
    ("work_on_tourist",
     re.compile(r"(?:can|could|may|able\s+to)\s+(?:\w+\s+){0,3}work[^.!?]*tourist|"
                r"work\s+(?:a\s+little\s+)?on\s+a?\s*tourist", re.IGNORECASE),
     re.compile(r"(?:can|may)\s?(?:not|n't)|cannot|without\s+a\s+permit|"
                r"are\s+not\s+allowed", re.IGNORECASE)),
    ("registration_extends",
     re.compile(r"(?:registration|register\w*)[^.!?]*"
                r"(?:extend|prolong|increase|stay|remain)[^.!?]*"
                r"(?:up\s+to|total|longer|more|\d{1,3}\s*days?)"
                r"|(?:stay|remain)[^.!?]*(?:up\s+to|total|longer)[^.!?]*"
                r"(?:registration|register\w*)"
                r"|(?:registration|register\w*)[^.!?]*(?:extend|prolong|increase)",
                re.IGNORECASE),
     re.compile(r"does\s+not\s+extend|doesn't\s+extend|never\s+extend|"
                r"cannot\s+extend|does\s+not\s+add|no\s+extra\s+days", re.IGNORECASE)),
    ("fine_at_airport",
     re.compile(r"fine[^.!?]*(?:at\s+the\s+)?(?:airport|border|checkpoint)",
                re.IGNORECASE),
     re.compile(r"(?:not|cannot|can't|never)\s+(?:be\s+)?(?:paid|pay)|only\s+through",
                re.IGNORECASE)),
    ("tourist_visa_extended",
     re.compile(r"tourist\s+visa[^.!?]*(?:extend|prolong)|extend[^.!?]*tourist\s+visa",
                re.IGNORECASE),
     re.compile(r"cannot\s+be\s+extended|can't\s+be\s+extended|is\s+not\s+extended|"
                r"not\s+extendable", re.IGNORECASE)),
    ("speed_by_acquaintance",
     re.compile(r"speed\s+(?:it\s+)?up\s+through[^.!?]*(?:contact|connection|friend)|"
                r"through\s+(?:our|my)\s+(?:contacts|connections)", re.IGNORECASE),
     NEVER),
    ("stay_while_pending",
     re.compile(r"(?:can|may)\s+stay[^.!?]*(?:pending|being\s+reviewed|under\s+review|"
                r"while\s+(?:we|they)\s+review)", re.IGNORECASE),
     re.compile(r"(?:can|may)\s?(?:not|n't)|cannot", re.IGNORECASE)),
)

# Те же шесть исправлений Б.7 по-английски, по именам ремней.
FORBIDDEN_EN: dict[str, str] = {
    "work_on_tourist": ("You may not work on a tourist visa — employment requires a "
                        "Unified Work Permit."),
    "registration_extends": ("Registration does not extend your visa-free period."),
    "fine_at_airport": ("A fine is paid only through the police before you leave, not "
                        "at the airport."),
    "tourist_visa_extended": "A tourist visa cannot be extended.",
    "speed_by_acquaintance": ("There is an official expedited option: a decision within "
                              "two working days, at a higher fee."),
    "stay_while_pending": ("We apply in advance so the decision arrives before your "
                           "permitted stay ends."),
}


def forbidden_safe(name: str, text: str, fallback: str) -> str:
    """Безопасная замена запрещённой формулировки — на языке реплики."""
    if _in_english(text):
        return FORBIDDEN_EN.get(name) or fallback
    return fallback


def _in_english(text: str) -> bool:
    """Отвечать надо на языке реплики. Латиница без кириллицы — английский."""
    from app.core.entry_intent import looks_english
    return looks_english(text or "")


def safe_price_reply(text: str) -> str:
    return SAFE_PRICE_REPLY_EN if _in_english(text) else SAFE_PRICE_REPLY


def safe_guarantee_reply(text: str) -> str:
    return SAFE_GUARANTEE_REPLY_EN if _in_english(text) else SAFE_GUARANTEE_REPLY


def safe_unconfirmed_reply(text: str) -> str:
    return SAFE_UNCONFIRMED_REPLY_EN if _in_english(text) else SAFE_UNCONFIRMED_REPLY


def safe_consent_reply(text: str) -> str:
    return SAFE_CONSENT_REPLY_EN if _in_english(text) else SAFE_CONSENT_REPLY


def safe_remaining_reply(text: str) -> str:
    return SAFE_REMAINING_REPLY_EN if _in_english(text) else SAFE_REMAINING_REPLY


def claimed_fields(text: str) -> frozenset[str]:
    """Какие утверждения о законе содержит реплика."""
    out: set[str] = set()
    for pattern, field in _CLAIM_FIELDS:
        if pattern.search(text or ""):
            out.add(field)
    return frozenset(out)


_PERIOD_LITERAL = re.compile(
    r"(\d{1,3})\s*(календарн\w*\s+дн\w*|рабоч\w*\s+дн\w*|working\s+day\w*|"
    r"calendar\s+day\w*|дн\w*|сут\w*|месяц\w*|month\w*|day\w*)",
    re.IGNORECASE)


def _unit_class(unit: str) -> str:
    low = (unit or "").lower()
    if low.startswith(("рабоч", "working")):
        return "working_day"
    if low.startswith(("календарн", "calendar")):
        return "calendar_day"
    if low.startswith(("месяц", "month")):
        return "month"
    return "day"


def period_literals(text: str) -> frozenset[tuple[int, str]]:
    """Числа со сроками, буквально встречающиеся в тексте: (число, класс единицы).

    Нужно, чтобы разрешать боту произносить СРОК ИЗ ИСТОЧНИКА, не разрешая при этом
    говорить о сроках вообще. Класс единицы различается нарочно: «5 рабочих дней» в
    базе не даёт права сказать «5 календарных дней» — для дедлайна подачи это разные
    сроки.
    """
    found: set[tuple[int, str]] = set()
    for match in _PERIOD_LITERAL.finditer(text or ""):
        try:
            number = int(match.group(1))
        except ValueError:          # pragma: no cover — защита от странного ввода
            continue
        found.add((number, _unit_class(match.group(2))))
    return frozenset(found)


def claims_remaining_days(text: str) -> bool:
    """Называет ли реплика остаток дней по конкретному человеку (ТЗ 2.9 запрещает)."""
    return bool(_RULE_REMAINING.search(text or ""))


def asks_for_documents(text: str) -> bool:
    return bool(_ASK_DOCS.search(text or ""))


# Отрицание гарантии по-русски: между «не» и «гаранти» бывают слова («мы не можем
# гарантировать»), а бывает и другая форма отказа («гарантий нет», «невозможно»).
# Без этого ремень затирал ПРАВИЛЬНЫЙ ответ бота. Найдено прогоном историй 22.10.
GUARANTEE_RU_NEG = re.compile(
    r"не\s+(?:\w+\s+){0,2}гаранти"
    r"|гаранти\w*\s+(?:нет|не\s+да|невозможн)"
    r"|гарантир\w*[^.!?]{0,24}(?:нельзя|невозможно|не\s+можем|не\s+даём|не\s+даем)"
    r"|без\s+гаранти",
    re.IGNORECASE)
