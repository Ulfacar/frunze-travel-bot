# -*- coding: utf-8 -*-
"""Рабочее окно CRM у сторожа «клиент ждёт» — ответ заказчика 2.5 от 05.11.2026.

Сторож считал ожидание по календарю, и это давало две неправды сразу:

* ночью он тикал и к утру сообщал «клиент ждёт 11 часов» — пинг уходил тогда, когда
  ответить некому, а к открытию очередь выглядела горящей целиком;
* у виз он тикал с 9:00, хотя приём с 10:00 (решение Гриши 09.08) — ровно то, о чём
  сказал Алан: «с 9 до 10 у виз крутится SLA и пинги, пока менеджеров нет».

Часы берём из `app/core/schedule.py` через `reply_sla.working_minutes` — тем же
счётчиком, которым уже считает очередь «ждут ответа» и сводка пилота. Второго
источника правды о часах в проекте быть не должно.

Флаг `awaiting_working_hours_enabled`, дефолт OFF: порог детектора от правки меняется,
значит до включения нужна калибровка на истории прода.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.core import awaiting

BISHKEK = timedelta(hours=6)


def _utc(year, month, day, hour, minute=0):
    """Местное время Бишкека → UTC: в коде сторожа всё в UTC."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc) - BISHKEK


def conv(bot_id, last_at, **kw):
    base = dict(user_id="996700000097", phone="996700000097",
                funnel="visa" if bot_id.startswith("getvisa") else "tours",
                bot_id=bot_id, stage="manager", intercepted=True, archived=False,
                outcome=None, last_sender="client", last_message_at=last_at,
                assigned_to="medina", qualification={}, last_text="Когда будет готово?")
    base.update(kw)
    return SimpleNamespace(**base)


def cfg(**kw):
    base = dict(alert_awaiting_minutes=30, alert_cooldown_minutes=60,
                awaiting_telegram_enabled=True, awaiting_max_age_hours=24,
                awaiting_max_age_working_hours=12,
                awaiting_working_hours_enabled=False)
    base.update(kw)
    return SimpleNamespace(**base)


def picked(convs, now, *, working_hours):
    return [c.user_id for c in awaiting.select_awaiting_targets(
        convs, now, cfg(), working_hours=working_hours)]


# --- 1. Ночь ----------------------------------------------------------------

def test_at_night_the_watchdog_no_longer_counts():
    """Написал в 23:00, смотрим в 02:00 — в рабочих минутах ожидания нет."""
    wrote = _utc(2026, 11, 5, 23, 0)          # четверг, 23:00 по Бишкеку
    now = _utc(2026, 11, 6, 2, 0)             # пятница, 02:00
    c = conv("getvisa", wrote)
    assert picked([c], now, working_hours=False) == ["996700000097"]   # как было
    assert picked([c], now, working_hours=True) == []                  # стало


def test_the_morning_count_starts_at_opening_not_at_midnight():
    """В 10:05 клиент ждёт 5 рабочих минут, а не одиннадцать часов."""
    wrote = _utc(2026, 11, 5, 23, 0)
    now = _utc(2026, 11, 6, 10, 5)
    c = conv("getvisa", wrote)
    assert round(awaiting.waited_minutes(c, now, working_hours=True)) == 5
    assert round(awaiting.waited_minutes(c, now, working_hours=False)) == 665


# --- 2. Разные часы у направлений -------------------------------------------

def test_visas_do_not_tick_between_nine_and_ten():
    """Главный случай из разбора: приём виз с 10:00, туров — с 9:00."""
    wrote = _utc(2026, 11, 6, 8, 30)          # пятница, 08:30
    now = _utc(2026, 11, 6, 9, 45)            # 09:45 — визы ещё закрыты
    visa, tours = conv("getvisa", wrote), conv("frunze_tours", wrote)
    assert awaiting.waited_minutes(visa, now, working_hours=True) == 0.0
    assert round(awaiting.waited_minutes(tours, now, working_hours=True)) == 45
    assert picked([visa], now, working_hours=True) == []
    assert picked([tours], now, working_hours=True) == ["996700000097"]


def test_sunday_is_closed_on_both_directions():
    """Воскресенье — выходной: ожидание не копится ни у виз, ни у туров."""
    wrote = _utc(2026, 11, 8, 11, 0)          # воскресенье, 11:00
    now = _utc(2026, 11, 8, 18, 0)
    for bot in ("getvisa", "frunze_tours"):
        assert awaiting.waited_minutes(conv(bot, wrote), now, working_hours=True) == 0.0


# --- 3. Внутри рабочего дня ничего не меняется ------------------------------

