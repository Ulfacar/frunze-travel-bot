"""Страница «Сводка пилота» для руководителя направления (флаг `panel_pilot_summary_enabled`).

Гриша ведёт пилот менеджерской учёткой, а `/admin/analytics` открыт только полному
админу — цифр он не видел вовсе. Здесь: за сегодня, вчера и 7 дней по направлению —
новые обращения, ответы из панели, ожидание дольше X минут, максимальное ожидание,
ошибки отправки и «неизвестно», продажи; разрез по менеджерам; любая цифра раскрывается
в список диалогов (ТЗ REPORT-05). Расчёт — `app/core/pilot_summary.py`.

Права (сервер):
* полный админ — оба направления;
* руководитель направления — логин в `PANEL_DIRECTION_LEADS` (`{"visa": ["grisha"]}`),
  и только если его собственный скоуп покрывает это направление;
* остальные — 403. Направление из query, которое не разрешено, — 403 (не «тихо своё»).
В агрегатах нет имён и номеров; в раскрытии — как в обычном списке диалогов.
"""
from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote, urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from app.admin import router as ar
from app.config import settings
from app.core import pilot_summary as ps

FLAG = "panel_pilot_summary_enabled"
DIRECTIONS = (("visa", "Визы"), ("tours", "Туры и билеты"))
LIST_CAP = 200


def allowed_directions(manager: dict | None) -> list[str]:
    from app.core.live_authz import actor_for
    actor = actor_for(manager)
    if actor.is_full_admin:
        return [d for d, _ in DIRECTIONS]
    login = str((manager or {}).get("login") or "").strip().lower()
    leads = settings.panel_direction_leads or {}
    return [d for d, _ in DIRECTIONS
            if d in actor.allowed_directions
            and login in {str(x).strip().lower() for x in (leads.get(d) or [])}]


def bots_for(direction: str) -> set[str]:
    from app.core.live_authz import _FALLBACK_DIRECTIONS, direction_for_bot
    known = ({b.id for b in settings.bots} | {b.id for b in settings.telegram_bots}
             | set(_FALLBACK_DIRECTIONS))
    return {b for b in known if direction_for_bot(b) == direction}


async def _sales_action_runtime() -> str:
    on = await ar._media_flag("sale_by_full_payment_enabled")
    return "sale_full_payment" if on else "outcome"


@ar.router.get("/pilot-summary", response_class=HTMLResponse)
async def pilot_summary(request: Request, direction: str = "", period: str = "today",
                        metric: str = "", who: str = "",
                        manager: dict = Depends(ar.require_admin)):
    if settings.crm_standalone_enabled or not await ar._media_flag(FLAG):
        raise HTTPException(status_code=404)
    allowed = allowed_directions(manager)
    if not allowed:
        raise HTTPException(status_code=403, detail="Сводка — для руководителя направления")
    direction = direction or allowed[0]
    if direction not in allowed:
        raise HTTPException(status_code=403, detail="Нет доступа к этому направлению")
    periods = dict(ps.PERIODS)
    period = period if period in periods else "today"
    metrics = dict(ps.METRICS)
    if metric and metric not in metrics:
        raise HTTPException(status_code=422)
    sla = int(settings.pilot_reply_sla_minutes)
    sales_action = await _sales_action_runtime()
    now = datetime.now(timezone.utc)
    week_start, _ = ps.period_bounds("week", now)
    # Только боты, которые этот человек и так видит: руководитель не получает цифр по
    # номерам вне своего скоупа (у Адеми — `frunze_tours`, но не номер Айсины).
    bots = bots_for(direction)
    scope = ar._manager_bot_scope(manager)
    if scope is not None:
        bots &= set(scope)
    dialogs, audit = await ps.load(bots, week_start, now)
    results = {}
    for key, _label in ps.PERIODS:
        start, end = ps.period_bounds(key, now)
        rows = [r for r in audit if r.get("created_at") is None
                or start <= ps._aware(r["created_at"]) < end]
        results[key] = ps.compute(dialogs, rows, start, end, sla=sla, sales_action=sales_action)
    current = results[period]
    listing = None
    if metric:
        source = (current["per_ids"].get(who, {}).get(metric, set()) if who
                  else current["ids"][metric])
        store = ar.get_conversation_store()
        rows = []
        for uid in sorted(source)[:LIST_CAP]:
            conv = await store.get(uid)
            if conv is None or not ar._can_view_conversation(conv, manager):
                continue
            rows.append({"open_url": "/admin?open=" + quote(uid, safe=""),
                         "name": (conv.qualification or {}).get("name") or "",
                         "phone": conv.phone or uid.split(":")[-1],
                         "owner": conv.assigned_to or "", "bot": conv.bot_id,
                         "last_text": conv.last_text or "", "last_sender": conv.last_sender or "",
                         "last_at": conv.last_message_at})
        listing = {"metric": metric, "label": metrics[metric].format(sla=sla), "who": who,
                   "rows": rows, "total": len(source)}

    def link(**kw):
        q = {"direction": direction, "period": period, **kw}
        return "/admin/pilot-summary?" + urlencode({k: v for k, v in q.items() if v})
    return ar.templates.TemplateResponse(request, "pilot_summary.html", {
        "manager": manager, "direction": direction, "period": period, "sla": sla,
        "directions": [(d, label) for d, label in DIRECTIONS if d in allowed],
        "periods": ps.PERIODS, "metrics": [(k, v.format(sla=sla)) for k, v in ps.METRICS],
        "results": results, "current": current, "listing": listing, "link": link,
        "sales_rule": ("полная оплата по договору" if sales_action == "sale_full_payment"
                       else "отметка «Продажа состоялась»"),
    }, headers={"Cache-Control": "no-store"})
