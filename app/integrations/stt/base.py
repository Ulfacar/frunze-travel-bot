"""Контракт STT-провайдеров, независимый от WhatsApp и бизнес-логики."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Transcript:
    text: str
    provider: str
    model: str
    duration_sec: float = 0.0
    cost_usd: float = 0.0


class SttError(Exception):
    """Базовая ожидаемая ошибка распознавания."""


class SttTemporaryError(SttError):
    """Временный сбой сети или провайдера, который допустимо повторить."""


class SttPermanentError(SttError):
    """Ошибка запроса или настройки, повтор которой не поможет."""


class TranscriptionProvider(Protocol):
    name: str

    async def transcribe(
        self, audio: bytes, *, filename: str, mime: str, language_hint: str = ""
    ) -> Transcript: ...
