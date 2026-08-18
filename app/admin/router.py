"""Роутер админ-панели (FastAPI + Jinja2 + HTMX).

Канбан-доски диалогов, полный контекст переписки, перехват (бот замолкает),
ответ менеджера клиенту, исход сделки. Аккаунты менеджеров — сессия (cookie),
список логинов в settings.managers. Действия пишутся в аудит-лог.
"""
from __future__ import annotations

import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import (HTMLResponse, JSONResponse, PlainTextResponse,
                               RedirectResponse)
from fastapi.templating import Jinja2Templates

from app.agent.llm import chat, llm_enabled
from app.channels import outbound
from app.config import settings
from app.core import budget
from app.core.branding import quick_replies_for
from app.core.intercept import set_intercept
from app.core.leadstate import HUMAN_STAGES, STAGE_TO_COLUMN, is_noise, is_silent
from app.core.manager_scope import BOT_SCOPE_BY_MANAGER, bot_scope_for
from app.core.own_outbound import mark_own
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("admin")

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Доски (вкладки) — по воронкам. Визы и Туры основные, Билеты — третья.
FUNNELS = [("visa", "Визы"), ("tours", "Туры"), ("tickets", "Билеты")]
# Короткие ярлыки воронок для бейджа в инбоксе/поиске (где смешаны все воронки).
FUNNEL_LABELS = {"visa": "Визы", "tours": "Туры", "tickets": "Билеты"}
FAQ_TABS = FUNNELS + [("common", "Общие")]

# Колонки канбана и маппинг внутренних стадий диалога в колонку.
BOARD_COLUMNS = [
    ("greeting", "Новый"),
    ("qualification", "Квалификация"),
    ("progress", "Подбор / оценка"),
    ("office", "В офис / консультация"),
    ("manager", "У менеджера"),
    ("silent", "Молчат (на дожим)"),
    ("follow_up", "Повторное касание"),
]
# Обратный маппинг для ручного переноса (drag-and-drop): колонка → каноническая стадия.
# Стадии-ключи = ключи колонок, чтобы карточка осталась в той колонке, куда её положили.
COLUMN_TO_STAGE = {key: key for key, _ in BOARD_COLUMNS if key != "silent"}

# Палитра градиентов для аватаров (детерминированно по имени/номеру).
AVATAR_GRADIENTS = [
    "linear-gradient(135deg,#2dd4bf,#0d9488)",
    "linear-gradient(135deg,#818cf8,#4f46e5)",
    "linear-gradient(135deg,#c084fc,#7c3aed)",
    "linear-gradient(135deg,#fbbf24,#d97706)",
    "linear-gradient(135deg,#fb7185,#e11d48)",
    "linear-gradient(135deg,#38bdf8,#0284c7)",
    "linear-gradient(135deg,#34d399,#059669)",
]
WAIT_WARM_MIN = 5    # клиент ждёт дольше — карточка теплеет
WAIT_HOT_MIN = 20    # ждёт долго — горит

# Исходы диалога для ручной отметки менеджером.
OUTCOMES = [("won", "✅ Оплатил"), ("office", "🏢 Дошёл в офис"), ("lost", "❌ Слился")]

# BOT_SCOPE_BY_MANAGER now lives in app.core.manager_scope (shared with scheduler jobs);
# re-exported via the import above so existing references keep working.


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _minutes_since(dt: datetime | None, now: datetime) -> float | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)  # SQLite отдаёт naive — считаем UTC
    return max(0.0, (now - dt).total_seconds() / 60)


def _initials(name: str | None, user_id: str) -> str:
    if name:
        parts = name.split()
        if len(parts) >= 2:
            return (parts[0][:1] + parts[1][:1]).upper()
        return name[:2].upper()
    return user_id[-2:]


def _avatar(user_id: str) -> str:
    return AVATAR_GRADIENTS[sum(user_id.encode()) % len(AVATAR_GRADIENTS)]


def _time_label(mins: float | None) -> str:
    if mins is None:
        return ""
    if mins < 1:
        return "сейчас"
    if mins < 60:
        return f"{int(mins)} мин"
    if mins < 1440:
        return f"{int(mins // 60)} ч"
    return f"{int(mins // 1440)} дн"


def _card_model(conv, now: datetime) -> dict:
    """Обогащённая карточка для доски: аватар, сигналы срочности, время, «кто ведёт»."""
    name = conv.qualification.get("name")
    phone = conv.phone or conv.user_id
    since = _minutes_since(conv.last_message_at, now)
    # «Клиент ждёт» = последним писал клиент и ему ещё не ответили (ни бот, ни менеджер).
    waiting = conv.last_sender == "client"
    wait_min = since if waiting else None
    if wait_min is None:
        level = "none"
    elif wait_min >= WAIT_HOT_MIN:
        level = "hot"
    elif wait_min >= WAIT_WARM_MIN:
        level = "warm"
    else:
        level = "fresh"
    # «Требуют ответа человека» = клиент ждёт И диалог у менеджера/перехвачен.
    needs_reply = waiting and (conv.intercepted or conv.stage in HUMAN_STAGES)
    noise = is_noise(conv, now, settings)
    silent = is_silent(conv, now, settings)
    return {
        "user_id": conv.user_id, "phone": phone, "name": name or phone,
        "bot_id": conv.bot_id,
        "initials": _initials(name, phone),
        "avatar": _avatar(phone),
        "channel": conv.channel, "stage": conv.stage, "intercepted": conv.intercepted,
        "funnel": conv.funnel or "", "funnel_label": FUNNEL_LABELS.get(conv.funnel, conv.funnel or "—"),
        "assigned_to": conv.assigned_to, "outcome": conv.outcome,
        "last_text": conv.last_text, "last_sender": conv.last_sender,
        "time_label": _time_label(since),
        "wait_label": _time_label(wait_min) if wait_min is not None else "",
        "wait_level": level,                       # none|fresh|warm|hot
        "needs_reply": needs_reply,
        "is_noise": noise,
        "is_silent": silent,
        "lead_temperature": conv.lead_temperature,
        "source": getattr(conv, "source", "") or "",
        "source_headline": getattr(conv, "source_headline", "") or "",
        "sort_key": (wait_min if wait_min is not None else -1),
    }


# ---------------- авторизация (сессия менеджера) ----------------
def current_manager(request: Request) -> dict | None:
    """Текущий менеджер из cookie-сессии (или None)."""
    m = request.session.get("manager")
    return m if isinstance(m, dict) else None


def require_admin(request: Request) -> dict:
    """Зависимость: пускаем только залогиненного менеджера, иначе 401."""
    m = current_manager(request)
    if not m:
        raise HTTPException(status_code=401, detail="login required")
    return m


def require_full_admin(request: Request) -> dict:
    """Зависимость: только полный админ (видит все воронки). Скоуп-менеджер → 403.

    Статистика, статус системы и аудит — админские: скоуп-менеджеру там делать нечего.
    """
    m = require_admin(request)                 # сперва проверка логина (401)
    if _manager_bot_scope(m) is not None:
        raise HTTPException(status_code=403, detail="admin only")
    return m


def _check_credentials(login: str, password: str) -> dict | None:
    # Стрипаем обе стороны: случайный пробел вокруг логина/пароля (в форме ИЛИ
    # в env prod.env при копипасте) не должен ронять вход. compare_digest — от таймингов.
    login = (login or "").strip()
    password = (password or "").strip()
    for mgr in settings.manager_list():
        if (secrets.compare_digest(login, (mgr.login or "").strip())
                and secrets.compare_digest(password, (mgr.password or "").strip())):
            return {"login": mgr.login, "name": mgr.name or mgr.login, "admin": bool(mgr.admin)}
    return None


def _manager_bot_scope(manager: dict | None) -> set[str] | None:
    """Return bot ids visible to this manager. None means unrestricted admin view."""
    return bot_scope_for(manager, admin_user=settings.admin_user)


def _can_view_conversation(conv, manager: dict | None) -> bool:
    scope = _manager_bot_scope(manager)
    if scope is None:
        return True
    if not scope:
        return False
    bot_id = getattr(conv, "bot_id", "") or ""
    user_id = getattr(conv, "user_id", "") or ""
    return bot_id in scope or any(user_id.startswith(f"{allowed}:") for allowed in scope)


def _filter_conversations(convs: list, manager: dict | None) -> list:
    return [c for c in convs if _can_view_conversation(c, manager)]


def _demo_profiles() -> list[dict]:
    """Virtual demo logins for per-manager views, even if MANAGERS lacks the account."""
    return [
        {"login": "ademi", "name": "Адеми"},
        {"login": "sezim", "name": "Сезим"},
        {"login": "medina", "name": "Медина"},
        {"login": "eliza", "name": "Элиза"},
    ]


def _demo_managers() -> list[dict]:
    """Список менеджеров для кнопок быстрого входа (только при demo_login)."""
    if not settings.demo_login:
        return []
    rows = [{"login": m.login, "name": m.name or m.login} for m in settings.manager_list()]
    by_login = {row["login"]: row for row in rows}
    for row in _demo_profiles():
        by_login.setdefault(row["login"], row)
    return list(by_login.values())


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if current_manager(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "login.html",
                                      {"error": None, "demo_managers": _demo_managers()},
                                      headers={"Cache-Control": "no-store"})


