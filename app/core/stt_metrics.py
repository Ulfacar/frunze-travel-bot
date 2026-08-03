"""Боевые Redis-метрики STT и независимый circuit breaker каждого бота.

Модуль намеренно не имеет memory-фолбэка: после рестарта локальные числа дали бы владельцу
ложную картину. При недоступном Redis измерения тихо исчезают, но голосовое обрабатывается.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.core.budget import _bishkek_day

_redis_client: Any | None = None
_METRIC_TTL = 48 * 3600
_STREAK_TTL = 24 * 3600
_PAID_TTL = 7 * 24 * 3600
_FIELDS = ("received", "ok", "empty", "errors", "cache_hits", "lock_waits",
           "duration_sum", "latency_sum", "cost_sum", "double_paid")
_ERROR_CODES = {"insufficient_quota", "401", "403", "429", "timeout", "download", "other"}
_BOT_NAMES = {"frunze_tours": "Адеми", "frunze_tours_sezim": "Айсина", "getvisa": "GetVisa"}


def _redis() -> Any:
    global _redis_client
    if _redis_client is None:
        from redis import asyncio as aioredis
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


def _day(day: Any = None) -> str:
    if day is None:
        return _bishkek_day()
    if isinstance(day, datetime):
        return _bishkek_day(day)
    return str(day).replace("-", "")


def _mkey(bot_id: str, day: Any = None) -> str:
    return f"stt:m:{bot_id}:{_day(day)}"


async def _hincr(bot_id: str, field: str, value: int | float = 1) -> None:
    if settings.state_backend != "redis":
        return
    try:
        client = _redis()
        await client.hincrbyfloat(_mkey(bot_id), field, value)
        await client.expire(_mkey(bot_id), _METRIC_TTL)
    except Exception:  # noqa: BLE001 — метрика не важнее ответа клиенту
        return


async def _latency(bot_id: str, latency_ms: int | float) -> None:
    if settings.state_backend != "redis":
        return
    try:
        client = _redis()
        key = f"stt:lat:{bot_id}:{_day()}"
        await client.lpush(key, max(0, float(latency_ms)))
        await client.ltrim(key, 0, 499)
        await client.expire(key, _METRIC_TTL)
    except Exception:  # noqa: BLE001
        return


async def note_received(bot_id: str) -> None:
    await _hincr(bot_id, "received")


async def _paid(bot_id: str, msg_id: str) -> bool:
    if settings.state_backend != "redis" or not msg_id:
        return False
    try:
        fresh = await _redis().set(f"stt:paid:{bot_id}:{msg_id}", "1", nx=True, ex=_PAID_TTL)
        if not fresh:
            await _hincr(bot_id, "double_paid")
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


async def note_success(bot_id: str, *, latency_ms: int, duration_sec: float,
                       cost_usd: float, msg_id: str) -> bool:
    """Учесть оплату и успех; True означает повторную оплату одного provider message."""
    duplicate = await _paid(bot_id, msg_id)
    await _hincr(bot_id, "ok")
    await _hincr(bot_id, "latency_sum", max(0, latency_ms))
    await _hincr(bot_id, "duration_sum", max(0, duration_sec))
    await _hincr(bot_id, "cost_sum", max(0, cost_usd))
    await _latency(bot_id, latency_ms)
    if settings.state_backend == "redis":
        try:
            await _redis().delete(f"stt:streak:{bot_id}")
        except Exception:  # noqa: BLE001
            pass
    return duplicate


async def note_empty(bot_id: str, *, latency_ms: int, cost_usd: float, msg_id: str) -> bool:
    """Пустой ответ оплачен, но не является успехом и не сбрасывает серию ошибок."""
    duplicate = await _paid(bot_id, msg_id)
    await _hincr(bot_id, "empty")
    await _hincr(bot_id, "latency_sum", max(0, latency_ms))
    await _hincr(bot_id, "cost_sum", max(0, cost_usd))
    await _latency(bot_id, latency_ms)
    return duplicate


def error_code(exc: BaseException) -> str:
    """Свести нестабильные тексты SDK/HTTP к ограниченному набору безопасных кодов."""
    status = getattr(exc, "status_code", None)
    text = f"{type(exc).__name__} {exc}".lower()
    if "insufficient_quota" in text:
        return "insufficient_quota"
    for code in (401, 403, 429):
        if status == code or f"http {code}" in text or f"status {code}" in text:
            return str(code)
    if isinstance(exc, TimeoutError) or "timeout" in text or "timed out" in text:
        return "timeout"
    if "download" in text or "скач" in text or "media" in text:
        return "download"
    return "other"


async def note_error(bot_id: str, *, latency_ms: int, code: str) -> None:
    safe = code if code in _ERROR_CODES else "other"
    await _hincr(bot_id, "errors")
    await _hincr(bot_id, f"err:{safe}")
    await _hincr(bot_id, "latency_sum", max(0, latency_ms))
    await _latency(bot_id, latency_ms)
    if settings.state_backend == "redis":
        try:
            key = f"stt:streak:{bot_id}"
            await _redis().incr(key)
            await _redis().expire(key, _STREAK_TTL)
        except Exception:  # noqa: BLE001
            pass


async def note_cache_hit(bot_id: str) -> None:
    await _hincr(bot_id, "cache_hits")


async def note_lock_wait(bot_id: str) -> None:
    await _hincr(bot_id, "lock_waits")


async def snapshot(bot_id: str, day: Any = None) -> dict:
    values = {field: 0 for field in _FIELDS}
    values.update({f"err:{code}": 0 for code in _ERROR_CODES})
    latencies: list[float] = []
    streak = 0
    breaker: dict = {}
    if settings.state_backend == "redis":
        try:
            client = _redis()
            raw = await client.hgetall(_mkey(bot_id, day))
            for key, value in raw.items():
                values[key] = float(value or 0)
            latencies = [float(v) for v in await client.lrange(
                f"stt:lat:{bot_id}:{_day(day)}", 0, -1)]
            streak = int(await client.get(f"stt:streak:{bot_id}") or 0)
            breaker = json.loads(await client.get(f"stt:breaker:{bot_id}") or "{}")
        except Exception:  # noqa: BLE001
            pass
    received, ok = int(values["received"]), int(values["ok"])
    ordered = sorted(latencies)
    p95 = ordered[max(0, math.ceil(len(ordered) * .95) - 1)] if ordered else 0.0
    latency_count = int(values["ok"] + values["empty"] + values["errors"])
    return {**values, "received": received, "ok": ok, "empty": int(values["empty"]),
            "errors": int(values["errors"]), "cache_hits": int(values["cache_hits"]),
            "lock_waits": int(values["lock_waits"]), "double_paid": int(values["double_paid"]),
            "success_rate": (ok / received * 100.0) if received else 0.0,
            "p95_ms": p95, "avg_latency_ms": (float(values["latency_sum"]) / latency_count
                                                if latency_count else 0.0),
            "streak": streak, "breaker": breaker, "day": _day(day)}


async def check_and_trip(bot_id: str) -> str:
    """Отключить только проблемный STT; повторный вызов не дублирует Telegram-алерт."""
    try:
        snap = await snapshot(bot_id)
        reason = ""
        if snap["err:401"] or snap["err:403"]:
            reason = "провайдер отклонил авторизацию (HTTP 401/403)"
        elif snap["err:insufficient_quota"]:
            reason = "исчерпана квота STT-провайдера"
        elif snap["double_paid"]:
            reason = "повторная оплата одного голосового"
        elif snap["streak"] >= 3:
            reason = "три ошибки распознавания подряд"
        elif snap["received"] >= 10 and snap["success_rate"] < 70:
            reason = f"доля успешных распознаваний {snap['success_rate']:.1f}% ниже 70%"
        elif snap["received"] >= 5 and snap["p95_ms"] > 15000:
            reason = f"p95 задержки {snap['p95_ms'] / 1000:.1f} с выше 15 с"
        if not reason:
            return ""
        from app.core import flags
        await flags.set_flag(f"stt_enabled:{bot_id}", False)
        already = bool(snap.get("breaker"))
        if settings.state_backend == "redis" and not already:
            payload = json.dumps({"reason": reason, "at": datetime.now(timezone.utc).isoformat()},
                                 ensure_ascii=False)
            await _redis().set(f"stt:breaker:{bot_id}", payload, ex=_PAID_TTL)
        if not already:
            from app.core.ops_alert import send
            await send("🔴 STT автоматически отключён.\n"
                       f"Бот: {_BOT_NAMES.get(bot_id, bot_id)}\nПричина: {reason}\n"
                       "WhatsApp и текстовые сообщения продолжают работать.")
        return reason
    except Exception:  # noqa: BLE001 — breaker также fail-safe и не ломает сообщение
        return ""


async def clear_breaker(bot_id: str) -> None:
    """Начать чистое окно после ручного включения, иначе старая 401 сразу выключит STT снова.

    Платёжные отметки не удаляем: один provider message нельзя оплачивать повторно даже после
    ручного сброса. Сбрасываются лишь агрегаты текущего окна и причина прошлой аварии.
    """
    if settings.state_backend == "redis":
        try:
            await _redis().delete(f"stt:breaker:{bot_id}", _mkey(bot_id),
                                  f"stt:lat:{bot_id}:{_day()}", f"stt:streak:{bot_id}")
        except Exception:  # noqa: BLE001
            pass
