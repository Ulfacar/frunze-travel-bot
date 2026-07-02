"""Recent provider message ids sent by this process."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict

_TTL_SECONDS = 15 * 60
_MAX_IDS = 5000
_own_ids: "OrderedDict[str, float]" = OrderedDict()
_lock = threading.RLock()


def _cleanup(now: float) -> None:
    while _own_ids:
        _, ts = next(iter(_own_ids.items()))
        if now - ts <= _TTL_SECONDS:
            break
        _own_ids.popitem(last=False)
    while len(_own_ids) > _MAX_IDS:
        _own_ids.popitem(last=False)


def mark_own(provider_msg_id: str | None) -> None:
    if not provider_msg_id:
        return
    now = time.monotonic()
    provider_msg_id = str(provider_msg_id)
    with _lock:
        _own_ids[provider_msg_id] = now
        _own_ids.move_to_end(provider_msg_id)
        _cleanup(now)


def is_own(provider_msg_id: str | None) -> bool:
    if not provider_msg_id:
        return False
    now = time.monotonic()
    provider_msg_id = str(provider_msg_id)
    with _lock:
        _cleanup(now)
        found = provider_msg_id in _own_ids
        if found:
            _own_ids.move_to_end(provider_msg_id)
        return found


def _reset_for_tests() -> None:
    with _lock:
        _own_ids.clear()