@router.post("/login/demo")
async def login_demo(request: Request, login: str = Form(...)):
    """Быстрый вход для демо (без пароля). Доступен ТОЛЬКО при settings.demo_login."""
    if not settings.demo_login:
        raise HTTPException(status_code=404, detail="not found")
    mgr = next((m for m in settings.manager_list() if m.login == login), None)
    if mgr is None:
        demo = next((m for m in _demo_profiles() if m["login"] == login), None)
        if demo is None:
            raise HTTPException(status_code=404, detail="manager not found")
        request.session["manager"] = demo
        await get_conversation_store().add_audit(demo["login"], "login")
        return RedirectResponse("/admin", status_code=303)
    request.session["manager"] = {"login": mgr.login, "name": mgr.name or mgr.login,
                                   "admin": bool(mgr.admin)}
    await get_conversation_store().add_audit(mgr.login, "login")
    return RedirectResponse("/admin", status_code=303)


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, login: str = Form(...), password: str = Form(...)):
    from app.admin import ratelimit
    ip = request.client.host if request.client else "unknown"
    if ratelimit.is_blocked(ip):
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Слишком много попыток. Подождите минуту.",
                                           "demo_managers": _demo_managers()}, status_code=429)
    manager = _check_credentials(login.strip(), password)
    if manager is None:
        ratelimit.note_failure(ip)        # к блокировке ведут только провалы
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Неверный логин или пароль",
                                           "demo_managers": _demo_managers()}, status_code=401)
    request.session["manager"] = manager
    await get_conversation_store().add_audit(manager["login"], "login")
    return RedirectResponse("/admin", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.pop("manager", None)
    return RedirectResponse("/admin/login", status_code=303)


def _build_board(cards: list, now: datetime) -> tuple[list[dict], dict]:
    """Колонки канбана (карточки обогащены и отсортированы: ждут дольше — наверх) + метрики."""
    buckets: dict[str, list] = {key: [] for key, _ in BOARD_COLUMNS}
    models = [_card_model(c, now) for c in cards]
    for m in models:
        column = "silent" if m["is_silent"] else STAGE_TO_COLUMN.get(m["stage"], "greeting")
        buckets[column].append(m)
    for col in buckets.values():
        col.sort(key=lambda m: m["sort_key"], reverse=True)  # горячие наверх
    columns = [{"key": key, "label": label, "cards": buckets[key], "is_empty": not buckets[key]}
               for key, label in BOARD_COLUMNS]
    metrics = {
        "total": len(cards),
        "waiting": sum(1 for m in models if m["wait_level"] != "none"),
        "needs_reply": sum(1 for m in models if m["needs_reply"]),
        "noise": sum(1 for m in models if m["is_noise"]),
        "silent": sum(1 for m in models if m["is_silent"]),
        "intercepted": sum(1 for c in cards if c.intercepted),
    }
    return columns, metrics


@router.get("", response_class=HTMLResponse)
async def index(request: Request):
    """Главная страница панели с вкладками-досками. Без сессии — на форму логина."""
    manager = current_manager(request)
    if not manager:
        return RedirectResponse("/admin/login", status_code=303)
    return templates.TemplateResponse(request, "boards.html",
                                      {"funnels": FUNNELS, "manager": manager,
                                       "is_admin": _manager_bot_scope(manager) is None},
                                      headers={"Cache-Control": "no-store"})


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request, period: str = "all",
                    manager: dict = Depends(require_full_admin)):
    """Дашборд «ИИ vs менеджер»: containment, исходы, воронки, время ответа/перехвата.
    period — окно периода (today|7d|30d|all)."""
    from app.core import observ
    from app.integrations.panel.analytics import PERIODS, compute_analytics, compute_today_stats
    convs = _filter_conversations(await get_conversation_store().all_conversations(), manager)
    now = _now()
    data = compute_analytics(convs, period=period, now=now)
    today = compute_today_stats(convs, now)
    if _manager_bot_scope(manager) is None:
        usage_today = observ.snapshot().get("usage_daily", {}).get(date.today().isoformat(), {})
        today.update({
            "spend_today": await budget.spend_today(),
            "budget_usd": settings.llm_daily_budget_usd,
            "budget_status": await budget.status(),
            "llm_calls": usage_today.get("calls", 0),
            "llm_cost": usage_today.get("cost", 0.0),
        })
    return templates.TemplateResponse(request, "analytics.html",
                                      {"a": data, "manager": manager, "funnels": FUNNELS,
                                       "periods": PERIODS, "period": period, "today": today},
                                      headers={"Cache-Control": "no-store"})


@router.get("/buyers", response_class=HTMLResponse)
async def buyers(request: Request, manager: dict = Depends(require_admin)):
    """«Покупатели сегодня»: авто-триаж 🟢 + сводка владельца. Скоуп-фильтр по ботам менеджера."""
    from app.integrations.panel.buyers import compute_buyers
    convs = _filter_conversations(await get_conversation_store().all_conversations_light(), manager)
    data = compute_buyers(convs, _now())
    return templates.TemplateResponse(request, "buyers.html",
                                      {"b": data, "manager": manager},
                                      headers={"Cache-Control": "no-store"})


@router.get("/morning", response_class=HTMLResponse)
async def morning(request: Request, manager: dict = Depends(require_admin)):
    """Утренний «горячий лист» (Фаза 0 календаря): green/warm лиды, ждущие звонка. Скоуп по ботам."""
    from app.core.morning_brief import build_brief
    convs = _filter_conversations(await get_conversation_store().all_conversations_light(), manager)
    data = build_brief(convs, _now())
    return templates.TemplateResponse(request, "morning.html",
                                      {"b": data, "manager": manager},
                                      headers={"Cache-Control": "no-store"})


@router.get("/buyers/feed", response_class=HTMLResponse)
async def buyers_feed(request: Request, manager: dict = Depends(require_admin)):
    """HTMX-partial ленты 🟢 (поллинг every 30s): сервер владеет сортировкой и цветом ожидания."""
    from app.integrations.panel.buyers import compute_buyers
    convs = _filter_conversations(await get_conversation_store().all_conversations_light(), manager)
    data = compute_buyers(convs, _now())
    return templates.TemplateResponse(request, "_buyers_feed.html",
                                      {"b": data, "manager": manager},
                                      headers={"Cache-Control": "no-store"})


@router.post("/buyers/{user_id}/claim", response_class=HTMLResponse)
async def buyers_claim(user_id: str, manager: dict = Depends(require_admin)):
    """«Взять в работу» из ленты: атомарный claim (гонка менеджеров) + перехват. Карточка исчезает."""
    conv = await _require_visible_conversation(user_id, manager)
    allowed, deny_notice = await _ownership_guard(conv, manager, "claim")
    if not allowed:
        from html import escape
        return HTMLResponse(f'<div class="lead-card taken">{escape(deny_notice)}</div>')
    ok = await get_conversation_store().claim(user_id, manager["login"])
    if not ok:
        from html import escape
        conv = await get_conversation_store().get(user_id)
        who = escape(getattr(conv, "assigned_to", "") or "другой менеджер")
        return HTMLResponse(f'<div class="lead-card taken">Уже взял: {who}</div>')
    await _set_intercept(user_id, True)
    await get_conversation_store().add_audit(manager["login"], "takeover", user_id)
    return HTMLResponse("")  # успешный claim → карточка убирается из ленты


@router.get("/system", response_class=HTMLResponse)
async def system(request: Request, manager: dict = Depends(require_full_admin)):
    """Статус системы: LLM, тишина вебхуков, бэкенды, счётчики сбоев, боты."""
    from app.core import observ, tours_health
    from app.integrations.tourvisor import quota as tv_quota
    snap = observ.snapshot()
    flag_views = await _flag_views()
    bot_flags = await _bot_flag_views()
    stt_flags = await _stt_flag_views()
    data = {
        "llm_enabled": llm_enabled(),
        "spend_today": await budget.spend_today(),
        "budget_usd": settings.llm_daily_budget_usd,
        "budget_status": await budget.status(),
        "last_inbound_ago": observ.last_inbound_ago(),
        "state_backend": settings.state_backend,
        "panel_backend": settings.panel_backend,
        "crm_backend": settings.crm_backend,
        "followup_enabled": settings.followup_enabled,
        "alerts_configured": bool(settings.alert_whatsapp_to and settings.alert_bot_id),
        "webhook_secret_set": bool(settings.webhook_secret),
        "llm_failures": snap.get("llm_failures", 0),
        "send_failures": snap.get("send_failures", 0),
        "llm_failure_ago": snap.get("llm_failure_ago"),
        "send_failure_ago": snap.get("send_failure_ago"),
        # Подбор туров: и расход квоты, и РЕЗУЛЬТАТ. Раньше в панели не было ни того, ни
        # другого — поэтому месяц пустых подборов прошёл незамеченным.
        "tours_health": await tours_health.status(),
        "tourvisor_quota": await tv_quota.status(),
    }
    return templates.TemplateResponse(request, "system.html",
                                      {"s": data, "manager": manager,
                                       "flags": flag_views, "bot_flags": bot_flags,
                                       "stt_flags": stt_flags,
                                       "visa_queue": await _visa_queue_views()},
                                      headers={"Cache-Control": "no-store"})


