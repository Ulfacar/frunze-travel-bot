"""О чём разговор на визовом номере: выезд гражданина КР или въезд иностранца в КР.

Зачем это нужно. Решение Алана 21.10: въездные визы живут на том же номере GetVisa, что
и выездные, отдельного канала не будет. Но это два разных бизнеса с разными базами
знаний: выездной бот знает про собеседование в посольстве США и Шенген, въездной — про
безвизовые лимиты, регистрацию иностранца и Единое разрешение. Перепутать их — значит
ответить человеку чужими фактами.

Главное правило: **при сомнении остаётся прежнее поведение.** Выездная воронка работает
и приносит деньги; новая ветка не имеет права забирать диалог «на всякий случай». Поэтому
`unknown` — это не ошибка, а штатный и самый частый исход, при котором всё идёт как
сегодня.

Порядок проверок выстрадан гейтом и важен:

1. липкость — режим не переобувается посреди разговора;
2. **сильный** маркер въезда («виза в Кыргызстан», Единое разрешение, резидент-карта).
   Он сильнее вето, потому что австриец, который пишет «я из Австрии, нужна виза в
   Кыргызстан», называет Австрию как своё гражданство, а не как пункт назначения;
3. вето выездного — страна или слово из выездной работы без сильного маркера въезда;
4. **слабый** маркер въезда (Бишкек, e-visa) — только если вето не сработало;
5. английская реплика про визу без выездной страны;
6. всё остальное — прежнее поведение.

Сравнение идёт по ОСНОВАМ слов, а не по целым словам: клиент пишет «в Польшу», «в
Канаду», «регистрацию иностранца», и совпадение по полной форме не срабатывает.
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

Intent = Literal["kg_entry", "outbound", "unknown"]

# Сильные маркеры въезда: Кыргызстан назван пунктом назначения либо речь о сугубо
# въездных продуктах. Перебивают вето выездного.
_ENTRY_STRONG = (
    "в кыргызстан", "в киргизи", "в кыргызи", "виза в кыргыз", "кыргызстан виза",
    "въезд в кыргыз", "единое разрешение", "резидент-карт", "резидент карт",
    "регистрац",                      # «регистрацию иностранца», «регистрация иностранцев»
    "to kyrgyzstan", "kyrgyzstan visa", "kyrgyz visa", "enter kyrgyzstan",
    "entry to kyrgyzstan", "unified permit", "residence card",
    "register in kyrgyzstan", "stay in kyrgyzstan",
)

# Слабые маркеры: указывают на въезд, но уступают вето.
_ENTRY_WEAK = ("бишкек", "bishkek", "e-visa", "evisa", "мигрант", "osh airport")

# Выездные маркеры: слова, встречающиеся только в выездной работе GetVisa.
_OUTBOUND_WORDS = (
    "шенген", "schengen", "консульств", "посольств", "собеседовани", "интервью",
    "ds-160", "ds160", "визовый центр", "vfs", "слот", "аппойнтмент",
    "appointment", "грин карт", "green card", "отказали в визе",
)

# Короткие выездные страны, которые не вытащить разбором строки брендинга.
_OUTBOUND_SHORT = ("сша", "оаэ", "корея", "корею", "китай", "япони", "индонез")

# Визовые слова на английском: сами тему не решают, только в паре с отсутствием вето.
_VISA_WORDS_EN = ("visa", "visas", "entry", "border", "passport", "stay", "permit")

_CYRILLIC = re.compile(r"[а-яёА-ЯЁ]")
_LATIN = re.compile(r"[a-zA-Z]")
_STEM = 5          # сколько первых букв страны считаем основой: «польш», «канад»

# Заявленное СВОЁ гражданство. Прогон клиентских историй 22.10 показал, что живой
# иностранец почти никогда не пишет «виза в Кыргызстан»: он пишет «Я из Нигерии, хочу
# приехать туристом на 50 дней». Без этой пары шесть историй из двадцати уходили в
# выездную воронку, и бот спрашивал «в какую страну вам нужна виза?».
_ORIGIN_CLAIM = re.compile(
    r"(?:я\s+из|родом\s+из|я\s+гражданин|я\s+гражданка|гражданин|гражданка|"
    r"гражданство)\s+([а-яё\-]{4,22})"
    r"|(?:i\s*am|i'?m)\s+(?:a\s+)?(?:citizen\s+of\s+|from\s+)([a-z\-]{3,22})"
    r"|citizen\s+of\s+([a-z\-]{3,22})",
    re.IGNORECASE)

# Приезд СЮДА, а не поездка отсюда. Разница в приставке: «приехать» против «поехать».
_ARRIVAL = (
    "приехать", "приеду", "приезжа", "приеха", "въехать", "въезжа", "въеду", "въезд",
    "прилет", "прибыва", "прибыть", "come to", "come for", "coming", "arrive",
    "arriving", "arrival", "visit",
)

# Отъезд ОТСЮДА. Иностранец, живущий в Бишкеке и собравшийся за границу, — выездной
# клиент, и забирать его во въездную ветку нельзя даже при названном гражданстве.
_DEPARTURE = (
    "поехать", "поеду", "выехать", "выезжа", "уехать", "уеду", "за границу",
    "за рубеж", "улета", "go abroad", "travel to", "fly to",
)

# Слова про сам визовый вопрос. Сами тему не решают: нужны вместе с названным чужим
# гражданством и при молчащем вето выездного.
_VISA_WORDS_RU = ("виз", "оформит", "оформлен", "документы на")


def _outbound_stems() -> tuple[str, ...]:
    """Основы названий выездных стран из брендинга, чтобы список не разъехался с промптом."""
    from app.core.branding import GETVISA_VISA_SCOPE
    words = re.findall(r"[а-яёa-z]{5,}", GETVISA_VISA_SCOPE.lower())
    skip = {"шенген", "зона"}
    return tuple(sorted({w[:_STEM] for w in words if w not in skip}))


def looks_english(text: str) -> bool:
    """Реплика на латинице и без кириллицы — клиент почти наверняка иностранец."""
    t = text or ""
    return bool(_LATIN.search(t)) and not _CYRILLIC.search(t)


@lru_cache(maxsize=1)
def _origin_keys() -> dict[str, str]:
    """Основа русского названия страны → ISO3, с запасом на падеж.

    Клиент пишет «я из Нигерии», «я гражданин Пакистана» — родительный падеж, и
    сравнение по полной форме не срабатывает. Отрезаем последнюю букву у названий от
    пяти букв: «индия» → «инди» покрывает «индии», «пакистан» → «пакиста» покрывает
    «пакистана». У коротких («иран», «ирак») не отрезаем, иначе они сольются в одну
    основу и страна определится неверно.
    """
    try:
        from app.knowledge.entry_bundle import loaded
        bundle = loaded()
    except Exception:  # noqa: BLE001 — без бандла правило просто не срабатывает
        return {}
    if bundle is None:
        return {}
    keys: dict[str, str] = {}
    for alias, iso in (bundle.countries or {}).items():
        name = str(alias).strip().lower()
        if len(name) < 4 or not _CYRILLIC.search(name):
            continue
        key = name[:-1] if len(name) >= 5 else name
        keys.setdefault(key, str(iso))
    return keys


def _origin_iso3(word: str) -> str | None:
    """ISO3 по слову, которым клиент назвал своё гражданство."""
    name = (word or "").strip().lower()
    if not name:
        return None
    from app.knowledge.country_aliases_en import iso3_for_en
    found = iso3_for_en(name)
    if found:
        return found
    for key, iso in _origin_keys().items():
        if name.startswith(key):
            return iso
    return None


def _claimed_origins(low: str) -> list[str]:
    """Все гражданства, названные клиентом про СЕБЯ."""
    out: list[str] = []
    for match in _ORIGIN_CLAIM.finditer(low):
        word = next((g for g in match.groups() if g), "")
        iso = _origin_iso3(word)
        if iso:
            out.append(iso)
    return out


def _without_origin(low: str) -> str:
    """Текст без упоминаний своего гражданства.

    Страна во фразе «я из Германии» — это гражданство клиента, а не пункт назначения,
    и вето выездного по ней срабатывать не должно. Тот же принцип уже записан выше в
    докстроке про австрийца; здесь он доведён до вето.
    """
    return _ORIGIN_CLAIM.sub(" ", low)


# Что ломает липкость режима. Только то, чего во въездном разговоре быть не может:
# выездная страна как пункт назначения и сугубо выездные артефакты. Слова
# «посольство», «консульство», «собеседование» сюда НЕ входят — их задаёт и
# иностранец про МИД Кыргызстана, и прибитый тест это требует.
_OUTBOUND_HARD = ("шенген", "schengen", "ds-160", "ds160", "грин карт", "green card",
                  "vfs", "визовый центр")


def _outbound_evidence(low: str) -> bool:
    """Твёрдая улика выездного разговора — достаточная, чтобы перебить липкость."""
    veto = _without_origin(low)
    return (any(w in veto for w in _OUTBOUND_HARD)
            or any(w in veto for w in _OUTBOUND_SHORT)
            or any(stem in veto for stem in _outbound_stems()))


def detect(text: str, *, sticky: str | None = None) -> Intent:
    """Тема реплики. `sticky` — уже определённый режим диалога, он сильнее текста."""
    low = (text or "").lower()

    if sticky in ("kg_entry", "outbound"):
        # Липкость не должна запирать диалог в неверной ветке: режим мог быть угадан
        # по косвенным признакам. Прямая улика выездного её перебивает — но только
        # прямая, иначе обычное продолжение въездного разговора будет перескакивать.
        if sticky == "kg_entry" and low.strip() and _outbound_evidence(low):
            return "outbound"
        return sticky                                  # type: ignore[return-value]

    if not low.strip():
        return "unknown"

    if any(w in low for w in _ENTRY_STRONG):
        return "kg_entry"

    # Вето считаем по тексту БЕЗ своего гражданства, иначе «я из Германии, хочу
    # приехать туристом» уезжает в выездную воронку из-за слова «Германии».
    leaving = any(word in low for word in _DEPARTURE)

    veto = _without_origin(low)
    if any(w in veto for w in _OUTBOUND_WORDS) or any(w in veto for w in _OUTBOUND_SHORT):
        return "outbound"
    if any(stem in veto for stem in _outbound_stems()):
        return "outbound"

    # Назвал чужое гражданство — дальше смотрим, куда он собрался. Гражданин КР так
    # про себя не пишет, а его собственное гражданство чужим не считается.
    foreign = any(iso != "KGZ" for iso in _claimed_origins(low))
    if foreign and not leaving:
        if any(word in low for word in _ARRIVAL):
            return "kg_entry"
        # Просит визу и не назвал ни одной страны (вето выше молчало) — речь о
        # Кыргызстане. Иначе иностранец, написавший «оформите мне визу», уходил в
        # выездную воронку, и бот спрашивал, какую страну он рассматривает.
        if any(word in low for word in _VISA_WORDS_RU) or (
                looks_english(low) and any(re.search(rf"\b{w}\b", low)
                                           for w in _VISA_WORDS_EN)):
            return "kg_entry"

    # Слабый маркер не работает, если клиент прямо говорит об отъезде отсюда:
    # «живу в Бишкеке, хочу выехать на учёбу» — это выездной клиент.
    if any(w in low for w in _ENTRY_WEAK) and not leaving:
        return "kg_entry"

    # Клиентура выездного GetVisa — граждане КР, они пишут по-русски. Англоязычный
    # визовый вопрос без единой выездной страны почти наверняка про въезд. «Почти» —
    # поэтому только после вето выше.
    if looks_english(low) and any(re.search(rf"\b{w}\b", low) for w in _VISA_WORDS_EN):
        return "kg_entry"

    return "unknown"
