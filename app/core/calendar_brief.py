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
from app.core.manager_scope import bot_scope_for
from app.core.morning_brief import (
    BISHKEK_UTC_OFFSET, SEND_WINDOW_HOURS, _FUNNEL_LABEL, _direction, _fmt_wait,
    _name, _wait_minutes,
)

log = logging.getLogger("calendar_brief")

NIGHT_REQUEST_CAP = 15
# Сводка владельца: клиент, ждущий ответа дольше этого, считается «висяком».
OWNER_STALE_HOURS = 24
# Порядок направлений в сводке; всё неизвестное падает в «Прочее» последним.
OWNER_DIGEST_ORDER = ["visa", "tours", "tickets"]
OWNER_DIGEST_MANAGER_CAP = 6
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


def _phone_display(user_id: str) -> str:
    """+996 555 12 34 56 — тапом по номеру в Telegram менеджер сразу звонит.
    Иностранные/короткие номера отдаём как есть, лишь бы с плюсом."""
    d = "".join(ch for ch in (user_id or "").split(":")[-1] if ch.isdigit())
    if len(d) == 12 and d.startswith("996"):
        return f"+{d[:3]} {d[3:6]} {d[6:8]} {d[8:10]} {d[10:]}"
    return f"+{d}" if d else ""


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
        "phone": _phone_display(task.user_id),
        "wa_link": _wa_link(task.user_id or ""),
        "comment": (task.comment or "").strip(),
        "context": (task.ai_summary or "").strip(),   # AI-written context recap only
        "direction": task.direction,
    }


def _is_open_lead(conv) -> bool:
    """A live lead still in play (not marked won/lost)."""
    return (getattr(conv, "outcome", "") or "") not in ("won", "lost")


def _owner_login(conv) -> str:
    """Active owner login of a conversation (empty = unassigned)."""
    return (getattr(conv, "assigned_to", "") or "").strip().lower()


def _last_activity(conv) -> datetime | None:
    """Момент последней активности диалога (для фильтра свежести)."""
    return _aware(getattr(conv, "last_message_at", None))


def _is_recent(conv, now: datetime, hours: int) -> bool:
    """Диалог активен за последние `hours` часов (свежий → в список на обзвон).

    Нет отметки времени → считаем свежим (не прячем клиента из-за пустого поля)."""
    last = _last_activity(conv)
    if last is None:
        return True
    return (now - last) <= timedelta(hours=hours)


def _wa_link(user_id: str) -> str:
    """Прямая ссылка «написать в WhatsApp» (wa.me/<цифры номера>). Пусто, если не номер."""
    tail = "".join(ch for ch in (user_id or "").split(":")[-1] if ch.isdigit())
    return f"https://wa.me/{tail}" if len(tail) >= 10 else ""


def _lead_card(conv, now: datetime) -> dict:
    uid = getattr(conv, "user_id", "")
    known_name = ((getattr(conv, "qualification", None) or {}).get("name") or "").strip()
    return {
        "user_id": uid,
        "name": _name(conv),
        # Шапка строки: «Имя · +996 …» либо просто номер — «Без имени · 4386» бесполезно,
        # звонить по нему нельзя.
        "head": f"{known_name} · {_phone_display(uid)}".strip(" ·") if known_name
                else (_phone_display(uid) or _name(conv)),
        "direction": _direction(conv),
        "wait_min": int(_wait_minutes(conv, now)),
        "wait_label": _fmt_wait(int(_wait_minutes(conv, now))),
        "wa_link": _wa_link(getattr(conv, "user_id", "")),
    }


