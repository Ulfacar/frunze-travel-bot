"""Роутер админ-панели (FastAPI + Jinja2 + HTMX).

MVP: смотреть канбан-доски диалогов, открыть полный контекст переписки, перехватить
(бот замолкает). Двусторонняя отправка из панели — следующая фаза.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates

from app.channels import outbound
from app.config import settings
from app.core.state import get_state_store
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("admin")

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
_security = HTTPBasic()

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
    """Обогащённая карточка для доски: аватар, сигналы срочности, время."""
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
    return {
        "user_id": conv.user_id, "name": name or conv.user_id,
        "initials": _initials(name, conv.user_id),
        "avatar": AVATAR_GRADIENTS[sum(conv.user_id.encode()) % len(AVATAR_GRADIENTS)],
        "channel": conv.channel, "stage": conv.stage, "intercepted": conv.intercepted,
        "last_text": conv.last_text, "last_sender": conv.last_sender,
        "time_label": _time_label(since),
        "wait_label": _time_label(wait_min) if wait_min is not None else "",
        "wait_level": level,                       # none|fresh|warm|hot
        "lead_temperature": conv.lead_temperature,
        "sort_key": (wait_min if wait_min is not None else -1),
    }


def require_admin(creds: HTTPBasicCredentials = Depends(_security)) -> None:
    """HTTP Basic для всех эндпоинтов панели."""
    ok = (secrets.compare_digest(creds.username, settings.admin_user)
          and secrets.compare_digest(creds.password, settings.admin_password))
    if not ok:
        raise HTTPException(status_code=401, detail="Unauthorized",
                            headers={"WWW-Authenticate": "Basic"})


def _build_board(cards: list, now: datetime) -> tuple[list[dict], dict]:
    """Колонки канбана (карточки обогащены и отсортированы: ждут дольше — наверх) + метрики."""
    buckets: dict[str, list] = {key: [] for key, _ in BOARD_COLUMNS}
    for c in cards:
        col = STAGE_TO_COLUMN.get(c.stage, "greeting")
        buckets[col].append(_card_model(c, now))
    for col in buckets.values():
        col.sort(key=lambda m: m["sort_key"], reverse=True)  # горячие наверх
    columns = [{"key": key, "label": label, "cards": buckets[key], "is_empty": not buckets[key]}
               for key, label in BOARD_COLUMNS]
    metrics = {
        "total": len(cards),
        "waiting": sum(1 for col in buckets.values() for m in col if m["wait_level"] != "none"),
        "intercepted": sum(1 for c in cards if c.intercepted),
    }
    return columns, metrics


@router.get("", response_class=HTMLResponse)
async def index(request: Request, _: None = Depends(require_admin)):
    """Главная страница панели с вкладками-досками."""
    return templates.TemplateResponse(request, "boards.html", {"funnels": FUNNELS},
                                      headers={"Cache-Control": "no-store"})


@router.get("/board/{funnel}", response_class=HTMLResponse)
async def board(funnel: str, request: Request, _: None = Depends(require_admin)):
    """HTMX-партиал одной доски: колонки по стадиям с карточками."""
    panel = get_conversation_store()
    cards = await panel.list_cards(funnel)
    columns, metrics = _build_board(cards, _now())
    return templates.TemplateResponse(request, "_board.html", {
        "funnel": funnel, "columns": columns, "metrics": metrics,
    })


@router.get("/conversation/{user_id}", response_class=HTMLResponse)
async def conversation(user_id: str, request: Request, _: None = Depends(require_admin)):
    """HTMX-партиал: полный контекст диалога + квалификация + кнопка перехвата."""
    panel = get_conversation_store()
    conv = await panel.get(user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    name = conv.qualification.get("name")
    return templates.TemplateResponse(request, "_conversation.html", {
        "c": conv,
        "initials": _initials(name, conv.user_id),
        "avatar": AVATAR_GRADIENTS[sum(conv.user_id.encode()) % len(AVATAR_GRADIENTS)],
    })


@router.post("/conversation/{user_id}/takeover", response_class=HTMLResponse)
async def takeover(user_id: str, request: Request, _: None = Depends(require_admin)):
    """Менеджер перехватывает диалог: бот замолкает (флаг в состоянии + в карточке)."""
    await _set_intercept(user_id, True)
    return await conversation(user_id, request)


@router.post("/conversation/{user_id}/release", response_class=HTMLResponse)
async def release(user_id: str, request: Request, _: None = Depends(require_admin)):
    """Вернуть диалог боту."""
    await _set_intercept(user_id, False)
    return await conversation(user_id, request)


@router.post("/conversation/{user_id}/send", response_class=HTMLResponse)
async def send_message(user_id: str, request: Request, _: None = Depends(require_admin)):
    """Менеджер отвечает клиенту прямо из панели. Ручная отправка авто-перехватывает диалог."""
    form = await request.form()
    text = (form.get("text") or "").strip()
    panel = get_conversation_store()
    conv = await panel.get(user_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    if text:
        await _set_intercept(user_id, True)  # отвечает человек → бот молчит
        try:
            await outbound.send_to_client(conv.channel, conv.bot_id, conv.chat_id or user_id, text)
        except Exception:  # noqa: BLE001 — не теряем сообщение в логе при сбое канала
            log.warning("manager send failed (channel=%s)", conv.channel, exc_info=True)
        await panel.add_message(user_id, "manager", text)
    return await conversation(user_id, request)


async def _set_intercept(user_id: str, value: bool) -> None:
    # Источник правды для глушения бота — DialogState.intercepted (его читает оркестратор).
    store = get_state_store()
    state = await store.load(user_id)
    state.intercepted = value
    await store.save(state)
    # Отражаем в карточке панели.
    await get_conversation_store().set_intercepted(user_id, value)
