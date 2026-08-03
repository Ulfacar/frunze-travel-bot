"""Реестр STT-провайдеров: расширение не затрагивает канал и оркестратор."""
from __future__ import annotations

import logging
from collections.abc import Callable

from app.config import settings
from app.integrations.stt.base import SttPermanentError, TranscriptionProvider
from app.integrations.stt.openai_stt import OpenAiTranscriptionProvider

logger = logging.getLogger("stt.registry")

_PROVIDERS: dict[str, Callable[[], TranscriptionProvider]] = {
    "openai": OpenAiTranscriptionProvider,
}
_fallback_warned = False


def warn_fallback_configuration() -> None:
    """Один раз предупредить о неработающем заделе, чтобы конфигурация не вводила в заблуждение."""
    global _fallback_warned
    if settings.stt_fallback_provider and not _fallback_warned:
        logger.warning(
            "fallback-провайдер задан, но в этой версии не реализован — используется только основной"
        )
        _fallback_warned = True


def get_provider(name: str = "") -> TranscriptionProvider:
    warn_fallback_configuration()
    selected = (name or settings.stt_provider).strip().lower()
    factory = _PROVIDERS.get(selected)
    if factory is None:
        raise SttPermanentError(f"неизвестный STT-провайдер: {selected or '<пусто>'}")
    return factory()
