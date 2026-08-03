"""Здоровье подбора туров: счётчик исходов + алерт владельцу.

Смысл модуля — чтобы поломка подбора не прожила ещё месяц незамеченной (31.07.2026: за
неделю 5 поисков, все пустые, мониторинг зелёный). Тут проверяем, что счётчик считает
исходы и что алерт срабатывает по доле пустых, а не по их количеству.
"""
import asyncio

from app.core import tours_health


def setup_function():
    tours_health._reset_for_tests()


def _status():
    return asyncio.run(tours_health.status())


def test_counts_outcomes_of_each_search():
    asyncio.run(tours_health.note("ok"))
    asyncio.run(tours_health.note("ok", fallback=True))
    asyncio.run(tours_health.note("nothing_found"))
    asyncio.run(tours_health.note("no_destination", has_dates=False))

    snap = _status()

    assert snap["total"] == 4
    assert snap["ok"] == 2
    assert snap["nothing_found"] == 1
    assert snap["no_destination"] == 1
    assert snap["fallback"] == 1
    assert snap["no_dates"] == 1
    assert snap["empty"] == 2


def test_missing_duration_is_counted_separately_from_searches():
    asyncio.run(tours_health.note("no_duration"))
    snap = _status()
    assert snap["no_duration"] == 1
    assert snap["total"] == 0
    assert snap["empty"] == 0


def test_small_sample_stays_quiet():
    """На двух поисках выводов не делаем — иначе алерт будет кричать каждое утро."""
    asyncio.run(tours_health.note("nothing_found"))
    asyncio.run(tours_health.note("nothing_found"))

    assert _status()["zone"] == "quiet"


def test_mostly_empty_searches_are_broken():
    """Ровно та картина, что была на проде: подборов достаточно, результата нет."""
    for _ in range(5):
        asyncio.run(tours_health.note("nothing_found"))

    snap = _status()

    assert snap["zone"] == "broken"
    assert snap["zero_ratio"] == 1.0


def test_healthy_search_does_not_alarm():
    for _ in range(5):
        asyncio.run(tours_health.note("ok"))
    asyncio.run(tours_health.note("nothing_found"))

    assert _status()["zone"] == "ok"


def test_alert_fires_once_per_day(monkeypatch):
    sent: list[str] = []

    async def fake_notify(text):
        sent.append(text)
        return True

    monkeypatch.setattr(tours_health, "_notify_owners", fake_notify)
    for _ in range(6):
        asyncio.run(tours_health.note("nothing_found"))

    assert asyncio.run(tours_health.check_and_alert()) is True
    assert asyncio.run(tours_health.check_and_alert()) is False  # повторно за сутки — молчим
    assert len(sent) == 1
    assert "Подбор туров возвращает пусто" in sent[0]


def test_no_alert_while_healthy(monkeypatch):
    monkeypatch.setattr(tours_health, "_notify_owners", lambda text: asyncio.sleep(0))
    for _ in range(6):
        asyncio.run(tours_health.note("ok"))

    assert asyncio.run(tours_health.check_and_alert()) is False


def test_counter_failure_never_breaks_search(monkeypatch):
    """Счётчик не важнее ответа клиенту: сбой хранилища гасим."""
    async def boom(_field):
        raise RuntimeError("redis down")

    monkeypatch.setattr(tours_health, "_incr", boom)

    asyncio.run(tours_health.note("ok"))  # не должно поднять исключение
