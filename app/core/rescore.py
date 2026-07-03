"""Периодический ре-скоринг тира готовности с учётом застоя (ghost).

readiness считается на каждое сообщение — но в этот момент клиент только что написал,
поэтому «спросил цену и пропал» там не виден (застой — явление МЕЖДУ сообщениями).
Этот sweep (раз в час) пере-метит застойные неготовые диалоги в noise, чтобы чипы
владельца и калибровочные данные были честны. Ноль LLM — чистая арифметика по времени.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from app.config import settings
from app.core.readiness import ghost_downgrade
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("rescore")

_RUN_EVERY_SECONDS = 3600     # тик планировщика 5 мин — само-троттлимся до ~часа
_last_run = 0.0


def _ghost_hours(conv, now: datetime) -> float | None:
    dt = getattr(conv, "last_message_at", None)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0.0, (now - dt).total_seconds() / 3600)


async def run() -> None:
    """Джоба планировщика: застойный неготовый диалог → noise (персист в БД)."""
    global _last_run
    from app.core import flags
    if not await flags.get_flag("readiness_rescore_enabled", settings.readiness_rescore_enabled):
        return
    now_ts = time.time()
    if now_ts - _last_run < _RUN_EVERY_SECONDS:
        return
    _last_run = now_ts

    store = get_conversation_store()
    convs = await store.all_conversations_light()
    now = datetime.now(timezone.utc)
    changed = 0
    for c in convs:
        tier = getattr(c, "readiness_tier", "") or ""
        if tier not in ("insufficient", "warm"):
            continue
        new = ghost_downgrade(tier, getattr(c, "readiness_signals", None) or {},
                              _ghost_hours(c, now), getattr(c, "last_sender", "") or "")
        if new != tier:
            await store.update_meta(
                c.user_id, readiness_tier=new,
                readiness_reason="Шум: клиент пропал после ответа бота (застой >24ч)")
            changed += 1
    if changed:
        log.info("readiness rescore: %d застойных диалогов → noise", changed)
