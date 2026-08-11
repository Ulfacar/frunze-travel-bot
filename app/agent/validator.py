"""Валидатор исходящих реплик бота — «ремень безопасности» поверх промптов.

Проверяет сгенерированный LLM ответ ДО отправки клиенту:
- АВТО-ЧИНИТ безопасное: убирает markdown (мессенджер, не лендинг); для туров дописывает
  дисклеймер про изменчивость цен, если в ответе есть сумма, а оговорки нет.
- МЯГКО ЛОГИРУЕТ рискованное (гарантии визы, цены в билетах, длина, много вопросов) — БЕЗ
  правки текста, чтобы случайно не испортить корректный ответ (напр. «визу НЕ гарантируем»
  или эхо бюджета клиента «поняла, 500$»). Профилактика этого — в самих промптах.
  NB: цены в ВИЗОВОЙ воронке больше не «нарушение» — заказчик разрешил называть официальный
  прайс услуг (см. VISA_SERVICE_PRICES); ремень безопасности здесь — только детектор гарантий.

Чистые функции (тестируемо). Подключается в `app/agent/runner.run_turn`; сводка сработок —
через `observ.note_validation` (видна на /admin/system).
"""
from __future__ import annotations

import re

from app.core.branding import PRICE_DISCLAIMER

MAX_LEN = 600  # мягкий лимит длины реплики (символов) — только для лога, текст не режем
_URL = re.compile(r"https?://[^\s>)\]]+", re.IGNORECASE)
# Разрешённых ссылок у бота НЕТ. Раньше здесь стоял поиск Google по названию отеля — и он
# уводил оплаченного рекламой клиента в выдачу с Booking и конкурентами. Своей карточки тура
# бот собрать не умеет, поэтому любой URL в его реплике теперь вырезается: ссылку с бронью
# присылает менеджер. Пустой кортеж оставлен намеренно — механизм понадобится, когда появится
# собственная карточка (`tourcart.ru/?tvcard=…`), которой пользуются менеджеры.
_SAFE_URL_PREFIXES: tuple[str, ...] = ()

# --- markdown-разметка, неуместная в мессенджере ---
_BOLD = re.compile(r"\*{1,3}(.+?)\*{1,3}", re.DOTALL)       # **жирный** / *курсив*
_UNDERSCORE = re.compile(r"__(.+?)__", re.DOTALL)
_HEADER = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)     # # Заголовок
_BULLET = re.compile(r"^\s{0,3}[-*•]\s+", re.MULTILINE)      # «- пункт» / «* пункт»
_MULTINL = re.compile(r"\n{3,}")
_SPACED_DASH = re.compile(r"\s+[—–]\s+")

# деньги: 250$, $300, 5000 сом, 185 usd, 5 тыс$
_PRICE = re.compile(
    r"(?:\$\s?\d[\d\s.,]*|\d[\d\s.,]*\s?(?:\$|usd|долл|сом|руб|eur|€|тыс))",
    re.IGNORECASE)
# утвердительная гарантия визы (для ЛОГА, не для правки). «не гарантируем» исключаем.
_GUARANTEE = re.compile(
    r"(100\s?%|(?<!не )гаранти\w*|обязательно (?:дад|одобр|получ)|"
    r"точно (?:дад|одобр|получ)|виза будет точно)",
    re.IGNORECASE)
# дисклеймер про цену уже присутствует?
_DISCLAIMER_MARK = re.compile(
    r"варьир|зависит от дат|может меня|уточним|подтвердим", re.IGNORECASE)

SAFE_FLIGHT_REPLY = (
    "По прямым рейсам и наличию мест лучше проверить актуальность по конкретным датам — "
    "уточним и подскажем точный вариант."
)
# Отказ обязан заканчиваться ходом, а не точкой. До 11.08 бот отвечал «не занимаемся» и
# разговор кончался: живой диалог getvisa:996708011087 («В Америку рабочую визу делаете?»)
# оборвался ровно на этом ответе. Со встречи 11.08, дословно: «Мы можем сказать, что нет, но
# есть другие способы уехать, и тогда пригласить на консультацию» — и там же «уже третий,
# четвёртый человек приходит». Обещать рабочую визу по-прежнему нельзя ни в каком виде.
SAFE_WORKVISA_REPLY = (
    "Рабочие визы за границу мы не оформляем: для них нужно приглашение от работодателя, "
    "это отдельная услуга. Часто подходит другой путь: туристическая, гостевая, деловая или "
    "учебная виза (например, США: B1/B2, F1, M1). Давайте разберём вашу ситуацию на "
    "консультации и подскажем, что реально подходит именно вам."
)

