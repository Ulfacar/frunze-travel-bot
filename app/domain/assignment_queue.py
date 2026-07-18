"""WP1B: deterministic round-robin selection of the next available VISA manager.

Two SEPARATE axes:

* **Eligibility** — who is on the visa team — comes from
  ``settings.visa_manager_roster`` (each has their own Bitrix account).
* **Availability** — temporary on/off — is read per manager from app_flags
  (``manager_off:<login>``). An unavailable manager is skipped; clearing the flag
  puts them straight back into the rotation.

This module ONLY selects the next manager. It does NOT auto-assign anyone: the
shadow bridge never calls it. Activating automatic assignment and making it
concurrency-safe with a PostgreSQL row lock are WP3 — the selection here is
deterministic but NOT a concurrency-safe production assignment on its own.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.flags import get_flag
from app.domain.models import Assignment

VISA_DIRECTION = "visa"

AvailabilityFn = Callable[[str], Awaitable[bool]]


async def default_is_available(login: str) -> bool:
    """A manager is available unless explicitly flagged off (``manager_off:<login>``)."""
    return not await get_flag(f"manager_off:{login}", False)


async def _latest_visa_assigned_at(session: AsyncSession, logins: list[str]) -> dict:
    """Map login → most recent visa ``assigned_at`` (active or historical)."""
    if not logins:
        return {}
    rows = (await session.execute(
        select(Assignment.manager_id, func.max(Assignment.assigned_at))
        .where(Assignment.direction == VISA_DIRECTION,
               Assignment.manager_id.in_(logins))
        .group_by(Assignment.manager_id))).all()
    return {manager_id: ts for manager_id, ts in rows}


async def select_next_visa_manager(session: AsyncSession, *,
                                   roster: list[str] | None = None,
                                   is_available: AvailabilityFn | None = None) -> str | None:
    """Return the next visa manager to receive a client, or None if none available.

    Deterministic least-recently-assigned policy: a manager never assigned in the
    visa direction wins first; otherwise the one whose most recent visa assignment
    is oldest. Ties break by roster order. Only the visa direction is considered, so
    a manager's tours history never affects visa rotation (no cross-team).
    """
    roster = list(roster if roster is not None else settings.visa_manager_roster)
    check = is_available or default_is_available

    available: list[str] = []
    for login in roster:
        if await check(login):
            available.append(login)
    if not available:
        return None

    latest = await _latest_visa_assigned_at(session, available)

    def _key(login: str):
        ts = latest.get(login)
        # never assigned → highest priority (0); else by oldest assigned_at.
        # Stable tie-break by roster position.
        if ts is None:
            return (0, 0.0, roster.index(login))
        return (1, ts.timestamp(), roster.index(login))

    return min(available, key=_key)
