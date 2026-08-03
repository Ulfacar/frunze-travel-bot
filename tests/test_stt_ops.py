"""Операционный контур STT: Redis-метрики, независимый breaker, запуск и отчёт."""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.core import flags, stt_metrics


class FakeRedis:
    def __init__(self):
        self.values, self.hashes, self.lists = {}, {}, {}

    async def hincrbyfloat(self, key, field, value):
        row = self.hashes.setdefault(key, {})
        row[field] = float(row.get(field, 0)) + float(value)
        return row[field]

    async def hgetall(self, key): return dict(self.hashes.get(key, {}))
    async def expire(self, key, ttl): return True
    async def lpush(self, key, value): self.lists.setdefault(key, []).insert(0, value)
    async def ltrim(self, key, start, end): self.lists[key] = self.lists.get(key, [])[start:end + 1]
    async def lrange(self, key, start, end):
        rows = self.lists.get(key, [])
        return rows[start:] if end == -1 else rows[start:end + 1]
    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values: return False
        self.values[key] = value
        return True
    async def get(self, key): return self.values.get(key)
    async def delete(self, *keys):
        for key in keys:
            self.values.pop(key, None); self.hashes.pop(key, None); self.lists.pop(key, None)
    async def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]


@pytest.fixture(autouse=True)
def _redis_metrics(monkeypatch):
    redis = FakeRedis()
    flags.reset()
    monkeypatch.setattr(settings, "state_backend", "redis")
    monkeypatch.setattr(settings, "panel_backend", "memory")
    monkeypatch.setattr(stt_metrics, "_redis_client", redis)

    async def alert(text): return True
    monkeypatch.setattr("app.core.ops_alert.send", alert)
    return redis


def run(coro): return asyncio.run(coro)


def test_metrics_of_two_bots_do_not_mix():
    run(stt_metrics.note_received("frunze_tours"))
    run(stt_metrics.note_received("frunze_tours_sezim"))
    run(stt_metrics.note_received("frunze_tours_sezim"))
    assert run(stt_metrics.snapshot("frunze_tours"))["received"] == 1
    assert run(stt_metrics.snapshot("frunze_tours_sezim"))["received"] == 2


def test_three_errors_trip_only_bad_bot_and_do_not_touch_whatsapp():
    run(flags.set_flag("stt_enabled:frunze_tours", True))
    run(flags.set_flag("stt_enabled:frunze_tours_sezim", True))
    run(flags.set_flag("bots_enabled:frunze_tours", True))
    for _ in range(3):
        run(stt_metrics.note_error("frunze_tours", latency_ms=10, code="other"))
    assert run(stt_metrics.check_and_trip("frunze_tours"))
    assert run(flags.get_flag("stt_enabled:frunze_tours", True)) is False
    assert run(flags.get_flag("stt_enabled:frunze_tours_sezim", False)) is True
    assert run(flags.get_flag("bots_enabled:frunze_tours", False)) is True


def test_success_resets_error_streak():
    run(stt_metrics.note_error("frunze_tours", latency_ms=1, code="other"))
    run(stt_metrics.note_success("frunze_tours", latency_ms=1, duration_sec=1,
                                 cost_usd=.001, msg_id="ok-1"))
    assert run(stt_metrics.snapshot("frunze_tours"))["streak"] == 0


@pytest.mark.parametrize("code", ["401", "403", "insufficient_quota"])
def test_provider_fatal_errors_trip_immediately(code):
    run(flags.set_flag("stt_enabled:frunze_tours", True))
    run(stt_metrics.note_error("frunze_tours", latency_ms=1, code=code))
    assert run(stt_metrics.check_and_trip("frunze_tours"))
    assert run(flags.get_flag("stt_enabled:frunze_tours", True)) is False


def test_double_paid_message_trips():
    kwargs = dict(latency_ms=2, duration_sec=1, cost_usd=.001, msg_id="provider-1")
    assert run(stt_metrics.note_success("frunze_tours", **kwargs)) is False
    assert run(stt_metrics.note_success("frunze_tours", **kwargs)) is True
    assert run(stt_metrics.check_and_trip("frunze_tours"))