_SENTENCE_SPLIT = re.compile(r"([^.!?\n]+)([.!?\n]+|$)")
_AFFIRM_FLIGHT = re.compile(
    r"(?:\b(?:есть|доступн\w*)\s+прям\w*[^.!?\n]*(?:рейс|вылет|перел[её]т|чартер))|"
    r"(?:\b(?:летают|выполняются|доступны)\s+прям\w*)|"
    r"(?:\bпрям\w*[^.!?\n]*(?:рейс|вылет|перел[её]т)[^.!?\n]*"
    r"(?:есть|доступн\w*|летают|выполняются))|"
    r"(?:\b(?:есть|доступн\w*)\s+чартер\w*)|"
    r"(?:\bчартер\w*[^.!?\n]*(?:есть|доступн\w*|летают|выполняются))|"
    r"(?:\b(?:есть|доступн\w*)\s+(?:свободн\w*\s+)?мест\w*[^.!?\n]*"
    r"(?:рейс|вылет|чартер))|"
    r"(?:\b(?:рейс|вылет|чартер)[^.!?\n]*"
    r"(?:есть|доступн\w*)\s+(?:свободн\w*\s+)?мест\w*)",
    re.IGNORECASE,
)
_NEG_FLIGHT = re.compile(
    r"\b(?:нет|не|без)\b|пересадк|уточн|провер|актуальн|скорее всего|возможно|"
    r"обычно|ближе к осени|под вопросом|к сожалению",
    re.IGNORECASE,
)
_AFFIRM_WORKVISA = re.compile(r"рабоч\w*\s+виз", re.IGNORECASE)
_NEG_WORKVISA = re.compile(
    r"\bне\b|не\s+занимаемся|не\s+делаем|не\s+оформляем|к сожалению|нельзя",
    re.IGNORECASE,
)


def _replace_sentences(
    text: str,
    *,
    affirm: re.Pattern[str],
    neg: re.Pattern[str],
    safe_text: str,
) -> tuple[str, bool]:
    """Replace unsafe affirmative sentences with one safe sentence, preserving others."""
    parts: list[str] = []
    blocked = False
    safe_inserted = False
    pos = 0

    for match in _SENTENCE_SPLIT.finditer(text):
        if match.start() > pos:
            parts.append(text[pos:match.start()])
        pos = match.end()

        body, sep = match.group(1), match.group(2)
        if not body:
            parts.append(sep)
            continue

        sent = body.strip()
        if sent and affirm.search(sent) and not neg.search(sent):
            blocked = True
            if not safe_inserted:
                parts.append(safe_text)
                safe_inserted = True
            continue

        parts.append(body + sep)

    if pos < len(text):
        parts.append(text[pos:])

    if not blocked:
        return text, False

    replaced = " ".join("".join(parts).split())
    return replaced, blocked


def strip_markdown(text: str) -> str:
    """Снять markdown-разметку → обычный текст мессенджера."""
    text = _BOLD.sub(r"\1", text)
    text = _UNDERSCORE.sub(r"\1", text)
    text = _HEADER.sub("", text)
    text = _BULLET.sub("", text)
    text = _MULTINL.sub("\n\n", text)
    text = _SPACED_DASH.sub(". ", text)
    return text.strip()


def _strip_unknown_urls(text: str) -> tuple[str, bool]:
    """Убрать любой URL, кроме безопасных google-поисков отеля."""
    stripped = False

    def _rep(match: re.Match[str]) -> str:
        nonlocal stripped
        url = match.group(0)
        if url.startswith(_SAFE_URL_PREFIXES):
            return url
        stripped = True
        return ""

    new = _URL.sub(_rep, text)
    if stripped:
        new = " ".join(new.split())
    return new, stripped


def validate_reply(text: str, funnel: str | None) -> tuple[str, list[str]]:
    """Вернуть (очищенный_текст, список_нарушений).

    Мутируем ТОЛЬКО безопасное (markdown, дисклеймер цен туров). Остальное — в список
    нарушений для логирования, текст не трогаем.
    """
    violations: list[str] = []

    clean = strip_markdown(text)
    if clean != text.strip():
        violations.append("markdown")

    clean, url_stripped = _strip_unknown_urls(clean)
    if url_stripped:
        violations.append("invented_url_stripped")

    has_price = bool(_PRICE.search(clean))

    # Туры: цены показываем, но обязателен дисклеймер изменчивости — допишем, если забыт.
    if funnel == "tours" and has_price and not _DISCLAIMER_MARK.search(clean):
        clean = f"{clean}\n\n{PRICE_DISCLAIMER}"
        violations.append("tours_price_disclaimer_added")

    if funnel == "tours":
        clean, blocked = _replace_sentences(
            clean,
            affirm=_AFFIRM_FLIGHT,
            neg=_NEG_FLIGHT,
            safe_text=SAFE_FLIGHT_REPLY,
        )
        if blocked:
            violations.append("direct_flight_claim_blocked")
    elif funnel == "visa":
        clean, blocked = _replace_sentences(
            clean,
            affirm=_AFFIRM_WORKVISA,
            neg=_NEG_WORKVISA,
            safe_text=SAFE_WORKVISA_REPLY,
        )
        if blocked:
            violations.append("work_visa_offer_blocked")

    # --- мягкие сигналы (только лог, без правки текста) ---
    # Визы теперь называют официальный прайс услуг → цена тут НЕ нарушение. Билеты — цену
    # называет менеджер, поэтому сумму в реплике бота помечаем.
    if funnel == "tickets" and has_price:
        violations.append("price_in_no_price_funnel")
    if funnel == "visa" and _GUARANTEE.search(clean):
        violations.append("possible_visa_guarantee")
    if len(clean) > MAX_LEN:
        violations.append("too_long")
    if clean.count("?") > 1:
        violations.append("multiple_questions")

    return clean, violations
