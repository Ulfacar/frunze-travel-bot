"""WP0 automatic test network guard + external-network opt-in.

Blocks the real external in-process Python socket stack (DNS + TCP) so no test
can accidentally reach Wappi, Bitrix, OpenRouter, TourVisor, Telegram or any
other outside host. Loopback (127.0.0.1, ::1, localhost) stays allowed so the
in-process Starlette TestClient and the asyncio self-pipe keep working. Applied
automatically on import — no fixture and no new dependency required.

Scope note: the guard patches Python's `socket` module in-process only. It does
NOT block a subprocess / `curl` / `os.system` call — those run in another process
outside this interpreter and are out of WP0 scope.

A test that genuinely needs the real network must be marked
``@pytest.mark.external_network`` and run with ``--allow-external-network``.
Without that flag such tests are skipped. No ordinary (unmarked) test can
re-enable the network.
"""
from __future__ import annotations

import ipaddress
import socket

import pytest

from app.config import settings

_ALLOWED_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


@pytest.fixture(autouse=True)
def _neutralize_external_credentials(monkeypatch):
    """Hermetic default: blank TourVisor credentials so the tours funnel takes its
    offline/demo path instead of a real gateway call, regardless of the local
    `.env`. This is a deliberate belt-and-suspenders measure together with the
    socket guard below (which hard-blocks any accidental external call)."""
    monkeypatch.setattr(settings, "tourvisor_login", "", raising=False)
    monkeypatch.setattr(settings, "tourvisor_pass", "", raising=False)


# --- external-network opt-in (for future contract tests) -----------------------
def pytest_addoption(parser):
    parser.addoption(
        "--allow-external-network", action="store_true", default=False,
        help="Permit tests marked @pytest.mark.external_network to use real network.")


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "external_network: test needs real external network; skipped unless "
        "--allow-external-network is passed.")


def pytest_runtest_setup(item):
    if item.get_closest_marker("external_network") and not item.config.getoption(
            "--allow-external-network"):
        pytest.skip("needs --allow-external-network")


# --- socket guard --------------------------------------------------------------
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


def _install_guard() -> None:
    socket.socket.connect = _guard_connect
    socket.socket.connect_ex = _guard_connect_ex
    socket.create_connection = _guard_create_connection
    socket.getaddrinfo = _guard_getaddrinfo


def _restore_real() -> None:
    socket.socket.connect = _real_connect
    socket.socket.connect_ex = _real_connect_ex
    socket.create_connection = _real_create_connection
    socket.getaddrinfo = _real_getaddrinfo


# Install once at import (conftest loads before test modules).
_install_guard()


@pytest.fixture(autouse=True)
def _external_network_gate(request):
    """Lift the guard ONLY inside a test marked ``external_network`` AND only when
    ``--allow-external-network`` is set; restore it afterwards. An unmarked test can
    never re-enable the network (and a marked test without the flag is skipped)."""
    marked = request.node.get_closest_marker("external_network") is not None
    allowed = request.config.getoption("--allow-external-network")
    if marked and allowed:
        _restore_real()
        try:
            yield
        finally:
            _install_guard()
    else:
        yield
