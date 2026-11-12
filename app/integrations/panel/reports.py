# -*- coding: utf-8 -*-
"""Отчёты, которые просила Медина (её ответы по воронкам, раздел «Отчёты и доступ»).

Её список из двенадцати:

    новые лиды за день, неделю и месяц · консультации онлайн и в офисе · заключённые
    договоры · конверсия из обращения в договор · клиенты по странам · общая сумма
    продаж · фактически полученные оплаты · задолженности клиентов · количество виз,
    одобрений и отказов · задачи сотрудников и просроченные · эффективность каждого
    менеджера · источники обращений клиентов

Здесь считается ТОЛЬКО то, под что в базе есть данные. Остальное возвращается с
пометкой, почему посчитать нельзя, — и это не отговорка, а главная ценность отчёта на
сегодня: видно, что именно мешает мерить. Пустой столбец «клиенты по странам»
означает, что поле страны у карточек не заполнено, а не что клиентов нет.

Существующая аналитика (`analytics.compute_analytics`) отвечает на другой вопрос —
«ИИ против менеджера»: containment, время ответа, перехваты. Её метрики там не
считаются, поэтому отдельный модуль, а не правка той.

Функция чистая: принимает уже загруженные карточки и задачи, ничего не читает сама.
Так её можно проверить тестами и прогнать на боевом срезе одним скриптом.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

# Окна, которые она назвала дословно: «за день, неделю и месяц».
WINDOWS = (("день", 1), ("неделя", 7), ("месяц", 30))

# Почему метрика не считается. Текст идёт в отчёт как есть: человек должен понимать,
# чего не хватает, без похода к разработчику.
BLOCKED = {
    "contracts": "Договоры в CRM не заводятся: запись дел выключена (cases_write_enabled).",
    "payments": "Оплаты по договору не вносятся — нет ни одного дела.",
    "debts": "Задолженность считается от суммы договора и оплат, которых нет.",
    "visa_outcomes": "Одобрения и отказы ставятся на этапе заявки; заявок в системе нет.",
    "consultations": "Консультации онлайн и в офисе отдельно не отмечаются: "
                     "в карточке есть стадия «Записан в офис», но факт визита не фиксируется.",
}


def _aware(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _is_overdue(task: Any, now: datetime) -> bool:
    """Просрочена: срок в прошлом и задача не закрыта.

    День сравниваем по дате, а не по времени: задача «на сегодня» не считается
    просроченной в 09:00 только потому, что час назад начался день.
    """
    if str(getattr(task, "status", "")) in ("done", "cancelled"):
        return False
    scheduled = getattr(task, "scheduled_date", None)
    if scheduled is None:
        return False
    day = scheduled.date() if isinstance(scheduled, datetime) else scheduled
    return day < now.date()


def compute_reports(conversations: Iterable[Any], tasks: Iterable[Any] = (), *,
                    now: datetime | None = None, direction: str | None = None) -> dict:
    """Свод по её списку. `direction` — фильтр воронки ('visa'/'tours'), None — все."""
    now = _aware(now) or datetime.now(timezone.utc)
    convs = [c for c in conversations
             if direction is None or (getattr(c, "funnel", "") or "") == direction]

    # --- новые лиды за день / неделю / месяц -------------------------------
    new_leads = {}
    for label, days in WINDOWS:
        since = now - timedelta(days=days)
        new_leads[label] = sum(
            1 for c in convs if (_aware(getattr(c, "created_at", None)) or now) >= since)

    # --- источники обращений ------------------------------------------------
    sources = Counter()
    for c in convs:
        src = (getattr(c, "source", "") or "").strip()
        sources["реклама" if src == "ad" else "пост" if src == "post" else "без источника"] += 1

    # --- клиенты по странам -------------------------------------------------
    # Поле заполняет менеджер руками (её ответ 6). Пусто — значит ещё не заполняют,
    # и в отчёте это видно честно, а не как «клиентов нет».
    countries = Counter()
    for c in convs:
        country = (getattr(c, "visa_country", "") or "").strip()
        if country:
            countries[country] += 1
    filled = sum(countries.values())

    # --- эффективность менеджера: сколько ведёт и сколько закрыто -----------
    by_manager: dict[str, dict[str, int]] = {}
    for c in convs:
        owner = (getattr(c, "assigned_to", "") or "").strip().lower()
        if not owner:
            continue
        row = by_manager.setdefault(owner, {"всего": 0, "оплатил": 0, "слился": 0})
        row["всего"] += 1
        outcome = (getattr(c, "outcome", "") or "")
        if outcome == "won":
            row["оплатил"] += 1
        elif outcome == "lost":
            row["слился"] += 1

    # --- задачи и просроченные ---------------------------------------------
    # Фильтр по направлению обязателен и для задач: без него визовый и туровый отчёт
    # показывали одинаковые 3133 открытых задачи. Поймано прогоном на боевых данных
    # 12.11.2026 — на выдуманных числах такое совпадение в глаза не бросается.
    tasks = [t for t in tasks
             if direction is None or (getattr(t, "direction", "") or "") == direction]
    open_tasks = [t for t in tasks if str(getattr(t, "status", "")) not in ("done", "cancelled")]
    overdue = [t for t in open_tasks if _is_overdue(t, now)]
    tasks_by_manager: dict[str, dict[str, int]] = {}
    for t in open_tasks:
        owner = (getattr(t, "manager_id", "") or "").strip().lower() or "без владельца"
        row = tasks_by_manager.setdefault(owner, {"открыто": 0, "просрочено": 0})
        row["открыто"] += 1
    for t in overdue:
        owner = (getattr(t, "manager_id", "") or "").strip().lower() or "без владельца"
        tasks_by_manager.setdefault(owner, {"открыто": 0, "просрочено": 0})["просрочено"] += 1

    # --- причины закрытия (её справочник из восьми) -------------------------
    lost_reasons = Counter()
    for c in convs:
        if (getattr(c, "outcome", "") or "") == "lost":
            lost_reasons[(getattr(c, "outcome_reason", "") or "") or "без причины"] += 1

    return {
        "считано_на": now,
        "направление": direction or "все",
        "всего_карточек": len(convs),
        "новые_лиды": new_leads,
        "источники": dict(sources.most_common()),
        "клиенты_по_странам": dict(countries.most_common()),
        "страна_заполнена_у": filled,
        "по_менеджерам": by_manager,
        "задачи": {"открыто": len(open_tasks), "просрочено": len(overdue),
                   "по_менеджерам": tasks_by_manager},
        "причины_закрытия": dict(lost_reasons.most_common()),
        "пока_не_считается": dict(BLOCKED),
    }
