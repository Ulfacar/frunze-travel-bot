"""ГЕЙТ задачи «сторож живости каналов» (per-channel heartbeat).

Написан ДО реализации и исполнителем НЕ редактируется. Кажется, что тест неверный —
остановись и спроси, не правь.

Зачем: 03.08 визовый WhatsApp лежал разлогиненным 12 часов, и алерта НЕ БЫЛО.
Существующий `watchdog.decide()` смотрит `observ.last_inbound_ago()` — АГРЕГАТ по всем
каналам. Пока хоть один канал жив, тишина никогда не срабатывает: агрегат маскирует
смерть части. При 66 лидах/день и 79% платного трафика 12 часов простоя канала — это
деньги, сожжённые в рекламе при нуле на приёме.

Человека в контуре нет вообще: сторож смотрит на факт входящих, а не на чью-то
дисциплину. Это единственный класс проверки, который в этой организации замыкается
сам (см. docs/venom-v2.md).

Требуется от реализации:
    app/core/channel_heartbeat.py
        decide(now, last_seen: dict[str, float], state: dict, cfg,
               *, bishkek_hour: int) -> list[tuple[str, str]]
            Чистая функция без I/O: (bot_id, текст алерта) для каналов, по которым
            пора бить тревогу. Мутирует state (защёлка/cooldown), как watchdog.decide.
        async note_inbound(bot_id) -> None      — отметить входящее по каналу
        async run() -> None                     — джоба планировщика
"""
from __future__ import annotations

import pytest

# Тихий час по Бишкеку: ночью трафик реально падает, порог мягче.
DAY_HOUR = 14
NIGHT_HOUR = 3

NOW = 1_000_000.0


class Cfg:
    """Пороги в настройках, а не в коде."""
    channel_heartbeat_enabled = True
    channel_silence_minutes = 90          # днём
    channel_silence_night_minutes = 300   # ночью (22:00–09:00 Бишкек)
    channel_alert_cooldown_minutes = 180
    channel_heartbeat_quiet_from = 22
    channel_heartbeat_quiet_to = 9


def _ago(minutes: float) -> float:
    return NOW - minutes * 60


def _ids(alerts) -> list[str]:
    return [bot_id for bot_id, _ in alerts]


# --- главный кейс: ровно та авария, которую агрегат пропустил -------------------

def test_dead_channel_alerts_even_when_others_are_busy():
    """03.08: визовый молчит 12 часов, туровые кипят. Старый сторож молчал.

    Это единственный тест, ради которого задача существует. Если он покраснеет —
    сторож снова слеп к смерти части.
    """
    from app.core.channel_heartbeat import decide

    last_seen = {
        "frunze_tours": _ago(2),        # жив
        "frunze_tours_sezim": _ago(5),  # жив
        "getvisa": _ago(12 * 60),       # МЁРТВ 12 часов
    }
    alerts = decide(NOW, last_seen, {}, Cfg(), bishkek_hour=DAY_HOUR)

    assert _ids(alerts) == ["getvisa"]
    assert "getvisa" in alerts[0][1]


def test_all_channels_alive_is_quiet():
    from app.core.channel_heartbeat import decide

    last_seen = {"frunze_tours": _ago(3), "getvisa": _ago(10)}
    assert decide(NOW, last_seen, {}, Cfg(), bishkek_hour=DAY_HOUR) == []


def test_every_dead_channel_is_named():
    """Молчат двое — алерт по обоим, а не «что-то не так»."""
    from app.core.channel_heartbeat import decide

    last_seen = {"frunze_tours": _ago(600), "getvisa": _ago(600),
                 "frunze_tours_sezim": _ago(1)}
    assert sorted(_ids(decide(NOW, last_seen, {}, Cfg(), bishkek_hour=DAY_HOUR))) == \
        ["frunze_tours", "getvisa"]


# --- ночь: тишина в 3 часа ночи — это норма, а не авария -----------------------

def test_night_silence_is_tolerated():
    """Порог мягче ночью. Иначе сторож будит владельца каждую ночь и его отключат —
    а отключённый сторож хуже отсутствующего."""
    from app.core.channel_heartbeat import decide

    last_seen = {"getvisa": _ago(120)}   # 2 часа тишины
    assert decide(NOW, last_seen, {}, Cfg(), bishkek_hour=NIGHT_HOUR) == []
    assert _ids(decide(NOW, last_seen, {}, Cfg(), bishkek_hour=DAY_HOUR)) == ["getvisa"]