def build_manager_brief(login: str, name: str, tasks: list, night_requests: list,
                        now: datetime | None = None, *,
                        to_distribute: list | None = None) -> dict:
    """Assemble one manager's brief.

    tasks — their active CalendarTask rows for today.
    night_requests — overnight leads ASSIGNED to this manager (owner-routed; never
        duplicated across managers).
    to_distribute — UNASSIGNED overnight leads, passed ONLY for a full-admin and shown
        in a separate "Требуют распределения" section. No assignment happens here.
    """
    now = _aware(now) or datetime.now(timezone.utc)
    local = now + timedelta(hours=BISHKEK_UTC_OFFSET)
    by_kind: dict[str, list] = {}
    for t in tasks:
        by_kind.setdefault(t.kind, []).append(_task_card(t))
    # Дольше всех ждёт — наверху (самый горячий клиент первым, не потеряется под капом).
    night = sorted((_lead_card(c, now) for c in night_requests),
                   key=lambda c: c["wait_min"], reverse=True)
    distribute = sorted((_lead_card(c, now) for c in (to_distribute or [])),
                        key=lambda c: c["wait_min"], reverse=True)
    return {
        "login": login,
        "name": name or login,
        "date_label": local.strftime("%d.%m"),
        "by_kind": by_kind,
        "task_count": len(tasks),
        "night": night[:NIGHT_REQUEST_CAP],
        "night_count": len(night),
        "to_distribute": distribute[:NIGHT_REQUEST_CAP],
        "to_distribute_count": len(distribute),
        "generated_at": now,
    }


def _conv_direction(conv) -> str:
    """Направление диалога по воронке. Пусто → «прочее» (не молчим о таких лидах)."""
    return (getattr(conv, "funnel", "") or "").strip().lower() or "other"


def _task_direction(task) -> str:
    return (getattr(task, "direction", "") or "").strip().lower() or "other"


def _empty_direction_row() -> dict:
    return {"open": 0, "fresh": 0, "waiting": 0, "waiting_stale": 0, "unassigned": 0,
            "tasks_today": 0, "tasks_overdue": 0, "by_manager": {}}


def build_owner_digest(convs: list, tasks: list, now: datetime | None = None, *,
                       lookback_hours: int, day=None,
                       stale_hours: int = OWNER_STALE_HOURS) -> dict:
    """Утренняя сводка ПО ВСЕЙ КОМПАНИИ для владельца/руководителя (full-admin).

    Личный блок брифа отвечает на «что делать мне», а этот — на «что происходит по
    визам и по турам»: сколько пришло за ночь, сколько клиентов ждёт ответа, что
    висит без владельца и как загружена команда. Считает по ОТКРЫТЫМ (не won/lost,
    не архивным) диалогам — то же определение лида, что и в остальном брифе.

    convs — все живые диалоги; tasks — активные задачи ВСЕХ менеджеров по день `day`
    включительно (просрочка = активная задача со вчера и раньше).
    """
    now = _aware(now) or datetime.now(timezone.utc)
    rows: dict[str, dict] = {}

    for conv in convs:
        if not _is_open_lead(conv):
            continue
        row = rows.setdefault(_conv_direction(conv), _empty_direction_row())
        row["open"] += 1
        if not _owner_login(conv):
            row["unassigned"] += 1
        last = _last_activity(conv)
        # Строгая свежесть: без отметки времени лид в «пришло за ночь» не попадает,
        # иначе счётчик раздувается старьём с пустым полем.
        if last is not None and (now - last) <= timedelta(hours=lookback_hours):
            row["fresh"] += 1
        wait = _wait_minutes(conv, now)
        if wait > 0:
            row["waiting"] += 1
            if wait >= stale_hours * 60:
                row["waiting_stale"] += 1

    for task in tasks:
        row = rows.setdefault(_task_direction(task), _empty_direction_row())
        scheduled = getattr(task, "scheduled_date", None)
        if day is not None and scheduled is not None and scheduled < day:
            row["tasks_overdue"] += 1
        else:
            row["tasks_today"] += 1
        owner = (getattr(task, "manager_id", "") or "").strip().lower()
        if owner:
            row["by_manager"][owner] = row["by_manager"].get(owner, 0) + 1

    order = {key: i for i, key in enumerate(OWNER_DIGEST_ORDER)}
    directions = []
    for key in sorted(rows, key=lambda k: (order.get(k, len(order)), k)):
        row = rows[key]
        by_manager = sorted(row["by_manager"].items(), key=lambda kv: (-kv[1], kv[0]))
        directions.append({**row, "key": key,
                           "label": _FUNNEL_LABEL.get(key, "Прочее"),
                           "by_manager": by_manager[:OWNER_DIGEST_MANAGER_CAP]})
    local = now + timedelta(hours=BISHKEK_UTC_OFFSET)
    return {"date_label": local.strftime("%d.%m"), "directions": directions,
            "stale_hours": stale_hours}


