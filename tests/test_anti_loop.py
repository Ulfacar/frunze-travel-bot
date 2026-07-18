"""WP2: anti-loop service — pure/deterministic three-level severity (M5)."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.anti_loop import (
    LoopAction, evaluate_inbound, evaluate_outbound, is_inbound_echo,
)

NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class Msg:
    direction: str
    body: str = ""
    provider_msg_id: str = ""
    idempotency_key: str = ""
    occurred_at: datetime = NOW


def _ago(seconds: int) -> datetime:
    return NOW - timedelta(seconds=seconds)


# --- exact echo / replay → SUPPRESS -------------------------------------------

def test_inbound_echo_of_our_outbound_is_suppressed():
    recent = [Msg("outbound", provider_msg_id="out-9")]
    assert is_inbound_echo(recent, "out-9") is True
    d = evaluate_inbound(recent, provider_msg_id="out-9")
    assert d.action is LoopAction.SUPPRESS and d.allow is False


def test_inbound_non_echo_is_allowed():
    recent = [Msg("outbound", provider_msg_id="out-9")]
    d = evaluate_inbound(recent, provider_msg_id="fresh-inbound-id")
    assert d.action is LoopAction.ALLOW and d.allow is True


def test_exact_provider_msg_id_replay_suppressed():
    recent = [Msg("outbound", body="hi", provider_msg_id="p-1", occurred_at=_ago(5))]
    d = evaluate_outbound(recent, body="hi again", now=NOW, candidate_provider_msg_id="p-1",
                          repeat_window_seconds=60, runaway_window_seconds=60,
                          runaway_max_outbound=5)
    assert d.action is LoopAction.SUPPRESS and d.reason == "replay_provider_msg_id"


def test_exact_idempotency_key_replay_suppressed():
    recent = [Msg("outbound", body="hi", idempotency_key="idem-1", occurred_at=_ago(5))]
    d = evaluate_outbound(recent, body="hi", now=NOW, candidate_idempotency_key="idem-1",
                          repeat_window_seconds=60, runaway_window_seconds=60,
                          runaway_max_outbound=5)
    assert d.action is LoopAction.SUPPRESS and d.reason == "replay_idempotency_key"


# --- duplicate body → WARN (still delivered) ----------------------------------

def test_identical_body_is_warn_not_suppress():
    recent = [Msg("outbound", body="Спасибо!", occurred_at=_ago(10))]
    d = evaluate_outbound(recent, body="Спасибо!", now=NOW, repeat_window_seconds=60,
                          runaway_window_seconds=60, runaway_max_outbound=5)
    assert d.action is LoopAction.WARN and d.reason == "duplicate_body"
    assert d.allow is True     # a legitimate repeated "Спасибо" is NOT blocked


# --- runaway burst → WARN (still delivered) -----------------------------------

def test_runaway_burst_is_warn_not_suppress():
    recent = [Msg("outbound", body=f"m{i}", occurred_at=_ago(i)) for i in range(5)]
    d = evaluate_outbound(recent, body="new", now=NOW, repeat_window_seconds=60,
                          runaway_window_seconds=60, runaway_max_outbound=5)
    assert d.action is LoopAction.WARN and d.reason == "runaway_outbound"
    assert d.allow is True


def test_inbound_in_window_clears_runaway():
    recent = [Msg("outbound", body=f"m{i}", occurred_at=_ago(i)) for i in range(5)]
    recent.append(Msg("inbound", body="client", occurred_at=_ago(2)))
    d = evaluate_outbound(recent, body="new", now=NOW, repeat_window_seconds=60,
                          runaway_window_seconds=60, runaway_max_outbound=5)
    assert d.action is LoopAction.ALLOW


# --- normal → ALLOW -----------------------------------------------------------

def test_normal_outbound_allowed():
    recent = [Msg("inbound", body="hi", occurred_at=_ago(5)),
              Msg("outbound", body="hello", occurred_at=_ago(4))]
    d = evaluate_outbound(recent, body="how can I help?", now=NOW,
                          repeat_window_seconds=60, runaway_window_seconds=60,
                          runaway_max_outbound=5)
    assert d.action is LoopAction.ALLOW and d.allow is True