@pytest.mark.parametrize("received,should_trip", [(9, False), (10, True)])
def test_low_success_rate_respects_minimum_sample(received, should_trip):
    for index in range(received):
        run(stt_metrics.note_received("frunze_tours"))
        if index < 6:
            run(stt_metrics.note_success("frunze_tours", latency_ms=1, duration_sec=1,
                                         cost_usd=0, msg_id=f"m-{index}"))
    assert bool(run(stt_metrics.check_and_trip("frunze_tours"))) is should_trip


def test_high_p95_trips_after_five_received():
    for index, latency in enumerate((100, 200, 300, 400, 16001)):
        run(stt_metrics.note_received("frunze_tours"))
        run(stt_metrics.note_success("frunze_tours", latency_ms=latency, duration_sec=1,
                                     cost_usd=0, msg_id=f"p-{index}"))
    assert run(stt_metrics.check_and_trip("frunze_tours"))


def test_public_flag_bypasses_allowlist_and_owner_works_in_both_modes(monkeypatch):
    from app.channels.wappi import _stt_allowed
    monkeypatch.setattr(settings, "stt_enabled", True)
    monkeypatch.setattr(settings, "stt_api_key", "key")
    monkeypatch.setattr(settings, "stt_allowlist_phones", ["996555000111"])
    run(flags.set_flag("stt_public_enabled", False))
    assert run(_stt_allowed("frunze_tours", "996700000222")) is False
    assert run(_stt_allowed("frunze_tours", "996555000111")) is True
    run(flags.set_flag("stt_public_enabled", True))
    assert run(_stt_allowed("frunze_tours", "996700000222")) is True
    assert run(_stt_allowed("frunze_tours", "996555000111")) is True


def test_admin_stt_toggle_is_authorized_audited_and_isolated(monkeypatch):
    from app import main
    from app.integrations.panel import store as panel_store
    monkeypatch.setattr(settings, "state_backend", "memory")
    unauth = TestClient(main.app, base_url="https://testserver")
    assert unauth.post("/admin/bots/frunze_tours/stt-toggle", data={"on": "1"}).status_code == 401
    client = TestClient(main.app, base_url="https://testserver")
    assert client.post("/admin/login", data={"login": "admin", "password": "frunze"}).status_code == 200
    run(flags.set_flag("bots_enabled:frunze_tours", True))
    response = client.post("/admin/bots/frunze_tours/stt-toggle", data={"on": "1"})
    assert response.status_code == 200
    assert run(flags.get_flag("stt_enabled:frunze_tours", False)) is True
    assert run(flags.get_flag("bots_enabled:frunze_tours", False)) is True
    assert any("stt_enabled:frunze_tours=on" in row["detail"]
               for row in panel_store._memory_store._audit)


def test_failed_preflight_does_not_enable_public_and_sends_alert(monkeypatch):
    from scripts import stt_public_launch as launch
    sent = []
    async def bad(): return False, "Redis недоступен"
    async def alert(text): sent.append(text); return True
    monkeypatch.setattr(launch, "preflight", bad)
    monkeypatch.setattr(launch.ops_alert, "send", alert)
    assert run(launch.run()) is False
    assert run(flags.get_flag("stt_public_enabled", False)) is False
    assert sent and "Redis недоступен" in sent[0]


def test_zero_activity_report_is_honest(monkeypatch):
    from scripts import stt_hourly_report
    monkeypatch.setattr(settings, "state_backend", "memory")
    text = run(stt_hourly_report.build_report())
    assert text.count("голосовых не было") == 2


def test_metric_keys_never_contain_phone_or_media_url(_redis_metrics):
    run(stt_metrics.note_received("frunze_tours"))
    keys = " ".join([*_redis_metrics.hashes, *_redis_metrics.values, *_redis_metrics.lists])
    assert "996700123456" not in keys
    assert "https://" not in keys
