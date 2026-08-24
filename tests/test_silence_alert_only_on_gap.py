"""ГЕЙТ: тишина будит человека только когда она означает поломку.

Написан ДО реализации и исполнителем НЕ редактируется.

## Замер, из которого выросла задача (прод, 23-24.08.2026)

Владелец получал красные тревоги четыре раза за трое суток при полностью здоровых
каналах (`authorized=True, app_status=open`, QR держится третьи сутки):

    23.08 07:31  🔴 Канал frunze_tours_sezim (Айсина) молчит 12 ч
    23.08 15:00  🔴 Канал getvisa (Медина) молчит 12 ч
    24.08 08:12  🔴 Канал frunze_tours (Адеми) молчит 12 ч
    24.08 08:28  🔴 Канал frunze_tours_sezim (Айсина) молчит 12 ч

Три из четырёх — сразу после ночи. Порог тишины 720 минут, а клиенты пишут примерно
с девяти утра до девяти вечера: двенадцать часов активности и двенадцать тишины.
Порог стоит впритык к обычной ночи и срабатывает почти каждое утро. Ночной порог
настраивается отдельно (`channel_silence_night_minutes`), но на проде равен дневному —
послабления фактически нет.

Главное же: сторож САМ знал, что чинить нечего. В его собственном тексте стояло
«В Wappi по этому номеру тоже тихо — значит дело не в технике», то есть он сходил,
убедился, что канал жив, и всё равно разбудил владельца в 7:31 советом «проверь рекламу».

## Правило

Тишина нужна ради ОДНОГО случая, который точный сторож (`wappi_health`) не видит:
профиль жив, Wappi принимает сообщения, а до нас они не доходят. Это `diagnosis
== "webhook"` — настоящая поломка, будим.

«Тихо и у нас, и в Wappi» (`no_traffic`) — не авария, а отсутствие клиентов. Ночью это
норма, днём — вопрос к рекламе, и ни то ни другое не чинится в семь утра.

Неизвестный диагноз (счётчик Wappi недоступен) будим по-прежнему: неизвестность может
скрывать поломку, и молчать про неё опаснее, чем лишний раз спросить.

За флагом `silence_alert_only_on_gap`, дефолт OFF — прежнее поведение не меняется.
"""
from __future__ import annotations

import pytest

from app.core import channel_heartbeat as hb

HOUR = 3600.0
NOW = 1_755_000_000.0
DAY_HOUR = 14          # день по Бишкеку


class Cfg:
    channel_heartbeat_enabled = True
    channel_silence_minutes = 720
    channel_silence_night_minutes = 720
    channel_alert_cooldown_minutes = 1440
    silence_alert_only_on_gap = True


class CfgOff(Cfg):
    silence_alert_only_on_gap = False


def _silent(hours=13.0):
    return {"frunze_tours": NOW - hours * HOUR}


def _ids(alerts):
    return [bot_id for bot_id, _ in alerts]


# ---------------- поломка: будим ----------------------------------------------------
def test_webhook_gap_still_alerts():
    """Wappi принимает, до нас не доходит — ровно то, ради чего сторож и существует."""
    alerts = hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=DAY_HOUR,
                       diagnoses={"frunze_tours": "webhook"})
    assert _ids(alerts) == ["frunze_tours"]
    assert "вебхук" in alerts[0][1]


def test_unknown_diagnosis_still_alerts():
    """Счётчик Wappi недоступен — молчать про неизвестность опаснее, чем спросить."""
    assert _ids(hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=DAY_HOUR,
                          diagnoses={})) == ["frunze_tours"]


# ---------------- не поломка: молчим ------------------------------------------------
def test_no_traffic_does_not_wake_anyone():
    """Тихо и у нас, и в Wappi — это отсутствие клиентов, а не авария."""
    assert hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=DAY_HOUR,
                     diagnoses={"frunze_tours": "no_traffic"}) == []


def test_no_traffic_silent_at_night_too():
    """Утренние 7:31 и 8:12 — те самые ложные, ради которых всё делается."""
    assert hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=7,
                     diagnoses={"frunze_tours": "no_traffic"}) == []


def test_no_traffic_latch_not_set_so_real_gap_alerts_later():
    """Промолчали — защёлку не ставим: если следом вскроется настоящая поломка, скажем."""
    state: dict = {}
    hb.decide(NOW, _silent(), state, Cfg, bishkek_hour=DAY_HOUR,
              diagnoses={"frunze_tours": "no_traffic"})
    later = hb.decide(NOW + HOUR, _silent(14.0), state, Cfg, bishkek_hour=DAY_HOUR,
                      diagnoses={"frunze_tours": "webhook"})
    assert _ids(later) == ["frunze_tours"], "тишина про одно не должна глушить другое"


# ---------------- ложноположительные: прежнее поведение при снятом флаге ------------
def test_flag_off_keeps_old_behaviour():
    assert _ids(hb.decide(NOW, _silent(), {}, CfgOff, bishkek_hour=DAY_HOUR,
                          diagnoses={"frunze_tours": "no_traffic"})) == ["frunze_tours"]


def test_healthy_channel_never_alerts_regardless_of_flag():
    """Ложноположительный: канал, который писал недавно, не трогаем ни при каком флаге."""
    fresh = {"frunze_tours": NOW - HOUR}
    assert hb.decide(NOW, fresh, {}, Cfg, bishkek_hour=DAY_HOUR, diagnoses={}) == []
    assert hb.decide(NOW, fresh, {}, CfgOff, bishkek_hour=DAY_HOUR, diagnoses={}) == []


def test_reported_by_wappi_still_deduped():
    """Ложноположительный: дедуп с точным сторожем не сломан."""
    assert hb.decide(NOW, _silent(), {}, Cfg, bishkek_hour=DAY_HOUR,
                     reported=frozenset({"frunze_tours"}),
                     diagnoses={"frunze_tours": "webhook"}) == []
