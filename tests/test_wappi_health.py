"""ГЕЙТ задачи «сторож каналов v3» (docs/task-wappi-health-v3.md).

Написан ДО реализации и исполнителем НЕ редактируется.

Зачем: гадание по тишине не имеет решения при любых порогах — молчащий живой канал и
мёртвый канал по этому признаку неразличимы. Честная симуляция на 21 сутках показала,
что даже пороги 180/420 из v2 оставляют 2.5 ложных инцидента в сутки.

При этом Wappi отвечает на вопрос точно: `GET /api/sync/get/status` отдаёт `authorized`
и `app_status`, а в поле `logouted_at` визового профиля стоит 03.08 09:06 — ровно та
авария, которую мы 12 часов не замечали.

Требуется от реализации (app/core/wappi_health.py):

    decide(now, statuses: dict[str, dict | None], state: dict, cfg) -> list[tuple[str, str]]
        Чистая функция без I/O. statuses: bot_id -> ответ Wappi (None = запрос не удался).
        Мутирует state (защёлка/cooldown), как decide в channel_heartbeat.

    async fetch_status(profile_id) -> dict | None
    async run() -> None
"""
from __future__ import annotations

NOW = 1_000_000.0


class Cfg:
    wappi_health_enabled = True
    wappi_health_cooldown_minutes = 360
    wappi_payment_warn_days = 5


def _ok(**over) -> dict:
    """Здоровый профиль — форма ответа списана с живого прода 07.08."""
    base = {
        "app_status": "open",
        "authorized": True,
        "authorized_at": "2026-08-07T02:40:35.189138+03:00",
        "logouted_at": "2026-08-03T09:06:44.904385+03:00",
        "payment_expired_at": "2026-12-20T00:00:00Z",
        "name": "GetVisa",
        "phone": "996706660009",
        "profile_id": "2f099bc3-478d",
    }
    base.update(over)
    return base


def _ids(alerts) -> list[str]:
    return [bot_id for bot_id, _ in alerts]


def _texts(alerts) -> str:
    return " | ".join(text for _, text in alerts)


# --- A. разлогин: сигнал, которого не хватало 03.08 -----------------------------

def test_unauthorized_profile_alerts():
    from app.core.wappi_health import decide

    alerts = decide(NOW, {"getvisa": _ok(authorized=False)}, {}, Cfg())

    assert _ids(alerts) == ["getvisa"]
    text = alerts[0][1].lower()
    assert "getvisa" in text
    assert "qr" in text or "авториз" in text


def test_closed_app_alerts_even_when_authorized():
    """Профиль привязан, но приложение легло — сообщения до нас не дойдут так же."""
    from app.core.wappi_health import decide

    assert _ids(decide(NOW, {"getvisa": _ok(app_status="close")}, {}, Cfg())) == ["getvisa"]


def test_healthy_profile_is_quiet_no_matter_the_silence():
    """ГЛАВНЫЙ ложноположительный. Канал может молчать сутки — если Wappi говорит
    «авторизован и открыт», это тишина, а не авария. Ровно здесь ломался детектор
    по тишине: он поднимал тревогу по живому каналу с 149 входящими в сутки."""
    from app.core.wappi_health import decide

    assert decide(NOW, {"getvisa": _ok(), "frunze_tours": _ok()}, {}, Cfg()) == []


def test_failed_request_is_fail_open():
    """Wappi недоступен → молчим. Тревога из-за собственной сетевой ошибки
    обесценивает все остальные."""
    from app.core.wappi_health import decide

    assert decide(NOW, {"getvisa": None}, {}, Cfg()) == []


def test_every_broken_channel_is_named():
    from app.core.wappi_health import decide

    statuses = {"getvisa": _ok(authorized=False), "frunze_tours": _ok(),
                "frunze_tours_sezim": _ok(app_status="close")}
    assert sorted(_ids(decide(NOW, statuses, {}, Cfg()))) == ["frunze_tours_sezim", "getvisa"]


