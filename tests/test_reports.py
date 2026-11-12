# -*- coding: utf-8 -*-
"""Отчёты по списку Медины.

Главное требование к отчёту — не красота, а честность: если метрику посчитать не из
чего, отчёт обязан это сказать, а не показать ноль. Ноль и «нечем мерить» выглядят
одинаково, а значат противоположное: по нулю руководитель решит, что клиентов нет, и
будет неправ. Поэтому половина тестов здесь про то, что пустота названа пустотой.
"""
from datetime import date, datetime, timedelta, timezone

from app.integrations.panel.reports import compute_reports

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)


class Conv:
    def __init__(self, *, created_days_ago=0, funnel="visa", source="", country="",
                 assigned_to="", outcome="", outcome_reason=""):
        self.created_at = NOW - timedelta(days=created_days_ago)
        self.funnel = funnel
        self.source = source
        self.visa_country = country
        self.assigned_to = assigned_to
        self.outcome = outcome
        self.outcome_reason = outcome_reason


class Task:
    def __init__(self, *, manager_id="medina", status="planned", days_ago=0,
                 direction="visa"):
        self.manager_id = manager_id
        self.status = status
        self.direction = direction
        self.scheduled_date = (NOW - timedelta(days=days_ago)).date()


# --- новые лиды -------------------------------------------------------------

def test_new_leads_are_counted_in_her_three_windows():
    """Её слова: «за день, неделю и месяц»."""
    convs = [Conv(created_days_ago=0), Conv(created_days_ago=3),
             Conv(created_days_ago=20), Conv(created_days_ago=100)]

    r = compute_reports(convs, now=NOW)

    assert r["новые_лиды"] == {"день": 1, "неделя": 2, "месяц": 3}


def test_the_windows_are_nested_not_exclusive():
    """Лид, созданный сегодня, попадает и в день, и в неделю, и в месяц."""
    r = compute_reports([Conv(created_days_ago=0)], now=NOW)
    assert r["новые_лиды"]["день"] == r["новые_лиды"]["месяц"] == 1


def test_a_direction_filter_narrows_everything():
    convs = [Conv(funnel="visa"), Conv(funnel="tours"), Conv(funnel="tours")]
    assert compute_reports(convs, now=NOW, direction="visa")["всего_карточек"] == 1
    assert compute_reports(convs, now=NOW, direction="tours")["всего_карточек"] == 2
    assert compute_reports(convs, now=NOW)["всего_карточек"] == 3


# --- честность пустоты ------------------------------------------------------

def test_an_empty_country_column_is_distinguishable_from_no_clients():
    """Ноль и «нечем мерить» значат разное, и отчёт обязан их различать.

    Сто карточек без заполненной страны — это не «клиентов нет», а «поле не
    заполняют». По нулю без этой подписи руководитель сделает неверный вывод.
    """
    convs = [Conv() for _ in range(100)]

    r = compute_reports(convs, now=NOW)

    assert r["клиенты_по_странам"] == {}
    assert r["всего_карточек"] == 100
    assert r["страна_заполнена_у"] == 0


def test_filled_countries_are_counted_and_ranked():
    convs = [Conv(country="Германия"), Conv(country="Германия"), Conv(country="Корея")]

    r = compute_reports(convs, now=NOW)

    assert list(r["клиенты_по_странам"]) == ["Германия", "Корея"]
    assert r["страна_заполнена_у"] == 3


def test_metrics_without_data_say_why():
    """Договоры, оплаты, долги, одобрения, консультации — с объяснением, а не нулём."""
    r = compute_reports([Conv()], now=NOW)

    blocked = r["пока_не_считается"]
    assert set(blocked) == {"contracts", "payments", "debts", "visa_outcomes",
                            "consultations"}
    assert "cases_write_enabled" in blocked["contracts"]
    for text in blocked.values():
        assert len(text) > 20, "объяснение должно быть человеческим, а не меткой"


# --- источники и менеджеры --------------------------------------------------

