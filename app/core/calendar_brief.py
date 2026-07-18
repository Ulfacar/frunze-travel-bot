"""Sprint 1: personal calendar Morning Brief per manager.

Once a day in the Bishkek morning window, sends each manager THEIR tasks for today
(calls/meetings/office visits) plus a separate "ночные заявки без точного времени"
block, to their PERSONAL Telegram chat (`ManagerConfig.telegram_chat_id`). Managers
without a chat id are skipped (the /admin/calendar screen still works); nothing is
sent to the shared group.

Reuses the hot-list scheduler conventions: Bishkek send window `[morning_brief_hour,
+3)`, dated idempotency flag (here PER MANAGER), fail-safe push. Separate feature flag
`calendar_brief_enabled` (default OFF). No Bitrix, no new dependency.

Secrets: `telegram_chat_id` is never logged.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.config import settings
from app.core.manager_scope import bot_scope_for, conversation_in_scope
from app.core.morning_brief import (
    BISHKEK_UTC_OFFSET, SEND_WINDOW_HOURS, _direction, _fmt_wait, _name,
    _needs_human, _wait_minutes,
)

log = logging.getLogger("calendar_brief")

NIGHT_REQUEST_CAP = 15
_KIND_LABEL = {"call": "📞 Звонки", "meeting": "🤝 Встречи",
               "office_visit": "🏢 Визиты в офис", "followup": "🔁 Повторные касания",
               "other": "📋 Другое"}
_KIND_ORDER = ["call", "meeting", "office_visit", "followup", "other"]


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _phone_tail(user_id: str) -> str:
    phone = (user_id or "").split(":")[-1]
    return phone[-4:] if phone else "—"


def _task_time_label(task) -> str:
    at = _aware(getattr(task, "scheduled_at", None))
    if at is None:
        return "без времени"
    return (at + timedelta(hours=BISHKEK_UTC_OFFSET)).strftime("%H:%M")


def _task_card(task) -> dict:
    return {
        "kind": task.kind,
        "priority": task.priority,
        "status": task.status,
        "time": _task_time_label(task),
        "user_id": task.user_id or "",
        "client": _phone_tail(task.user_id),
        "comment": (task.comment or "").strip(),
        "context": (task.ai_summary or "").strip(),   # AI-written context recap only
        "direction": task.direction,
    }


def build_manager_brief(login: str, name: str, tasks: list, night_requests: list,
                        now: datetime | None = None) -> dict:
    """Assemble one manager's brief. tasks — their active CalendarTask rows for today;
    night_requests — unowned overnight leads (ConversationView) in their scope."""
    now = _aware(now) or datetime.now(timezone.utc)
    local = now + timedelta(hours=BISHKEK_UTC_OFFSET)
    by_kind: dict[str, list] = {}
    for t in tasks:
        by_kind.setdefault(t.kind, []).append(_task_card(t))
    night = []
    for c in night_requests:
        night.append({
            "user_id": getattr(c, "user_id", ""),
            "name": _name(c),
            "direction": _direction(c),
            "wait_label": _fmt_wait(int(_wait_minutes(c, now))),
        })
    return {
        "login": login,
        "name": name or login,
        "date_label": local.strftime("%d.%m"),
        "by_kind": by_kind,
        "task_count": len(tasks),
        "night": night[:NIGHT_REQUEST_CAP],
        "night_count": len(night),
        "generated_at": now,
    }


def _client_link(user_id: str, base_url: str) -> str:
    path = f"/admin/conversation/{user_id}"
    base = (base_url or "").rstrip("/")
    return f"{base}{path}" if base else path


def render_manager_brief_text(brief: dict, base_url: str = "") -> str:
    lines = [f"📅 План на {brief['date_label']} · {brief['name']}",
             f"Задач сегодня: {brief['task_count']}"]
    for kind in _KIND_ORDER:
        cards = brief["by_kind"].get(kind)
        if not cards:
            continue
        lines += ["", _KIND_LABEL.get(kind, kind)]
        for c in cards:
            head = f"• {c['time']} · {c['client']}"
            if c["priority"] == "high":
                head += " 🔴"
            lines.append(head)
            if c["comment"]:
                lines.append(f"    {c['comment']}")
            if c["context"]:
                lines.append(f"    ℹ {c['context']}")
            if c["user_id"]:
                lines.append(f"    {_client_link(c['user_id'], base_url)}")
    if brief["night"]:
        lines += ["", f"🌙 Ночные заявки без точного времени ({brief['night_count']}):"]
        for c in brief["night"]:
            tail = f" · {c['wait_label']}" if c["wait_label"] else ""
            lines.append(f"• {c['name']} · {c['direction']}{tail}")
            if c["user_id"]:
                lines.append(f"    {_client_link(c['user_id'], base_url)}")
    if brief["task_count"] == 0 and not brief["night"]:
        lines += ["", "На сегодня задач и новых заявок нет ☕"]
    return "\n".join(lines)


def _token() -> str:
    return (settings.managers_telegram_bot_token or settings.telegram_bot_token or "").strip()


async def _push_telegram(token: str, chat_id: str, text: str) -> bool:
    """Send one manager's brief. Returns True on success. chat_id is never logged."""
    try:
        from app.channels.telegram import TelegramAdapter
        await TelegramAdapter(token).send(chat_id, text)
        return True
    except Exception:  # noqa: BLE001 — push must not break the scheduler
        log.warning("calendar brief push failed for manager=%s", "<redacted-chat>",
                    exc_info=True)
        return False


