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
* менеджер — только свои закреплённые диалоги в доступном направлении;
* направление или чужой менеджер из query вне доступа — 403.
В агрегатах нет имён и номеров; в раскрытии — как в обычном списке диалогов.
"""
from __future__ import annotations

from datetime import datetime, timezone
import secrets
import hmac
from urllib.parse import quote, urlencode

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.admin import router as ar
from app.config import settings
from app.core import pilot_summary as ps

FLAG = "panel_pilot_summary_enabled"
DIRECTIONS = (("visa", "Визы"), ("tours", "Туры и билеты"))
LIST_CAP = 200


def _phone_human(value) -> str:
    """Номер читаемо для простого режима: «+996 555 80 00 01» (ревью ux, P2).

    Фильтр простого режима `router._phone_human` живёт в ветке ux; если он есть — берём
    его, чтобы номер выглядел так же, как в остальной панели."""
    shared = getattr(ar, "_phone_human", None)
    if shared is not None:
        return shared(value)
    raw = str(value or "").strip()
    if not (raw.isdigit() and len(raw) >= 9):
        return raw
    if len(raw) == 12 and raw.startswith("996"):
        return f"+{raw[:3]} {raw[3:6]} {raw[6:8]} {raw[8:10]} {raw[10:]}"
    return f"+{raw}"


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
    if settings.report_sale_definition == "full_payment":
        return "report_full_payment"
    if settings.report_sale_definition == "prepayment":
        return "report_prepayment"
    if settings.report_sale_definition != "legacy":
        raise HTTPException(status_code=503, detail="Некорректное определение продажи в настройках отчёта")
    on = await ar._media_flag("sale_by_full_payment_enabled")
    return "sale_full_payment" if on else "outcome"


@ar.router.get("/pilot-summary", response_class=HTMLResponse)
async def pilot_summary(request: Request, direction: str = "", period: str = "today",
                        metric: str = "", who: str = "",
                        manager: dict = Depends(ar.require_admin)):
    if settings.crm_standalone_enabled or not await ar._media_flag(FLAG):
        raise HTTPException(status_code=404)
    allowed = allowed_directions(manager)
    lead_directions = list(allowed)
    from app.core.live_authz import actor_for
    actor = actor_for(manager)
    allowed = sorted(set(allowed) | (set(actor.allowed_directions) & {d for d, _ in DIRECTIONS}))
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
    week_start, _ = ps.period_bounds("month", now)
    # Только боты, которые этот человек и так видит: руководитель не получает цифр по
    # номерам вне своего скоупа (у Адеми — `frunze_tours`, но не номер Айсины).
    bots = bots_for(direction)
    scope = ar._manager_bot_scope(manager)
    if scope is not None:
        bots &= set(scope)
    dialogs, audit = await ps.load(bots, week_start, now)
    personal = direction not in lead_directions
    if personal:
        dialogs = [d for d in dialogs if d.owner.strip().lower() == actor.manager_id]
        if who and who != actor.manager_id:
            raise HTTPException(status_code=403)
        audit = [r for r in audit if r.get("action") not in ps.PANEL_SENDS
                 or (r.get("manager") or "").strip().lower() == actor.manager_id]
    from app.core import report_catalog
    from app.core.report_metrics import acquisition
    creative_names = report_catalog.names(settings.report_catalog_path, direction)
    results = {}
    for key, _label in ps.PERIODS:
        start, end = ps.period_bounds(key, now)
        rows = [r for r in audit if r.get("created_at") is None
                or start <= ps._aware(r["created_at"]) < end]
        results[key] = ps.compute(dialogs, rows, start, end, sla=sla, sales_action=sales_action)
        r = results[key]
        r["acquisition"] = acquisition(dialogs, r["ids"]["new"], r["ids"]["sales"], creative_names)
    current = results[period]
    finance = None
    finance_note = "Договоры и задачи недоступны в этом хранилище."
    from app.integrations.panel.store import get_conversation_store
    store = get_conversation_store()
    if getattr(store, "_conv", None) is None:
        if not personal and bots != bots_for(direction):
            finance_note = "Денежный отчёт требует доступа ко всему направлению."
        else:
            from app.core.report_finance import load as load_finance
            from sqlalchemy.exc import SQLAlchemyError
            try:
                finance = await load_finance(ps._sessionmaker(store), direction,
                                             actor.manager_id if personal else None,
                                             now)
            except (SQLAlchemyError, OSError):
                finance_note = "Не удалось прочитать договоры и задачи. Итоги не подменены нулями."
    if sales_action in ("report_prepayment", "report_full_payment"):
        if finance is None:
            raise HTTPException(status_code=503, detail="Для продаж по оплате нужен доступный журнал договоров")
        from app.admin.contracts import _identity
        from app.domain.models import DomainError
        views = await ps.cards([d.user_id for d in dialogs])
        seen = set()
        for d in sorted(dialogs, key=lambda d: (ps._aware(d.created_at) or now, d.user_id)):
            conv = views.get(d.user_id)
            if conv is None:
                continue
            try:
                identity = _identity(conv)
            except DomainError:
                continue
            sale = finance["prepayments" if sales_action == "report_prepayment" else "full_payments"].get(identity)
            if sale is None:
                continue
            contact_id, paid_at = sale
            if contact_id in seen or d.created_at is None or ps._aware(d.created_at) > paid_at:
                continue
            seen.add(contact_id)
            audit.append({"action": sales_action, "user_id": d.user_id,
                          "manager": d.owner, "created_at": paid_at})
        for key, _label in ps.PERIODS:
            start, end = ps.period_bounds(key, now)
            results[key] = ps.compute(dialogs, audit, start, end, sla=sla, sales_action=sales_action)
            r = results[key]
            r["acquisition"] = acquisition(dialogs, r["ids"]["new"], r["ids"]["sales"], creative_names)
        current = results[period]
    online_code = settings.report_online_consultation_outcome
    start, end = ps.period_bounds(period, now)
    visible_ids = {d.user_id for d in dialogs}
    online = (len({r["user_id"] for r in audit if r.get("user_id") in visible_ids
                   and r.get("action") == "outcome" and r.get("detail") == online_code
                   and r.get("created_at") is not None and start <= ps._aware(r["created_at"]) < end})
              if online_code else None)
    listing = None
    if metric:
        source = (current["per_ids"].get(who, {}).get(metric, set()) if who
                  else current["ids"][metric])
        wanted = sorted(source)[:LIST_CAP]
        views = await ps.cards(wanted)
        rows = []
        for uid in wanted:
            conv = views.get(uid)
            if conv is None or not ar._can_view_conversation(conv, manager):
                continue
            phone = conv.phone or uid.split(":")[-1]
            rows.append({"open_url": "/admin?open=" + quote(uid, safe=""),
                         "name": (conv.qualification or {}).get("name") or "",
                         "phone": phone, "phone_h": _phone_human(phone),
                         "owner": conv.assigned_to or "", "bot": conv.bot_id,
                         "last_text": conv.last_text or "", "last_sender": conv.last_sender or "",
                         "last_at": conv.last_message_at})
        listing = {"metric": metric, "label": metrics[metric].format(sla=sla), "who": who,
                   "rows": rows, "total": len(source)}

    def link(**kw):
        q = {"direction": direction, "period": period, **kw}
        return "/admin/pilot-summary?" + urlencode({k: v for k, v in q.items() if v})
    if "report_csrf" not in request.session:
        request.session["report_csrf"] = secrets.token_hex(32)
    return ar.templates.TemplateResponse(request, "pilot_summary.html", {
        "report_csrf": request.session["report_csrf"], "can_edit_creatives": not personal,
        "finance": finance, "finance_note": finance_note,
        "online": online,
        "manager": manager, "direction": direction, "period": period, "sla": sla,
        "directions": [(d, label) for d, label in DIRECTIONS if d in allowed],
        "periods": ps.PERIODS, "metrics": [(k, v.format(sla=sla)) for k, v in ps.METRICS],
        "results": results, "current": current, "listing": listing, "link": link,
        "sales_rule": ("первая зачтённая предоплата по подписанному договору" if sales_action == "report_prepayment"
                       else "полная оплата по договору" if sales_action in ("sale_full_payment", "report_full_payment")
                       else "отметка «Продажа состоялась»"),
    }, headers={"Cache-Control": "no-store"})


@ar.router.post("/pilot-summary/creative")
async def rename_creative(request: Request, manager: dict = Depends(ar.require_admin)):
    if settings.crm_standalone_enabled or not await ar._media_flag(FLAG):
        raise HTTPException(status_code=404)
    form = await request.form()
    direction = str(form.get("direction") or "")
    if direction not in allowed_directions(manager):
        raise HTTPException(status_code=403)
    expected = request.session.get("report_csrf", "")
    if not expected or not hmac.compare_digest(expected, str(form.get("csrf_token") or "")):
        raise HTTPException(status_code=403)
    from app.core.report_catalog import rename
    try:
        rename(settings.report_catalog_path, direction, str(form.get("source") or ""),
               str(form.get("code") or ""), str(form.get("label") or ""))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return RedirectResponse("/admin/pilot-summary?" + urlencode({"direction": direction}), status_code=303)