def test_sources_split_ads_from_organic():
    convs = [Conv(source="ad"), Conv(source="ad"), Conv(source="post"), Conv(source="")]

    r = compute_reports(convs, now=NOW)

    assert r["источники"]["реклама"] == 2
    assert r["источники"]["пост"] == 1
    assert r["источники"]["без источника"] == 1


def test_manager_rows_count_outcomes():
    convs = [Conv(assigned_to="medina", outcome="won"),
             Conv(assigned_to="medina", outcome="lost"),
             Conv(assigned_to="medina"),
             Conv(assigned_to="eliza", outcome="won")]

    r = compute_reports(convs, now=NOW)

    assert r["по_менеджерам"]["medina"] == {"всего": 3, "оплатил": 1, "слился": 1}
    assert r["по_менеджерам"]["eliza"] == {"всего": 1, "оплатил": 1, "слился": 0}


def test_unassigned_cards_are_not_attributed_to_anyone():
    """Ничей лид не должен попадать в чью-то эффективность."""
    r = compute_reports([Conv(assigned_to="")], now=NOW)
    assert r["по_менеджерам"] == {}


# --- задачи -----------------------------------------------------------------

def test_overdue_counts_only_unfinished_tasks_in_the_past():
    tasks = [Task(days_ago=5),                      # просрочена
             Task(days_ago=5, status="done"),       # закрыта — не считается
             Task(days_ago=0),                      # сегодня — ещё не просрочена
             Task(days_ago=-3)]                     # в будущем

    r = compute_reports([], tasks, now=NOW)

    assert r["задачи"]["открыто"] == 3
    assert r["задачи"]["просрочено"] == 1


def test_a_task_due_today_is_not_overdue_yet():
    """Иначе утром все сегодняшние задачи выглядели бы просроченными."""
    r = compute_reports([], [Task(days_ago=0)], now=NOW)
    assert r["задачи"]["просрочено"] == 0


def test_tasks_are_split_by_manager():
    tasks = [Task(manager_id="medina", days_ago=5), Task(manager_id="medina"),
             Task(manager_id="eliza")]

    r = compute_reports([], tasks, now=NOW)

    assert r["задачи"]["по_менеджерам"]["medina"] == {"открыто": 2, "просрочено": 1}
    assert r["задачи"]["по_менеджерам"]["eliza"] == {"открыто": 1, "просрочено": 0}


# --- причины закрытия -------------------------------------------------------

def test_lost_reasons_are_counted_and_the_missing_one_is_named():
    convs = [Conv(outcome="lost", outcome_reason="price"),
             Conv(outcome="lost", outcome_reason="price"),
             Conv(outcome="lost", outcome_reason=""),
             Conv(outcome="won")]

    r = compute_reports(convs, now=NOW)

    assert r["причины_закрытия"]["price"] == 2
    assert r["причины_закрытия"]["без причины"] == 1
    assert "won" not in r["причины_закрытия"]


def test_naive_timestamps_do_not_crash_the_report():
    """В базе встречаются даты без часового пояса — отчёт не должен на них падать."""
    conv = Conv()
    conv.created_at = datetime(2026, 11, 12, 10, 0)      # без tzinfo

    r = compute_reports([conv], now=NOW)

    assert r["новые_лиды"]["день"] == 1


def test_tasks_are_filtered_by_direction_too():
    """Без этого визовый и туровый отчёт показывали одни и те же задачи.

    Поймано прогоном на боевых данных: в обоих разрезах стояло 3133 открытых задачи,
    хотя карточки фильтровались правильно.
    """
    tasks = [Task(direction="visa"), Task(direction="visa"), Task(direction="tours")]

    assert compute_reports([], tasks, now=NOW, direction="visa")["задачи"]["открыто"] == 2
    assert compute_reports([], tasks, now=NOW, direction="tours")["задачи"]["открыто"] == 1
    assert compute_reports([], tasks, now=NOW)["задачи"]["открыто"] == 3
