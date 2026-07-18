"""WP2: anti-loop service — pure/deterministic, no DB, no clock reads."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.domain.anti_loop import evaluate_outbound, is_inbound_echo

NOW = datetime(2026, 7, 18, 12, 0, 0, tzinfo=timezone.utc)


@dataclass
class Msg:
    direction: str
    body: str = ""
    provider_msg_id: str = ""
    occurred_at: datetime = NOW


def _ago(seconds: int) -> datetime:
    return NOW - timedelta(seconds=seconds)


# --- echo ---------------------------------------------------------------------

def test_inbound_echo_detected_when_matches_our_outbound():
    recent = [Msg("outbound", provider_msg_id="out-9")]
    assert is_inbound_echo(recent, "out-9") is True


def test_inbound_not_echo_for_unknown_id_or_empty():
    recent = [Msg("outbound", provider_msg_id="out-9")]
    assert is_inbound_echo(recent, "other") is False
    assert is_inbound_echo(recent, "") is False


# --- duplicate outbound -------------------------------------------------------

def test_identical_outbound_within_window_suppressed():
    recent = [Msg("outbound", body="привет", occurred_at=_ago(10))]
    d = evaluate_outbound(recent, body="привет", now=NOW, repeat_window_seconds=60,
                          runaway_window_seconds=60, runaway_max_outbound=5)
    assert d.allow is False and d.reason == "duplicate_outbound"


def test_identical_outbound_outside_window_allowed():
    recent = [Msg("outbound", body="привет", occurred_at=_ago(120))]
    d = evaluate_outbound(recent, body="привет", now=NOW, repeat_window_seconds=60,
                          runaway_window_seconds=60, runaway_max_outbound=5)
    assert d.allow is True


# --- runaway ------------------------------------------------------------------

def test_runaway_burst_without_inbound_suppressed():
    recent = [Msg("outbound", body=f"m{i}", occurred_at=_ago(i)) for i in range(5)]
    d = evaluate_outbound(recent, body="new", now=NOW, repeat_window_seconds=60,
                          runaway_window_seconds=60, runaway_max_outbound=5)
    assert d.allow is False and d.reason == "runaway_outbound"


def test_inbound_in_window_resets_runaway():
    recent = [Msg("outbound", body=f"m{i}", occurred_at=_ago(i)) for i in range(5)]
    recent.append(Msg("inbound", body="client", occurred_at=_ago(2)))
    d = evaluate_outbound(recent, body="new", now=NOW, repeat_window_seconds=60,
                          runaway_window_seconds=60, runaway_max_outbound=5)
    assert d.allow is True


def test_normal_outbound_allowed():
    recent = [Msg("inbound", body="hi", occurred_at=_ago(5)),
              Msg("outbound", body="hello", occurred_at=_ago(4))]
    d = evaluate_outbound(recent, body="how can I help?", now=NOW,
                          repeat_window_seconds=60, runaway_window_seconds=60,
                          runaway_max_outbound=5)
    assert d.allow is True and d.reason == ""
