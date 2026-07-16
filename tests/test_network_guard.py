"""WP0: the automatic test network guard (tests/conftest.py)."""
import socket

import pytest

from fastapi.testclient import TestClient

from app.main import app


def test_external_tcp_create_connection_blocked():
    with pytest.raises(RuntimeError):
        socket.create_connection(("example.com", 80), timeout=1)


def test_external_socket_connect_blocked():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError):
            s.connect(("1.1.1.1", 80))
    finally:
        s.close()


def test_external_dns_resolve_blocked():
    for host in ("wappi.pro", "openrouter.ai", "tourvisor.ru"):
        with pytest.raises(RuntimeError):
            socket.getaddrinfo(host, 443)


def test_loopback_is_not_blocked():
    # The guard must let loopback through; a refused/timeout OSError is fine,
    # a RuntimeError would mean the guard wrongly blocked loopback.
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.2)
    try:
        s.connect(("127.0.0.1", 65000))
    except RuntimeError:
        pytest.fail("guard must not block loopback")
    except OSError:
        pass  # connection refused / timeout — guard allowed it through
    finally:
        s.close()


def test_testclient_still_works_under_guard():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_guard_is_applied_automatically():
    # No fixture is requested in this module; the block below proves the guard is
    # installed automatically by conftest import.
    with pytest.raises(RuntimeError):
        socket.getaddrinfo("bitrix24.example", 443)
