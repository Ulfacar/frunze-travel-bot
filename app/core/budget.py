"""Daily LLM spend guard.

The guard uses a Redis counter in production and an in-memory counter in local
or test runs. The day boundary follows Bishkek time (UTC+6).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.config import settings

logger = logging.getLogger("budget")

_REDIS_TTL_SECONDS = 48 * 3600
_MEM_SPEND: dict[str, float] = {}
_redis_client: Any | None = None
_last_reported_status: str | None = None

_MODEL_PRICE_PER_1M = {
    "haiku": (1.0, 5.0),
    "sonnet": (3.0, 15.0),
}
_DEFAULT_PRICE_PER_1M = (3.0, 15.0)


def _bishkek_day(now: datetime | None = None) -> str:
    base = now if now is not None else datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return (base.astimezone(timezone.utc) + timedelta(hours=6)).date().isoformat()


def _key(day: str | None = None) -> str:
    return f"llm_spend:{day or _bishkek_day()}"


def _price_for(model: str) -> tuple[float, float]:
    model_l = (model or "").lower()
    for marker, price in _MODEL_PRICE_PER_1M.items():
        if marker in model_l:
            return price
    return _DEFAULT_PRICE_PER_1M


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def estimate_cost(model: str, prompt_tokens: object, completion_tokens: object) -> float:
    input_price, output_price = _price_for(model)
    prompt = max(0.0, _as_float(prompt_tokens))
    completion = max(0.0, _as_float(completion_tokens))
    return (prompt * input_price + completion * output_price) / 1_000_000


def cost_from_usage(model: str, usage: dict[str, Any]) -> float:
    cost = _as_float(usage.get("cost"))
    if cost > 0:
        return cost
    return estimate_cost(model, usage.get("prompt_tokens"), usage.get("completion_tokens"))


def _make_redis() -> Any:
    from redis import asyncio as aioredis

    return aioredis.from_url(settings.redis_url, decode_responses=True)


def _redis() -> Any:
    global _redis_client
    if _redis_client is None:
        _redis_client = _make_redis()
    return _redis_client


async def add_spend(cost: float) -> None:
    amount = _as_float(cost)
    if amount <= 0:
        return
    if settings.state_backend == "redis":
        redis = _redis()
        key = _key()
        await redis.incrbyfloat(key, amount)
        await redis.expire(key, _REDIS_TTL_SECONDS)
        return
    day = _bishkek_day()
    _MEM_SPEND[day] = _MEM_SPEND.get(day, 0.0) + amount


async def spend_today() -> float:
    if settings.state_backend == "redis":
        raw = await _redis().get(_key())
        return _as_float(raw)
    return _MEM_SPEND.get(_bishkek_day(), 0.0)


async def status() -> str:
    global _last_reported_status
    daily_budget = _as_float(settings.llm_daily_budget_usd)
    if daily_budget <= 0:
        current = "off"
    else:
        spend = await spend_today()
        soft_ratio = max(0.0, _as_float(settings.llm_daily_budget_soft_ratio, 0.8))
        if spend >= daily_budget:
            current = "hard"
        elif spend >= daily_budget * soft_ratio:
            current = "soft"
        else:
            current = "ok"

    if current in {"soft", "hard"} and current != _last_reported_status:
        logger.warning("llm_budget_%s spend=%s budget=%s", current, await spend_today(), daily_budget)
    _last_reported_status = current
    return current


async def soft_capped() -> bool:
    return await status() in {"soft", "hard"}


async def hard_capped() -> bool:
    return await status() == "hard"
