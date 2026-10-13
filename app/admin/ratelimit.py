"""Простой in-memory rate-limiter НЕУДАЧНЫХ попыток логина (защита от брутфорса).

Считаем только провалы: успешный вход не приближает к блокировке. Прод — один
инстанс, поэтому хватает счётчика в памяти процесса (как `_seen_wappi_ids` в
app/main.py). Скользящее окно по IP: не более `limit` провалов за `window` секунд.
"""
from __future__ import annotations

import time
from collections import OrderedDict, deque

_LOGIN_LIMIT = 10           # провалов
_LOGIN_WINDOW = 60.0        # секунд
_MAX_IPS = 4096
_MAX_FAILURES = 1024
_fails: "OrderedDict[str, deque[float]]" = OrderedDict()


def _prune(ip: str, now: float, window: float) -> "deque[float]":
    q = _fails.get(ip)
    if q is None:
        if len(_fails) >= _MAX_IPS:
            _fails.popitem(last=False)
        q = deque(maxlen=_MAX_FAILURES)
        _fails[ip] = q
    _fails.move_to_end(ip)
    cutoff = now - window
    while q and q[0] < cutoff:
        q.popleft()
    return q


def is_blocked(ip: str, *, limit: int = _LOGIN_LIMIT,
               window: float = _LOGIN_WINDOW, now: float | None = None) -> bool:
    """Только проверка (без записи): превышен ли лимит провалов за окно."""
    if not 1 <= limit <= _MAX_FAILURES:
        raise ValueError('Unsupported login failure limit')
    t = now if now is not None else time.monotonic()
    return len(_prune(ip, t, window)) >= limit


def note_failure(ip: str, *, window: float = _LOGIN_WINDOW, now: float | None = None) -> None:
    """Зафиксировать неудачную попытку логина с IP."""
    t = now if now is not None else time.monotonic()
    _prune(ip, t, window).append(t)


def reset() -> None:
    """Очистить счётчики (для тестов)."""
    _fails.clear()
