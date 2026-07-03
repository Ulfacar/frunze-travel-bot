"""Экран «Покупатели сегодня» — расчёт над диалогами (чистая функция, тестируемо).

Из scope-фильтрованного списка ConversationView строит:
- feed: открытые 🟢-покупатели, сортировка по ожиданию×чеку, кап под ёмкость;
- hero: сводка владельца (сколько готовых, сумма чеков, «шум отфильтрован N из M»).
Ноль LLM — всё из полей readiness (см. app/core/readiness.py) + таймстемпов.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

from app.core.budget import bishkek_day_start_utc

WAIT_WARM_MIN = 5     # ждёт дольше — карточка желтеет
WAIT_LATE_MIN = 15    # ждёт дольше — горит (SLA нарушен)
FEED_CAP = 15         # столько 🟢 показываем менеджеру (ёмкость), остальное «показать ещё»
_TIERS = ("green", "warm", "noise", "insufficient")
_FUNNEL_LABEL = {"visa": "Визы", "tours": "Туры", "tickets": "Билеты"}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _wait_minutes(conv, now: datetime) -> float:
    """Сколько клиент ждёт ответа. 0, если последним писал не клиент (мяч не у нас)."""
    if (getattr(conv, "last_sender", "") or "") != "client":
        return 0.0
    dt = _aware(getattr(conv, "last_message_at", None))
    if dt is None:
        return 0.0
    return max(0.0, (_aware(now) - dt).total_seconds() / 60)


def _wait_state(minutes: float) -> str:
    if minutes >= WAIT_LATE_MIN:
        return "late"
    if minutes >= WAIT_WARM_MIN:
        return "warn"
    return "ok"


def _name(conv) -> str:
    name = (getattr(conv, "qualification", None) or {}).get("name")
    if name:
        return str(name)
    phone = getattr(conv, "phone", "") or getattr(conv, "user_id", "")
    tail = phone[-4:] if phone else "—"
    return f"Без имени · {tail}"


def _direction(conv) -> str:
    label = _FUNNEL_LABEL.get(getattr(conv, "funnel", "") or "", "—")
    dest = (getattr(conv, "qualification", None) or {}).get("destination") \
        or (getattr(conv, "qualification", None) or {}).get("country")
    return f"{label} · {dest}" if dest else label


def _card(conv, now: datetime) -> dict:
    wait = _wait_minutes(conv, now)
    return {
        "user_id": getattr(conv, "user_id", ""),
        "name": _name(conv),
        "direction": _direction(conv),
        "value": getattr(conv, "estimated_value", None),
        "currency": getattr(conv, "estimated_value_currency", "") or "",
        "reason": getattr(conv, "readiness_reason", "") or "",
        "wait": int(wait),
        "wait_state": _wait_state(wait),
    }


def compute_buyers(convs: list, now: datetime | None = None) -> dict:
    """convs — non-archived, scope-фильтрованные ConversationView с readiness_*."""
    now = _aware(now) or datetime.now(timezone.utc)
    start = bishkek_day_start_utc(now)

    # Сводка владельца — по «сегодняшнему потоку» (активные сегодня). Тир берём хранимый:
    # ghost-noise (застой >24ч) фоновый sweep проставляет для СТАРЫХ диалогов, а сегодняшние
    # честно остаются insufficient (нельзя объявить шум в тот же день — клиент ещё может ответить).
    today = [c for c in convs
             if (_aware(getattr(c, "last_message_at", None)) or start) >= start]
    tiers = Counter((getattr(c, "readiness_tier", "") or "insufficient") for c in today)
    total_today = len(today)
    filtered = tiers.get("noise", 0) + tiers.get("insufficient", 0)

    # Лента: НЕВЗЯТЫЕ открытые 🟢-покупатели. Как только менеджер забрал (claim →
    # assigned_to/intercepted) — диалог уходит из очереди «на разбор» (иначе после
    # клика карточка возвращается на следующем поллинге — очередь не тает).
    green = [c for c in convs
             if (getattr(c, "readiness_tier", "") or "") == "green"
             and (getattr(c, "outcome", "") or "") not in ("won", "lost")
             and not (getattr(c, "assigned_to", "") or "")
             and not getattr(c, "intercepted", False)]
    cards = [_card(c, now) for c in green]
    cards.sort(key=lambda c: (c["wait"], c["value"] or 0), reverse=True)

    value_by_currency: dict[str, float] = {}
    for c in cards:
        if c["value"]:
            value_by_currency[c["currency"] or "?"] = \
                value_by_currency.get(c["currency"] or "?", 0.0) + c["value"]

    hero = {
        "green_count": len(cards),
        "value_by_currency": value_by_currency,
        "waiting_late": sum(1 for c in cards if c["wait_state"] == "late"),
        "tiers": {t: tiers.get(t, 0) for t in _TIERS},
        "total_today": total_today,
        "filtered": filtered,
        "noise_pct": round(100 * filtered / total_today) if total_today else 0,
    }
    return {
        "hero": hero,
        "feed": cards[:FEED_CAP],
        "more": max(0, len(cards) - FEED_CAP),
        "generated_at": now,
        "date_label": (now + timedelta(hours=6)).strftime("%d.%m"),  # бишкекская дата (UTC+6)
    }
