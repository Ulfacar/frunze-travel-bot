"""Ежедневная сводка пилота виз (только чтение, только агрегаты — без имён и номеров).

    python scripts/pilot_daily_summary.py --day 2026-10-27 [--bots getvisa,getvisa_tg] [--sla 30]

Считает за местный день (Бишкек):
- эпизоды ожидания клиента: от сообщения клиента до первого ответа менеджера/бота (или до
  конца дня, если ответа нет) — в рабочих минутах по часам приёма (`reply_sla`);
- сколько ждали дольше X и максимальное ожидание;
- ошибки отправки менеджера (failed / unknown);
- продажи по полной оплате (`audit_log.action = 'sale_full_payment'`).
Подключение — `DATABASE_URL` из окружения (на сервере — read-only роль). Ничего не пишет.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select

BISHKEK = timedelta(hours=6)


def _aware(at: datetime) -> datetime:
    return at if at.tzinfo is not None else at.replace(tzinfo=timezone.utc)


def day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) - BISHKEK
    return start, start + timedelta(days=1)


def episodes(messages, bot_id: str, start: datetime, end: datetime) -> list[float]:
    """Рабочие минуты каждого эпизода ожидания, начавшегося в [start, end)."""
    from app.core.reply_sla import working_minutes
    out: list[float] = []
    waiting_since = None
    for m in sorted(messages, key=lambda x: (_aware(x.created_at), x.id)):
        at = _aware(m.created_at)
        if m.sender == "client":
            if waiting_since is None and start <= at < end:
                waiting_since = at
        elif waiting_since is not None:
            out.append(working_minutes(bot_id, waiting_since, at))
            waiting_since = None
    if waiting_since is not None:
        out.append(working_minutes(bot_id, waiting_since, end))
    return out


async def compute(sessionmaker, day: date, bot_ids: set[str], sla: int) -> dict:
    from app.integrations.crm.db import AuditLog, Conversation, ConvMessage
    start, end = day_bounds(day)
    async with sessionmaker() as session:
        convs = (await session.execute(select(Conversation).where(Conversation.bot_id.in_(bot_ids)))).scalars().all()
        waits: list[float] = []
        failed = unknown = 0
        for conv in convs:
            rows = (await session.execute(select(ConvMessage).where(
                ConvMessage.conversation_id == conv.id,
                ConvMessage.created_at < end, ConvMessage.created_at >= start - timedelta(days=2)))).scalars().all()
            waits += episodes(rows, conv.bot_id, start, end)
            for r in rows:
                if r.sender == "manager" and start <= _aware(r.created_at) < end:
                    failed += r.status == "failed"
                    unknown += r.status == "unknown"
        sales = len((await session.execute(select(AuditLog.id).where(
            AuditLog.action == "sale_full_payment", AuditLog.created_at >= start,
            AuditLog.created_at < end))).scalars().all())
    over = [w for w in waits if w > sla]
    return {"day": day.isoformat(), "bots": sorted(bot_ids), "sla_minutes": sla,
            "waiting_episodes": len(waits), "waited_longer_than_sla": len(over),
            "max_wait_minutes": round(max(waits), 1) if waits else 0.0,
            "send_failed": failed, "send_unknown": unknown, "sales_full_payment": sales}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", required=True)
    ap.add_argument("--bots", default="getvisa,getvisa_tg")
    ap.add_argument("--sla", type=int, default=None)
    args = ap.parse_args()
    from app.config import settings
    from app.integrations.crm.db import get_sessionmaker
    sla = args.sla if args.sla is not None else settings.pilot_reply_sla_minutes
    result = asyncio.run(compute(get_sessionmaker(), date.fromisoformat(args.day),
                                 {b.strip() for b in args.bots.split(",") if b.strip()}, sla))
    print(json.dumps(result, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