def render_owner_digest_text(digest: dict) -> str:
    """Текстовый блок сводки. Пусто, если считать нечего — не шлём заголовок впустую."""
    if not digest["directions"]:
        return ""
    lines = [f"🏢 По компании · {digest['date_label']}"]
    for d in digest["directions"]:
        lines += ["", f"{d['label']} · открытых {d['open']}"]
        if d["fresh"]:
            lines.append(f"  🌙 новых за ночь: {d['fresh']}")
        if d["waiting"]:
            tail = (f" (дольше {digest['stale_hours']} ч: {d['waiting_stale']})"
                    if d["waiting_stale"] else "")
            lines.append(f"  ⏳ ждут ответа: {d['waiting']}{tail}")
        if d["unassigned"]:
            lines.append(f"  📥 без владельца: {d['unassigned']}")
        if d["tasks_today"] or d["tasks_overdue"]:
            tail = f" · просрочено {d['tasks_overdue']}" if d["tasks_overdue"] else ""
            lines.append(f"  📅 задач на сегодня: {d['tasks_today']}{tail}")
        if d["by_manager"]:
            who = " · ".join(f"{login} {count}" for login, count in d["by_manager"])
            lines.append(f"  👤 {who}")
    return "\n".join(lines)


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
            head = f"• {c['time']} · {c.get('phone') or c['client']}"
            if c["priority"] == "high":
                head += " 🔴"
            lines.append(head)
            if c["comment"]:
                lines.append(f"    {c['comment']}")
            if c["context"]:
                lines.append(f"    ℹ {c['context']}")
            if c.get("wa_link"):
                lines.append(f"    💬 {c['wa_link']}")
            if c["user_id"]:
                lines.append(f"    {_client_link(c['user_id'], base_url)}")
    if brief["night"]:
        lines += ["", f"🌙 Ночные заявки без точного времени ({brief['night_count']}):"]
        for c in brief["night"]:
            tail = f" · {c['wait_label']}" if c["wait_label"] else ""   # уже «ждёт N ч»
            lines.append(f"• {c.get('head') or c['name']} · {c['direction']}{tail}")
            if c.get("wa_link"):
                lines.append(f"    💬 написать: {c['wa_link']}")
            if c["user_id"]:
                lines.append(f"    открыть: {_client_link(c['user_id'], base_url)}")
    # Full-admin only: unassigned leads awaiting distribution (no assignment done here).
    if brief["to_distribute"]:
        lines += ["", f"📥 Требуют распределения ({brief['to_distribute_count']}):"]
        for c in brief["to_distribute"]:
            tail = f" · {c['wait_label']}" if c["wait_label"] else ""
            lines.append(f"• {c.get('head') or c['name']} · {c['direction']}{tail}")
            if c["user_id"]:
                lines.append(f"    {_client_link(c['user_id'], base_url)}")
    if brief["task_count"] == 0 and not brief["night"] and not brief["to_distribute"]:
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


async def _tasks_for(login: str, day, sessionmaker) -> list:
    from app.domain.calendar_tasks import CalendarTaskService
    async with sessionmaker() as session:
        return await CalendarTaskService.today_for_manager(session, login, day)


async def _all_tasks(day, sessionmaker) -> list:
    """Активные задачи ВСЕХ менеджеров по сегодня включительно (для сводки владельца).

    Окно назад ограничено: просрочка старше месяца — это уже не утренняя сводка."""
    from datetime import timedelta as _td

    from app.domain.calendar_tasks import CalendarTaskService
    async with sessionmaker() as session:
        return await CalendarTaskService.list_all(
            session, date_from=day - _td(days=30), date_to=day)


