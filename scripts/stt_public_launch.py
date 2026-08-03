"""Идемпотентный preflight и публичный запуск STT без изменения env и рестарта."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.core import flags, ops_alert  # noqa: E402

TOUR_BOTS = ("frunze_tours", "frunze_tours_sezim")


async def _redis_ok() -> bool:
    try:
        from redis import asyncio as aioredis
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        return bool(await client.ping())
    except Exception:  # noqa: BLE001 — preflight обязан вернуть точную проверку, а не traceback
        return False


async def _database_ok() -> bool:
    try:
        from app.integrations.crm.db import get_sessionmaker
        async with get_sessionmaker()() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False


async def _profile_authorized(profile_id: str) -> bool:
    """Проверить профиль тем же аккаунтовым токеном; ответ без authorized считаем провалом."""
    if not settings.wappi_token or not profile_id:
        return False
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{settings.wappi_base_url.rstrip('/')}/api/profile/all/get",
                params={"profile_id": profile_id},
                headers={"Authorization": settings.wappi_token},
            )
        response.raise_for_status()
        payload = response.json()
        profiles = payload.get("profiles") if isinstance(payload, dict) else None
        if isinstance(profiles, list):
            return any(isinstance(item, dict)
                       and str(item.get("profile_id") or item.get("uuid") or "") == profile_id
                       and item.get("authorized") is True for item in profiles)
        return False
    except Exception:  # noqa: BLE001
        return False


async def _openai_ok() -> tuple[bool, str]:
    if not settings.stt_api_key.strip():
        return False, "ключ OpenAI пуст"
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{settings.stt_base_url.rstrip('/')}/models",
                headers={"Authorization": f"Bearer {settings.stt_api_key}"},
            )
        body = response.text.lower()
        if response.status_code in (401, 403):
            return False, f"OpenAI вернул HTTP {response.status_code}"
        if "insufficient_quota" in body:
            return False, "OpenAI вернул insufficient_quota"
        if response.status_code >= 400:
            return False, f"OpenAI /models вернул HTTP {response.status_code}"
        return True, ""
    except Exception as exc:  # noqa: BLE001
        return False, f"OpenAI /models недоступен ({type(exc).__name__})"


async def preflight() -> tuple[bool, str]:
    if settings.state_backend != "redis" or not await _redis_ok():
        return False, "Redis недоступен или STATE_BACKEND не redis"
    if not await _database_ok():
        return False, "база данных недоступна"
    by_id = {bot.id: bot for bot in settings.bots}
    for bot_id in TOUR_BOTS:
        bot = by_id.get(bot_id)
        if bot is None or not await _profile_authorized(bot.wappi_profile_id):
            return False, f"Wappi-профиль {bot_id} не авторизован"
    ok, reason = await _openai_ok()
    if not ok:
        return False, reason
    for bot_id in TOUR_BOTS:
        if not await flags.get_flag(f"stt_enabled:{bot_id}", settings.stt_enabled):
            return False, f"флаг stt_enabled:{bot_id} выключен"
    if await flags.get_flag("stt_enabled:getvisa", False):
        return False, "флаг stt_enabled:getvisa должен быть выключен"
    if not await ops_alert.send("✅ STT preflight: Telegram-канал технических уведомлений работает."):
        return False, "Telegram-уведомление не доставлено"
    return True, ""


async def run() -> bool:
    if await flags.get_flag("stt_public_launch_done", False):
        return True
    ok, reason = await preflight()
    if not ok:
        await ops_alert.send("🔴 Публичный запуск STT отменён.\n"
                             f"Причина: {reason}\nТекущий режим и WhatsApp не изменены.")
        return False
    await flags.set_flag("stt_public_enabled", True)
    await flags.set_flag("stt_public_launch_done", True)
    await ops_alert.send("🎤 Голосовые включены для всех клиентов Адеми и Айсины.\n"
                         "Менеджеры видят готовый текст в админке.\n"
                         "GetVisa не затронут.\nНачат мониторинг первого часа.")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if asyncio.run(run()) else 1)