# --- B. подписка ---------------------------------------------------------------

def test_expiring_payment_warns():
    """У getvisa подписка до 20.08. Отвалившаяся подписка убивает канал молча —
    это уже было с TourVisor 06.07."""
    from app.core.wappi_health import decide

    soon = NOW + 3 * 24 * 3600
    alerts = decide(NOW, {"getvisa": _ok(payment_expired_at=_iso(soon))}, {}, Cfg())

    assert _ids(alerts) == ["getvisa"]
    assert "подпис" in alerts[0][1].lower() or "оплат" in alerts[0][1].lower()


def test_distant_payment_is_quiet():
    from app.core.wappi_health import decide

    far = NOW + 30 * 24 * 3600
    assert decide(NOW, {"getvisa": _ok(payment_expired_at=_iso(far))}, {}, Cfg()) == []


def test_broken_payment_date_does_not_crash_or_alert():
    from app.core.wappi_health import decide

    for bad in ("", None, "не дата", "2026-13-45"):
        assert decide(NOW, {"getvisa": _ok(payment_expired_at=bad)}, {}, Cfg()) == []


def test_real_wappi_date_formats_are_parsed():
    """Формат с прода: 'Z' у payment_expired_at и '+03:00' у остальных полей."""
    from app.core.wappi_health import parse_wappi_time

    assert parse_wappi_time("2026-08-20T00:00:00Z") is not None
    assert parse_wappi_time("2026-08-03T09:06:44.904385+03:00") is not None
    assert parse_wappi_time("мусор") is None
    assert parse_wappi_time(None) is None


# --- защёлка и независимость поводов -------------------------------------------

def test_logout_and_payment_are_separate_reasons():
    """Разлогин и кончающаяся подписка — разные поводы: защёлка одного не смеет
    заглушить другой, иначе про второй мы узнаем постфактум."""
    from app.core.wappi_health import decide

    state: dict = {}
    soon = _iso(NOW + 2 * 24 * 3600)

    assert _ids(decide(NOW, {"getvisa": _ok(authorized=False)}, state, Cfg())) == ["getvisa"]
    alerts = decide(NOW + 60, {"getvisa": _ok(authorized=False, payment_expired_at=soon)},
                    state, Cfg())
    assert _ids(alerts) == ["getvisa"]
    assert "подпис" in _texts(alerts).lower() or "оплат" in _texts(alerts).lower()


def test_one_incident_one_alert():
    from app.core.wappi_health import decide

    state: dict = {}
    broken = {"getvisa": _ok(authorized=False)}

    assert _ids(decide(NOW, broken, state, Cfg())) == ["getvisa"]
    assert decide(NOW + 300, broken, state, Cfg()) == []
    assert decide(NOW + 3600, broken, state, Cfg()) == []


def test_reminder_after_cooldown():
    from app.core.wappi_health import decide

    state: dict = {}
    broken = {"getvisa": _ok(authorized=False)}

    decide(NOW, broken, state, Cfg())
    later = NOW + Cfg.wappi_health_cooldown_minutes * 60 + 1
    assert _ids(decide(later, broken, state, Cfg())) == ["getvisa"]


def test_recovery_rearms():
    """Канал починили и он снова лёг — про второй инцидент обязаны сказать сразу,
    не дожидаясь cooldown."""
    from app.core.wappi_health import decide

    state: dict = {}
    decide(NOW, {"getvisa": _ok(authorized=False)}, state, Cfg())
    decide(NOW + 60, {"getvisa": _ok()}, state, Cfg())              # починили
    assert _ids(decide(NOW + 120, {"getvisa": _ok(authorized=False)}, state, Cfg())) \
        == ["getvisa"]


def test_disabled_by_flag():
    from app.core.wappi_health import decide

    cfg = Cfg()
    cfg.wappi_health_enabled = False
    assert decide(NOW, {"getvisa": _ok(authorized=False)}, {}, cfg) == []


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
