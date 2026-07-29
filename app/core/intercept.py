"""Shared dialog intercept helper."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.core.state import get_state_store
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


async def set_intercept(
    user_id: str,
    value: bool,
    *,
    automatic: bool = False,
    now: datetime | None = None,
) -> None:
    """Установить ручной либо временный автоматический перехват диалога."""
    store = get_state_store()
    state = await store.load(user_id)
    has_permanent_intercept = state.intercepted and state.auto_intercept_until is None
    state.intercepted = value
    if not value:
        state.auto_intercept_until = None
    elif automatic and not has_permanent_intercept:
        current = now or _utcnow()
        state.auto_intercept_until = (
            current + timedelta(hours=settings.manager_silence_hours)
        ).timestamp()
    elif not automatic:
        state.auto_intercept_until = None
    await store.save(state)
    await get_conversation_store().set_intercepted(user_id, value)


async def expire_auto_intercept(user_id: str, *, now: datetime | None = None) -> None:
    """Лениво снять истёкший автоперехват; ошибки хранилищ не роняют живое сообщение."""
    try:
        store = get_state_store()
        state = await store.load(user_id)
        deadline = state.auto_intercept_until
        if not state.intercepted or deadline is None:
            return
        current_timestamp = (now or _utcnow()).timestamp()
        if current_timestamp < deadline:
            return
        # Echo менеджера не берёт диалоговый лок и мог продлить окно после первой
        # проверки. Перед записью убеждаемся, что истекает всё ещё то же состояние.
        state = await store.load(user_id)
        deadline = state.auto_intercept_until
        if (
            not state.intercepted
            or deadline is None
            or current_timestamp < deadline
        ):
            return
        state.intercepted = False
        state.auto_intercept_until = None
        await store.save(state)
        try:
            await get_conversation_store().set_intercepted(user_id, False)
        except Exception:  # noqa: BLE001 — state уже разблокирован, ответ клиенту важнее панели
            log.warning("panel auto-intercept expiry sync failed (key=%s)", user_id,
                        exc_info=True)
    except Exception:  # noqa: BLE001 — сбой TTL-проверки не должен ронять вебхук
        log.warning("auto-intercept expiry check failed (key=%s)", user_id, exc_info=True)