def test_night_still_alerts_on_long_silence():
    """Ночь смягчает порог, но не отменяет его: 12 часов молчания — авария всегда."""
    from app.core.channel_heartbeat import decide

    last_seen = {"getvisa": _ago(12 * 60)}
    assert _ids(decide(NOW, last_seen, {}, Cfg(), bishkek_hour=NIGHT_HOUR)) == ["getvisa"]


# --- анти-дребезг --------------------------------------------------------------

def test_no_repeat_alert_while_still_dead():
    """Канал лежит сутки — это ОДИН инцидент, а не 288 сообщений по тику в 5 минут.
    Алерт-фатиг = следующий простой пропустят."""
    from app.core.channel_heartbeat import decide

    state: dict = {}
    last_seen = {"getvisa": _ago(200)}

    assert _ids(decide(NOW, last_seen, state, Cfg(), bishkek_hour=DAY_HOUR)) == ["getvisa"]
    assert decide(NOW + 300, last_seen, state, Cfg(), bishkek_hour=DAY_HOUR) == []
    assert decide(NOW + 600, last_seen, state, Cfg(), bishkek_hour=DAY_HOUR) == []


def test_recovery_rearms_the_alert():
    """Канал ожил и снова умер — про второй инцидент обязаны сказать."""
    from app.core.channel_heartbeat import decide

    state: dict = {}
    assert _ids(decide(NOW, {"getvisa": _ago(200)}, state, Cfg(), bishkek_hour=DAY_HOUR)) \
        == ["getvisa"]

    later = NOW + 10_000
    decide(later, {"getvisa": later - 60}, state, Cfg(), bishkek_hour=DAY_HOUR)  # ожил

    much_later = later + 100_000
    assert _ids(decide(much_later, {"getvisa": much_later - 200 * 60}, state, Cfg(),
                       bishkek_hour=DAY_HOUR)) == ["getvisa"]


def test_dead_channels_are_independent():
    """Защёлка на один канал не должна глушить алерт по другому."""
    from app.core.channel_heartbeat import decide

    state: dict = {}
    decide(NOW, {"getvisa": _ago(200), "frunze_tours": _ago(1)}, state, Cfg(),
           bishkek_hour=DAY_HOUR)
    alerts = decide(NOW + 300, {"getvisa": _ago(200), "frunze_tours": _ago(200)}, state,
                    Cfg(), bishkek_hour=DAY_HOUR)
    assert _ids(alerts) == ["frunze_tours"]


# --- ложные тревоги, которых быть не должно ------------------------------------

def test_channel_without_history_never_alerts():
    """Свежедобавленный бот и первые минуты после рестарта: истории нет.

    Алерт «канал мёртв» сразу после каждого деплоя — верный способ приучить
    владельца игнорировать сторожа.
    """
    from app.core.channel_heartbeat import decide

    assert decide(NOW, {}, {}, Cfg(), bishkek_hour=DAY_HOUR) == []
    assert decide(NOW, {"getvisa": None}, {}, Cfg(), bishkek_hour=DAY_HOUR) == []


def test_disabled_by_flag():
    from app.core.channel_heartbeat import decide

    cfg = Cfg()
    cfg.channel_heartbeat_enabled = False
    assert decide(NOW, {"getvisa": _ago(10_000)}, {}, cfg, bishkek_hour=DAY_HOUR) == []


def test_alert_text_says_how_long_and_what_to_do():
    """Алерт в 4 утра читают спросонья: сколько молчит и что открыть."""
    from app.core.channel_heartbeat import decide

    text = decide(NOW, {"getvisa": _ago(12 * 60)}, {}, Cfg(), bishkek_hour=DAY_HOUR)[0][1]
    assert "12" in text                       # длительность названа
    assert "getvisa" in text
    assert any(w in text.lower() for w in ("wappi", "qr", "авториз"))


# --- изоляция от старого сторожа -----------------------------------------------

def test_old_watchdog_untouched():
    """Старый агрегатный watchdog остаётся как есть: он ловит «легло ВСЁ», новый —
    «легла ЧАСТЬ». Это разные детекторы, один другого не заменяет."""
    from app.core.watchdog import decide as old_decide

    state = {"alert_silence_ts": 0.0, "alert_fail_ts": 0.0, "fail_baseline": 0.0}

    class OldCfg:
        alert_cooldown_minutes = 60
        alert_silence_minutes = 30
        alert_fail_threshold = 5

    alerts = old_decide(NOW, 60 * 60, {"llm_failures": 0, "send_failures": 0},
                        state, OldCfg())
    assert [reason for reason, _ in alerts] == ["silence"]
