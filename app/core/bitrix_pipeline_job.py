"""Ten-minute scheduler cadence for Bitrix pipeline read-back."""
from __future__ import annotations

from app.integrations.crm.bitrix_pipeline import catchup_once, read_back_once

_ticks = 0


async def run() -> None:
    global _ticks
    _ticks += 1
    # The shared scheduler ticks every five minutes. Start read-back at minute ten.
    if _ticks % 2 == 0:
        await read_back_once()
        # Догоняющий проход по стадиям: сам себя выключает, если тумблер снят.
        stats = await catchup_once()
        # Результат прогона раньше выбрасывался, и застревание прохода (07.09: moved=0
        # сутки подряд при непустой очереди) не видел никто — оно жило только в логах.
        from app.core import pipeline_metrics
        await pipeline_metrics.note_run(stats or {})
