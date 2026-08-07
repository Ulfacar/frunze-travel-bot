"""ГЕЙТ задачи «сторож каналов v2» (docs/task-channel-heartbeat-v2.md).

Написан ДО реализации и исполнителем НЕ редактируется. Кажется, что тест неверный —
остановись и спроси, не правь. Гейт v1 (tests/test_channel_heartbeat.py) обязан
остаться зелёным целиком: контракт `decide()` эта задача не меняет.

Три дефекта, найденные первым боевым срабатыванием 07.08.2026:

1. ГЛАВНЫЙ. Отметка живости пишется только в момент входящего, а `decide()` пропускает
   каналы без отметки. Канал, умерший ДО старта процесса, невидим навсегда — то есть
   сторож слеп ровно к тому состоянию, которое ищет. На проде 07.08 в слепой зоне был
   `frunze_tours_sezim`: 641 входящее за неделю, ключа в Redis нет.
2. Ночной порог (300 мин) равен длине нормальной ночной паузы → ложная тревога по
   живому каналу с 149 входящими в сутки.
3. Защёлка живёт в памяти процесса → деплой при длящейся аварии даёт дубль алерта.

Требуется от реализации (app/core/channel_heartbeat.py):

    merge_baseline(last_seen, baseline, now, max_age_seconds) -> dict[str, float | None]
        Чистая функция без I/O. Заполняет пустые отметки значениями из baseline,
        игнорируя слишком старые. Живую отметку не трогает.

    async _db_baseline(bot_ids) -> dict[str, float]
        Время последнего клиентского сообщения по каналу. Сбой БД → {}.

    async _state_load() / _state_save(state)
        Защёлка в хранилище, переживающая рестарт процесса.
"""
from __future__ import annotations

import asyncio

import pytest

DAY_HOUR = 14
NIGHT_HOUR = 3
NOW = 1_000_000.0
HOUR = 3600.0


def _run(coro):
    return asyncio.run(coro)


def _ago(minutes: float) -> float:
    return NOW - minutes * 60


def _ids(alerts) -> list[str]:
    return [bot_id for bot_id, _ in alerts]


# --- дефект 1: слепая зона ------------------------------------------------------

def test_channel_without_redis_mark_is_judged_by_db_history():
    """ГЛАВНЫЙ ТЕСТ. Кейс frunze_tours_sezim на 07.08: отметки в Redis нет, потому что
    с момента старта процесса по каналу не было входящих. История в БД есть.

    Если этот тест покраснеет — сторож снова не видит канал, который уже лежит.
    """
    from app.core.channel_heartbeat import decide, merge_baseline

    class Cfg:
        channel_heartbeat_enabled = True
        channel_silence_minutes = 180
        channel_silence_night_minutes = 420
        channel_alert_cooldown_minutes = 180
        channel_heartbeat_quiet_from = 22
        channel_heartbeat_quiet_to = 9

    last_seen = {"frunze_tours": _ago(2), "getvisa": _ago(5), "frunze_tours_sezim": None}
    baseline = {"frunze_tours_sezim": _ago(11 * 60)}   # последнее входящее 11 часов назад

    merged = merge_baseline(last_seen, baseline, NOW, max_age_seconds=7 * 24 * HOUR)

    assert merged["frunze_tours_sezim"] == pytest.approx(_ago(11 * 60))
    assert _ids(decide(NOW, merged, {}, Cfg(), bishkek_hour=DAY_HOUR)) == ["frunze_tours_sezim"]


def test_baseline_older_than_limit_is_ignored():
    """Канал без трафика неделю не «внезапно лёг», он выведен из работы. Вечный алерт
    по нему — тот же алерт-фатиг, от которого сторожа отключают."""
    from app.core.channel_heartbeat import merge_baseline

    merged = merge_baseline({"old_bot": None}, {"old_bot": NOW - 8 * 24 * HOUR}, NOW,
                            max_age_seconds=7 * 24 * HOUR)
    assert merged["old_bot"] is None


def test_baseline_never_overwrites_a_live_mark():
    """Отметка из Redis/памяти — настоящая и свежая. БД знает только про сообщения,
    записанные в лог, и обязана уступать."""
    from app.core.channel_heartbeat import merge_baseline

    merged = merge_baseline({"getvisa": _ago(3)}, {"getvisa": _ago(600)}, NOW,
                            max_age_seconds=7 * 24 * HOUR)
    assert merged["getvisa"] == pytest.approx(_ago(3))


def test_no_history_anywhere_stays_silent():
    """Ложноположительный, который обязан пройти: канала нет ни в Redis, ни в БД."""
    from app.core.channel_heartbeat import decide, merge_baseline

    class Cfg:
        channel_heartbeat_enabled = True
        channel_silence_minutes = 180
        channel_silence_night_minutes = 420
        channel_alert_cooldown_minutes = 180
        channel_heartbeat_quiet_from = 22
        channel_heartbeat_quiet_to = 9

    merged = merge_baseline({"new_bot": None}, {}, NOW, max_age_seconds=7 * 24 * HOUR)
    assert merged["new_bot"] is None
    assert decide(NOW, merged, {}, Cfg(), bishkek_hour=DAY_HOUR) == []


