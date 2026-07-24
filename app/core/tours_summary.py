"""Еженедельная тур-сводка ВЛАДЕЛЬЦУ (Грише) в личный Telegram.

Закрывает боль «не вижу цифр по турам → не оправдать таргет»: раз в неделю
собирает из НАШИХ данных честную картину туровой воронки и шлёт владельцу туда,
где он живёт (Telegram), а не в экран, куда он не заходит.

ЧЕСТНОСТЬ (требование ревью Opus/John): «продано» = ТОЛЬКО ручная отметка менеджера
(outcome=="won"), НЕ AI-догадка. Оценку ИИ (outcome_inferred) показываем ОТДЕЛЬНОЙ
строкой с явной пометкой «оценка, не подтверждено» — никогда не смешиваем с фактом.

Гейт: флаг `tours_summary_enabled` (БД, default OFF) + получатель = менеджеры с
admin=True и заданным telegram_chat_id. Окно и идемпотентность — как у morning_brief,
но per-ISO-неделя. Переиспользует Telegram-пуш и токен из calendar_brief.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.core.leadstate import is_noise

log = logging.getLogger("tours_summary")

BISHKEK_UTC_OFFSET = 6
_OFFICE_STAGES = {"office", "office_consultation", "manager", "manager_handoff"}


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _is_tour(conv) -> bool:
    return (getattr(conv, "funnel", "") or "") == "tours"


def _destination(conv) -> str:
    q = getattr(conv, "qualification", None) or {}
    return (q.get("destination") or q.get("country") or "").strip()


def build_tours_summary(convs: list, now: datetime, *, days: int = 7) -> dict:
    """Собрать честную тур-сводку за последние `days` дней. Только факты + отдельно оценка ИИ."""
    now = _aware(now) or datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    leads = [c for c in convs
             if _is_tour(c) and not getattr(c, "archived", False)
             and not is_noise(c, now, settings)
             and (_aware(getattr(c, "last_message_at", None)) or now) >= since]

    total = len(leads)
    reached_office = sum(1 for c in leads if (getattr(c, "stage", "") or "") in _OFFICE_STAGES)
    # ПРОДАНО — только ручная отметка менеджера (факт), НЕ AI.
    sold_manual = sum(1 for c in leads if (getattr(c, "outcome", "") or "") == "won")
    lost_manual = sum(1 for c in leads if (getattr(c, "outcome", "") or "") == "lost")
    unmarked = total - sold_manual - lost_manual
    # Оценка ИИ — ОТДЕЛЬНО, с пометкой (никогда не выдаём за факт).
    ai_won = sum(1 for c in leads
                 if (getattr(c, "outcome", "") or "") not in ("won", "lost")
                 and (getattr(c, "outcome_inferred", "") or "") == "won")

    dests = Counter(d for c in leads if (d := _destination(c)))
    conv_pct = round(100 * sold_manual / total, 1) if total else 0.0
    return {
        "days": days,
        "week_label": f"{(now - timedelta(days=days)):%d.%m}–{now:%d.%m}",
        "total": total,
        "reached_office": reached_office,
        "sold_manual": sold_manual,
        "lost_manual": lost_manual,
        "unmarked": unmarked,
        "conversion_pct": conv_pct,
        "ai_won_estimate": ai_won,
        "top_destinations": dests.most_common(5),
    }


def render_tours_summary(s: dict) -> str:
    lines = [f"📊 Туры за неделю ({s['week_label']})", ""]
    lines.append(f"Новых лидов: {s['total']}")
    lines.append(f"Дошли до офиса/менеджера: {s['reached_office']}")
    lines.append(f"Продано (отметил менеджер): {s['sold_manual']}")
    if s["total"]:
        lines.append(f"Конверсия (продано/лиды): {s['conversion_pct']}%")
    if s["unmarked"]:
        lines.append(f"Без отметки исхода: {s['unmarked']} "
                     f"(конверсия точна только когда всё отмечено)")
    if s["ai_won_estimate"]:
        lines += ["", f"~ Оценка ИИ (НЕ подтверждено вручную): ещё ~{s['ai_won_estimate']} "
                      "похоже на продажу — для ориентира, не факт"]
    if s["top_destinations"]:
        lines += ["", "Топ-направления:"]
        for dest, n in s["top_destinations"]:
            lines.append(f"• {dest} — {n}")
    if s["total"] == 0:
        lines += ["", "За неделю туровых лидов не было."]
    return "\n".join(lines)


def _owner_recipients() -> list[tuple[str, str]]:
    """(login, chat_id) владельцев-админов с заданным личным Telegram."""
    out = []
    for mgr in settings.manager_list():
        chat_id = (getattr(mgr, "telegram_chat_id", "") or "").strip()
        if bool(getattr(mgr, "admin", False)) and chat_id:
            out.append(((mgr.login or "").strip().lower(), chat_id))
    return out


async def run(now: datetime | None = None, *, sessionmaker=None) -> None:
    """Scheduler-джоба: раз в неделю в утреннем окне шлёт тур-сводку владельцу.

    sessionmaker принят для единообразия с другими джобами (здесь не нужен)."""
    from app.core import flags
    from app.core.calendar_brief import _push_telegram, _token
    from app.integrations.panel.store import get_conversation_store

    if not await flags.get_flag("tours_summary_enabled", settings.tours_summary_enabled):
        return
    now = _aware(now) or datetime.now(timezone.utc)
    local = now + timedelta(hours=BISHKEK_UTC_OFFSET)
    # День недели и окно из настроек (по умолчанию понедельник, утро).
    if local.weekday() != settings.tours_summary_weekday:
        return
    if not (settings.morning_brief_hour <= local.hour < settings.morning_brief_hour + 3):
        return

    iso_year, iso_week, _ = local.isocalendar()
    sent_key = f"tours_summary_sent_{iso_year}w{iso_week}"
    if await flags.get_flag(sent_key, False):
        return

    recipients = _owner_recipients()
    if not recipients:
        await flags.set_flag(sent_key, True)   # некому слать → экран покрывает
        log.info("tours summary: no owner recipient with telegram_chat_id")
        return

    try:
        convs = await get_conversation_store().all_conversations()
        summary = build_tours_summary(convs, now)
        text = render_tours_summary(summary)
    except Exception:  # noqa: BLE001 — джоба не должна падать
        log.warning("tours summary build failed", exc_info=True)
        return

    token = _token()
    if not token:
        await flags.set_flag(sent_key, True)
        log.info("tours summary built (telegram off) total=%d sold=%d",
                 summary["total"], summary["sold_manual"])
        return

    ok_any = False
    for login, chat_id in recipients:
        if await _push_telegram(token, chat_id, text):
            ok_any = True
            log.info("tours summary sent owner=%s total=%d sold=%d",
                     login, summary["total"], summary["sold_manual"])
    if ok_any:
        await flags.set_flag(sent_key, True)   # флаг только при успехе → ретрай на след. тик
