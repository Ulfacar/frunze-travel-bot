"""Распознавание речи через OpenAI-совместимый multipart API."""
from __future__ import annotations

import asyncio

import httpx

from app.config import settings
from app.integrations.stt.base import SttPermanentError, SttTemporaryError, Transcript


class OpenAiTranscriptionProvider:
    name = "openai"

    async def transcribe(
        self, audio: bytes, *, filename: str, mime: str, language_hint: str = ""
    ) -> Transcript:
        if not settings.stt_api_key:
            raise SttPermanentError("не задан ключ STT-провайдера")
        data = {"model": settings.stt_model, "response_format": "json"}
        if language_hint:
            data["language"] = language_hint
        try:
            async with httpx.AsyncClient(timeout=settings.stt_timeout_seconds) as client:
                for attempt in range(3):
                    try:
                        response = await client.post(
                            f"{settings.stt_base_url.rstrip('/')}/audio/transcriptions",
                            headers={"Authorization": f"Bearer {settings.stt_api_key}"},
                            files={"file": (filename, audio, mime)},
                            data=data,
                        )
                    except httpx.TransportError as exc:
                        if attempt == 2:
                            raise SttTemporaryError("связь со STT-провайдером недоступна") from exc
                        await asyncio.sleep(0.7 * (attempt + 1))
                        continue
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 2:
                            raise SttTemporaryError(
                                f"STT-провайдер временно ответил HTTP {response.status_code}"
                            )
                        await asyncio.sleep(0.7 * (attempt + 1))
                        continue
                    if 400 <= response.status_code < 500:
                        raise SttPermanentError(
                            f"STT-провайдер отклонил запрос: HTTP {response.status_code}"
                        )
                    response.raise_for_status()
                    try:
                        payload = response.json()
                        text = str(payload.get("text") or "")
                        duration = float(payload.get("duration") or 0.0)
                    except (ValueError, TypeError) as exc:
                        raise SttPermanentError("STT-провайдер вернул некорректный JSON") from exc
                    return Transcript(
                        text=text,
                        provider=self.name,
                        model=settings.stt_model,
                        duration_sec=duration,
                        cost_usd=(duration / 60.0) * settings.stt_cost_per_minute_usd,
                    )
        except (SttTemporaryError, SttPermanentError):
            raise
        except httpx.HTTPError as exc:
            raise SttTemporaryError("сбой HTTP-клиента STT") from exc
        except Exception as exc:  # noqa: BLE001 — наружу выходит только контрактная ошибка
            raise SttPermanentError("не удалось обработать ответ STT-провайдера") from exc

        raise SttTemporaryError("STT-провайдер не ответил")