async def _materialize_call_tasks(login: str, night_convs: list, day, sessionmaker) -> int:
    """Bot auto-creates a 'call' task (created_by='bot') for each owner-routed overnight
    lead, so the morning call-list lands in the manager's calendar without manual entry.

    Idempotent by construction: the caller's ``night`` set already excludes leads that
    have a task today. Best-effort — a domain error on one lead never blocks the rest or
    the brief send. Returns how many tasks were created."""
    from app.domain.calendar_tasks import CalendarTaskService
    from app.domain.models import DIRECTIONS
    from app.domain.services import ContactService
    created = 0
    try:
        async with sessionmaker() as s:
            for c in night_convs:
                # Same as admin task_create: phone if known, else the user_id — normalize_phone
                # strips the bot prefix and validates; bad/short numbers raise → skipped below.
                ident = (getattr(c, "phone", "") or getattr(c, "user_id", "") or "").strip()
                if not ident:
                    continue
                direction = (getattr(c, "funnel", "") or "tours").strip()
                if direction not in DIRECTIONS:
                    direction = "tours"
                try:
                    contact = await ContactService.find_or_create_by_identity(s, "phone", ident)
                    await CalendarTaskService.create(
                        s, manager_id=login, direction=direction, kind="call",
                        scheduled_date=day, scheduled_at=None, contact_id=contact.id,
                        user_id=getattr(c, "user_id", "") or "", priority="normal",
                        comment="Автозадача: перезвонить по ночной заявке", created_by="bot")
                    created += 1
                except Exception:  # noqa: BLE001 — one lead's failure must not block others
                    log.warning("calendar autotask failed user=%s",
                                getattr(c, "user_id", "?"), exc_info=True)
            await s.commit()
    except Exception:  # noqa: BLE001 — auto-task must never break the brief flow
        log.warning("calendar autotask batch failed manager=%s", login, exc_info=True)
    if created:
        log.info("calendar autotask created=%d manager=%s", created, login)
    return created


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
    autotask_on = await flags.get_flag(
        "calendar_autotask_enabled", cfg.calendar_autotask_enabled)

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
            convs = await store.all_conversations_light()
            is_admin = bot_scope_for(
                {"login": mgr.login, "name": mgr.name, "admin": bool(mgr.admin)},
                admin_user=cfg.admin_user) is None
            lookback = cfg.night_lookback_hours
            # Клиенты, на кого уже есть задача сегодня — не дублируем в «ночных».
            task_uids = {(getattr(t, "user_id", "") or "") for t in tasks}

            def _is_night(c) -> bool:
                # Список на обзвон: открытый лид + свежая активность (за ночь/вечер) +
                # ещё не запланирован задачей. Не весь пайплайн, а «кто написал недавно».
                return (_is_open_lead(c) and _is_recent(c, now, lookback)
                        and getattr(c, "user_id", "") not in task_uids)

            # Owner-routed: назначенный ночной лид идёт ТОЛЬКО своему владельцу.
            night = [c for c in convs if _is_night(c) and _owner_login(c) == login]
            # Неназначенные свежие лиды видит только full-admin (раздел «Требуют распределения»).
            to_distribute = ([c for c in convs if _is_night(c) and not _owner_login(c)]
                             if is_admin else [])
        except Exception:  # noqa: BLE001 — one manager's data error must not block others
            log.warning("calendar brief build failed for manager=%s", login, exc_info=True)
            continue

        brief = build_manager_brief(login, mgr.name or login, tasks, night, now,
                                    to_distribute=to_distribute)
        text = render_manager_brief_text(brief, cfg.admin_base_url)

        # Владелец/руководитель дополнительно видит срез по ОБОИМ направлениям —
        # личный блок отвечает «что делать мне», сводка «что происходит в компании».
        if is_admin:
            try:
                digest = build_owner_digest(convs, await _all_tasks(day, sessionmaker),
                                            now, lookback_hours=lookback, day=day)
                block = render_owner_digest_text(digest)
                if block:
                    text = f"{text}\n\n{block}"
            except Exception:  # noqa: BLE001 — сводка не должна ломать личный бриф
                log.warning("owner digest failed for manager=%s", login, exc_info=True)

        if not token:
            await flags.set_flag(sent_key, True)   # nowhere to send → screen covers it
            if autotask_on:
                await _materialize_call_tasks(login, night, day, sessionmaker)
            log.info("calendar brief built (telegram off) manager=%s tasks=%d night=%d",
                     login, brief["task_count"], brief["night_count"])
            continue

        if await _push_telegram(token, chat_id, text):
            await flags.set_flag(sent_key, True)   # flag only on success → retry next tick
            if autotask_on:
                await _materialize_call_tasks(login, night, day, sessionmaker)
            log.info("calendar brief sent manager=%s tasks=%d night=%d",
                     login, brief["task_count"], brief["night_count"])