# Тумблеры фич для менеджера: ключ → заголовок, описание, дефолт (из env), примечание.
FEATURE_FLAGS = {
    "bitrix_pipeline_enabled": {
        "title": "Конвейер лидов Bitrix",
        "desc": "Двигать лид вперёд и поддерживать краткое досье в карточке.",
        "default": lambda: settings.bitrix_pipeline_enabled,
        "note": lambda: "",
    },
    "tour_facts_enabled": {
        "title": "Запоминать сказанное клиентом сразу",
        "desc": ("Направление, город вылета, даты, бюджет и состав попадают в карточку в тот "
                 "момент, когда клиент их назвал, — не дожидаясь, пока бот запустит подбор. "
                 "Раньше карточка оставалась пустой, если до подбора дело не дошло."),
        "default": lambda: settings.tour_facts_enabled,
        "note": lambda: "",
    },
    "offer_change_notice_enabled": {
        "title": "Сигнал «клиент передумал»",
        "desc": ("Если клиент уже получил подборку и после этого сменил страну или город "
                 "вылета, менеджеру уходит короткое сообщение «было → стало». Смену "
                 "бюджета, дат и состава бот отрабатывает сам и не беспокоит."),
        "default": lambda: False,
        "note": lambda: "",
    },
    "bitrix_autodeal_enabled": {
        "title": "Автосоздание сделок Bitrix",
        "desc": "Создавать сделку в туровой воронке после статуса «Подписан».",
        "default": lambda: settings.bitrix_autodeal_enabled,
        "note": lambda: "",
    },
    "bots_enabled": {
        "title": "Авто-ответы бота (главный рубильник)",
        "desc": ("Если выключить — бот перестаёт отвечать клиентам во всех воронках "
                 "(туры / визы / билеты). Входящие сообщения по-прежнему попадают в панель, "
                 "и менеджеры ведут диалоги вручную. Включите обратно, чтобы бот снова "
                 "отвечал автоматически."),
        "default": lambda: True,
        "note": lambda: "",
    },
    "followup_enabled": {
        "title": "Автодожим молчащих клиентов",
        "desc": ("Если клиент замолчал на этапе квалификации дольше 24 часов, бот сам отправит "
                 "один мягкий напоминающий месседж и переместит карточку в «Повторное касание». "
                 "Ночью (22:00–09:00 по Бишкеку) не беспокоит. Каждому клиенту — не больше одного "
                 "раза; как только клиент ответит, диалог продолжается обычным образом."),
        "default": lambda: settings.followup_enabled,
        "note": lambda: "",
    },
    "dozhim_enabled": {
        "title": "Дожим + ценовая вилка",
        "desc": ("Бот активнее ведёт тёплого клиента в офис или к менеджеру и отрабатывает "
                 "возражение по цене без обещания скидок, процентов или специальных цен."),
        "default": lambda: settings.dozhim_enabled,
        "note": lambda: "",
    },
    "tours_cards_enabled": {
        "title": "Подборка туров карточками",
        "desc": ("Бот присылает клиенту варианты в том же виде, что и менеджеры: отдельная "
                 "карточка на отель — название, звёзды, вылет и курорт, дата и ночи, тип "
                 "номера и состав, питание, цена. Пять вариантов за раз, дешёвые сверху, и "
                 "ссылка на страницу подборки, где клиент листает их с фото. Без тумблера "
                 "бот пересказывает варианты своими словами и умещает в пару фраз один отель."),
        "default": lambda: settings.tours_cards_enabled,
        "note": lambda: ("" if settings.public_base_url
                         else "не задан PUBLIC_BASE_URL — карточки уйдут без ссылки на подборку"),
    },
    "bitrix_prefer_openline_lead": {
        "title": "Бот пишет в карточку менеджера (Bitrix)",
        "desc": ("Сейчас бот заводит в Битриксе собственную карточку, которую менеджер "
                 "не видит: она принадлежит служебному аккаунту. С этим тумблером бот "
                 "дописывает переписку в ту карточку клиента, которую менеджер уже "
                 "открывает — созданную интеграцией WhatsApp. Если такой карточки ещё "
                 "нет, бот подождёт 10 минут и только потом заведёт свою, сразу на "
                 "нужного менеджера. Клиенту при этом ничего не отправляется."),
        "default": lambda: settings.bitrix_prefer_openline_lead,
        "note": lambda: ("" if settings.bitrix_assignee_by_bot
                         else "не задан BITRIX_ASSIGNEE_BY_BOT — запасные карточки уйдут без владельца"),
    },
    "wappi_health_enabled": {
        "title": "Проверка каналов у Wappi",
        "desc": ("Каждые несколько минут спрашивает у Wappi состояние каждого номера "
                 "WhatsApp: авторизован ли он и открыто ли приложение. Если номер "
                 "отвалился и ждёт QR — уведомление приходит сразу, а не через часы "
                 "тишины. Отдельно предупреждает, когда подписка Wappi по номеру подходит "
                 "к концу: иначе канал однажды умрёт молча. Ложных тревог не даёт: это "
                 "точный ответ Wappi, а не догадка по молчанию клиентов."),
        "default": lambda: settings.wappi_health_enabled,
        "note": lambda: ("" if settings.wappi_token
                         else "не задан WAPPI_TOKEN — проверка молчит"),
    },
    "channel_heartbeat_enabled": {
        "title": "Сторож тишины на каналах (предохранитель)",
        "desc": ("Запасная проверка к основной: следит, что по каждому номеру вообще "
                 "приходят сообщения, и зовёт владельца, если по каналу тихо дольше "
                 "12 часов. Нужна для случая, когда номер авторизован, но сообщения до "
                 "нас не доходят — такое Wappi не покажет. Порог намеренно большой: по "
                 "замеру за 21 сутки более чувствительные пороги давали 2-5 ложных "
                 "тревог в сутки, а от шумного сторожа отписываются."),
        "default": lambda: settings.channel_heartbeat_enabled,
        "note": lambda: "",
    },
    "stt_guard_enabled": {
        "title": "Фильтр доверия к расшифровке голосовых",
        "desc": ("Проверяет расшифровку голосового перед тем, как отдать её боту: пустой "
                 "текст, чужой алфавит, склеенные слова, повторы, а на спорных — короткая "
                 "проверка дешёвой моделью. Сейчас работает в режиме наблюдения: вердикт "
                 "виден менеджеру пометкой ⚠️ рядом с расшифровкой, но текст боту всё равно "
                 "уходит и ответы клиенту не меняются. Снять этот тумблер = аварийно "
                 "выключить проверку всем ботам сразу."),
        "default": lambda: settings.stt_guard_enabled,
        "note": lambda: "",
    },
    "bitrix_mirror_enabled": {
        "title": "Зеркалирование диалогов в Bitrix",
        "desc": ("Дублировать переписку (клиент / бот / менеджер) в Bitrix24: на первое "
                 "сообщение создаётся ЛИД, дальше каждая реплика падает комментарием в его "
                 "таймлайн. Менеджер сам конвертит Лид → Сделку после оплаты. Клиенту ничего "
                 "повторно не отправляется. Работает, только если задан вебхук портала."),
        "default": lambda: settings.bitrix_mirror_enabled,
        "note": lambda: ("" if settings.bitrix24_webhook_url
                         else "⚠️ Задайте BITRIX24_WEBHOOK_URL в prod.env, иначе зеркало не работает."),
    },
    "tours_summary_enabled": {
        "title": "Еженедельная тур-сводка владельцу в Telegram",
        "desc": ("Раз в неделю (утро понедельника) отправляет владельцу личным сообщением "
                 "честную сводку по турам из наших данных: лиды, сколько дошло до офиса, "
                 "продажи (по ручным отметкам менеджера), топ-направления, конверсия. "
                 "AI-оценка показывается отдельно с пометкой «не подтверждено». Нужен "
                 "личный Telegram владельца (admin)."),
        "default": lambda: settings.tours_summary_enabled,
        "note": lambda: "",
    },
    "tours_pilot_assign_enabled": {
        "title": "Пилот: закреплять туровые лиды за менеджером",
        "desc": ("Новый клиент по турам автоматически закрепляется за пилотным "
                 "менеджером (чтобы ночные заявки попадали в его личную утреннюю "
                 "сводку). Уже закреплённого клиента не трогает. Бота не перехватывает. "
                 "Только боевой туровый бот."),
        "default": lambda: settings.tours_pilot_assign_enabled,
        "note": lambda: "",
    },
    "night_mode_enabled": {
        "title": "Ночной режим ботов (22:00–08:00)",
        "desc": ("Бот авто-отвечает только ночью по Бишкеку (с 22:00 до 08:00), днём "
                 "молчит — клиентов ведут менеджеры вручную. Входящие всё равно "
                 "попадают в панель и утренний бриф. Не включает выключенного кнопкой "
                 "бота — только сужает окно уже включённого."),
        "default": lambda: settings.night_mode_enabled,
        "note": lambda: "",
    },
    "authz_enforce_enabled": {
        "title": "Жёсткое владение лидами (без перехвата)",
        "desc": ("Менеджер может писать только своим или ничьим клиентам (ничей лид "
                 "закрепляется за первым ответившим). Чужой диалог — только просмотр; "
                 "передать лид может только администратор — кнопкой «Переназначить» "
                 "или собственным перехватом. "
                 "Выключено — как раньше: мягкое предупреждение «уже ведёт X»."),
        "default": lambda: settings.authz_enforce_enabled,
        "note": lambda: "",
    },
    "visa_autoassign_enabled": {
        "title": "Авто-распределение визовых лидов",
        "desc": ("Новый визовый клиент автоматически закрепляется за следующим менеджером "
                 "по очереди («кто дольше всех не получал»). Бот продолжает отвечать сам — "
                 "назначение только фиксирует владельца и шлёт менеджеру личное уведомление "
                 "в Telegram (если настроен chat_id). Временно убрать менеджера из очереди "
                 "можно тумблером «В очереди виз» ниже."),
        "default": lambda: settings.visa_autoassign_enabled,
        "note": lambda: "",
    },
    "alerts_enabled": {
        "title": "Watchdog-алерты",
        "desc": ("Уведомлять администратора в WhatsApp, если бот не получает входящих дольше "
                 "30 минут или пошёл всплеск сбоев (LLM/отправка). Помогает заметить, что бот "
                 "«отвалился», раньше, чем начнут жаловаться клиенты."),
        "default": lambda: True,
        "note": lambda: ("" if (settings.alert_whatsapp_to and settings.alert_bot_id)
                         else "⚠️ Чтобы алерты отправлялись, задайте в prod.env номер админа "
                              "(ALERT_WHATSAPP_TO) и бота (ALERT_BOT_ID)."),
    },
}


async def _flag_views() -> list[dict]:
    """Состояние всех тумблеров для рендера (значение из БД, дефолт из env)."""
    from app.core import flags
    views = []
    for key, spec in FEATURE_FLAGS.items():
        on = await flags.get_flag(key, spec["default"]())
        views.append({"key": key, "title": spec["title"], "desc": spec["desc"],
                      "on": on, "note": spec["note"]()})
    return views


SCENARIO_LABELS = {"tours": "туры", "visa": "визы", "tickets": "билеты"}


async def _bot_flag_views() -> list[dict]:
    """Эффективное состояние per-bot тумблеров с наследованием от главного рубильника."""
    from app.core import flags
    from app.core.bots import registry
    global_on = await flags.get_flag("bots_enabled", True)
    views = []
    for bot in registry.all():
        on = await flags.get_flag(f"bots_enabled:{bot.id}", global_on)
        channel = "WhatsApp" if bot.wappi_profile_id else "Telegram"
        profile = bot.wappi_profile_id or bot.bitrix_bot_id or bot.bitrix_line_id or ""
        views.append({
            "id": bot.id,
            "key": f"bots_enabled:{bot.id}",
            "title": bot.title or bot.id,
            "scenario": bot.scenario,
            "scenario_label": SCENARIO_LABELS.get(bot.scenario, bot.scenario),
            "channel": channel,
            "profile": profile,
            "on": on,
        })
    return views


async def _stt_flag_views() -> list[dict]:
    """Состояние распознавания отдельно от автоответов и причина последней аварии."""
    from app.core import flags, stt_metrics
    from app.core.bots import registry
    global_on = await flags.get_flag("stt_enabled", settings.stt_enabled)
    views = []
    for bot in registry.all():
        default = False if bot.id == "getvisa" else global_on
        on = await flags.get_flag(f"stt_enabled:{bot.id}", default)
        snap = await stt_metrics.snapshot(bot.id)
        views.append({"id": bot.id, "name": bot.manager_name or bot.title or bot.id,
                      "on": on, "breaker": (snap.get("breaker") or {}).get("reason", "")})
    return views


async def _visa_queue_views() -> list[dict]:
    """Sprint 2: состояние очереди виз — кто в ротации, кто временно выключен."""
    from app.core import flags
    views = []
    for login in settings.visa_manager_roster:
        off = await flags.get_flag(f"manager_off:{login}", False)
        views.append({"login": login, "off": off})
    return views


