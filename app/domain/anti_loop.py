"""WP2 anti-loop service — PURE and deterministic.

Given a slice of recent messages and a candidate, decide whether emitting it
would create a loop. No I/O, no clock reads: ``now`` and all thresholds are
passed in, so the result is fully reproducible and unit-testable.

This is a FOUNDATION service — it is NOT wired into the live send path. The
runtime still relies on the existing in-memory ``own_outbound`` echo guard.

Message-like inputs are duck-typed: any object exposing ``direction``
('inbound'|'outbound'), ``body``, ``provider_msg_id`` and ``occurred_at``
(tz-aware ``datetime``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class LoopDecision:
    allow: bool
    reason: str = ""


def is_inbound_echo(recent_messages, inbound_provider_msg_id: str) -> bool:
    """True if an inbound provider id matches one of OUR recent outbound ids — i.e.
    the channel echoed our own message back to us (durable analogue of own_outbound)."""
    if not inbound_provider_msg_id:
        return False
    for m in recent_messages:
        if (getattr(m, "direction", "") == "outbound"
                and getattr(m, "provider_msg_id", "") == inbound_provider_msg_id):
            return True
    return False


def evaluate_outbound(recent_messages, *, body: str, now: datetime,
                      repeat_window_seconds: int, runaway_window_seconds: int,
                      runaway_max_outbound: int) -> LoopDecision:
    """Suppress an identical outbound within the repeat window, or a runaway burst
    (>= N outbound with no inbound inside the runaway window)."""
    for m in recent_messages:
        if getattr(m, "direction", "") != "outbound":
            continue
        occurred = getattr(m, "occurred_at", None)
        if (getattr(m, "body", None) == body and occurred is not None
                and (now - occurred) <= timedelta(seconds=repeat_window_seconds)):
            return LoopDecision(False, "duplicate_outbound")

    window_start = now - timedelta(seconds=runaway_window_seconds)
    in_window = [m for m in recent_messages
                 if getattr(m, "occurred_at", None) is not None
                 and getattr(m, "occurred_at") >= window_start]
    outbound_ct = sum(1 for m in in_window if getattr(m, "direction", "") == "outbound")
    inbound_ct = sum(1 for m in in_window if getattr(m, "direction", "") == "inbound")
    if inbound_ct == 0 and outbound_ct >= runaway_max_outbound:
        return LoopDecision(False, "runaway_outbound")

    return LoopDecision(True, "")
