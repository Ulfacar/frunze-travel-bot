"""Лёгкие счётчики наблюдаемости (сбои LLM и отправок).

Инкрементируются из оркестратора при сбоях, читаются watchdog'ом (алерты) и
страницей «Статус системы». In-memory процесса (прод — один инстанс), сбрасываются
при рестарте — это ок, нужны для оперативной картины, не для долгой истории.
"""
from __future__ import annotations

import logging
import re
import time
import uuid
from contextvars import ContextVar
from datetime import date
from typing import Any

from starlette.datastructures import MutableHeaders

_COUNTERS: dict[str, int] = {"llm_failures": 0, "send_failures": 0}
_LAST_TS: dict[str, float] = {"llm_failure_ts": 0.0, "send_failure_ts": 0.0}
_INBOUND: dict[str, float] = {"ts": 0.0}
# Сработки валидатора ответов по виду нарушения (markdown, possible_visa_guarantee, …) —
# чтобы видеть, как часто модель отклоняется от политики, не калеча ответ.
_VALIDATIONS: dict[str, int] = {}
_USAGE_DAILY: dict[str, dict[str, Any]] = {}

log = logging.getLogger("observ")


def record_failure(kind: str) -> None:
    """kind: 'llm' | 'send'. Увеличить счётчик и запомнить время последнего сбоя."""
    _COUNTERS[f"{kind}_failures"] = _COUNTERS.get(f"{kind}_failures", 0) + 1
    _LAST_TS[f"{kind}_failure_ts"] = time.time()


def note_validation(kind: str) -> None:
    """Зафиксировать сработку валидатора исходящего ответа (по виду нарушения)."""
    _VALIDATIONS[kind] = _VALIDATIONS.get(kind, 0) + 1


def note_inbound() -> None:
    """Отметить время последнего входящего сообщения клиента (детектор «тишины»)."""
    _INBOUND["ts"] = time.time()


def record_usage(
    model: str,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    cost: float | str | None,
    bot_id: str,
    user_id: str,
    *,
    usage: dict[str, Any] | None = None,
) -> None:
    """Record LLM token/cost usage in logs and in-memory daily aggregates."""
    day = date.today().isoformat()
    prompt = _as_int(prompt_tokens)
    completion = _as_int(completion_tokens)
    cost_value = _as_float(cost)
    total = _as_int((usage or {}).get("total_tokens"))
    if total == 0:
        total = prompt + completion

    bucket = _USAGE_DAILY.setdefault(
        day,
        {
            "calls": 0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
            "by_model": {},
        },
    )
    bucket["calls"] += 1
    bucket["prompt_tokens"] += prompt
    bucket["completion_tokens"] += completion
    bucket["total_tokens"] += total
    bucket["cost"] += cost_value

    by_model = bucket["by_model"].setdefault(
        model,
        {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0.0},
    )
    by_model["calls"] += 1
    by_model["prompt_tokens"] += prompt
    by_model["completion_tokens"] += completion
    by_model["total_tokens"] += total
    by_model["cost"] += cost_value

    log.info(
        "llm_usage model=%s prompt_tokens=%s completion_tokens=%s total_tokens=%s cost=%s bot_id=%s user_id=%s usage=%s",
        model,
        prompt,
        completion,
        total,
        cost,
        bot_id,
        user_id,
        usage or {},
    )


def last_inbound_ago() -> float | None:
    """Сколько секунд назад было последнее входящее (None — ещё не было)."""
    ts = _INBOUND["ts"]
    return round(time.time() - ts, 1) if ts else None


def snapshot() -> dict:
    """Текущее состояние счётчиков (+ «сколько секунд назад был сбой»)."""
    now = time.time()
    out: dict = dict(_COUNTERS)
    for key, ts in _LAST_TS.items():
        out[key] = ts
        out[key.replace("_ts", "_ago")] = round(now - ts, 1) if ts else None
    out["validations"] = dict(_VALIDATIONS)
    out["usage_daily"] = {
        day: {
            **{k: v for k, v in values.items() if k != "by_model"},
            "by_model": {model: dict(model_values) for model, model_values in values["by_model"].items()},
        }
        for day, values in _USAGE_DAILY.items()
    }
    return out


def reset() -> None:
    """Сброс (для тестов)."""
    for k in _COUNTERS:
        _COUNTERS[k] = 0
    for k in _LAST_TS:
        _LAST_TS[k] = 0.0
    _INBOUND["ts"] = 0.0
    _VALIDATIONS.clear()
    _USAGE_DAILY.clear()


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


# --- Request correlation id (WP0 observability) --------------------------------
# Per-request id propagated via contextvars → structured logs + X-Request-ID header.
# Only the id is logged; never phones, message text, tokens or other PII.

_REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")


def sanitize_request_id(raw: str | None) -> str:
    """Return a safe correlation id: keep a valid inbound id, else generate one."""
    if raw and _SAFE_REQUEST_ID.match(raw):
        return raw
    return uuid.uuid4().hex


def get_request_id() -> str:
    return _REQUEST_ID.get()


def bind_request_id(value: str):
    return _REQUEST_ID.set(value)


def reset_request_id(token) -> None:
    _REQUEST_ID.reset(token)


class RequestIdLogFilter(logging.Filter):
    """Inject the current request id into every log record (default '-')."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _REQUEST_ID.get()
        return True


def install_request_id_logging() -> None:
    """Attach the request-id filter + format to the root log handlers."""
    root = logging.getLogger()
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s")
    filt = RequestIdLogFilter()
    for handler in root.handlers:
        handler.addFilter(filt)
        handler.setFormatter(fmt)


class RequestIdMiddleware:
    """ASGI middleware: bind a correlation id per HTTP request.

    Accepts a safe inbound `X-Request-ID`, otherwise generates one; echoes it in
    the response header and exposes it to logs via the context var. Each request
    runs in its own task, so two requests never share one context.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        raw: str | None = None
        for key, value in scope.get("headers", []):
            if key == b"x-request-id":
                raw = value.decode("latin-1", "replace")
                break
        request_id = sanitize_request_id(raw)
        token = _REQUEST_ID.set(request_id)

        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            _REQUEST_ID.reset(token)
