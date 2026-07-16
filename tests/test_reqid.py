"""WP0: request/correlation id (X-Request-ID) behaviour."""
import re

from fastapi.testclient import TestClient

from app.core import observ
from app.main import app

client = TestClient(app)
_GENERATED = re.compile(r"^[0-9a-f]{32}$")  # uuid4().hex


def test_generates_request_id_when_absent():
    r = client.get("/health")
    rid = r.headers.get("X-Request-ID")
    assert rid and _GENERATED.match(rid)


def test_preserves_valid_incoming_id():
    good = "abc-123.DEF_456"
    r = client.get("/health", headers={"X-Request-ID": good})
    assert r.headers.get("X-Request-ID") == good


def test_replaces_unsafe_id():
    r = client.get("/health", headers={"X-Request-ID": "bad id with spaces"})
    rid = r.headers.get("X-Request-ID")
    assert rid != "bad id with spaces"
    assert _GENERATED.match(rid)


def test_replaces_too_long_id():
    long_id = "a" * 200
    r = client.get("/health", headers={"X-Request-ID": long_id})
    rid = r.headers.get("X-Request-ID")
    assert rid != long_id
    assert _GENERATED.match(rid)


def test_response_always_contains_request_id():
    r = client.get("/health")
    assert "X-Request-ID" in r.headers


def test_contexts_are_isolated():
    # Two requests without an inbound id get distinct generated ids → no shared context.
    a = client.get("/health").headers["X-Request-ID"]
    b = client.get("/health").headers["X-Request-ID"]
    assert a != b


def test_default_request_id_outside_request():
    # Outside any HTTP request the context var falls back to the neutral default.
    assert observ.get_request_id() == "-"


def test_sanitize_helper():
    assert observ.sanitize_request_id("ok-1.2_3") == "ok-1.2_3"
    assert _GENERATED.match(observ.sanitize_request_id(None))
    assert _GENERATED.match(observ.sanitize_request_id(""))
    assert _GENERATED.match(observ.sanitize_request_id("has space"))
    assert _GENERATED.match(observ.sanitize_request_id("x" * 129))


def test_log_filter_injects_request_id():
    import logging

    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    assert observ.RequestIdLogFilter().filter(record) is True
    assert record.request_id == "-"
