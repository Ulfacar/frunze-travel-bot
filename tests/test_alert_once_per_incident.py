"""ГЕЙТ: один инцидент — одно сообщение владельцу.

Написан ДО реализации. Гейты v1/v2/v3/v3.1 не редактируются: там пороги и cooldown
задаются локальным `Cfg`, здесь проверяется поведение и ПРОДОВЫЕ настройки.

Жалоба владельца 07.08: «сделай, чтобы мне одно и то же не приходило». Источников
повтора два, и оба наши:

1. Периодический повтор внутри одной аварии. Cooldown стоял 180 мин у сторожа тишины и
   360 у проверки Wappi — то есть за сутки простоя владелец получал 8 и 4 сообщения об
   одном и том же событии. Он уже знает; новой информации в повторе нет.
2. Два детектора об одном канале. Разлогин профиля означает и «Wappi говорит: отвалился»,
   и «входящих нет» — про один и тот же факт приходило два разных сообщения.

Требуется от реализации:
    channel_heartbeat.decide(..., reported=frozenset())
        Каналы из `reported` пропускаются молча: про них уже сказал другой детектор.
    Повторное сообщение по длящейся аварии помечается как напоминание и отличается
    от первого текстом.
"""
from __future__ import annotations

NOW = 1_000_000.0
DAY_HOUR = 14
HOUR = 3600.0


def _ago(minutes: float) -> float:
    return NOW - minutes * 60


def _ids(alerts) -> list[str]:
    return [bot_id for bot_id, _ in alerts]


def _is_reminder(text: str) -> bool:
    return "напомин" in text.lower()


# --- один инцидент — одно сообщение --------------------------------------------

def test_silence_watchdog_does_not_repeat_within_a_day():
    """Канал лежит сутки — это одно событие, а не восемь сообщений."""
    from app.config import settings
    from app.core.channel_heartbeat import decide

    state: dict = {}
    dead = {"getvisa": _ago(13 * 60)}

    assert _ids(decide(NOW, dead, state, settings, bishkek_hour=DAY_HOUR)) == ["getvisa"]
    for hours in (1, 3, 6, 11):
        assert decide(NOW + hours * HOUR, dead, state, settings,
                      bishkek_hour=DAY_HOUR) == [], f"повтор через {hours} ч"


def test_silence_reminder_differs_from_the_first_message():
    """Напоминание раз в сутки допустимо — но оно обязано читаться как напоминание,
    а не как новое событие, иначе это то же самое сообщение второй раз."""
    from app.config import settings
    from app.core.channel_heartbeat import decide

    state: dict = {}
    dead = {"getvisa": _ago(13 * 60)}

    first = decide(NOW, dead, state, settings, bishkek_hour=DAY_HOUR)[0][1]
    later = NOW + settings.channel_alert_cooldown_minutes * 60 + 1
    repeat = decide(later, {"getvisa": _ago(13 * 60)}, state, settings,
                    bishkek_hour=DAY_HOUR)

    assert _ids(repeat) == ["getvisa"]
    assert _is_reminder(repeat[0][1])
    assert not _is_reminder(first)


def test_wappi_check_does_not_repeat_within_a_day():
    from app.config import settings
    from app.core.wappi_health import decide

    state: dict = {}
    broken = {"getvisa": {"authorized": False, "app_status": "close",
                          "payment_expired_at": "2026-12-20T00:00:00Z"}}

    ticks = settings.wappi_health_confirm_ticks
    for _ in range(ticks - 1):
        assert decide(NOW, broken, state, settings) == []
    assert _ids(decide(NOW, broken, state, settings)) == ["getvisa"]

    for hours in (1, 3, 6, 11):
        assert decide(NOW + hours * HOUR, broken, state, settings) == [], \
            f"повтор через {hours} ч"


def test_production_cooldowns_are_at_least_half_a_day():
    """Числа живут в настройках и обязаны доехать до прода обоими путями."""
    from app.config import settings

    assert settings.channel_alert_cooldown_minutes >= 720
    assert settings.wappi_health_cooldown_minutes >= 720


# --- два детектора об одном канале ---------------------------------------------

def test_silence_stays_quiet_about_a_channel_wappi_already_reported():
    """Разлогин — это и «Wappi говорит: отвалился», и «входящих нет». Факт один,
    сообщение должно быть одно."""
    from app.config import settings
    from app.core.channel_heartbeat import decide

    dead = {"getvisa": _ago(13 * 60)}
    assert decide(NOW, dead, {}, settings, bishkek_hour=DAY_HOUR,
                  reported=frozenset({"getvisa"})) == []


def test_other_channels_are_unaffected_by_suppression():
    """Глушим ровно тот канал, про который уже сказали, и никакой другой."""
    from app.config import settings
    from app.core.channel_heartbeat import decide

    dead = {"getvisa": _ago(13 * 60), "frunze_tours_sezim": _ago(13 * 60)}
    assert _ids(decide(NOW, dead, {}, settings, bishkek_hour=DAY_HOUR,
                       reported=frozenset({"getvisa"}))) == ["frunze_tours_sezim"]


def test_suppression_defaults_to_nothing():
    """Без явного списка ведём себя как раньше: параметр не должен ничего ломать."""
    from app.config import settings
    from app.core.channel_heartbeat import decide

    assert _ids(decide(NOW, {"getvisa": _ago(13 * 60)}, {}, settings,
                       bishkek_hour=DAY_HOUR)) == ["getvisa"]


def test_suppressed_channel_can_alert_after_the_other_incident_closes():
    """Инцидент Wappi закрылся, а канал всё ещё молчит — это уже другая беда
    (профиль жив, вебхук не доходит), и про неё сказать обязаны."""
    from app.config import settings
    from app.core.channel_heartbeat import decide

    state: dict = {}
    dead = {"getvisa": _ago(13 * 60)}

    assert decide(NOW, dead, state, settings, bishkek_hour=DAY_HOUR,
                  reported=frozenset({"getvisa"})) == []
    assert _ids(decide(NOW + 600, dead, state, settings,
                       bishkek_hour=DAY_HOUR)) == ["getvisa"]


def test_open_incidents_reads_only_logout_latches():
    """Список «про что уже сказали» собирается из защёлок разлогина, а не из счётчиков
    проб и не из предупреждений о подписке."""
    from app.core.wappi_health import open_incidents_from_state

    state = {"logout:getvisa": NOW, "streak:frunze_tours": 2.0,
             "payment:frunze_tours_sezim": NOW}
    assert open_incidents_from_state(state) == {"getvisa"}