def test_db_failure_is_fail_open(monkeypatch):
    """Сбой БД не имеет права породить алерт «канал мёртв»: тревога из-за собственной
    недоступности обесценивает все остальные."""
    from app.core import channel_heartbeat

    def boom():
        raise RuntimeError("БД недоступна")

    monkeypatch.setattr(channel_heartbeat, "_sessionmaker_for_baseline", boom, raising=False)
    assert _run(channel_heartbeat._db_baseline(["getvisa"])) == {}


# --- дефект 2: пороги. Тест читает ПРОДОВЫЕ настройки, а не локальный Cfg -------

def test_regression_false_alarm_of_07_08():
    """07.08 в 07:23 по Бишкеку прилетел алерт по живому каналу: 5 часов ночной тишины
    при ночном пороге ровно в 5 часов. В 07:36 клиент написал сам, за сутки 149 входящих.

    ЧИСЛА ОБНОВЛЕНЫ 07.08 (docs/task-wappi-health-v3.md). Требование изменилось, тест не
    подгонялся под код: первый расчёт порогов в v2 был ошибочным — паузы относились к
    «дню» или «ночи» по часу прихода СЛЕДУЮЩЕГО сообщения, хотя сторож судит на каждом
    тике. Честная симуляция дала 2.5 ложных инцидента в сутки на порогах 180/420 вместо
    обещанных 0-1. Чувствительность перенесена на детектор, у которого ложных тревог нет
    по построению (app/core/wappi_health.py), а тишина оставлена предохранителем на 12 ч.

    Тест намеренно берёт настройки из app.config.settings: если правку порогов сделать
    только в docker-compose или только в config.py, гейт обязан это заметить.
    """
    from app.config import settings
    from app.core.channel_heartbeat import decide

    assert decide(NOW, {"getvisa": _ago(5 * 60)}, {}, settings, bishkek_hour=NIGHT_HOUR) == []
    assert decide(NOW, {"getvisa": _ago(8 * 60)}, {}, settings, bishkek_hour=NIGHT_HOUR) == []
    assert _ids(decide(NOW, {"getvisa": _ago(13 * 60)}, {}, settings,
                       bishkek_hour=NIGHT_HOUR)) == ["getvisa"]


def test_regression_daytime_lull_is_not_an_outage():
    """Днём пауза в 2 часа случалась 59 раз за 14 дней на трёх каналах — это дыхание
    трафика, а не авария. Настоящий простой днём начинается заметно позже.

    Числа обновлены вместе с предыдущим тестом и по той же причине: 5 часов дневной
    тишины по симуляции тоже дают ложную тревогу, а не аварию."""
    from app.config import settings
    from app.core.channel_heartbeat import decide

    assert decide(NOW, {"getvisa": _ago(120)}, {}, settings, bishkek_hour=DAY_HOUR) == []
    assert decide(NOW, {"getvisa": _ago(5 * 60)}, {}, settings, bishkek_hour=DAY_HOUR) == []
    assert _ids(decide(NOW, {"getvisa": _ago(13 * 60)}, {}, settings,
                       bishkek_hour=DAY_HOUR)) == ["getvisa"]


def test_twelve_hour_outage_still_alerts_with_production_settings():
    """Пороги подняли — авария 03.08 (12 часов разлогина) обязана ловиться по-прежнему,
    и днём, и ночью."""
    from app.config import settings
    from app.core.channel_heartbeat import decide

    for hour in (DAY_HOUR, NIGHT_HOUR):
        assert _ids(decide(NOW, {"getvisa": _ago(12 * 60)}, {}, settings,
                           bishkek_hour=hour)) == ["getvisa"]


# --- дефект 3: защёлка переживает рестарт ---------------------------------------

def test_latch_survives_restart(monkeypatch):
    """Канал лежит, деплой в середине аварии. Владельцу приходит ОДИН алерт, а не по
    одному на каждый рестарт: инцидент тот же самый."""
    from app.core import channel_heartbeat as hb

    stored: dict = {}
    sent: list[str] = []

    async def fake_load():
        return dict(stored)

    async def fake_save(state):
        stored.clear()
        stored.update(state)

    async def fake_last_seen():
        return {"getvisa": _ago(10 * 60)}

    async def fake_flag(_key, default=None):
        return True

    async def fake_send(text):
        sent.append(text)
        return True

    monkeypatch.setattr(hb, "_state_load", fake_load, raising=False)
    monkeypatch.setattr(hb, "_state_save", fake_save, raising=False)
    monkeypatch.setattr(hb, "_load_last_seen", fake_last_seen)
    monkeypatch.setattr(hb.flags, "get_flag", fake_flag)
    monkeypatch.setattr(hb, "_started_at", 0.0)

    from app.core import ops_alert
    monkeypatch.setattr(ops_alert, "send", fake_send)

    _run(hb.run())
    assert len(sent) == 1

    # рестарт процесса: память обнулилась, хранилище — нет
    hb._state.clear()
    hb._memory_last_seen.clear()
    monkeypatch.setattr(hb, "_started_at", 0.0)

    _run(hb.run())
    assert len(sent) == 1, "после рестарта пришёл дубль по тому же инциденту"
