"""Fail-safe точка входа для скачивания и распознавания клиентского голосового."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import replace
from typing import Any
from urllib.parse import urlsplit

from app.config import settings
from app.core import observ
from app.core import stt_metrics
from app.integrations.stt.base import SttPermanentError
from app.integrations.stt.fetch import fetch_media
from app.integrations.stt.registry import get_provider

logger = logging.getLogger("stt.service")
_redis: Any = None


def _redis_client() -> Any:
    global _redis
    if _redis is None:
        from redis import asyncio as aioredis
        _redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis


async def _cache_get(key: str) -> tuple[bool, str]:
    if not key or settings.state_backend != "redis":
        return False, ""
    try:
        raw = await _redis_client().get(key)
    except Exception:  # noqa: BLE001 — недоступный Redis не должен блокировать платный путь
        return False, ""
    if raw is None:
        return False, ""
    try:
        payload = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        # До ввода метаданных в Redis лежала простая строка; старые ключи живут до семи суток.
        return True, str(raw)
    if isinstance(payload, dict):
        return True, str(payload.get("transcript") or "")
    return True, str(raw)


async def _cache_set(key: str, payload: dict[str, Any], *, ttl: int | None = None) -> None:
    if not key or settings.state_backend != "redis":
        return
    try:
        await _redis_client().set(
            key, json.dumps(payload, ensure_ascii=False),
            ex=ttl if ttl is not None else settings.stt_cache_ttl_seconds,
        )
    except Exception:  # noqa: BLE001 — готовая расшифровка важнее диагностического кэша
        return


def _media_ref(url: str) -> str:
    """Короткая ссылка на медиа для диагностики: хост и имя файла, БЕЗ query.

    В query у провайдеров обычно лежит подписанный токен доступа — класть его в Redis на
    неделю нельзя, а для «что это было за сообщение» хватает хоста и имени файла.
    """
    try:
        parts = urlsplit(url)
        name = (parts.path or "").rsplit("/", 1)[-1][:80]
        return f"{parts.hostname or ''}/{name}".strip("/")
    except Exception:  # noqa: BLE001 — диагностика не имеет права ломать распознавание
        return ""


async def _lock_acquire(key: str, token: str) -> bool | None:
    if not key or settings.state_backend != "redis":
        return None
    try:
        return bool(await _redis_client().set(
            key, token, nx=True, ex=settings.stt_lock_ttl_seconds
        ))
    except Exception:  # noqa: BLE001 — при сбое Redis продолжаем без распределённого lock
        return None


async def _lock_release(key: str, token: str) -> None:
    if not key or settings.state_backend != "redis":
        return
    try:
        client = _redis_client()
        # Не удаляем lock нового владельца, если наш TTL истёк во время медленного провайдера.
        if await client.get(key) == token:
            await client.delete(key)
    except Exception:  # noqa: BLE001 — TTL гарантирует выход даже при падении Redis
        return


async def _wait_for_cache(key: str) -> str:
    deadline = asyncio.get_running_loop().time() + settings.stt_timeout_seconds
    while True:
        found, transcript = await _cache_get(key)
        if found:
            return transcript
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return ""
        await asyncio.sleep(min(0.5, remaining))


def _audio_content_type(response_type: str, payload_mime: str) -> str:
    content_type = (response_type or payload_mime or "").strip().lower()
    if content_type.startswith("audio/") or content_type.startswith("application/ogg"):
        return content_type
    raise SttPermanentError("скачанный файл не является аудио")


def _metadata(*, transcript: str, provider: str, model: str, duration_sec: float,
              latency_ms: int, ok: bool, error: str, cost_usd: float, media_ref: str) -> dict[str, Any]:
    return {
        "transcript": transcript, "original_kind": "voice", "provider": provider,
        "model": model, "duration_sec": duration_sec, "latency_ms": latency_ms,
        "ok": ok, "error": error, "cost_usd": cost_usd, "media_ref": media_ref,
    }


async def transcribe(
    *, audio_url: str, mime: str, duration_sec: float, msg_id: str, bot_id: str,
    wappi_account: str = "unknown",
) -> str:
    """Вернуть чистый текст или пустую строку; сбой STT всегда деградирует в штатный non_text."""
    account = str(wappi_account or "unknown")
    cache_key = f"stt:{account}:{bot_id}:{msg_id}" if msg_id else ""
    lock_key = f"stt:lock:{account}:{bot_id}:{msg_id}" if msg_id else ""
    lock_token = uuid.uuid4().hex
    started = time.monotonic()
    acquired: bool | None = None
    provider_name = settings.stt_provider
    model = settings.stt_model
    result_duration = duration_sec
    cost_usd = 0.0
    await stt_metrics.note_received(bot_id)
    try:
        found, cached = await _cache_get(cache_key)
        if found:
            await stt_metrics.note_cache_hit(bot_id)
            await stt_metrics.check_and_trip(bot_id)
            return cached
        acquired = await _lock_acquire(lock_key, lock_token)
        if acquired is False:
            await stt_metrics.note_lock_wait(bot_id)
            cached = await _wait_for_cache(cache_key)
            await stt_metrics.check_and_trip(bot_id)
            return cached
        if not audio_url:
            raise SttPermanentError("в голосовом отсутствует ссылка на медиа")
        if duration_sec > settings.stt_max_duration_seconds:
            logger.info("STT пропущен: длительность %.1f с превышает лимит", duration_sec)
            raise SttPermanentError("голосовое превышает допустимую длительность")

        audio, response_type = await fetch_media(
            audio_url, max_bytes=settings.stt_max_bytes,
            timeout=settings.stt_download_timeout_seconds,
        )
        safe_mime = _audio_content_type(response_type, mime)
        provider = get_provider()
        provider_name = provider.name
        async with asyncio.timeout(settings.stt_timeout_seconds):
            result = await provider.transcribe(
                audio, filename="voice.ogg", mime=safe_mime,
                language_hint=settings.stt_language_hint,
            )
        text = result.text.strip()
        result_duration = result.duration_sec
        cost_usd = result.cost_usd
        model = result.model
        if result.duration_sec <= 0 and duration_sec > 0:
            result = replace(
                result, duration_sec=duration_sec,
                cost_usd=(duration_sec / 60.0) * settings.stt_cost_per_minute_usd,
            )
            result_duration, cost_usd = result.duration_sec, result.cost_usd
        await _cache_set(cache_key, _metadata(
            transcript=text, provider=result.provider, model=result.model,
            duration_sec=result.duration_sec, latency_ms=int((time.monotonic() - started) * 1000),
            ok=bool(text), error="" if text else "пустая транскрипция",
            cost_usd=result.cost_usd, media_ref=_media_ref(audio_url),
        ))
        latency_ms = int((time.monotonic() - started) * 1000)
        if not text:
            await stt_metrics.note_empty(bot_id, latency_ms=latency_ms,
                                         cost_usd=result.cost_usd, msg_id=msg_id)
            await stt_metrics.check_and_trip(bot_id)
            return ""
        await stt_metrics.note_success(
            bot_id, latency_ms=latency_ms, duration_sec=result.duration_sec,
            cost_usd=result.cost_usd, msg_id=msg_id,
        )
        await stt_metrics.check_and_trip(bot_id)
        observ.record_usage(
            f"stt/{result.provider}/{result.model}", 0, 0, result.cost_usd,
            bot_id, "", usage={"duration_sec": result.duration_sec},
        )
        logger.info("STT успешно: provider=%s длина=%s длительность=%.1f",
                    result.provider, len(text), result.duration_sec)
        return text
    except Exception as exc:  # noqa: BLE001 — голосовое всегда деградирует в штатный fallback
        # Сбой кэшируем НЕНАДОЛГО. Полный TTL здесь — ловушка: Wappi повторяет доставку
        # вебхука по таймауту, и недельная отметка «не получилось» навсегда закрыла бы
        # повторную попытку по тому же сообщению, хотя причина была разовой (обрыв, 5xx).
        # Короткого окна хватает, чтобы параллельные доставки не полезли скачивать разом.
        await _cache_set(cache_key, _metadata(
            transcript="", provider=provider_name, model=model, duration_sec=result_duration,
            latency_ms=int((time.monotonic() - started) * 1000), ok=False,
            error=type(exc).__name__, cost_usd=cost_usd, media_ref=_media_ref(audio_url),
        ), ttl=settings.stt_failure_cache_seconds)
        logger.warning("STT не выполнен: %s", type(exc).__name__)
        await stt_metrics.note_error(
            bot_id, latency_ms=int((time.monotonic() - started) * 1000),
            code=stt_metrics.error_code(exc),
        )
        await stt_metrics.check_and_trip(bot_id)
        return ""
    finally:
        if acquired is True:
            await _lock_release(lock_key, lock_token)
