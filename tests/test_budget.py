import asyncio
from datetime import datetime, timezone

from app.core import budget


def _reset_budget(monkeypatch):
    budget._MEM_SPEND.clear()
    monkeypatch.setattr(budget.settings, "state_backend", "memory")
    monkeypatch.setattr(budget, "_last_reported_status", None)


def test_estimate_cost_prices_models_by_tokens():
    haiku = budget.estimate_cost("anthropic/claude-haiku-4.5", 1_000_000, 1_000_000)
    sonnet = budget.estimate_cost("anthropic/claude-sonnet-4.6", 1_000_000, 1_000_000)

    assert haiku == 6.0
    assert sonnet == 18.0
    assert haiku < sonnet
    assert budget.estimate_cost("unknown-model", 1000, 2000) == 0.033


def test_budget_accumulates_and_switches_status(monkeypatch):
    _reset_budget(monkeypatch)
    monkeypatch.setattr(budget.settings, "llm_daily_budget_usd", 1.0)
    monkeypatch.setattr(budget.settings, "llm_daily_budget_soft_ratio", 0.8)

    async def scenario():
        assert await budget.status() == "ok"
        await budget.add_spend(0.79)
        assert await budget.status() == "ok"
        await budget.add_spend(0.01)
        assert await budget.status() == "soft"
        assert await budget.soft_capped() is True
        assert await budget.hard_capped() is False
        await budget.add_spend(0.20)
        assert await budget.status() == "hard"
        assert await budget.hard_capped() is True
        assert await budget.spend_today() == 1.0

    asyncio.run(scenario())


def test_budget_off_disables_caps(monkeypatch):
    _reset_budget(monkeypatch)
    monkeypatch.setattr(budget.settings, "llm_daily_budget_usd", 0.0)

    async def scenario():
        await budget.add_spend(10.0)
        assert await budget.status() == "off"
        assert await budget.soft_capped() is False
        assert await budget.hard_capped() is False

    asyncio.run(scenario())


def test_bishkek_day_uses_utc_plus_six():
    assert budget._bishkek_day(datetime(2026, 7, 1, 17, 59, tzinfo=timezone.utc)) == "2026-07-01"
    assert budget._bishkek_day(datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc)) == "2026-07-02"


def test_bishkek_day_start_utc_returns_local_midnight_in_utc():
    assert budget.bishkek_day_start_utc(
        datetime(2026, 7, 2, 5, 0, tzinfo=timezone.utc)
    ) == datetime(2026, 7, 1, 18, 0, tzinfo=timezone.utc)
