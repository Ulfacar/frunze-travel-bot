"""Роутер админ-панели (FastAPI + Jinja2 + HTMX).

Канбан-доски диалогов, полный контекст переписки, перехват (бот замолкает),
ответ менеджера клиенту, исход сделки. Аккаунты менеджеров — сессия (cookie),
список логинов в settings.managers. Действия пишутся в аудит-лог.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.agent.llm import chat, llm_enabled
from app.channels import outbound
from app.config import settings
from app.core.branding import quick_replies_for
from app.core.state import get_state_store
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("admin")

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Доски (вкладки) — по воронкам. Визы и Туры основные, Билеты — третья.
FUNNELS = [("visa", "Визы (GetVisa)"), ("tours", "Туры"), ("tickets", "Билеты")]

# Колонки канбана и маппинг внутренних стадий диалога в колонку.
BOARD_COLUMNS = [
    ("greeting", "Новый"),
    ("qualification", "Квалификация"),
    ("progress", "Подбор / оценка"),
    ("office", "В офис / консультация"),
    ("manager", "У менеджера"),
    ("follow_up", "Повторное касание"),
]
STAGE_TO_COLUMN = {
    "greeting": "greeting", "new": "greeting",
    "qualification": "qualification",
    "scoring": "progress", "search": "progress", "visa_scoring": "progress",
    "office": "office", "office_consultation": "office",
    "manager": "manager", "manager_handoff": "manager",
    "follow_up": "follow_up", "followup": "follow_up", "callback": "follow_up",
}

# Стадии, в которых ждут живого менеджера (для сигнала «требуют ответа»).
HUMAN_STAGES = {"office", "office_consultation", "manager", "manager_handoff"}

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
    return {
        "user_id": conv.user_id, "name": name or conv.user_id,
        "initials": _initials(name, conv.user_id),
        "avatar": _avatar(conv.user_id),
        "channel": conv.channel, "stage": conv.stage, "intercepted": conv.intercepted,
        "assigned_to": conv.assigned_to, "outcome": conv.outcome,
        "last_text": conv.last_text, "last_sender": conv.last_sender,
        "time_label": _time_label(since),
        "wait_label": _time_label(wait_min) if wait_min is not None else "",
        "wait_level": level,                       # none|fresh|warm|hot
        "needs_reply": needs_reply,
        "lead_temperature": conv.lead_temperature,
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


def _check_credentials(login: str, password: str) -> dict | None:
    for mgr in settings.manager_list():
        if (secrets.compare_digest(login, mgr.login)
                and secrets.compare_digest(password, mgr.password)):
            return {"login": mgr.login, "name": mgr.name or mgr.login}
    return None


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    if current_manager(request):
        return RedirectResponse("/admin", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None},
                                      headers={"Cache-Control": "no-store"})


@router.post("/login", response_class=HTMLResponse)
async def login_submit(request: Request, login: str = Form(...), password: str = Form(...)):
    manager = _check_credentials(login.strip(), password)
    if manager is None:
        return templates.TemplateResponse(request, "login.html",
                                          {"error": "Неверный логин или пароль"}, status_code=401)
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
        buckets[STAGE_TO_COLUMN.get(m["stage"], "greeting")].append(m)
    for col in buckets.values():
        col.sort(key=lambda m: m["sort_key"], reverse=True)  # горячие наверх
    columns = [{"key": key, "label": label, "cards": buckets[key], "is_empty": not buckets[key]}
               for key, label in BOARD_COLUMNS]
    metrics = {
        "total": len(cards),
        "waiting": sum(1 for m in models if m["wait_level"] != "none"),
        "needs_reply": sum(1 for m in models if m["needs_reply"]),
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
                                      {"funnels": FUNNELS, "manager": manager},
                                      headers={"Cache-Control": "no-store"})


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request, manager: dict = Depends(require_admin)):
    """Дашборд «ИИ vs менеджер»: containment, исходы, воронки, время ответа/перехвата."""
    from app.integrations.panel.analytics import compute_analytics
    convs = await get_conversation_store().all_conversations()
    data = compute_analytics(convs)
    return templates.TemplateResponse(request, "analytics.html",
                                      {"a": data, "manager": manager, "funnels": FUNNELS},
                                      headers={"Cache-Control": "no-store"})


@router.get("/board/{funnel}", response_class=HTMLResponse)
async def board(funnel: str, request: Request, _: dict = Depends(require_admin)):
    """HTMX-партиал одной доски: колонки по стадиям с карточками."""
    panel = get_conversation_store()
    cards = await panel.list_cards(funnel)
    columns, metrics = _build_board(cards, _now())
    return templates.TemplateResponse(request, "_board.html", {
        "funnel": funnel, "columns": columns, "metrics": metrics,
    })


async def _render_conversation(user_id: str, request: Request, manager: dict):
    panel = get_conversation_store()
    conv = await panel.get(user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    name = conv.qualification.get("name")
    # Кем занят, если не нами (мягкое предупреждение — не блок).
    busy_by = conv.assigned_to if conv.assigned_to and conv.assigned_to != manager["login"] else ""
    return templates.TemplateResponse(request, "_conversation.html", {
        "c": conv,
        "initials": _initials(name, conv.user_id),
        "avatar": _avatar(conv.user_id),
        "manager": manager,
        "busy_by": busy_by,
        "outcomes": OUTCOMES,
        "quick_replies": quick_replies_for(conv.funnel),
    })


@router.get("/conversation/{user_id}", response_class=HTMLResponse)
async def conversation(user_id: str, request: Request, manager: dict = Depends(require_admin)):
    """HTMX-партиал: полный контекст диалога + квалификация + действия менеджера."""
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/takeover", response_class=HTMLResponse)
async def takeover(user_id: str, request: Request, manager: dict = Depends(require_admin)):
    """Менеджер перехватывает диалог: бот замолкает, диалог закрепляется за менеджером."""
    await _set_intercept(user_id, True)
    await get_conversation_store().update_meta(user_id, assigned_to=manager["login"])
    await get_conversation_store().add_audit(manager["login"], "takeover", user_id)
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/release", response_class=HTMLResponse)
async def release(user_id: str, request: Request, manager: dict = Depends(require_admin)):
    """Вернуть диалог боту (снять перехват и закрепление)."""
    await _set_intercept(user_id, False)
    await get_conversation_store().release_claim(user_id)
    await get_conversation_store().add_audit(manager["login"], "release", user_id)
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/send", response_class=HTMLResponse)
async def send_message(user_id: str, request: Request, manager: dict = Depends(require_admin),
                       text: str = Form("")):
    """Менеджер отвечает клиенту прямо из панели. Ручная отправка авто-перехватывает диалог."""
    text = text.strip()
    panel = get_conversation_store()
    conv = await panel.get(user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if text:
        await _set_intercept(user_id, True)  # отвечает человек → бот молчит
        await panel.update_meta(user_id, assigned_to=manager["login"])
        msg_id = await panel.add_message(user_id, "manager", text, status="pending")
        try:
            provider = await outbound.send_to_client(
                conv.channel, conv.bot_id, conv.chat_id or user_id, text)
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
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    target = next((m for m in conv.messages if m.id == message_id), None)
    if target is not None and target.text:
        try:
            provider = await outbound.send_to_client(
                conv.channel, conv.bot_id, conv.chat_id or user_id, target.text)
            await panel.mark_message_status(message_id=message_id, status="sent",
                                            set_provider_msg_id=(provider or None))
        except Exception:  # noqa: BLE001
            await panel.mark_message_status(message_id=message_id, status="failed")
            log.warning("resend failed (channel=%s)", conv.channel, exc_info=True)
        await panel.add_audit(manager["login"], "resend", user_id)
    return await _render_conversation(user_id, request, manager)


@router.post("/conversation/{user_id}/suggest", response_class=PlainTextResponse)
async def suggest_reply(user_id: str, request: Request, _: dict = Depends(require_admin)):
    """Сгенерировать черновик ответа клиенту (Claude) из контекста — менеджер правит и шлёт."""
    conv = await get_conversation_store().get(user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if not llm_enabled():
        return "ИИ недоступен (нет ключа OpenRouter) — ответьте вручную."
    # История диалога → формат чата (client=user, bot/manager=assistant).
    history = [{"role": "user" if m.sender == "client" else "assistant", "content": m.text}
               for m in conv.messages if m.text]
    if not history or history[-1]["role"] != "user":
        history.append({"role": "user", "content": "(Предложи уместный следующий шаг.)"})
    persona = "GetVisa (Медина, визовый эксперт)" if conv.funnel == "visa" else "Frunze Travel (Сезим)"
    system = (
        f"Ты — менеджер {persona}. Предложи ОДИН следующий ответ клиенту по контексту "
        f"переписки: тепло, кратко, по-русски, в стиле бренда, без выдуманных цен. "
        f"Контекст для тебя: {conv.ai_summary or '—'}. Следующий шаг: {conv.manager_next_step or '—'}. "
        f"Верни ТОЛЬКО текст ответа клиенту, без пояснений."
    )
    try:
        resp = await chat(system, history)
        text = " ".join(b.get("text", "") for b in resp.get("content", [])
                        if b.get("type") == "text").strip()
        return text or "Не удалось сгенерировать черновик — попробуйте ещё раз."
    except Exception:  # noqa: BLE001
        log.warning("suggest failed", exc_info=True)
        return "Не удалось сгенерировать черновик — попробуйте ещё раз."


@router.post("/conversation/{user_id}/outcome", response_class=HTMLResponse)
async def set_outcome(user_id: str, request: Request, manager: dict = Depends(require_admin),
                      outcome: str = Form(...)):
    """Менеджер отмечает исход диалога (оплатил / дошёл / слился)."""
    valid = {key for key, _ in OUTCOMES}
    if outcome in valid:
        await get_conversation_store().update_meta(user_id, outcome=outcome)
        await get_conversation_store().add_audit(manager["login"], "outcome", user_id, outcome)
    return await _render_conversation(user_id, request, manager)


async def _set_intercept(user_id: str, value: bool) -> None:
    # Источник правды для глушения бота — DialogState.intercepted (его читает оркестратор).
    store = get_state_store()
    state = await store.load(user_id)
    state.intercepted = value
    await store.save(state)
    # Отражаем в карточке панели.
    await get_conversation_store().set_intercepted(user_id, value)
