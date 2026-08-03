"""Честный почасовой отчёт STT: каждый туровый бот показан отдельно."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.core import flags, ops_alert, stt_metrics  # noqa: E402

BOT_NAMES = {"frunze_tours": "Адеми", "frunze_tours_sezim": "Айсина"}


async def build_report() -> str:
    blocks = ["🎤 Отчёт STT за первый час"]
    for bot_id, name in BOT_NAMES.items():
        snap = await stt_metrics.snapshot(bot_id)
        enabled = await flags.get_flag(f"stt_enabled:{bot_id}", settings.stt_enabled)
        breaker = (snap.get("breaker") or {}).get("reason", "")
        if not snap["received"]:
            blocks.append(f"\n{name}: голосовых не было.\nSTT: {'включён' if enabled else 'выключен'}"
                          + (f"\nАвтоотключение: {breaker}" if breaker else ""))
            continue
        blocks.append(
            f"\n{name}:\nПолучено: {snap['received']}; успешно: {snap['ok']}; "
            f"пусто: {snap['empty']}; ошибок: {snap['errors']}\n"
            f"Success rate: {snap['success_rate']:.1f}%; средняя задержка: "
            f"{snap['avg_latency_ms']:.0f} мс; p95: {snap['p95_ms']:.0f} мс\n"
            f"Стоимость: ${float(snap['cost_sum']):.4f}; cache hits: {snap['cache_hits']}; "
            f"lock waits: {snap['lock_waits']}\n"
            f"Автоотключение: {breaker or 'нет'}; STT: {'включён' if enabled else 'выключен'}"
        )
    return "\n".join(blocks)


async def run() -> bool:
    return await ops_alert.send(await build_report())


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)
