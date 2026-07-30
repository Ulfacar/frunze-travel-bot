"""Суточная квота TourVisor: счёт запросов и алерт до того, как поиск умрёт молча."""
import asyncio

import pytest

from app.config import ManagerConfig, settings
from app.integrations.tourvisor import quota

OWNERS = [
    ManagerConfig(login="grisha", password="x", admin=True,
                  telegram_chat_id="434859857"),
    ManagerConfig(login="ademi", password="x", telegram_chat_id="8707616744"),
]


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    quota._reset_for_tests()
    monkeypatch.setattr(settings, "state_backend", "memory")
    monkeypatch.setattr(settings, "managers", OWNERS)
    monkeypatch.setattr(settings, "tourvisor_daily_quota", 100)
    monkeypatch.setattr(settings, "tourvisor_quota_alert_ratio", 0.7)
    yield
    quota._reset_for_tests()


def _run(coro):
    return asyncio.run(coro)


def test_counts_calls():
    async def check():
        assert await quota.used_today() == 0
        await quota.note_call()
        await quota.note_call(4)
        assert await quota.used_today() == 5
    _run(check())


def test_zones():
    async def check():
        assert (await quota.status())["zone"] == "ok"
        await quota.note_call(70)
        snap = await quota.status()
        assert snap["zone"] == "warn" and snap["left"] == 30
        await quota.note_call(30)
        assert (await quota.status())["zone"] == "exhausted"
    _run(check())


def test_zero_limit_disables_tracking(monkeypatch):
    async def check():
        monkeypatch.setattr(settings, "tourvisor_daily_quota", 0)
        await quota.note_call(500)
        assert (await quota.status())["zone"] == "off"
    _run(check())


def test_alerts_owner_once_per_day(monkeypatch):
    sent = []

    async def spy(text):
        sent.append(text)
        return True

    async def check():
        monkeypatch.setattr(quota, "_notify_owners", spy)
        await quota.note_call(69)
        assert await quota.check_and_alert() is False      # порог не перешли
        await quota.note_call(1)
        assert await quota.check_and_alert() is True        # 70/100
        assert await quota.check_and_alert() is False       # второй раз за сутки молчим
        assert len(sent) == 1
        assert "квота поиска на исходе" in sent[0]
        assert "70%" in sent[0] and "осталось 30" in sent[0]
    _run(check())


def test_exhausted_alert_says_search_is_down(monkeypatch):
    sent = []

    async def spy(text):
        sent.append(text)
        return True

    async def check():
        monkeypatch.setattr(quota, "_notify_owners", spy)
        await quota.note_call(100)
        assert await quota.check_and_alert() is True
        assert "ИСЧЕРПАНА" in sent[0]
        assert "поиск временно недоступен" in sent[0]
    _run(check())


def test_failed_send_retries_next_tick(monkeypatch):
    calls = []

    async def failing(text):
        calls.append(text)
        return False

    async def check():
        monkeypatch.setattr(quota, "_notify_owners", failing)
        await quota.note_call(80)
        assert await quota.check_and_alert() is False
        assert await quota.check_and_alert() is False
        assert len(calls) == 2          # день не помечен → пробуем снова
    _run(check())


def test_only_admins_with_chat_id_are_notified(monkeypatch):
    pushed = []

    async def fake_push(token, chat_id, text):
        pushed.append(chat_id)
        return True

    async def check():
        import app.core.calendar_brief as cb
        monkeypatch.setattr(cb, "_token", lambda: "token")
        monkeypatch.setattr(cb, "_push_telegram", fake_push)
        assert await quota._notify_owners("тест") is True
        assert pushed == ["434859857"]        # только admin=True, Адеми не получает
    _run(check())


def test_counter_failure_never_breaks_search(monkeypatch):
    """Сбой счётчика не важнее подбора туров."""
    async def check():
        monkeypatch.setattr(settings, "state_backend", "redis")

        def boom():
            raise RuntimeError("redis недоступен")

        monkeypatch.setattr(quota, "_redis", boom)
        await quota.note_call()                 # не поднимает исключение
        assert await quota.used_today() == 0
    _run(check())


def test_client_counts_every_api_call(monkeypatch):
    """Счётчик стоит в единственной точке выхода в API — _call."""
    import httpx

    from app.integrations.tourvisor.client import TourVisorClient

    class _Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"ok": True}

    class _Client:
        async def get(self, url, params=None):
            return _Resp()

    async def check():
        c = TourVisorClient()
        await c._call(_Client(), "search", {})
        await c._call(_Client(), "result", {})
        assert await quota.used_today() == 2
        assert isinstance(httpx.AsyncClient, type)     # модуль на месте
    _run(check())
