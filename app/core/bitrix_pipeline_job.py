"""Ten-minute scheduler cadence for Bitrix pipeline read-back."""
from __future__ import annotations

from app.integrations.crm.bitrix_pipeline import read_back_once

_ticks = 0


async def run() -> None:
    global _ticks
    _ticks += 1
    # The shared scheduler ticks every five minutes. Start read-back at minute ten.
    if _ticks % 2 == 0:
        await read_back_once()
