"""ГЕЙТ: авария подтверждается несколькими пробами подряд (v3.1).

Написан ДО реализации. Гейт v3 (`tests/test_wappi_health.py`) НЕ редактируется: там
`Cfg` не задаёт `wappi_health_confirm_ticks`, и по умолчанию подтверждение = 1 проба,
то есть прежний контракт сохраняется. Подтверждение включается только настройкой.

Зачем. 07.08 в 12:54 по Бишкеку новый детектор прислал тревогу по getvisa — и она была
ЧЕСТНОЙ: Wappi в тот момент отдал нездоровый статус. Но уже через 34 секунды в том же
профиле `authorized_at` обновился на 09:54:39+03:00, то есть канал переавторизовался сам.

`authorized_at` у всех трёх профилей меняется по несколько раз в сутки. Значит короткие
провалы статуса — штатное поведение Wappi, а не авария. Будить владельца на 34 секунды,
которые чинятся сами, — это тот же алерт-фатиг, только с другой стороны: сигнал точный,
а действие бессмысленное.

Настоящий разлогин выглядит иначе: 03.08 визовый профиль лежал 12 часов.

Требуется от реализации:
    decide(...) читает `cfg.wappi_health_confirm_ticks` (дефолт 1) и бьёт тревогу о
    разлогине только когда столько проб ПОДРЯД показали нездоровый статус. Счётчик
    живёт в state и обнуляется на первой же здоровой пробе.
"""
from __future__ import annotations

NOW = 1_000_000.0
TICK = 300.0


class Cfg:
    wappi_health_enabled = True
    wappi_health_cooldown_minutes = 360
    wappi_payment_warn_days = 5
    wappi_health_confirm_ticks = 3


def _status(healthy: bool = True, **over) -> dict:
    base = {
        "app_status": "open" if healthy else "close",
        "authorized": healthy,
        "payment_expired_at": "2026-12-20T00:00:00Z",
        "profile_id": "2f099bc3-478d",
    }
    base.update(over)
    return base


def _ids(alerts) -> list[str]:
    return [bot_id for bot_id, _ in alerts]


def test_single_bad_probe_does_not_wake_the_owner():
    """Ровно случай 07.08 12:54: одна нездоровая проба, через полминуты всё само чинится."""
    from app.core.wappi_health import decide

    state: dict = {}
    assert decide(NOW, {"getvisa": _status(False)}, state, Cfg()) == []
    assert decide(NOW + TICK, {"getvisa": _status(True)}, state, Cfg()) == []


def test_alert_after_enough_consecutive_probes():
    """Настоящий разлогин держится. 03.08 визовый лежал 12 часов — три пробы по 5 минут
    он переживёт с огромным запасом."""
    from app.core.wappi_health import decide

    state: dict = {}
    broken = {"getvisa": _status(False)}

    assert decide(NOW, broken, state, Cfg()) == []
    assert decide(NOW + TICK, broken, state, Cfg()) == []
    assert _ids(decide(NOW + 2 * TICK, broken, state, Cfg())) == ["getvisa"]


def test_flapping_never_accumulates():
    """Мигание не должно копиться: между провалами статус здоров, счётчик обнуляется."""
    from app.core.wappi_health import decide

    state: dict = {}
    now = NOW
    for _ in range(5):
        assert decide(now, {"getvisa": _status(False)}, state, Cfg()) == []
        now += TICK
        assert decide(now, {"getvisa": _status(True)}, state, Cfg()) == []
        now += TICK


def test_recovery_resets_the_streak():
    """После настоящей аварии и починки новая авария снова требует подтверждения."""
    from app.core.wappi_health import decide

    state: dict = {}
    broken = {"getvisa": _status(False)}
    for i in range(3):
        decide(NOW + i * TICK, broken, state, Cfg())

    decide(NOW + 3 * TICK, {"getvisa": _status(True)}, state, Cfg())      # починили

    later = NOW + 100 * TICK                                              # cooldown прошёл
    assert decide(later, broken, state, Cfg()) == []
    assert decide(later + TICK, broken, state, Cfg()) == []
    assert _ids(decide(later + 2 * TICK, broken, state, Cfg())) == ["getvisa"]


def test_payment_warning_is_not_debounced():
    """Подписка — стабильный факт из даты, а не мигающий статус. Ждать проб незачем."""
    from app.core.wappi_health import decide

    # NOW — синтетический epoch, поэтому дату считаем ОТ него, а не пишем литералом.
    from datetime import datetime, timezone
    soon = datetime.fromtimestamp(NOW + 2 * 86400, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    alerts = decide(NOW, {"getvisa": _status(True, payment_expired_at=soon)}, {}, Cfg())
    assert _ids(alerts) == ["getvisa"]


def test_probes_are_counted_per_channel():
    """Провал одного канала не приближает тревогу по другому."""
    from app.core.wappi_health import decide

    state: dict = {}
    decide(NOW, {"getvisa": _status(False), "frunze_tours": _status(True)}, state, Cfg())
    decide(NOW + TICK, {"getvisa": _status(False), "frunze_tours": _status(True)}, state, Cfg())
    alerts = decide(NOW + 2 * TICK,
                    {"getvisa": _status(False), "frunze_tours": _status(False)}, state, Cfg())
    assert _ids(alerts) == ["getvisa"]


def test_production_settings_require_confirmation():
    """Продовая настройка обязана требовать подтверждения: одна проба не будит.

    Тест читает app.config.settings — если правку сделать только в docker-compose или
    только в config.py, гейт это заметит.
    """
    from app.config import settings
    from app.core.wappi_health import decide

    assert settings.wappi_health_confirm_ticks >= 2
    assert decide(NOW, {"getvisa": _status(False)}, {}, settings) == []