async def _night_requests_for(scope: set[str] | None, store) -> list:
    convs = await store.all_conversations_light()
    return [c for c in convs if _needs_human(c)
            and conversation_in_scope(getattr(c, "bot_id", "") or "",
                                      getattr(c, "user_id", "") or "", scope)]


async def _tasks_for(login: str, day, sessionmaker) -> list:
    from app.domain.calendar_tasks import CalendarTaskService
    async with sessionmaker() as session:
        return await CalendarTaskService.today_for_manager(session, login, day)


async def run(now: datetime | None = None, *, sessionmaker=None) -> None:
    """Scheduler job: personal calendar brief to each manager with a telegram_chat_id.

    now / sessionmaker are for tests (time + domain-DB injection)."""
    from app.core import flags
    from app.domain.calendar_tasks import bishkek_today
    from app.integrations.panel.store import get_conversation_store

    cfg = settings
    if not await flags.get_flag("calendar_brief_enabled", cfg.calendar_brief_enabled):
        return

    now = _aware(now) or datetime.now(timezone.utc)
    local = now + timedelta(hours=BISHKEK_UTC_OFFSET)
    if not (cfg.morning_brief_hour <= local.hour < cfg.morning_brief_hour + SEND_WINDOW_HOURS):
        return

    token = _token()
    store = get_conversation_store()
    if sessionmaker is None:
        from app.integrations.crm.db import get_sessionmaker
        sessionmaker = get_sessionmaker()
    day = bishkek_today(now)

    for mgr in cfg.manager_list():
        login = (mgr.login or "").strip().lower()
        chat_id = (getattr(mgr, "telegram_chat_id", "") or "").strip()
        if not login or not chat_id:
            continue                       # no personal chat → screen-only, never the group

        sent_key = f"calendar_brief_sent_{login}_{local:%Y%m%d}"
        if await flags.get_flag(sent_key, False):
            continue

        try:
            tasks = await _tasks_for(login, day, sessionmaker)
            scope = bot_scope_for({"login": mgr.login, "name": mgr.name,
                                   "admin": bool(mgr.admin)}, admin_user=cfg.admin_user)
            night = await _night_requests_for(scope, store)
        except Exception:  # noqa: BLE001 — one manager's data error must not block others
            log.warning("calendar brief build failed for manager=%s", login, exc_info=True)
            continue

        brief = build_manager_brief(login, mgr.name or login, tasks, night, now)
        text = render_manager_brief_text(brief, cfg.admin_base_url)

        if not token:
            await flags.set_flag(sent_key, True)   # nowhere to send → screen covers it
            log.info("calendar brief built (telegram off) manager=%s tasks=%d night=%d",
                     login, brief["task_count"], brief["night_count"])
            continue

        if await _push_telegram(token, chat_id, text):
            await flags.set_flag(sent_key, True)   # flag only on success → retry next tick
            log.info("calendar brief sent manager=%s tasks=%d night=%d",
                     login, brief["task_count"], brief["night_count"])
