"""WP0: request/correlation id (X-Request-ID) behaviour + trust boundary."""
import logging
import re

from fastapi.testclient import TestClient
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core import observ
from app.main import app

_GENERATED = re.compile(r"^[0-9a-f]{32}$")  # uuid4().hex

# A trusted (loopback) peer may pass an inbound X-Request-ID; an untrusted peer
# (a non-loopback address) may not. TestClient sets scope["client"] to `client`.
trusted = TestClient(app, client=("127.0.0.1", 40000))
untrusted = TestClient(app, client=("203.0.113.7", 50000))  # TEST-NET, never dialed


def test_generates_request_id_when_absent():
    rid = trusted.get("/health").headers.get("X-Request-ID")
    assert rid and _GENERATED.match(rid)


def test_trusted_loopback_may_pass_valid_id():
    good = "abc-123.DEF_456"
    rid = trusted.get("/health", headers={"X-Request-ID": good}).headers.get("X-Request-ID")
    assert rid == good


def test_untrusted_peer_cannot_impose_id():
    rid = untrusted.get(
        "/health", headers={"X-Request-ID": "attacker-supplied-id"}
    ).headers.get("X-Request-ID")
    assert rid != "attacker-supplied-id"
    assert _GENERATED.match(rid)


def test_replaces_unsafe_id_even_from_trusted():
    rid = trusted.get(
        "/health", headers={"X-Request-ID": "bad id with spaces"}
    ).headers.get("X-Request-ID")
    assert rid != "bad id with spaces"
    assert _GENERATED.match(rid)


def test_replaces_too_long_id_even_from_trusted():
    long_id = "a" * 200
    rid = trusted.get("/health", headers={"X-Request-ID": long_id}).headers.get("X-Request-ID")
    assert rid != long_id
    assert _GENERATED.match(rid)


def test_response_always_contains_request_id():
    assert "X-Request-ID" in trusted.get("/health").headers


def test_contexts_are_isolated():
    a = trusted.get("/health").headers["X-Request-ID"]
    b = trusted.get("/health").headers["X-Request-ID"]
    assert a != b


def test_default_request_id_outside_request():
    assert observ.get_request_id() == "-"


def test_error_response_from_error_middleware_has_request_id():
    # A 404 is produced by Starlette's ExceptionMiddleware (inside our middleware),
    # so the error response still carries X-Request-ID.
    r = trusted.get("/no-such-route")
    assert r.status_code == 404
    assert "X-Request-ID" in r.headers


# --- context reset / isolation across an erroring request ----------------------
_seen: list[str] = []


async def _boom(request):
    _seen.append(observ.get_request_id())
    raise RuntimeError("boom")


async def _ok(request):
    _seen.append(observ.get_request_id())
    return PlainTextResponse("ok")


_err_app = Starlette(routes=[Route("/boom", _boom), Route("/ok", _ok)])
_err_app.add_middleware(observ.RequestIdMiddleware)
_err_client = TestClient(_err_app, client=("127.0.0.1", 1), raise_server_exceptions=False)


def test_contextvar_reset_and_isolated_after_exception():
    _seen.clear()
    r1 = _err_client.get("/boom", headers={"X-Request-ID": "err-id-1"})
    assert r1.status_code == 500
    r2 = _err_client.get("/ok", headers={"X-Request-ID": "ok-id-2"})
    assert r2.status_code == 200
    # Each request saw only its own id — the errored request's id did not leak into
    # the next request, and the context var is reset to the default outside requests.
    assert _seen == ["err-id-1", "ok-id-2"]
    assert observ.get_request_id() == "-"


def test_sanitize_helper():
    assert observ.sanitize_request_id("ok-1.2_3") == "ok-1.2_3"
    assert _GENERATED.match(observ.sanitize_request_id(None))
    assert _GENERATED.match(observ.sanitize_request_id(""))
    assert _GENERATED.match(observ.sanitize_request_id("has space"))
    assert _GENERATED.match(observ.sanitize_request_id("x" * 129))


def test_log_filter_injects_request_id():
    record = logging.LogRecord("t", logging.INFO, __file__, 1, "msg", None, None)
    assert observ.RequestIdLogFilter().filter(record) is True
    assert record.request_id == "-"