@router.post("/flags/{key}", response_class=HTMLResponse)
async def toggle_flag(key: str, request: Request,
                      manager: dict = Depends(require_full_admin), on: str = Form("0")):
    """Полный админ включает/выключает фичу кнопкой в панели (рантайм-флаг в БД, без
    рестарта). Только full-admin (аудит-фикс HIGH): страница флагов и так видна лишь
    ему, но раньше POST руками мог дёрнуть любой залогиненный менеджер — включая
    kill-switch ботов и новые authz/autoassign-флаги. Пер-бот тумблеры
    (/bots/{id}/toggle) намеренно остаются require_admin — менеджеры включают и
    выключают СВОИХ ботов сами (требование бизнеса)."""
    if key not in FEATURE_FLAGS:
        raise HTTPException(status_code=404, detail="unknown flag")
    from app.core import flags
    value = on in ("1", "true", "on", "True")
    await flags.set_flag(key, value)
    await get_conversation_store().add_audit(
        manager["login"], "flag", "", f"{key}={'on' if value else 'off'}")
    return templates.TemplateResponse(request, "_automation.html",
                                      {"flags": await _flag_views(),
                                       "visa_queue": await _visa_queue_views()})


@router.post("/queue/visa/{login}/toggle", response_class=HTMLResponse)
async def toggle_visa_availability(login: str, request: Request,
                                   manager: dict = Depends(require_full_admin),
                                   off: str = Form("0")):
    """Sprint 2: временно убрать/вернуть менеджера в очередь авто-распределения виз.

    Пишет рантайм-флаг ``manager_off:<login>`` (та же ось доступности, что читает
    round-robin). Только полный админ."""
    login = (login or "").strip().lower()
    if login not in [(l or "").strip().lower() for l in settings.visa_manager_roster]:
        raise HTTPException(status_code=404, detail="not in visa roster")
    from app.core import flags
    value = off in ("1", "true", "on", "True")
    await flags.set_flag(f"manager_off:{login}", value)
    await get_conversation_store().add_audit(
        manager["login"], "queue_toggle", "",
        f"manager_off:{login}={'on' if value else 'off'}")
    return templates.TemplateResponse(request, "_automation.html",
                                      {"flags": await _flag_views(),
                                       "visa_queue": await _visa_queue_views()})


@router.post("/followup/run", response_class=HTMLResponse)
async def run_followup_now(manager: dict = Depends(require_admin)):
    """Ручной дожим молчунов по кнопке (не зависит от авто-флага followup_enabled)."""
    from app.core import followup
    result = await followup.run_manual()
    await get_conversation_store().add_audit(
        manager["login"], "followup", "",
        f"manual sent={result['sent']} quiet={result['quiet']}")
    if result["quiet"]:
        msg = "Сейчас тихие часы (Бишкек 22–9) — дожим отложен, попробуйте днём 🌙"
    elif result["sent"] == 0:
        msg = "Сейчас некого дожимать — молчунов нет 👍"
    else:
        msg = f"Готово: отправлено {result['sent']} пингов молчунам ✅"
    return HTMLResponse(f'<span style="color:var(--muted)">{msg}</span>')


@router.post("/bots/{bot_id}/toggle", response_class=HTMLResponse)
async def toggle_bot_flag(bot_id: str, request: Request, manager: dict = Depends(require_admin),
                          on: str = Form("0")):
    """Менеджер включает/выключает авто-ответы конкретного бота."""
    from app.core import flags
    from app.core.bots import registry
    bot = registry.by_id(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail="unknown bot")
    value = on in ("1", "true", "on", "True")
    key = f"bots_enabled:{bot_id}"
    await flags.set_flag(key, value)
    await get_conversation_store().add_audit(
        manager["login"], "flag", "", f"{key}={'on' if value else 'off'}")
    return templates.TemplateResponse(request, "_bot_toggles.html",
                                      {"bot_flags": await _bot_flag_views(),
                                       "stt_flags": await _stt_flag_views()})


@router.post("/bots/{bot_id}/stt-toggle", response_class=HTMLResponse)
async def toggle_stt_flag(bot_id: str, request: Request, manager: dict = Depends(require_admin),
                          on: str = Form("0")):
    """Менять только распознавание: боевой WhatsApp и автоответы остаются включены."""
    from app.core import flags, stt_metrics
    from app.core.bots import registry
    if registry.by_id(bot_id) is None:
        raise HTTPException(status_code=404, detail="unknown bot")
    value = on in ("1", "true", "on", "True")
    key = f"stt_enabled:{bot_id}"
    await flags.set_flag(key, value)
    if value:
        await stt_metrics.clear_breaker(bot_id)
    await get_conversation_store().add_audit(
        manager["login"], "flag", "", f"{key}={'on' if value else 'off'}")
    return templates.TemplateResponse(request, "_bot_toggles.html",
                                      {"bot_flags": await _bot_flag_views(),
                                       "stt_flags": await _stt_flag_views()})


@router.get("/audit", response_class=HTMLResponse)
async def audit(request: Request, manager: dict = Depends(require_full_admin)):
    """Журнал действий менеджеров (перехват/ответ/исход/перенос/логин)."""
    rows = await get_conversation_store().list_audit(200)
    return templates.TemplateResponse(request, "audit.html",
                                      {"rows": rows, "manager": manager},
                                      headers={"Cache-Control": "no-store"})


def _lines(raw: str) -> list[str]:
    return [line.strip() for line in (raw or "").splitlines() if line.strip()]


def _faq_scope(scope: str) -> str | None:
    return scope if scope in FUNNEL_LABELS else None


@router.get("/faq", response_class=HTMLResponse)
async def faq_page(request: Request, scope: str = "visa",
                   manager: dict = Depends(require_admin)):
    """Редактор FAQ-правил: детерминированные ответы до LLM."""
    from app.core.faq import get_faq_store
    scope = scope if scope in {"visa", "tours", "tickets", "common"} else "visa"
    store = get_faq_store()
    rows = await store.list(scope)
    edit_id = int(request.query_params.get("edit") or 0)
    edit = await store.get(edit_id) if edit_id else None
    return templates.TemplateResponse(request, "faq.html", {
        "manager": manager, "tabs": FAQ_TABS, "scope": scope, "rows": rows,
        "edit": edit, "funnels": FUNNELS,
    }, headers={"Cache-Control": "no-store"})


@router.post("/faq/save", response_class=HTMLResponse)
async def faq_save(request: Request, manager: dict = Depends(require_admin),
                   entry_id: int = Form(0), scope: str = Form("common"),
                   title: str = Form(""), patterns: str = Form(""),
                   negative_terms: str = Form(""), answer: str = Form(""),
                   priority: int = Form(0), enabled: str = Form("0"),
                   handoff_only: str = Form("0"),
                   allow_during_qualification: str = Form("0")):
    """Создать или обновить FAQ-правило."""
    from app.core.faq import get_faq_store
    data = {
        "id": entry_id,
        "funnel": _faq_scope(scope),
        "enabled": enabled in ("1", "true", "on", "True"),
        "priority": priority,
        "title": title,
        "patterns": _lines(patterns),
        "negative_terms": _lines(negative_terms),
        "answer": answer,
        "handoff_only": handoff_only in ("1", "true", "on", "True"),
        "allow_during_qualification": allow_during_qualification in ("1", "true", "on", "True"),
    }
    if not data["title"] or not data["patterns"] or not data["answer"]:
        raise HTTPException(status_code=400, detail="title, patterns and answer are required")
    row = await get_faq_store().upsert(data, manager["login"])
    action = "faq_update" if entry_id else "faq_create"
    await get_conversation_store().add_audit(manager["login"], action, "", f"{row.id}: {row.title}")
    return RedirectResponse(f"/admin/faq?scope={scope}", status_code=303)


@router.post("/faq/{entry_id}/toggle")
async def faq_toggle(entry_id: int, scope: str = Form("common"),
                     enabled: str = Form("0"), manager: dict = Depends(require_admin)):
    """Включить/выключить FAQ-правило."""
    from app.core.faq import get_faq_store
    value = enabled in ("1", "true", "on", "True")
    store = get_faq_store()
    row = await store.get(entry_id)
    await store.set_enabled(entry_id, value, manager["login"])
    await get_conversation_store().add_audit(
        manager["login"], "faq_update" if value else "faq_disable", "",
        f"{entry_id}: {(row.title if row else '')}"
    )
    return RedirectResponse(f"/admin/faq?scope={scope}", status_code=303)


@router.post("/faq/test", response_class=HTMLResponse)
async def faq_test(request: Request, manager: dict = Depends(require_admin),
                   scope: str = Form("common"), text: str = Form("")):
    """Проверить фразу через тот же матчинг, без отправки клиенту."""
    from app.core.faq import get_faq_store, match_faq
    scope = scope if scope in {"visa", "tours", "tickets", "common"} else "common"
    funnel = _faq_scope(scope)
    store = get_faq_store()
    entries = await store.candidates(funnel)
    hit = match_faq(text, funnel, entries)
    return templates.TemplateResponse(request, "faq.html", {
        "manager": manager, "tabs": FAQ_TABS, "scope": scope,
        "rows": await store.list(scope), "edit": None, "funnels": FUNNELS,
        "test_text": text, "test_hit": hit, "tested": True,
    }, headers={"Cache-Control": "no-store"})


@router.get("/board/{funnel}", response_class=HTMLResponse)
async def board(funnel: str, request: Request, manager: dict = Depends(require_admin),
                mine: int = 0):
    """HTMX-партиал одной доски: колонки по стадиям с карточками.

    ?mine=1 — Sprint 2: показать только лиды, закреплённые за текущим менеджером."""
    panel = get_conversation_store()
    cards = _filter_conversations(await panel.list_cards(funnel), manager)
    if mine:
        login = str(manager.get("login") or "").strip().lower()
        cards = [c for c in cards
                 if (getattr(c, "assigned_to", "") or "").strip().lower() == login]
    columns, metrics = _build_board(cards, _now())
    return templates.TemplateResponse(request, "_board.html", {
        "funnel": funnel, "columns": columns, "metrics": metrics, "mine": mine,
    })


async def _all_models(now: datetime, manager: dict | None = None) -> list[dict]:
    """Обогащённые карточки по ВСЕМ воронкам (для инбокса, поиска, счётчиков)."""
    convs = await get_conversation_store().all_conversations()
    return [_card_model(c, now) for c in _filter_conversations(convs, manager)]


def _waiting_sorted(models: list[dict]) -> list[dict]:
    """Кто ждёт ответа (последним писал клиент), дольше всех — наверх."""
    cards = [m for m in models if m["wait_level"] != "none"]
    cards.sort(key=lambda m: m["sort_key"], reverse=True)
    return cards


