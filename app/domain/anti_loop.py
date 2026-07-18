"""WP2 anti-loop service — PURE, deterministic, three-level severity.

Returns one of:

* ``ALLOW``    — nothing suspicious;
* ``WARN``     — soft signal (identical body, runaway burst) — the caller MAY log
  it but MUST still deliver: legitimate repeats like "Спасибо" are never blocked;
* ``SUPPRESS`` — only for reliable signals: an exact provider-message-id echo, or an
  exact idempotency-key / provider-message-id replay.

No I/O and no clock reads: ``now`` and thresholds are passed in, so results are
fully reproducible. FOUNDATION service — NOT wired into the live send path (the
runtime still uses the in-memory ``own_outbound`` echo guard).

Message-like inputs are duck-typed: objects exposing ``direction``
('inbound'|'outbound'), ``body``, ``provider_msg_id``, optionally ``dedup_key`` /
``idempotency_key``, and ``occurred_at`` (tz-aware ``datetime``).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum


class LoopAction(str, Enum):
    ALLOW = "allow"
    WARN = "warn"
    SUPPRESS = "suppress"


@dataclass(frozen=True)
class LoopDecision:
    action: LoopAction
    reason: str = ""

    @property
    def allow(self) -> bool:
        """Deliver unless the action is a hard SUPPRESS (WARN still delivers)."""
        return self.action is not LoopAction.SUPPRESS


def is_inbound_echo(recent_messages, inbound_provider_msg_id: str) -> bool:
    """True if an inbound provider id equals one of OUR recent outbound ids — i.e. the
    channel echoed our own message back (durable analogue of own_outbound)."""
    if not inbound_provider_msg_id:
        return False
    for m in recent_messages:
        if (getattr(m, "direction", "") == "outbound"
                and getattr(m, "provider_msg_id", "") == inbound_provider_msg_id):
            return True
    return False


def evaluate_inbound(recent_messages, *, provider_msg_id: str = "") -> LoopDecision:
    """Hard-suppress an inbound that is our own echoed outbound; otherwise allow."""
    if is_inbound_echo(recent_messages, provider_msg_id):
        return LoopDecision(LoopAction.SUPPRESS, "echo_provider_msg_id")
    return LoopDecision(LoopAction.ALLOW)


def _idem_of(m) -> str:
    return getattr(m, "idempotency_key", "") or getattr(m, "dedup_key", "")


def evaluate_outbound(recent_messages, *, body: str, now: datetime,
                      candidate_provider_msg_id: str = "",
                      candidate_idempotency_key: str = "",
                      repeat_window_seconds: int, runaway_window_seconds: int,
                      runaway_max_outbound: int) -> LoopDecision:
    """Classify a candidate outbound.

    SUPPRESS only on an exact replay (same provider_msg_id or idempotency/action key
    as a prior outbound). Identical body and runaway bursts are WARN (still delivered)
    so ordinary repeats such as "Спасибо" are never blocked.
    """
    # 1) exact replay → hard suppress
    for m in recent_messages:
        if getattr(m, "direction", "") != "outbound":
            continue
        if (candidate_provider_msg_id
                and getattr(m, "provider_msg_id", "") == candidate_provider_msg_id):
            return LoopDecision(LoopAction.SUPPRESS, "replay_provider_msg_id")
        if candidate_idempotency_key and _idem_of(m) == candidate_idempotency_key:
            return LoopDecision(LoopAction.SUPPRESS, "replay_idempotency_key")

    # 2) identical body within window → WARN (still delivered)
    for m in recent_messages:
        if getattr(m, "direction", "") != "outbound":
            continue
        occurred = getattr(m, "occurred_at", None)
        if (getattr(m, "body", None) == body and occurred is not None
                and (now - occurred) <= timedelta(seconds=repeat_window_seconds)):
            return LoopDecision(LoopAction.WARN, "duplicate_body")

    # 3) runaway burst (>= N outbound, no inbound in window) → WARN (still delivered)
    window_start = now - timedelta(seconds=runaway_window_seconds)
    in_window = [m for m in recent_messages
                 if getattr(m, "occurred_at", None) is not None
                 and getattr(m, "occurred_at") >= window_start]
    outbound_ct = sum(1 for m in in_window if getattr(m, "direction", "") == "outbound")
    inbound_ct = sum(1 for m in in_window if getattr(m, "direction", "") == "inbound")
    if inbound_ct == 0 and outbound_ct >= runaway_max_outbound:
        return LoopDecision(LoopAction.WARN, "runaway_outbound")

    return LoopDecision(LoopAction.ALLOW)
