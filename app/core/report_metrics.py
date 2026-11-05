"""Чистые расчёты отчётов. Не меняют исходы, платежи и поведение бота."""
from datetime import datetime, timedelta, timezone

PERIODS = (("today", "Сегодня"), ("week", "7 дней"),
           ("fortnight", "14 дней"), ("month", "30 дней"))
ALIASES = {"7d": "week", "14d": "fortnight", "30d": "month"}


def period_bounds(period, now):
    now = now.replace(tzinfo=timezone.utc) if now.tzinfo is None else now
    now = now.astimezone(timezone.utc)
    local = now + timedelta(hours=6)
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=6)
    period = ALIASES.get(period, period)
    if period == "yesterday":
        return midnight - timedelta(days=1), midnight
    days = {"today": 1, "week": 7, "fortnight": 14, "month": 30}
    if period not in days:
        raise ValueError("Unknown report period")
    return midnight - timedelta(days=days[period] - 1), now


def conversion(leads, sales):
    """Потоковая конверсия: продажи периода / новые лиды периода, может быть >100%."""
    return round(100 * sales / leads, 2) if leads else None


def working_minutes(bot_id, start, end):
    """Рабочие часы отчёта 09–19; рабочие дни из существующего расписания канала."""
    from app.core.schedule import schedule_for
    days = schedule_for(bot_id)["days"]
    start = start.astimezone(timezone.utc) + timedelta(hours=6)
    end = end.astimezone(timezone.utc) + timedelta(hours=6)
    day = start.replace(hour=0, minute=0, second=0, microsecond=0)
    total = 0.0
    while day < end:
        if day.weekday() in days:
            lo, hi = max(start, day + timedelta(hours=9)), min(end, day + timedelta(hours=19))
            total += max(0, (hi - lo).total_seconds() / 60)
        day += timedelta(days=1)
    return total


def acquisition(dialogs, lead_ids, sale_ids, names=None):
    """Агрегаты без идентификаторов клиентов; неизвестные источники не теряются."""
    names = names or {}
    channels, creatives = {}, {}
    for dialog in dialogs:
        uid = dialog.user_id
        if uid not in lead_ids and uid not in sale_ids:
            continue
        source = (getattr(dialog, "source_type", "") or getattr(dialog, "source", "") or "")
        code = getattr(dialog, "source_id", "") or ""
        channel = {"post": "Instagram", "ad": "Facebook"}.get(source)
        if channel is None:
            channel = ("WhatsApp напрямую / источник не определён"
                       if not source and getattr(dialog, "channel", "") in ("whatsapp", "wappi")
                       else "Другой канал / источник не определён")
        for mapping, key in ((channels, channel), (creatives, (source, code))):
            row = mapping.setdefault(key, {"leads": 0, "sales": 0})
            row["leads"] += uid in lead_ids
            row["sales"] += uid in sale_ids
    def values(mapping):
        return [{"key": key, **row, "conversion": conversion(row["leads"], row["sales"])}
                for key, row in sorted(mapping.items())]
    creative_rows = values(creatives)
    for row in creative_rows:
        source, code = row["key"]
        row["label"] = names.get((source, code)) or code or "Без источника"
    return {"channels": values(channels), "creatives": creative_rows}
