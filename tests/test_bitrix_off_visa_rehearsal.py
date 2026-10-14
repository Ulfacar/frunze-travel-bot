"""B5 (14.10): репетиция «Bitrix выключен для виз».

A. «Визы — только чтение»: URL портала задан (туры живут), у визовых ботов ключи OFF →
   визовый трафик не делает ни одного обращения к порталу, туровый делает.
B. «Bitrix выключен совсем»: URL пуст → все джобы планировщика + реплей вебхука дают
   0 обращений к порталу и 0 предупреждений про Bitrix.
Сеть заглушена: любой httpx-запрос мгновенно падает ConnectError.
"""
import asyncio
import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import flags
from app.integrations.crm import bitrix_mirror, bitrix_pipeline
from app.integrations.crm.bitrix24 import Bitrix24Crm

VISA = "getvisa:996700000001"
TOURS = "frunze_tours:996700000002"


@pytest.fixture
def portal(monkeypatch):
    calls = []

    async def record(self, method, payload):
        calls.append(method)
        return {"result": []}
    monkeypatch.setattr(Bitrix24Crm, "_call", record)

    async def no_network(self, request, **kw):
        raise httpx.ConnectError("network disabled in rehearsal", request=request)
    monkeypatch.setattr(httpx.AsyncClient, "send", no_network)
    flags.reset()
    yield calls
    flags.reset()


class Conv:
    def __init__(self, key):
        self.user_id = key
        self.bot_id = key.partition(":")[0]


def test_a_visa_read_only_while_tours_keep_bitrix(portal, monkeypatch):
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix24_webhook_url", "https://portal.invalid/rest/1/x")
    for key, value in {"bitrix_mirror_enabled": True,
                       "bitrix_pipeline_enabled:frunze_tours": True,
                       "bitrix_mirror_enabled:getvisa": False, "bitrix_mirror_enabled:getvisa_tg": False,
                       "bitrix_pipeline_enabled:getvisa": False, "bitrix_pipeline_enabled:getvisa_tg": False}.items():
        asyncio.run(flags.set_flag(key, value))

    async def visa_traffic():
        await bitrix_mirror.mirror_message(VISA, sender="client", text="нужна виза", phone="996700000001",
                                           funnel="visa", bot_id="getvisa")
        await bitrix_mirror.mirror_message(VISA, sender="manager", text="ответ", phone="996700000001",
                                           funnel="visa")                     # bot из ключа диалога
        return await bitrix_mirror.resolve_lead_now("996700000001", "getvisa")
    assert asyncio.run(visa_traffic()) == ""
    assert asyncio.run(bitrix_pipeline._enabled(Conv(VISA))) is False
    assert portal == []

    asyncio.run(bitrix_mirror.mirror_message(TOURS, sender="client", text="тур", phone="996700000002",
                                             funnel="tours", bot_id="frunze_tours"))
    assert asyncio.run(bitrix_pipeline._enabled(Conv(TOURS))) is True
    assert portal, "туры не должны потерять Bitrix"


def test_a_default_without_per_bot_keys_is_unchanged(portal, monkeypatch):
    """Пока ключи по ботам не заданы, визы зеркалятся как раньше (поведение прода не меняется)."""
    monkeypatch.setattr(bitrix_mirror.settings, "bitrix24_webhook_url", "https://portal.invalid/rest/1/x")
    asyncio.run(flags.set_flag("bitrix_mirror_enabled", True))
    asyncio.run(bitrix_mirror.mirror_message(VISA, sender="client", text="x", phone="996700000001",
                                             funnel="visa", bot_id="getvisa"))
    assert portal


def test_b_bitrix_off_all_jobs_and_webhook_make_zero_portal_calls(portal, monkeypatch, caplog):
    import app.main as main
    from app.core import scheduler
    monkeypatch.setattr(main.settings, "bitrix24_webhook_url", "")
    monkeypatch.setattr(scheduler, "start", lambda: None)
    monkeypatch.setattr(scheduler, "_jobs", [])
    caplog.set_level(logging.WARNING)
    with TestClient(main.app):
        jobs = list(scheduler._jobs)
        assert len(jobs) >= 15, [n for n, _ in jobs]

        async def run_all():
            for name, job in jobs:
                try:
                    await asyncio.wait_for(job(), timeout=20)
                except Exception:  # noqa: BLE001 — сеть заглушена; важен только портал
                    pass
        asyncio.run(run_all())
    # Реплей вебхука визового клиента: зеркало/пайплайн не должны пойти в портал.
    from tests.test_manager_echo_capture import _incoming, _wire, _wrapped
    _wire(monkeypatch)
    TestClient(main.app).post("/webhook/wappi", json=_wrapped(_incoming(body="нужна виза в Китай")))
    asyncio.run(asyncio.sleep(0.05))
    assert portal == []
    bitrix_warnings = [r.getMessage() for r in caplog.records
                       if r.levelno >= logging.WARNING and ("bitrix" in r.getMessage().lower()
                                                            or "битрикс" in r.getMessage().lower()
                                                            or "bitrix" in r.name.lower())]
    assert bitrix_warnings == []
