"""Очередь «ждут ответа» для пилота виз без Bitrix (B2b, 14.10.2026).

Клиент «ждёт», если последним в диалоге писал он, а отвечать должен человек: диалог
перехвачен менеджером или стоит на стадии человека. Пока диалог ведёт бот, ожидание
менеджера не считается — бот отвечает сам.

Ожидание считаем в РАБОЧИХ минутах по часам приёма направления (`schedule.py`, время
Бишкека): клиент, написавший в 23:00, к 10:05 ждёт 5 минут, а не 11 часов. Иначе очередь
каждое утро открывалась бы «горящей» целиком, и её перестали бы читать.

Порог X — `pilot_reply_sla_minutes` (дефолт 30). ЖДЁТ РЕШЕНИЯ ГРИШИ.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.core import schedule
from app.core.leadstate import HUMAN_STAGES

BISHKEK = timedelta(hours=6)


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)


def working_minutes(bot_id: str, start: datetime, end: datetime) -> float:
    """Сколько минут из [start, end) пришлось на часы приёма канала `bot_id`."""
    start, end = _aware(start).astimezone(timezone.utc), _aware(end).astimezone(timezone.utc)
    if end <= start:
        return 0.0
    plan = schedule.schedule_for(bot_id)
    local_start, local_end = (start + BISHKEK).replace(tzinfo=None), (end + BISHKEK).replace(tzinfo=None)
    total = 0.0
    day = local_start.date()
    while day <= local_end.date():
        if day.weekday() in plan["days"]:
            opened = datetime(day.year, day.month, day.day, plan["open"])
            closed = datetime(day.year, day.month, day.day, plan["close"])
            lo, hi = max(opened, local_start), min(closed, local_end)
            if hi > lo:
                total += (hi - lo).total_seconds() / 60
        day += timedelta(days=1)
    return total


def needs_human(conv) -> bool:
    return bool(getattr(conv, "intercepted", False)) or getattr(conv, "stage", "") in HUMAN_STAGES


def waiting_minutes(conv, now: datetime) -> float | None:
    """Рабочие минуты ожидания или None, если клиент не ждёт человека."""
    if getattr(conv, "last_sender", "") != "client" or getattr(conv, "archived", False):
        return None
    if not needs_human(conv) or getattr(conv, "last_message_at", None) is None:
        return None
    return working_minutes(getattr(conv, "bot_id", "") or "", conv.last_message_at, now)


def overdue(convs, now: datetime, *, sla_minutes: int, login: str, full_admin: bool) -> list[dict]:
    """Диалоги менеджера (свои + ничьи в его видимости), где клиент ждёт дольше X рабочих минут.

    `convs` уже отфильтрованы по видимости (команде) вызывающим кодом. Сортировка — дольше
    всех ждущие сверху.
    """
    login = (login or "").strip().lower()
    out = []
    for conv in convs:
        owner = (getattr(conv, "assigned_to", "") or "").strip().lower()
        if not full_admin and owner not in ("", login):
            continue
        waited = waiting_minutes(conv, now)
        if waited is None or waited < sla_minutes:
            continue
        out.append({"conv": conv, "user_id": conv.user_id, "waited": waited, "owner": owner})
    out.sort(key=lambda item: item["waited"], reverse=True)
    return out