async def _render_inbox_partial(request: Request, *, mode: str = "inbox", query: str = ""):
    models = await _all_models(_now(), current_manager(request))
    query = query.strip()
    if mode == "search" and query:
        ql = query.lower()
        cards = [m for m in models
                 if ql in (m["name"] or "").lower() or ql in (m["phone"] or "").lower()
                 or ql in (m["last_text"] or "").lower()]
        cards.sort(key=lambda m: m["sort_key"], reverse=True)
    else:
        cards = _waiting_sorted(models)
        mode = "inbox"
        query = ""
    return templates.TemplateResponse(request, "_attention.html",
                                      {"mode": mode, "cards": cards, "query": query,
                                       "noise_count": sum(1 for c in cards if c["is_noise"])})


@router.get("/inbox", response_class=HTMLResponse)
async def inbox(request: Request, _: dict = Depends(require_admin)):
    """Единый инбокс: все ждущие ответа диалоги по всем воронкам в одном списке."""
    return await _render_inbox_partial(request)


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = "", _: dict = Depends(require_admin)):
    """Поиск по имени / номеру / последнему сообщению across все воронки.
    Пустой запрос возвращает инбокс — так очистка поля возвращает менеджера к списку."""
    q = q.strip()
    if not q:
        return await _render_inbox_partial(request)
    return await _render_inbox_partial(request, mode="search", query=q)


@router.get("/stats", response_class=JSONResponse)
async def stats(manager: dict = Depends(require_admin)):
    """Лёгкий счётчик для звуковых уведомлений и бейджа в заголовке вкладки."""
    models = await _all_models(_now(), manager)
    return JSONResponse({
        "waiting": sum(1 for m in models if m["wait_level"] != "none"),
        "needs_reply": sum(1 for m in models if m["needs_reply"]),
        "noise": sum(1 for m in models if m["is_noise"]),
        "total": len(models),
    })


