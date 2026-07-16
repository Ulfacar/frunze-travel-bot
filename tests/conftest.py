"""WP0 automatic test network guard.

Blocks real external DNS/TCP so no test can accidentally reach Wappi, Bitrix,
OpenRouter, TourVisor, Telegram or any other outside host. Loopback (127.0.0.1,
::1, localhost) stays allowed so the in-process Starlette TestClient and the
asyncio self-pipe keep working. Applied automatically on import — no fixture and
no new dependency required.
"""
from __future__ import annotations

import ipaddress
import socket

import pytest

from app.config import settings

_ALLOWED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost", ""}


@pytest.fixture(autouse=True)
def _neutralize_external_credentials(monkeypatch):
    """Make the suite hermetic: blank TourVisor credentials so the tours funnel
    takes its offline/demo path instead of a real gateway call, regardless of the
    developer's local `.env`. This mirrors a clean CI environment and pairs with
    the socket guard above (which hard-blocks any accidental external call)."""
    monkeypatch.setattr(settings, "tourvisor_login", "", raising=False)
    monkeypatch.setattr(settings, "tourvisor_pass", "", raising=False)


class BlockedNetworkError(RuntimeError):
    """Raised when a test attempts a real external network call."""


def _host_of(address) -> str:
    if isinstance(address, (tuple, list)) and address:
        return str(address[0])
    return str(address)


def _is_local(host: str) -> bool:
    if host in _ALLOWED_HOSTNAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False  # a real hostname (e.g. wappi.pro) → treat as external


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection
_real_getaddrinfo = socket.getaddrinfo


def _guard_connect(self, address, *args, **kwargs):
    host = _host_of(address)
    if not _is_local(host):
        raise BlockedNetworkError(
            f"WP0 guard: blocked external network connect to {host!r} during tests")
    return _real_connect(self, address, *args, **kwargs)


def _guard_connect_ex(self, address, *args, **kwargs):
    host = _host_of(address)
    if not _is_local(host):
        raise BlockedNetworkError(
            f"WP0 guard: blocked external connect_ex to {host!r} during tests")
    return _real_connect_ex(self, address, *args, **kwargs)


def _guard_create_connection(address, *args, **kwargs):
    host = _host_of(address)
    if not _is_local(host):
        raise BlockedNetworkError(
            f"WP0 guard: blocked external create_connection to {host!r} during tests")
    return _real_create_connection(address, *args, **kwargs)


def _guard_getaddrinfo(host, *args, **kwargs):
    if not _is_local(str(host)):
        raise BlockedNetworkError(
            f"WP0 guard: blocked external DNS resolve of {host!r} during tests")
    return _real_getaddrinfo(host, *args, **kwargs)


# Install once at import (conftest loads before test modules).
socket.socket.connect = _guard_connect
socket.socket.connect_ex = _guard_connect_ex
socket.create_connection = _guard_create_connection
socket.getaddrinfo = _guard_getaddrinfo
