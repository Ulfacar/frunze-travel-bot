"""Здоровье подбора туров: считаем РЕЗУЛЬТАТ поиска, а не только расход API.

Зачем это есть. 31.07.2026 разбор показал, что подбор был сломан больше месяца и никто не
заметил: бот честно отвечал «ничего не нашлось», клиенты уходили, а в мониторинге всё было
зелено. Считалась квота TourVisor (`tourvisor/quota.py`), стоимость LLM, сработки валидатора —
всё, кроме единственного, что важно бизнесу: **находит ли бот туры**.

За неделю до фикса: 5 поисков, из них 5 с нулевым результатом — 100% брака. Такой показатель
обязан кричать сам, а не ждать, пока клиент пожалуется владельцу.

Что считаем за сутки (день катится в 00:00 по Бишкеку, как у остальных суточных счётчиков):

* `total` — сколько раз бот вообще пытался подобрать тур;
* `ok` / `nothing_found` / `no_destination` — чем закончился выполненный поиск;
* `no_duration` — поиск остановлен до API, чтобы цена на случайный срок не отпугнула клиента;
* `fallback` — сколько раз спасал вылет из Алматы (растёт → пора говорить это клиентам сразу);
* `no_dates` — поиск ушёл без дат (главный симптом сломанного разбора дат: именно так
  выглядел дефект, из-за которого клиенту показывали туры на чужие числа).

Алерт уходит владельцам в Telegram один раз в сутки, когда поисков накопилось достаточно для
вывода и доля пустых перевалила порог. Ничего не блокирует — только предупреждает.

Механика (Redis + in-memory фолбэк, суточный ключ, TTL) намеренно повторяет `quota.py`:
одна знакомая форма на все суточные счётчики.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.config import settings
from app.core.budget import _bishkek_day  # единый день по Бишкеку для всех суточных счётчиков

logger = logging.getLogger("tours_health")

_REDIS_TTL_SECONDS = 48 * 3600
_MEM: dict[str, int] = {}
_redis_client: Any | None = None
_alerted_day: str | None = None

# Исходы подбора. Совпадают с `TourSearch.reason`, плюс служебные пометки.
REASONS = ("ok", "nothing_found", "no_destination", "no_duration")
_FIELDS = (*REASONS, "total", "fallback", "no_dates")

# Меньше этого числа поисков за сутки — выборка не показательна, молчим.
MIN_SAMPLE = 5
# Доля пустых подборов, выше которой это уже не невезение, а поломка.
ZERO_RATIO_ALERT = 0.6


def _key(field: str, day: str | None = None) -> str:
    return f"tours:search:{day or _bishkek_day()}:{field}"


def _redis() -> Any:
    global _redis_client
    if _redis_client is None:
        from redis import asyncio as aioredis
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def _incr(field: str) -> None:
    if settings.state_backend == "redis":
        redis = _redis()
        key = _key(field)
        await redis.incrby(key, 1)
        await redis.expire(key, _REDIS_TTL_SECONDS)
    else:
        _MEM[_key(field)] = _MEM.get(_key(field), 0) + 1


async def note(reason: str, *, fallback: bool = False, has_dates: bool = True) -> None:
    """Учесть один подбор. Никогда не поднимает исключение: счётчик не важнее ответа клиенту."""
    try:
        if reason == "no_duration":
            await _incr("no_duration")
            return
        await _incr("total")
        await _incr(reason if reason in REASONS else "nothing_found")
        if fallback:
            await _incr("fallback")
        if not has_dates:
            await _incr("no_dates")
    except Exception:  # noqa: BLE001 — сбой счётчика не должен ломать подбор туров
        logger.warning("tours_health: note failed", exc_info=True)


async def _read(field: str) -> int:
    if settings.state_backend == "redis":
        return int(await _redis().get(_key(field)) or 0)
    return _MEM.get(_key(field), 0)


async def status(now: datetime | None = None) -> dict[str, object]:
    """Снимок за сутки для админки, брифа и алерта."""
    try:
        values = {field: await _read(field) for field in _FIELDS}
    except Exception:  # noqa: BLE001
        logger.warning("tours_health: status failed", exc_info=True)
        values = dict.fromkeys(_FIELDS, 0)

    total = values["total"]
    empty = values["nothing_found"] + values["no_destination"]
    ratio = round(empty / total, 3) if total else 0.0
    if total < MIN_SAMPLE:
        zone = "quiet"          # данных мало, выводы делать рано
    elif ratio >= ZERO_RATIO_ALERT:
        zone = "broken"
    else:
        zone = "ok"
    return {**values, "empty": empty, "zero_ratio": ratio, "zone": zone,
            "day": _bishkek_day(now)}


async def check_and_alert(*, now: datetime | None = None) -> bool:
    """Один алерт владельцу за сутки, когда подбор массово возвращает пусто."""
    global _alerted_day
    try:
        snap = await status(now)
        if snap["zone"] != "broken":
            return False
        day = str(snap.get("day") or _bishkek_day(now))
        if _alerted_day == day:
            return False                       # за эти сутки уже предупредили
        text = (
            "🔴 Подбор туров возвращает пусто\n"
            f"Сегодня {snap['total']} подборов, из них БЕЗ результата {snap['empty']} "
            f"({int(float(snap['zero_ratio']) * 100)}%).\n"
            f"Не распознано направление: {snap['no_destination']}. "
            f"Поиск без дат: {snap['no_dates']}.\n"
            "Клиенты сейчас слышат «ничего не нашлось» и уходят. Проверьте бота."
        )
        if await _notify_owners(text):
            _alerted_day = day
            logger.warning("tours_health broken: %s/%s пусто", snap["empty"], snap["total"])
            return True
        return False
    except Exception:  # noqa: BLE001
        logger.warning("tours_health: alert failed", exc_info=True)
        return False


async def _notify_owners(text: str) -> bool:
    """Алерт админам с личным chat_id (владельцы). В общую группу не шлём."""
    from app.core.calendar_brief import _push_telegram, _token
    token = _token()
    if not token:
        return False
    sent = False
    for mgr in settings.manager_list():
        if not getattr(mgr, "admin", False):
            continue
        chat_id = (getattr(mgr, "telegram_chat_id", "") or "").strip()
        if chat_id and await _push_telegram(token, chat_id, text):
            sent = True
    return sent


async def run() -> None:
    """Точка для планировщика."""
    await check_and_alert()


def _reset_for_tests() -> None:
    global _alerted_day
    _MEM.clear()
    _alerted_day = None
