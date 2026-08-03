"""Короткий обезличенный Redis-буфер для сверки формата Wappi на проде."""
from __future__ import annotations

import json
from typing import Any

from app.config import settings

_KEYS = {"media": "frunze:media_capture", "voice": "frunze:voice_capture"}
_SENSITIVE_PARTS = ("token", "secret", "authorization", "apikey", "api_key", "password", "key")
_PHONE_KEYS = {"from", "to", "chatid", "chat_id", "whatsapp_chat_id", "contact_phone", "recipient", "sender"}
_redis: Any = None


def _client() -> Any:
    global _redis
    if _redis is None:
        from redis import asyncio as aioredis
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


def _mask_phone(value: Any) -> Any:
    if not isinstance(value, str) or len(value) <= 6:
        return value
    return f"{value[:4]}***{value[-2:]}"


def _sanitize(raw: dict) -> dict:
    """Убрать секреты и телефоны: capture выгружают с прода в тестовые фикстуры."""
    def clean(value: Any, key: str = "") -> Any:
        if isinstance(value, dict):
            return {
                str(child_key): clean(child_value, str(child_key))
                for child_key, child_value in value.items()
                if not any(part in str(child_key).lower() for part in _SENSITIVE_PARTS)
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        if key.lower() in _PHONE_KEYS:
            value = _mask_phone(value)
        if isinstance(value, str) and len(value) > 300:
            return f"{value[:300]}…[обрезано]"
        return value

    return clean(raw)


async def _note(kind: str, payload: dict) -> None:
    if not settings.media_capture_enabled or settings.state_backend != "redis":
        return
    try:
        client = _client()
        key = _KEYS[kind]
        await client.lpush(key, json.dumps(payload, ensure_ascii=False))
        await client.ltrim(key, 0, max(0, settings.media_capture_keep - 1))
        await client.expire(key, settings.media_capture_ttl_seconds)
    except Exception:  # noqa: BLE001 — Redis диагностики не должен ронять сообщение
        return


async def note_raw(raw: dict) -> None:
    """Сохранить событие best-effort: диагностика никогда не мешает живому вебхуку."""
    await _note("media", _sanitize(raw))


async def note_voice_miss(raw: dict) -> None:
    """Отдельно сохранить неразобранный voice: общий поток медиа быстро вытесняет редкий формат."""
    await _note("voice", {"payload": _sanitize(raw), "top_level_keys": sorted(map(str, raw.keys()))})


async def recent(kind: str = "media", limit: int = 50) -> list[dict]:
    """Вернуть свежую диагностику одной командой, не открывая прямой доступ к Redis."""
    if kind not in _KEYS or settings.state_backend != "redis":
        return []
    try:
        rows = await _client().lrange(_KEYS[kind], 0, max(0, limit - 1))
        return [json.loads(row) for row in rows]
    except Exception:  # noqa: BLE001 — отсутствие диагностики не является сбоем приложения
        return []
