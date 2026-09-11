# -*- coding: utf-8 -*-
"""Вырезание секретов из всего, что уходит в лог.

Зачем: половина наших ключей живёт прямо в URL. Вебхук Битрикса — это
`https://<портал>/rest/<id>/<ТОКЕН>/`, TourVisor принимает `authlogin`/`authpass`
параметрами запроса. `resp.raise_for_status()` кладёт URL целиком в текст исключения,
и одна ошибка портала печатает рабочий ключ в лог. Пока это так, перевыпуск ключа
ничего не даёт: следующая же 401 сдаст новый.

Фильтруем на выходе, а не в каждом месте вызова: точек, где секрет может всплыть
(текст ошибки, трейсбек, `repr` запроса, сторонняя библиотека), больше, чем мы способны
перечислить. Формат логов один — там и режем.
"""
from __future__ import annotations

import logging
import re
from urllib.parse import urlsplit

from app.config import settings

MASK = "***"
# Короткое значение в настройке (пустая строка, «kg», «1») — не секрет, а совпадение.
# Вырезать его из логов значит испортить их ради ничего.
_MIN_SECRET_LEN = 8

# Имена настроек, значение которых само по себе секрет.
_SECRET_SETTINGS = (
    "tourvisor_pass", "wappi_token", "openrouter_api_key", "anthropic_api_key",
    "stt_api_key", "telegram_bot_token", "managers_telegram_bot_token",
    "webhook_secret", "session_secret",
)


def _webhook_secrets() -> list[str]:
    """Токен из URL вебхука Битрикса: и сам URL, и отдельно его последний сегмент.

    Отдельно — потому что в тексте ошибки к базе приклеен метод
    (`.../<токен>/crm.lead.add.json`), и целиком базовый URL там уже не встречается.
    """
    url = str(getattr(settings, "bitrix24_webhook_url", "") or "").strip()
    if not url:
        return []
    out = [url.rstrip("/")]
    parts = [p for p in urlsplit(url).path.split("/") if p]
    out.extend(p for p in parts if len(p) >= _MIN_SECRET_LEN)
    return out


def secret_values() -> list[str]:
    """Все известные секреты, длинные — первыми (иначе короткий съест кусок длинного)."""
    values: list[str] = list(_webhook_secrets())
    for name in _SECRET_SETTINGS:
        value = str(getattr(settings, name, "") or "").strip()
        if len(value) >= _MIN_SECRET_LEN:
            values.append(value)
    for bot in list(getattr(settings, "telegram_bots", None) or []):
        token = str(getattr(bot, "token", "") or "").strip()
        if len(token) >= _MIN_SECRET_LEN:
            values.append(token)
    return sorted(set(values), key=len, reverse=True)


def redact(text: str) -> str:
    """Заменить все известные секреты в строке на `***`.

    Читаем настройки на каждом вызове: токен могут перевыпустить и подсунуть рестартом,
    а кэш тогда молча пропустит новый ключ в лог. Логов у нас единицы в секунду —
    цена десятка `str.replace` тут никакая.
    """
    out = str(text)
    for value in secret_values():
        if value in out:
            out = out.replace(value, MASK)
    # На случай ключа, о котором мы не знаем: параметр с говорящим именем в URL.
    return _QUERY_SECRET.sub(r"\1=" + MASK, out)


_QUERY_SECRET = re.compile(
    r"\b(authpass|password|api[_-]?key|access[_-]?token|token|secret)=[^&\s'\"]+",
    re.IGNORECASE,
)


class RedactingFormatter(logging.Formatter):
    """Форматтер, который режет секреты уже после сборки строки.

    Именно после: сообщение, аргументы и трейсбек склеиваются в одном месте, и это
    единственная точка, где виден весь текст, уходящий в stdout.
    """

    def format(self, record: logging.LogRecord) -> str:
        return redact(super().format(record))
