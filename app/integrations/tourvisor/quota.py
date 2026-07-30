"""Суточная квота TourVisor: счётчик запросов + алерт до того, как поиск умрёт.

Зачем. Тариф режет **3000 запросов в сутки**, а бот при исчерпании не падает, а честно
врёт всем подряд («Поиск туров сейчас временно недоступен») — тихо, без единого алерта,
ровно в деньги и ровно в сезон. Один подбор при пустой выдаче делает ДВА запроса, дневной
режим на турах умножает поиск ещё втрое, а публичный виджет на сайте выжжет квоту за часы.

Что делает модуль:

* считает каждый вызов API (единственная точка — ``TourVisorClient._call``);
* на пороге (по умолчанию 70%) один раз за сутки шлёт алерт владельцу в Telegram —
  чтобы узнать об исчерпании ДО клиентов, а не от клиентов;
* даёт число для админки и брифа.

Механика повторяет дневной бюджет LLM (`app/core/budget.py`): счётчик в Redis с суточным
ключом по Бишкеку и TTL, in-memory фолбэк для дев/тестов. День катится в 00:00 по Бишкеку,
как и у провайдера.

Ничего не блокирует: превысить квоту счётчик не мешает, он только считает и предупреждает.
Резать запросы на клиенте — отдельное решение, его принимать владельцу.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.config import settings
from app.core.budget import _bishkek_day  # единый день по Бишкеку для всех суточных счётчиков

logger = logging.getLogger("tourvisor_quota")

_REDIS_TTL_SECONDS = 48 * 3600
_MEM_CALLS: dict[str, int] = {}
_redis_client: Any | None = None
_alerted_day: str | None = None


def _key(day: str | None = None) -> str:
    return f"tourvisor:calls:{day or _bishkek_day()}"


def _redis() -> Any:
    global _redis_client
    if _redis_client is None:
        from redis import asyncio as aioredis
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def note_call(count: int = 1) -> None:
    """Учесть запрос(ы) к API. Никогда не поднимает исключение: счётчик не важнее поиска."""
    try:
        if count <= 0:
            return
        if settings.state_backend == "redis":
            redis = _redis()
            key = _key()
            await redis.incrby(key, count)
            await redis.expire(key, _REDIS_TTL_SECONDS)
        else:
            day = _bishkek_day()
            _MEM_CALLS[day] = _MEM_CALLS.get(day, 0) + count
    except Exception:  # noqa: BLE001 — сбой счётчика не должен ломать подбор туров
        logger.warning("tourvisor quota: note_call failed", exc_info=True)


async def used_today() -> int:
    try:
        if settings.state_backend == "redis":
            raw = await _redis().get(_key())
            return int(raw or 0)
        return _MEM_CALLS.get(_bishkek_day(), 0)
    except Exception:  # noqa: BLE001
        logger.warning("tourvisor quota: used_today failed", exc_info=True)
        return 0


def _limit() -> int:
    try:
        return int(settings.tourvisor_daily_quota or 0)
    except (TypeError, ValueError):
        return 0


async def status(now: datetime | None = None) -> dict[str, object]:
    """Снимок для админки/брифа: сколько ушло, сколько осталось, в какой мы зоне."""
    limit = _limit()
    used = await used_today()
    if limit <= 0:
        return {"used": used, "limit": 0, "left": 0, "ratio": 0.0, "zone": "off"}
    ratio = used / limit
    threshold = max(0.0, min(1.0, float(settings.tourvisor_quota_alert_ratio or 0.7)))
    zone = "exhausted" if used >= limit else ("warn" if ratio >= threshold else "ok")
    return {"used": used, "limit": limit, "left": max(0, limit - used),
            "ratio": round(ratio, 3), "zone": zone, "day": _bishkek_day(now)}


async def check_and_alert(*, now: datetime | None = None) -> bool:
    """Один алерт владельцу за сутки при переходе порога. True — алерт отправлен.

    Джоба планировщика; вызывать безопасно как угодно часто.
    """
    global _alerted_day
    try:
        snap = await status(now)
        if snap["zone"] not in ("warn", "exhausted"):
            return False
        day = str(snap.get("day") or _bishkek_day(now))
        if _alerted_day == day:
            return False                       # за эти сутки уже предупредили
        text = (
            "⚠️ TourVisor: квота поиска на исходе\n"
            f"Использовано {snap['used']} из {snap['limit']} запросов "
            f"({int(float(snap['ratio']) * 100)}%), осталось {snap['left']}.\n"
            "Когда квота кончится, бот перестанет подбирать туры и будет всем отвечать "
            "«поиск временно недоступен». Клиенты этого не поймут."
            if snap["zone"] == "warn" else
            "🔴 TourVisor: суточная квота ИСЧЕРПАНА\n"
            f"Использовано {snap['used']} из {snap['limit']}. Бот сейчас отвечает всем "
            "«поиск временно недоступен» — подбор туров не работает до 00:00 по Бишкеку."
        )
        if await _notify_owners(text):
            _alerted_day = day
            logger.warning("tourvisor quota %s: used=%s/%s",
                           snap["zone"], snap["used"], snap["limit"])
            return True
        return False
    except Exception:  # noqa: BLE001
        logger.warning("tourvisor quota: alert failed", exc_info=True)
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
    _MEM_CALLS.clear()
    _alerted_day = None