async def _render_conversation(user_id: str, request: Request, manager: dict, *,
                               notice: str = ""):
    panel = get_conversation_store()
    conv = await panel.get(user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if not _can_view_conversation(conv, manager):
        raise HTTPException(status_code=404, detail="conversation not found")
    name = conv.qualification.get("name")
    conv.phone = conv.phone or conv.user_id   # старые карточки без phone → ключ как номер
    # Кем занят, если не нами (мягкое предупреждение — не блок).
    busy_by = conv.assigned_to if conv.assigned_to and conv.assigned_to != manager["login"] else ""
    tasks = await _load_user_tasks(conv.user_id)
    active_tasks = [t for t in tasks if t["active"]]
    # Sprint 2: полный админ видит контрол «Переназначить» (список логинов менеджеров).
    is_full_admin = _manager_bot_scope(manager) is None
    reassign_targets = ([m.login for m in settings.manager_list() if (m.login or "").strip()]
                        if is_full_admin else [])
    return templates.TemplateResponse(request, "_conversation.html", {
        "c": conv,
        "initials": _initials(name, conv.phone),
        "avatar": _avatar(conv.phone),
        "manager": manager,
        "busy_by": busy_by,
        "notice": notice,
        "is_full_admin": is_full_admin,
        "reassign_targets": reassign_targets,
        "outcomes": OUTCOMES,
        "quick_replies": quick_replies_for(conv.funnel),
        "tasks": tasks,
        "active_tasks": active_tasks,
        "task_kinds": TASK_KIND_LABELS,
        "task_priorities": TASK_PRIORITY_LABELS,
        "today_iso": _bishkek_today().isoformat(),
    })


async def _require_visible_conversation(user_id: str, manager: dict):
    conv = await get_conversation_store().get(user_id)
    if conv is None or not _can_view_conversation(conv, manager):
        raise HTTPException(status_code=404, detail="conversation not found")
    return conv


@router.get("/conversation/{user_id}", response_class=HTMLResponse)
async def conversation(user_id: str, request: Request, manager: dict = Depends(require_admin)):
    """HTMX-партиал: полный контекст диалога + квалификация + действия менеджера."""
    return await _render_conversation(user_id, request, manager)


def _normalize_user_ids(user_ids: list[str], user_ids_csv: str = "") -> list[str]:
    items: list[str] = []
    for value in user_ids:
        items.extend(part.strip() for part in value.split(","))
    if user_ids_csv:
        items.extend(part.strip() for part in user_ids_csv.split(","))
    return [item for item in dict.fromkeys(items) if item]


@router.post("/conversations/archive", response_class=HTMLResponse)
async def archive_conversations(request: Request, manager: dict = Depends(require_admin),
                                user_ids: list[str] = Form(default=[]),
                                user_ids_csv: str = Form(default="")):
    """Soft-hide a batch of conversations and return the refreshed inbox partial."""
    ids = _normalize_user_ids(user_ids, user_ids_csv)
    panel = get_conversation_store()
    allowed = []
    for item in ids:
        conv = await panel.get(item)
        if conv is not None and _can_view_conversation(conv, manager):
            allowed.append(item)
    count = await panel.set_archived_many(allowed, True)
    await panel.add_audit(manager["login"], "archive_many", "", f"count={count}")
    return await _render_inbox_partial(request)


@router.post("/conversations/archive-noise", response_class=HTMLResponse)
async def archive_noise_conversations(request: Request, manager: dict = Depends(require_admin)):
    """Archive all current noise conversations using the same card model as the inbox."""
    models = await _all_models(_now(), manager)
    ids = [m["user_id"] for m in models if m["is_noise"]]
    panel = get_conversation_store()
    count = await panel.set_archived_many(ids, True)
    await panel.add_audit(manager["login"], "archive_noise", "", f"count={count}")
    return await _render_inbox_partial(request)


@router.post("/conversation/{user_id}/archive", response_class=JSONResponse)
async def archive_conversation(user_id: str, manager: dict = Depends(require_admin)):
    """Soft-hide a conversation from boards, inbox, search and counters."""
    panel = get_conversation_store()
    conv = await panel.get(user_id)
    if conv is None or not _can_view_conversation(conv, manager):
        raise HTTPException(status_code=404, detail="conversation not found")
    await panel.set_archived(user_id, True)
    await panel.add_audit(manager["login"], "archive", user_id)
    return JSONResponse({"ok": True})


@router.post("/conversation/{user_id}/unarchive", response_class=JSONResponse)
async def unarchive_conversation(user_id: str, manager: dict = Depends(require_admin)):
    """Return a conversation from archive."""
    panel = get_conversation_store()
    conv = await panel.get(user_id)
    if conv is None or not _can_view_conversation(conv, manager):
        raise HTTPException(status_code=404, detail="conversation not found")
    await panel.set_archived(user_id, False)
    await panel.add_audit(manager["login"], "unarchive", user_id)
    return JSONResponse({"ok": True})


# ------------- Sprint 2: живое владение лидом (флаг authz_enforce_enabled) -------------

def _authz_direction(conv) -> str:
    """Направление (команда) диалога для правил владения. Воронка «tickets» и пустая
    воронка сводятся к сценарию бота (билеты ведёт команда туров) — команда = бот."""
    from app.core import live_authz
    funnel = (getattr(conv, "funnel", "") or "").strip()
    if funnel in ("visa", "tours"):
        return funnel
    return live_authz.direction_for_bot(getattr(conv, "bot_id", "") or "")


async def _ownership_guard(conv, manager: dict, action: str) -> tuple[bool, str]:
    """Проверка (и фиксация) владения перед действием менеджера. action: send|claim|release.

    Возвращает (allowed, notice). Успешный claim / авто-захват ничьего лида пишет
    доменный Assignment под row-lock; панельный assigned_to выставляет вызывающий
    код (легаси-путь сохраняется). Fail-open: сбой домена не кладёт панель — правила
    владения тут дисциплина команды, не граница безопасности; сбой виден в логах.
    """
    from app.core import live_authz
    try:
        if not await live_authz.enforcement_enabled():
            return True, ""
    except Exception:  # noqa: BLE001 — сбой чтения флага не должен ломать панель
        log.warning("authz guard: flag read failed — fail-open", exc_info=True)
        return True, ""
    direction = _authz_direction(conv)
    if not direction:                       # команду не определить → не форсим
        log.debug("authz guard: no direction for conversation, skipping")
        return True, ""
    try:
        from app.domain import live_assign
        from app.domain.models import DomainError
        from app.domain.permissions import can_reassign, can_send
        actor = live_authz.actor_for(manager)
        async with _domain_sessionmaker()() as s:
            contact = await live_assign.contact_for_channel(
                s, channel=(getattr(conv, "channel", "") or ""),
                raw=conv.phone or conv.user_id)
            asg = await live_assign.active_assignment(s, contact.id, direction)
            owner = (getattr(asg, "manager_id", "") or "") if asg is not None else ""
            if not owner:
                # Легаси-владение из панели (до-доменные клеймы): уважаем его и лениво
                # мигрируем в домен при первом действии самого владельца.
                owner = (getattr(conv, "assigned_to", "") or "").strip().lower()
            if action == "release":
                # Вернуть боту может владелец или полный админ; назначение закрывается.
                if actor.is_full_admin or owner in ("", actor.manager_id):
                    await live_assign.end_active(s, contact.id, direction)
                    await s.commit()
                    return True, ""
                await s.commit()
                return False, (f"Диалог ведёт {owner} — вернуть боту может "
                               "владелец или администратор.")
            if action == "send" and can_send(actor, asg, direction):
                await s.commit()
                return True, ""
            if owner and owner != actor.manager_id and not (
                    action == "claim" and actor.is_full_admin):
                await s.commit()
                if actor.is_full_admin:
                    return False, (f"Диалог ведёт {owner}. Сначала передайте лид "
                                   "(кнопка «Переназначить») — затем пишите.")
                return False, (f"Диалог ведёт {owner}. Перехват запрещён — "
                               "передать лид может только администратор.")
            if action == "claim" and asg is not None and owner == actor.manager_id:
                await s.commit()                # свой лид повторно — без новой ревизии
                return True, ""
            if not can_reassign(actor, asg, actor.manager_id, direction):
                await s.commit()
                return False, "Нет доступа к этой воронке."
            # Ничей лид (или лениво мигрируемый свой, или админский перехват) → закрепляем.
            try:
                await live_assign.assign_locked(
                    s, contact.id, direction, actor.manager_id,
                    assigned_by=actor.manager_id,
                    reason=("takeover" if action == "claim" else "auto_claim_on_send"),
                    allow_emergency=actor.is_full_admin)
                await s.commit()
            except DomainError:
                # Гонка: другой менеджер взял лид между нашим чтением и локом. Это
                # честный отказ бизнес-правила, НЕ инфраструктурный сбой → блокируем.
                return False, ("Диалог только что взял другой менеджер — "
                               "обновите карточку.")
            return True, ""
    except Exception:  # noqa: BLE001 — fail-open только для ИНФРА-сбоев, см. докстринг
        log.warning("authz guard failed — fail-open (action=%s)", action, exc_info=True)
        return True, ""


@router.post("/conversation/{user_id}/takeover", response_class=HTMLResponse)
async def takeover(user_id: str, request: Request, manager: dict = Depends(require_admin)):
    """Менеджер перехватывает диалог: бот замолкает, диалог закрепляется за менеджером."""
    conv = await _require_visible_conversation(user_id, manager)
    allowed, deny_notice = await _ownership_guard(conv, manager, "claim")
    if not allowed:
        return await _render_conversation(user_id, request, manager, notice=deny_notice)
    await _set_intercept(user_id, True)
    await get_conversation_store().update_meta(user_id, assigned_to=manager["login"])
    await get_conversation_store().add_audit(manager["login"], "takeover", user_id)
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/release", response_class=HTMLResponse)
async def release(user_id: str, request: Request, manager: dict = Depends(require_admin)):
    """Вернуть диалог боту (снять перехват и закрепление)."""
    conv = await _require_visible_conversation(user_id, manager)
    allowed, deny_notice = await _ownership_guard(conv, manager, "release")
    if not allowed:
        return await _render_conversation(user_id, request, manager, notice=deny_notice)
    await _set_intercept(user_id, False)
    await get_conversation_store().release_claim(user_id)
    await get_conversation_store().add_audit(manager["login"], "release", user_id)
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/reassign", response_class=HTMLResponse)
async def reassign(user_id: str, request: Request,
                   manager: dict = Depends(require_full_admin), target: str = Form("")):
    """Полный админ передаёт лид другому менеджеру (аварийный перехват — с историей).

    Работает и при выключенном authz-флаге: пишет доменный Assignment + зеркалит в
    панельный assigned_to, так что включение флага позже ничего не потеряет.
    """
    conv = await _require_visible_conversation(user_id, manager)
    target = (target or "").strip().lower()
    known = {(m.login or "").strip().lower() for m in settings.manager_list()}
    if not target or target not in known:
        raise HTTPException(status_code=400, detail="unknown target manager")
    direction = _authz_direction(conv)
    if not direction:
        return await _render_conversation(
            user_id, request, manager, notice="Не удалось определить воронку диалога.")
    try:
        from app.domain import live_assign
        async with _domain_sessionmaker()() as s:
            contact = await live_assign.contact_for_channel(
                s, channel=(getattr(conv, "channel", "") or ""),
                raw=conv.phone or conv.user_id)
            await live_assign.assign_locked(
                s, contact.id, direction, target, assigned_by=manager["login"],
                reason="admin_reassign", allow_emergency=True)
            await s.commit()
    except Exception:  # noqa: BLE001
        log.warning("reassign failed", exc_info=True)
        return await _render_conversation(
            user_id, request, manager, notice="Не удалось переназначить — попробуйте ещё раз.")
    await get_conversation_store().update_meta(user_id, assigned_to=target)
    await get_conversation_store().add_audit(manager["login"], "reassign", user_id, target)
    return await _render_conversation(
        user_id, request, manager, notice=f"Лид передан менеджеру {target}.")


@router.post("/conversation/{user_id}/send", response_class=HTMLResponse)
async def send_message(user_id: str, request: Request, manager: dict = Depends(require_admin),
                       text: str = Form("")):
    """Менеджер отвечает клиенту прямо из панели. Ручная отправка авто-перехватывает диалог."""
    text = text.strip()
    panel = get_conversation_store()
    conv = await panel.get(user_id)
    if conv is None or not _can_view_conversation(conv, manager):
        raise HTTPException(status_code=404, detail="conversation not found")
    if text:
        allowed, deny_notice = await _ownership_guard(conv, manager, "send")
        if not allowed:
            return await _render_conversation(user_id, request, manager, notice=deny_notice)
        await _set_intercept(user_id, True)  # отвечает человек → бот молчит
        await panel.update_meta(user_id, assigned_to=manager["login"])
        msg_id = await panel.add_message(user_id, "manager", text, status="pending")
        try:
            provider = await outbound.send_to_client(
                conv.channel, conv.bot_id, conv.chat_id or user_id, text)
            mark_own(provider)
            await panel.mark_message_status(message_id=msg_id, status="sent",
                                            set_provider_msg_id=(provider or None))
        except Exception:  # noqa: BLE001 — не теряем сообщение в логе при сбое канала
            await panel.mark_message_status(message_id=msg_id, status="failed")
            log.warning("manager send failed (channel=%s)", conv.channel, exc_info=True)
        await panel.add_audit(manager["login"], "send", user_id, text[:120])
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/resend/{message_id}", response_class=HTMLResponse)
async def resend(user_id: str, message_id: int, request: Request,
                 manager: dict = Depends(require_admin)):
    """Повторить отправку сообщения, помеченного failed."""
    panel = get_conversation_store()
    conv = await panel.get(user_id)
    if conv is None or not _can_view_conversation(conv, manager):
        raise HTTPException(status_code=404, detail="conversation not found")
    target = next((m for m in conv.messages if m.id == message_id), None)
    if target is not None and target.text:
        try:
            provider = await outbound.send_to_client(
                conv.channel, conv.bot_id, conv.chat_id or user_id, target.text)
            mark_own(provider)
            await panel.mark_message_status(message_id=message_id, status="sent",
                                            set_provider_msg_id=(provider or None))
        except Exception:  # noqa: BLE001
            await panel.mark_message_status(message_id=message_id, status="failed")
            log.warning("resend failed (channel=%s)", conv.channel, exc_info=True)
        await panel.add_audit(manager["login"], "resend", user_id)
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/suggest", response_class=PlainTextResponse)
async def suggest_reply(user_id: str, request: Request, manager: dict = Depends(require_admin)):
    """Сгенерировать черновик ответа клиенту (Claude) из контекста — менеджер правит и шлёт."""
    conv = await get_conversation_store().get(user_id)
    if conv is None or not _can_view_conversation(conv, manager):
        raise HTTPException(status_code=404, detail="conversation not found")
    if not llm_enabled():
        return "ИИ недоступен (нет ключа OpenRouter) — ответьте вручную."
    # История диалога → формат чата (client=user, bot/manager=assistant).
    history = [{"role": "user" if m.sender == "client" else "assistant", "content": m.text}
               for m in conv.messages if m.text]
    if not history or history[-1]["role"] != "user":
        history.append({"role": "user", "content": "(Предложи уместный следующий шаг.)"})
    persona = "Frunze Travel (Медина, визовый эксперт)" if conv.funnel == "visa" else "Frunze Travel (Адеми)"
    system = (
        f"Ты — менеджер {persona}. Предложи ОДИН следующий ответ клиенту по контексту "
        f"переписки: тепло, кратко, по-русски, в стиле бренда, без выдуманных цен. "
        f"Контекст для тебя: {conv.ai_summary or '—'}. Следующий шаг: {conv.manager_next_step or '—'}. "
        f"Верни ТОЛЬКО текст ответа клиенту, без пояснений."
    )
    try:
        resp = await chat(
            system,
            history,
            model=settings.llm_model_cheap,
            bot_id=conv.bot_id,
            user_id=conv.user_id,
            tools=[],
            cacheable_system=False,
        )
        text = " ".join(b.get("text", "") for b in resp.get("content", [])
                        if b.get("type") == "text").strip()
        return text or "Не удалось сгенерировать черновик — попробуйте ещё раз."
    except Exception:  # noqa: BLE001
        log.warning("suggest failed", exc_info=True)
        return "Не удалось сгенерировать черновик — попробуйте ещё раз."


@router.post("/conversation/{user_id}/stage", response_class=PlainTextResponse)
async def set_stage(user_id: str, manager: dict = Depends(require_admin),
                    stage: str = Form(...)):
    """Ручной перенос карточки в другую колонку канбана (drag-and-drop менеджером)."""
    target = COLUMN_TO_STAGE.get(stage)
    if target is None:
        raise HTTPException(status_code=400, detail="unknown column")
    await _require_visible_conversation(user_id, manager)
    await get_conversation_store().update_meta(user_id, stage=target)
    await get_conversation_store().add_audit(manager["login"], "stage", user_id, target)
    return PlainTextResponse("ok")


@router.post("/conversation/{user_id}/outcome", response_class=HTMLResponse)
async def set_outcome(user_id: str, request: Request, manager: dict = Depends(require_admin),
                      outcome: str = Form(...)):
    """Менеджер отмечает исход диалога (оплатил / дошёл / слился)."""
    await _require_visible_conversation(user_id, manager)
    valid = {key for key, _ in OUTCOMES}
    if outcome in valid:
        await get_conversation_store().update_meta(user_id, outcome=outcome)
        await get_conversation_store().add_audit(manager["login"], "outcome", user_id, outcome)
    return await _render_conversation(user_id, request, manager)


# ==================== Sprint 1: calendar tasks ====================
# Manager calendar (day/week) + a Tasks block inside the client card. Tasks are a
# DOMAIN entity (see app/domain/calendar_tasks.py) linked to a Contact resolved from
# the conversation phone at CREATE time (explicit action). Reads by user_id (no Contact
# creation on render). All domain access is fail-safe: if the domain DB is absent
# (dev/memory or migration not applied), the panel shows an empty calendar, never 500s.

TASK_KIND_LABELS = [("call", "📞 Звонок"), ("meeting", "🤝 Встреча"),
                    ("office_visit", "🏢 Визит в офис"), ("followup", "🔁 Повторное касание"),
                    ("other", "📋 Другое")]
TASK_PRIORITY_LABELS = [("low", "Низкий"), ("normal", "Обычный"), ("high", "Высокий")]
_KIND_LABEL_MAP = dict(TASK_KIND_LABELS)
_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_WEEKDAYS_FULL_RU = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница",
                     "Суббота", "Воскресенье"]
_MONTHS_RU = ["января", "февраля", "марта", "апреля", "мая", "июня",
              "июля", "августа", "сентября", "октября", "ноября", "декабря"]
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _domain_sessionmaker():
    """Async sessionmaker for the domain DB. Isolated for test injection/monkeypatch."""
    from app.integrations.crm.db import get_sessionmaker
    return get_sessionmaker()


