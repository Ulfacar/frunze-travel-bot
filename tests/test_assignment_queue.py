"""WP1B: deterministic round-robin selection of the next available visa manager.
Selection ONLY — no auto-assignment. In-memory SQLite; WP0 guard active."""
import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core import flags
from app.domain.assignment_queue import default_is_available, select_next_visa_manager
from app.domain.models import Assignment, Contact


def run_with_db(scenario):
    async def _main():
        engine = create_async_engine(
            "sqlite+aiosqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        async with engine.begin() as conn:
            from app.domain.models import DomainBase
            await conn.run_sync(DomainBase.metadata.create_all)
        sm = async_sessionmaker(engine, expire_on_commit=False)
        try:
            await scenario(sm)
        finally:
            await engine.dispose()

    asyncio.run(_main())


def _dt(minute: int) -> datetime:
    return datetime(2026, 7, 18, 10, minute, tzinfo=timezone.utc)


async def _assign(session, contact_id, manager_id, direction, minute, *, active=True):
    session.add(Assignment(contact_id=contact_id, direction=direction,
                           manager_id=manager_id, active=active,
                           assigned_at=_dt(minute)))
    await session.flush()


ROSTER = ["medina", "eliza"]


async def _all_available(_login):  # test injection: everyone available
    return True


def test_never_assigned_picks_first_in_roster_order():
    async def scenario(sm):
        async with sm() as s:
            m = await select_next_visa_manager(s, roster=ROSTER, is_available=_all_available)
            assert m == "medina"
    run_with_db(scenario)


def test_least_recently_assigned_wins():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            await _assign(s, c.id, "medina", "visa", minute=5)
            # medina just got one; eliza never did → eliza is next.
            assert await select_next_visa_manager(
                s, roster=ROSTER, is_available=_all_available) == "eliza"
            await _assign(s, c.id, "eliza", "visa", minute=6, active=False)
            # both assigned; medina's (min 5) is older than eliza's (min 6) → medina.
            assert await select_next_visa_manager(
                s, roster=ROSTER, is_available=_all_available) == "medina"
    run_with_db(scenario)


def test_unavailable_manager_skipped_then_returns():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            # eliza just assigned (recent) but medina is OFF → eliza chosen anyway.
            await _assign(s, c.id, "eliza", "visa", minute=5)

            async def medina_off(login):
                return login != "medina"

            assert await select_next_visa_manager(
                s, roster=ROSTER, is_available=medina_off) == "eliza"
            # medina returns to availability → back in rotation and wins (never assigned).
            assert await select_next_visa_manager(
                s, roster=ROSTER, is_available=_all_available) == "medina"
    run_with_db(scenario)


def test_none_available_returns_none():
    async def scenario(sm):
        async with sm() as s:
            async def nobody(_login):
                return False
            assert await select_next_visa_manager(
                s, roster=ROSTER, is_available=nobody) is None
    run_with_db(scenario)


def test_tours_history_does_not_affect_visa_rotation():
    async def scenario(sm):
        async with sm() as s:
            c = Contact(); s.add(c); await s.flush()
            # medina has a recent TOURS assignment — must NOT count against visa turn.
            await _assign(s, c.id, "medina", "tours", minute=9)
            # Both have zero visa history → roster order → medina first.
            assert await select_next_visa_manager(
                s, roster=ROSTER, is_available=_all_available) == "medina"
    run_with_db(scenario)


def test_default_availability_reads_app_flags():
    async def scenario(sm):
        flags.reset()
        async with sm() as s:
            assert await default_is_available("medina") is True
            await flags.set_flag("manager_off:medina", True)
            assert await default_is_available("medina") is False
            # With medina flagged off (via default provider), eliza is selected.
            assert await select_next_visa_manager(s, roster=ROSTER) == "eliza"
            await flags.set_flag("manager_off:medina", False)
            assert await default_is_available("medina") is True
        flags.reset()
    run_with_db(scenario)