def test_inside_working_hours_the_count_is_the_same():
    """Днём обе ветки должны давать одно и то же — иначе правка меняет не часы."""
    wrote = _utc(2026, 11, 6, 14, 0)
    now = _utc(2026, 11, 6, 14, 40)
    c = conv("getvisa", wrote)
    assert round(awaiting.waited_minutes(c, now, working_hours=True)) == 40
    assert round(awaiting.waited_minutes(c, now, working_hours=False)) == 40
    assert picked([c], now, working_hours=True) == ["996700000097"]


def test_the_flag_defaults_to_off_everywhere():
    """Выкатили код — поведение сторожа не изменилось."""
    from app.config import settings
    assert settings.awaiting_working_hours_enabled is False
    wrote = _utc(2026, 11, 5, 23, 0)
    now = _utc(2026, 11, 6, 2, 0)
    # Без аргумента — прежний календарный отсчёт.
    assert [c.user_id for c in awaiting.select_awaiting_targets(
        [conv("getvisa", wrote)], now, cfg())] == ["996700000097"]


def test_an_unknown_bot_falls_back_to_the_wider_schedule():
    """Неизвестный канал не должен терять ожидание совсем.

    `schedule.schedule_for` на незнакомом bot_id отдаёт туровый график (самый
    широкий) — сторож тогда считает с 9:00, а не молчит.
    """
    wrote = _utc(2026, 11, 6, 9, 10)
    now = _utc(2026, 11, 6, 9, 50)
    c = conv("", wrote)
    assert round(awaiting.waited_minutes(c, now, working_hours=True)) == 40


def test_a_saturday_evening_client_still_gets_a_personal_ping_on_monday():
    """Возраст меряется той же единицей, что и порог, иначе клиент теряется совсем.

    Ревью 09.11.2026: порог считался в рабочих минутах, а потолок свежести
    `awaiting_max_age_hours` остался календарным. Клиент, написавший в субботу вечером,
    при включённом окне не получал личного пуша НИКОГДА: в субботу рабочих минут мало,
    а в понедельник его выбрасывал календарный возраст (39 ч > 24 ч). Без флага пуш
    уходил в субботу — то есть правка, которая должна была убрать ночные пинги, молча
    убирала и самого клиента.

    7 ноября 2026 — суббота, 8-е — воскресенье (у виз нерабочее), 9-е — понедельник.
    """
    last = _utc(2026, 11, 7, 20, 0)                     # сб 20:00, после закрытия
    settings = cfg(alert_awaiting_minutes=10, awaiting_working_hours_enabled=True)

    # Суббота поздним вечером: рабочих минут нет — не будим никого, это и есть цель флага.
    saturday = awaiting.select_telegram_targets([conv("getvisa", last)],
                                                _utc(2026, 11, 7, 23, 0), settings,
                                                working_hours=True)
    assert saturday == []

    # Понедельник, приём виз открыт час: ожидание набрало рабочие минуты → пуш уходит.
    monday = awaiting.select_telegram_targets([conv("getvisa", last)],
                                              _utc(2026, 11, 9, 11, 0), settings,
                                              working_hours=True)
    assert len(monday) == 1, "клиент выходного дня обязан дождаться напоминания"

    # Мера одна на обе границы, но потолок в рабочих часах СВОЙ (12, не 24): иначе
    # 24 рабочих часа = 2,4 рабочих дня, и недельный лид снова будил бы менеджера.
    # Замер на пн 11:00, канал getvisa: вечер пятницы — 11 рабочих часов, четверг — 27.
    friday = awaiting.select_telegram_targets([conv("getvisa", _utc(2026, 11, 6, 18, 0))],
                                              _utc(2026, 11, 9, 11, 0), settings,
                                              working_hours=True)
    assert len(friday) == 1, "вечер пятницы — ещё живое ожидание"
    thursday = awaiting.select_telegram_targets([conv("getvisa", _utc(2026, 11, 5, 11, 0))],
                                                _utc(2026, 11, 9, 11, 0), settings,
                                                working_hours=True)
    assert thursday == [], "недельный лид напоминанием только злит"


def test_without_the_flag_the_age_ceiling_stays_calendar():
    """Флаг OFF — прежний календарный потолок, строка в строку."""
    settings = cfg(alert_awaiting_minutes=10, awaiting_working_hours_enabled=False)
    old = conv("getvisa", _utc(2026, 11, 7, 20, 0))
    assert awaiting.select_telegram_targets([old], _utc(2026, 11, 9, 11, 0),
                                            settings, working_hours=False) == []
    fresh = conv("getvisa", _utc(2026, 11, 9, 10, 0))
    assert len(awaiting.select_telegram_targets([fresh], _utc(2026, 11, 9, 11, 0),
                                                settings, working_hours=False)) == 1