def _bishkek_today() -> date:
    return (datetime.now(timezone.utc) + timedelta(hours=6)).date()


def _fmt_phone(digits: str) -> str:
    """996555123456 → +996 555 12 34 56. Foreign/short numbers → '+<digits>' as-is."""
    d = "".join(ch for ch in (digits or "") if ch.isdigit())
    if len(d) == 12 and d.startswith("996"):
        return f"+{d[:3]} {d[3:6]} {d[6:8]} {d[8:10]} {d[10:]}"
    return f"+{d}" if d else ""


def _as_utc(when: datetime | None) -> datetime:
    """Store rows may carry naive UTC timestamps — normalize before any comparison."""
    if when is None:
        return _EPOCH
    return when if when.tzinfo is not None else when.replace(tzinfo=timezone.utc)


def _ago_short(when: datetime | None) -> str:
    """'ждёт 3 ч' / 'ждёт 2 дн' — how long the client has been waiting. '' if unknown."""
    if when is None:
        return ""
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    mins = int((datetime.now(timezone.utc) - when).total_seconds() // 60)
    if mins < 0:
        return ""
    if mins < 60:
        return f"{mins} мин"
    if mins < 60 * 36:
        return f"{mins // 60} ч"
    return f"{mins // 1440} дн"


def _task_ui(t, today: date, conv=None) -> dict:
    """One task as the calendar/card renders it. ``conv`` (optional live conversation)
    supplies the human bits a manager needs before dialling: name, waiting time, context."""
    at = t.scheduled_at
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    phone = (t.user_id or "").split(":")[-1]
    digits = "".join(ch for ch in phone if ch.isdigit())
    active = t.status in ("planned", "rescheduled")
    name, context, waiting, last_text = "", (t.ai_summary or ""), "", ""
    if conv is not None:
        name = (getattr(conv, "qualification", None) or {}).get("name") or ""
        digits = digits or "".join(ch for ch in (conv.phone or "") if ch.isdigit())
        context = context or (conv.ai_summary or "")
        last_text = (conv.last_text or "").strip().replace("\n", " ")[:120]
        if (conv.last_sender or "") == "client":
            waiting = _ago_short(conv.last_message_at)
    return {
        "id": t.id, "kind": t.kind, "kind_label": _KIND_LABEL_MAP.get(t.kind, t.kind),
        "priority": t.priority, "status": t.status,
        "time": (at + timedelta(hours=6)).strftime("%H:%M") if at else "",
        "has_time": at is not None, "date": t.scheduled_date,
        "date_iso": t.scheduled_date.isoformat(),
        "date_label": t.scheduled_date.strftime("%d.%m"),
        "user_id": t.user_id or "", "client": (phone[-4:] if phone else "—"),
        "name": name, "title": name or _fmt_phone(digits) or "Без номера",
        "digits": digits, "phone_display": _fmt_phone(digits),
        "tel": f"tel:+{digits}" if digits else "", "wa": f"https://wa.me/{digits}" if digits else "",
        "waiting": waiting, "last_text": last_text,
        "comment": t.comment or "", "context": context,
        "direction": t.direction, "manager_id": t.manager_id, "active": active,
        "done": t.status == "completed", "cancelled": t.status == "cancelled",
        "overdue": active and t.scheduled_date < today,
    }


async def _load_user_tasks(user_id: str) -> list[dict]:
    """Tasks for the client card, keyed by live user_id. Read-only, fail-safe."""
    today = _bishkek_today()
    try:
        from app.domain.calendar_tasks import CalendarTaskService
        async with _domain_sessionmaker()() as s:
            rows = await CalendarTaskService.list_for_user(s, user_id)
        return [_task_ui(t, today) for t in rows]
    except Exception:  # noqa: BLE001 — domain DB may be absent; card must still render
        log.debug("calendar: load user tasks failed", exc_info=True)
        return []


def _parse_task_when(scheduled_date: str, scheduled_time: str) -> tuple[date, datetime | None]:
    """Bishkek wall-clock inputs → (Bishkek date, exact UTC instant | None)."""
    d = date.fromisoformat(scheduled_date.strip())
    at = None
    t = (scheduled_time or "").strip()
    if t:
        hh, mm = t.split(":")[:2]
        naive = datetime(d.year, d.month, d.day, int(hh), int(mm))   # Bishkek wall time
        at = (naive - timedelta(hours=6)).replace(tzinfo=timezone.utc)  # → UTC (Bishkek = UTC+6)
    return d, at


def _manager_can_touch_task(manager: dict, task) -> bool:
    if _manager_bot_scope(manager) is None:          # full-admin
        return True
    return (task.manager_id or "") == str(manager.get("login") or "").strip().lower()


@router.post("/conversation/{user_id}/task/create", response_class=HTMLResponse)
async def task_create(user_id: str, request: Request, manager: dict = Depends(require_admin),
                      kind: str = Form("call"), scheduled_date: str = Form(""),
                      scheduled_time: str = Form(""), priority: str = Form("normal"),
                      comment: str = Form(""), direction: str = Form("")):
    """Create a task for this client. Resolves/creates a domain Contact by phone (explicit
    action — does NOT enable shadow or touch Bitrix)."""
    conv = await _require_visible_conversation(user_id, manager)
    direction = (direction or getattr(conv, "funnel", "") or "visa").strip()
    try:
        d, at = _parse_task_when(scheduled_date, scheduled_time)
    except Exception:
        raise HTTPException(status_code=400, detail="bad date/time")
    try:
        from app.domain.calendar_tasks import CalendarTaskService
        from app.domain.services import ContactService
        async with _domain_sessionmaker()() as s:
            contact = await ContactService.find_or_create_by_identity(
                s, "phone", conv.phone or conv.user_id)
            await CalendarTaskService.create(
                s, manager_id=manager["login"], direction=direction, kind=kind,
                scheduled_date=d, scheduled_at=at, contact_id=contact.id, user_id=user_id,
                priority=priority, comment=comment, created_by=manager["login"])
            await s.commit()
        await get_conversation_store().add_audit(
            manager["login"], "task_create", user_id, f"{kind} {d.isoformat()}")
    except Exception:  # noqa: BLE001 — never break the card on a domain error
        log.warning("calendar: task create failed", exc_info=True)
    return await _render_conversation(user_id, request, manager)


async def _apply_task_action(user_id: str, task_id: int, manager: dict, action: str, *,
                             new_date: date | None = None, new_at: datetime | None = None) -> None:
    try:
        from app.domain.calendar_tasks import CalendarTaskService
        async with _domain_sessionmaker()() as s:
            task = await CalendarTaskService.get(s, task_id)
            if (task is None or (task.user_id or "") != user_id
                    or not _manager_can_touch_task(manager, task)):
                return
            if action == "complete":
                await CalendarTaskService.complete(s, task, actor=manager["login"])
            elif action == "cancel":
                await CalendarTaskService.cancel(s, task, actor=manager["login"])
            elif action == "reschedule" and new_date is not None:
                await CalendarTaskService.reschedule(
                    s, task, new_date=new_date, new_at=new_at, actor=manager["login"])
            await s.commit()
        await get_conversation_store().add_audit(
            manager["login"], f"task_{action}", user_id, str(task_id))
    except Exception:  # noqa: BLE001
        log.warning("calendar: task %s failed", action, exc_info=True)


@router.post("/conversation/{user_id}/task/{task_id}/complete", response_class=HTMLResponse)
async def task_complete(user_id: str, task_id: int, request: Request,
                        manager: dict = Depends(require_admin)):
    await _require_visible_conversation(user_id, manager)
    await _apply_task_action(user_id, task_id, manager, "complete")
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/task/{task_id}/cancel", response_class=HTMLResponse)
async def task_cancel(user_id: str, task_id: int, request: Request,
                      manager: dict = Depends(require_admin)):
    await _require_visible_conversation(user_id, manager)
    await _apply_task_action(user_id, task_id, manager, "cancel")
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/task/{task_id}/reschedule", response_class=HTMLResponse)
async def task_reschedule(user_id: str, task_id: int, request: Request,
                          manager: dict = Depends(require_admin),
                          scheduled_date: str = Form(""), scheduled_time: str = Form("")):
    await _require_visible_conversation(user_id, manager)
    try:
        d, at = _parse_task_when(scheduled_date, scheduled_time)
    except Exception:
        raise HTTPException(status_code=400, detail="bad date/time")
    await _apply_task_action(user_id, task_id, manager, "reschedule", new_date=d, new_at=at)
    return await _render_conversation(user_id, request, manager)


async def _fetch_calendar_tasks(manager: dict, date_from: date, date_to: date, *,
                                include_terminal: bool = False) -> list:
    """Tasks in the range for the calendar. Full-admin → all; else own only.
    Active tasks use a wider lower bound so overdue ones surface; done/cancelled ones are
    never back-filled — only the visible range (that's the 'сделано' counter). Fail-safe."""
    try:
        from app.domain.calendar_tasks import CalendarTaskService
        scoped = _manager_bot_scope(manager) is not None
        login = str(manager.get("login") or "").strip().lower()
        async with _domain_sessionmaker()() as s:
            async def _q(low: date, terminal: bool) -> list:
                if scoped:
                    return await CalendarTaskService.list_for_manager(
                        s, login, date_from=low, date_to=date_to, include_terminal=terminal)
                return await CalendarTaskService.list_all(
                    s, date_from=low, date_to=date_to, include_terminal=terminal)

            rows = await _q(date_from - timedelta(days=60), False)
            if include_terminal:
                seen = {t.id for t in rows}
                rows = rows + [t for t in await _q(date_from, True) if t.id not in seen]
            return rows
    except Exception:  # noqa: BLE001
        log.debug("calendar: fetch failed", exc_info=True)
        return []


async def _conv_map(user_ids: set[str]) -> dict:
    """user_id → live conversation, for the human bits on a task card (name, waiting, context).
    One light store read for the whole page. Fail-safe: empty map degrades to phone-only cards."""
    if not user_ids:
        return {}
    try:
        convs = await get_conversation_store().all_conversations_light()
        return {c.user_id: c for c in convs if c.user_id in user_ids}
    except Exception:  # noqa: BLE001
        log.debug("calendar: conversation map failed", exc_info=True)
        return {}


@router.get("/calendar", response_class=HTMLResponse)
async def calendar_view(request: Request, manager: dict = Depends(require_admin),
                        view: str = "day", day: str = ""):
    """Manager calendar. Day = the working call-list (overdue → now → later → done);
    week = a planning grid. Scoped manager sees only their tasks; full-admin all."""
    today = _bishkek_today()
    try:
        anchor = date.fromisoformat(day) if day else today
    except Exception:
        anchor = today
    if view == "week":
        d_from = anchor - timedelta(days=anchor.weekday())   # Monday
        d_to = d_from + timedelta(days=6)
    else:
        view, d_from, d_to = "day", anchor, anchor

    rows = await _fetch_calendar_tasks(manager, d_from, d_to, include_terminal=(view == "day"))
    convs = await _conv_map({t.user_id for t in rows if t.user_id})
    cards = [_task_ui(t, today, convs.get(t.user_id or "")) for t in rows]

    # Older-than-range tasks only ever surface as the overdue tail.
    overdue = sorted((c for c in cards if c["active"] and c["date"] < d_from),
                     key=lambda c: (c["date_iso"], c["time"] or "99:99"))
    in_range = [c for c in cards if d_from <= c["date"] <= d_to]

    days = [d_from + timedelta(days=i) for i in range((d_to - d_from).days + 1)]
    by_date: dict[date, list] = {d: [] for d in days}
    for c in in_range:
        if c["active"]:
            by_date[c["date"]].append(c)
    day_views = []
    for d in days:
        cards_d = by_date[d]
        day_views.append({
            "iso": d.isoformat(), "label": d.strftime("%d.%m"),
            "weekday": _WEEKDAYS_RU[d.weekday()], "is_today": d == today,
            "timed": sorted((c for c in cards_d if c["has_time"]), key=lambda c: c["time"]),
            "untimed": [c for c in cards_d if not c["has_time"]],
            "count": len(cards_d),
        })

    # Day screen: one list in the order the manager actually works it.
    todo = [c for c in in_range if c["active"] and c["date"] == anchor]
    timed = sorted((c for c in todo if c["has_time"]), key=lambda c: c["time"])
    untimed = [c for c in todo if not c["has_time"]]
    done = [c for c in in_range if c["done"] and c["date"] == anchor]
    now_hhmm = (datetime.now(timezone.utc) + timedelta(hours=6)).strftime("%H:%M")
    next_id = 0
    if anchor == today:
        upcoming = [c for c in timed if c["time"] >= now_hhmm]
        nxt = (upcoming or untimed or timed)
        next_id = nxt[0]["id"] if nxt else 0
    elif timed or untimed:
        next_id = (timed or untimed)[0]["id"]
    planned_total = len(todo) + len(done)

    step = 7 if view == "week" else 1
    return templates.TemplateResponse(request, "calendar.html", {
        "manager": manager,
        "is_admin": _manager_bot_scope(manager) is None,
        "view": view,
        "anchor_iso": anchor.isoformat(),
        "prev_day": (anchor - timedelta(days=step)).isoformat(),
        "next_day": (anchor + timedelta(days=step)).isoformat(),
        "today_iso": today.isoformat(),
        "is_today": anchor == today,
        "day_title": (f"{_WEEKDAYS_FULL_RU[anchor.weekday()]}, "
                      f"{anchor.day} {_MONTHS_RU[anchor.month - 1]}"),
        "range_label": (f"{d_from.strftime('%d.%m')} – {d_to.strftime('%d.%m')}"
                        if view == "week" else anchor.strftime("%d.%m.%Y")),
        "days": day_views,
        "overdue": overdue,
        "timed": timed, "untimed": untimed, "done": done, "next_id": next_id,
        "n_left": len(todo), "n_done": len(done), "n_planned": planned_total,
        "progress": int(round(100 * len(done) / planned_total)) if planned_total else 0,
        "now_hhmm": now_hhmm,
        "task_total": sum(dv["count"] for dv in day_views),
        "kind_labels": TASK_KIND_LABELS,
        "priority_labels": TASK_PRIORITY_LABELS,
    }, headers={"Cache-Control": "no-store"})


# ---- one-tap actions straight from the calendar (no client-card round-trip) ----------

def _calendar_redirect(view: str, day: str) -> RedirectResponse:
    v = "week" if view == "week" else "day"
    d = (day or "").strip()
    return RedirectResponse(f"/admin/calendar?view={v}" + (f"&day={d}" if d else ""),
                            status_code=303)


def _snoozed_when(task, mode: str, today: date) -> tuple[date, datetime | None]:
    """New (Bishkek date, exact UTC instant) for a one-tap snooze.
    h1/h2 — push from now (or from the task time if it is still ahead); tomorrow/today —
    keep the wall-clock time, move the day."""
    at = task.scheduled_at
    if at is not None and at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    if mode in ("h1", "h2"):
        now = datetime.now(timezone.utc)
        base = at if (at is not None and at > now) else now
        new_at = base + timedelta(hours=1 if mode == "h1" else 2)
        return (new_at + timedelta(hours=6)).date(), new_at
    if mode in ("tomorrow", "today"):
        d = (max(task.scheduled_date, today) + timedelta(days=1)) if mode == "tomorrow" else today
        shift = (d - task.scheduled_date).days
        return d, (at + timedelta(days=shift)) if at is not None else None
    raise HTTPException(status_code=400, detail="bad snooze mode")


async def _apply_calendar_action(task_id: int, manager: dict, action: str, *, mode: str = "",
                                 new_date: date | None = None,
                                 new_at: datetime | None = None) -> None:
    """Task lifecycle from the calendar. Ownership is checked on the task itself — unlike the
    client card, user_id may be empty (quick-added task). Fail-safe: never 500s the page."""
    try:
        from app.domain.calendar_tasks import CalendarTaskService
        async with _domain_sessionmaker()() as s:
            task = await CalendarTaskService.get(s, task_id)
            if task is None or not _manager_can_touch_task(manager, task):
                return
            uid = task.user_id or ""
            if action == "complete":
                await CalendarTaskService.complete(s, task, actor=manager["login"])
            elif action == "cancel":
                await CalendarTaskService.cancel(s, task, actor=manager["login"])
            elif action == "reschedule":
                if mode:
                    new_date, new_at = _snoozed_when(task, mode, _bishkek_today())
                if new_date is None:
                    return
                await CalendarTaskService.reschedule(
                    s, task, new_date=new_date, new_at=new_at, actor=manager["login"])
            await s.commit()
        await get_conversation_store().add_audit(
            manager["login"], f"task_{action}", uid, str(task_id))
    except Exception:  # noqa: BLE001
        log.warning("calendar: %s from calendar failed task=%s", action, task_id, exc_info=True)


@router.post("/calendar/task/{task_id}/complete")
async def calendar_task_complete(task_id: int, manager: dict = Depends(require_admin),
                                 view: str = Form("day"), day: str = Form("")):
    await _apply_calendar_action(task_id, manager, "complete")
    return _calendar_redirect(view, day)


@router.post("/calendar/task/{task_id}/cancel")
async def calendar_task_cancel(task_id: int, manager: dict = Depends(require_admin),
                               view: str = Form("day"), day: str = Form("")):
    await _apply_calendar_action(task_id, manager, "cancel")
    return _calendar_redirect(view, day)


@router.post("/calendar/task/{task_id}/snooze")
async def calendar_task_snooze(task_id: int, manager: dict = Depends(require_admin),
                               mode: str = Form("h2"), view: str = Form("day"),
                               day: str = Form("")):
    await _apply_calendar_action(task_id, manager, "reschedule", mode=mode)
    return _calendar_redirect(view, day)


@router.post("/calendar/task/{task_id}/reschedule")
async def calendar_task_reschedule(task_id: int, manager: dict = Depends(require_admin),
                                   scheduled_date: str = Form(""), scheduled_time: str = Form(""),
                                   view: str = Form("day"), day: str = Form("")):
    try:
        d, at = _parse_task_when(scheduled_date, scheduled_time)
    except Exception:
        raise HTTPException(status_code=400, detail="bad date/time")
    await _apply_calendar_action(task_id, manager, "reschedule", new_date=d, new_at=at)
    return _calendar_redirect(view, day)


def _default_direction(manager: dict) -> str:
    scope = _manager_bot_scope(manager) or set()
    return "visa" if any("getvisa" in b for b in scope) else "tours"


async def _find_conv_by_phone(digits: str, manager: dict):
    """Newest visible conversation whose number ends with the same 9 digits. '' → None."""
    tail = (digits or "")[-9:]
    if not tail:
        return None
    try:
        convs = await get_conversation_store().all_conversations_light()
    except Exception:  # noqa: BLE001
        return None
    best = None
    for c in convs:
        cd = "".join(ch for ch in (c.phone or c.user_id or "") if ch.isdigit())
        if not cd.endswith(tail) or not _can_view_conversation(c, manager):
            continue
        if best is None or _as_utc(c.last_message_at) > _as_utc(best.last_message_at):
            best = c
    return best


@router.post("/calendar/task/create")
async def calendar_task_quick_create(manager: dict = Depends(require_admin),
                                     phone: str = Form(""), kind: str = Form("call"),
                                     scheduled_date: str = Form(""), scheduled_time: str = Form(""),
                                     priority: str = Form("normal"), comment: str = Form(""),
                                     view: str = Form("day"), day: str = Form("")):
    """Add a task from the calendar itself, by phone — the manager does not have to hunt for
    the dialog first. Links the live conversation when one exists for that number."""
    try:
        d, at = _parse_task_when(scheduled_date, scheduled_time)
    except Exception:
        raise HTTPException(status_code=400, detail="bad date/time")
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if not digits:
        return _calendar_redirect(view, day)
    conv = await _find_conv_by_phone(digits, manager)
    try:
        from app.domain.calendar_tasks import CalendarTaskService
        from app.domain.models import DIRECTIONS
        from app.domain.services import ContactService
        direction = (getattr(conv, "funnel", "") or "") if conv is not None else ""
        if direction not in DIRECTIONS:
            direction = _default_direction(manager)
        async with _domain_sessionmaker()() as s:
            contact = await ContactService.find_or_create_by_identity(s, "phone", digits)
            await CalendarTaskService.create(
                s, manager_id=manager["login"], direction=direction, kind=kind,
                scheduled_date=d, scheduled_at=at, contact_id=contact.id,
                user_id=(conv.user_id if conv is not None else ""),
                priority=priority, comment=comment, created_by=manager["login"])
            await s.commit()
        await get_conversation_store().add_audit(
            manager["login"], "task_create", (conv.user_id if conv is not None else ""),
            f"{kind} {d.isoformat()} {digits}")
    except Exception:  # noqa: BLE001 — bad number / domain down must not break the page
        log.warning("calendar: quick task create failed", exc_info=True)
    return _calendar_redirect(view, day)


async def _set_intercept(user_id: str, value: bool) -> None:
    await set_intercept(user_id, value)
