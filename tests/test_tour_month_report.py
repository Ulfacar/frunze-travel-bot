# -*- coding: utf-8 -*-
"""Месячный отчёт по турам: арифметика, на которой он стоит.

Отчёт идёт заказчику, поэтому каждая цифра в нём — обещание. Закрепляем ровно те места,
где первый прогон 15.09 соврал или мог соврать:

* месяц КАЛЕНДАРНЫЙ и по Бишкеку — «последние 30 дней» дают другое число;
* сравнение с прошлым месяцем не выдумывает данных, которых нет;
* «0 мин» у бота — это не «нет данных», а доли секунды: показываем секундами;
* хвост важнее середины: у менеджеров медиана 3 мин при p90 11.7 часа, и отчёт,
  печатающий только медиану, врёт умолчанием.
"""
from datetime import datetime, timedelta, timezone

from scripts.tour_month_report import (
    REPLY_DEADLINE_MIN,
    _delta,
    _median,
    _minutes,
    _month_bounds,
    _percentile,
)

BISHKEK = timezone(timedelta(hours=6))


# ---------------- 1. календарный месяц по Бишкеку --------------------------------------
def test_month_starts_at_bishkek_midnight_not_utc():
    """Сентябрь начинается 01.09 в 00:00 Бишкека — это 31.08 18:00 UTC."""
    start, end, title = _month_bounds("2026-09")
    assert start == datetime(2026, 8, 31, 18, 0, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 30, 18, 0, tzinfo=timezone.utc)
    assert title == "09.2026"


def test_calendar_month_is_not_thirty_days():
    """Август длиннее 30 суток — окно обязано это учитывать, иначе 31-е выпадает."""
    start, end, _ = _month_bounds("2026-08")
    assert (end - start) == timedelta(days=31)


def test_december_rolls_over_into_january():
    start, end, _ = _month_bounds("2026-12")
    assert start.year == 2026 and end.year == 2026
    assert end == datetime(2026, 12, 31, 18, 0, tzinfo=timezone.utc)


def test_february_is_short():
    start, end, _ = _month_bounds("2026-02")
    assert (end - start) == timedelta(days=28)


def test_late_evening_of_the_last_day_belongs_to_its_own_month():
    """31.08 в 23:00 по Бишкеку — ещё август, хотя по UTC это уже 31.08 17:00."""
    start_sep, _, _ = _month_bounds("2026-09")
    last_evening = datetime(2026, 8, 31, 23, 0, tzinfo=BISHKEK).astimezone(timezone.utc)
    assert last_evening < start_sep


# ---------------- 2. сравнение с прошлым месяцем ---------------------------------------
def test_no_previous_data_means_no_comparison():
    """Нечего сравнивать — молчим, а не печатаем выдуманный ноль."""
    assert _delta(10, None) == ""
    assert _delta(None, 10) == ""


def test_zero_base_is_named_not_divided():
    assert "0" in _delta(10, 0)


def test_direction_of_good_depends_on_the_metric():
    """Рост лидов — хорошо, рост времени ответа — плохо."""
    assert "лучше" in _delta(10, 5)
    assert "хуже" in _delta(5, 10)
    assert "лучше" in _delta(5, 10, less_is_better=True)
    assert "хуже" in _delta(10, 5, less_is_better=True)


def test_equal_values_say_so():
    assert "как в прошлом" in _delta(10, 10)


# ---------------- 3. медиана и хвост ----------------------------------------------------
def test_median_of_nothing_is_not_zero():
    """Пустой месяц не должен выглядеть как «отвечали мгновенно»."""
    assert _median([]) is None
    assert _percentile([], 0.9) is None


def test_median_and_percentile():
    assert _median([1, 2, 3]) == 2
    assert _median([1, 2, 3, 4]) == 2.5
    assert _percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == 10


def test_tail_is_not_hidden_by_the_median():
    """Замер 15.09: у менеджеров середина 3 мин, а каждый десятый ждал 11.7 часа."""
    values = [1.0] * 90 + [700.0] * 10
    assert _median(values) == 1.0
    assert _percentile(values, 0.9) >= 700.0


# ---------------- 4. человеческий формат времени ----------------------------------------
def test_subminute_is_shown_in_seconds():
    """«0 мин» читается как «нет данных» — у бота это доли секунды."""
    assert "сек" in _minutes(0.2)
    assert _minutes(None) == "нет данных"


def test_minutes_and_hours():
    assert "мин" in _minutes(3.0)
    assert "ч" in _minutes(700.0)


# ---------------- 5. отсечка «ответ через неделю» ---------------------------------------
def test_reply_deadline_is_two_days():
    """Реплика через неделю — не ответ на то сообщение; в среднее её не берём."""
    assert REPLY_DEADLINE_MIN == 48 * 60
