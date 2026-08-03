"""Безопасная загрузка голосового из недоверенного webhook payload."""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.integrations.stt.base import SttPermanentError, SttTemporaryError


def _host_allowed(host: str) -> bool:
    allowed = [item.strip().lower().rstrip(".") for item in settings.stt_media_host_allowlist if item.strip()]
    return not allowed or any(host == item or host.endswith(f".{item}") for item in allowed)


async def _validate_url(url: str) -> None:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme.lower() != "https":
        raise SttPermanentError("медиа разрешено скачивать только по HTTPS")
    if not host or host == "localhost" or host.endswith(".local") or host == "metadata.google.internal":
        raise SttPermanentError("запрещённый хост медиа")
    if not _host_allowed(host):
        raise SttPermanentError("хост медиа отсутствует в allowlist")
    try:
        addresses = await asyncio.to_thread(socket.getaddrinfo, host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise SttTemporaryError("не удалось разрешить хост медиа") from exc
    if not addresses:
        raise SttTemporaryError("DNS не вернул адрес медиа")
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
                or ip.is_multicast or ip.is_unspecified):
            raise SttPermanentError("хост медиа указывает на служебный адрес")


async def fetch_media(url: str, *, max_bytes: int, timeout: float) -> tuple[bytes, str]:
    """Скачать ограниченный аудиофайл; каждый повтор остаётся на проверенном URL без редиректов."""
    await _validate_url(url)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
        for attempt in range(3):
            try:
                async with client.stream("GET", url) as response:
                    if 300 <= response.status_code < 400:
                        raise SttPermanentError("редирект медиа запрещён")
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt == 2:
                            raise SttTemporaryError(f"медиа-сервер временно ответил HTTP {response.status_code}")
                        await asyncio.sleep(0.7 * (2 ** attempt))
                        continue
                    if 400 <= response.status_code < 500:
                        raise SttPermanentError(f"медиа-сервер отклонил запрос: HTTP {response.status_code}")
                    chunks: list[bytes] = []
                    size = 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > max_bytes:
                            raise SttPermanentError("аудиофайл превышает допустимый размер")
                        chunks.append(chunk)
                    return b"".join(chunks), response.headers.get("content-type", "").split(";", 1)[0].strip()
            except (SttPermanentError, SttTemporaryError):
                raise
            except httpx.TransportError as exc:
                if attempt == 2:
                    raise SttTemporaryError("медиа-сервер недоступен") from exc
                await asyncio.sleep(0.7 * (2 ** attempt))
    raise SttTemporaryError("медиа-сервер не ответил")
