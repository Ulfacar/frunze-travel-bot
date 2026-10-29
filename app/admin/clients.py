"""Клиенты без Bitrix: ручное обращение, заметки менеджера, карточка клиента.

Три вещи, которые менеджеры виз и туров каждый день делают в Bitrix и которых в панели
не было (таблица — `docs/pm-review-2026-10-30/bitrix.md`):

* **Новый клиент** (`/admin/clients/new`) — позвонили, пришли в офис, написали в Instagram.
  Откуда пришёл клиент, хранится в квитанции формы, а не в `conversations.source`: это
  поле шаблоны читают как «реклама/пост», и ручной клиент выглядел бы пришедшим с поста.
  Карточка заводится на WhatsApp-номер направления (`<бот>:<телефон>`), поэтому, когда
  клиент потом напишет сам, его сообщения лягут в ту же переписку, а менеджер может
  написать ему первым из панели. Диалог сразу закреплён за автором и перехвачен —
  бот в него не вмешивается. Флаг `panel_manual_lead_enabled`, дефолт OFF.
* **Заметки** — внутренний комментарий к клиенту, клиенту не уходит никогда.
  Флаг `panel_client_card_enabled`, дефолт OFF.
* **Карточка клиента** (`/admin/client/<телефон>`) — все переписки этого номера, которые
  менеджер вправе видеть, задачи, услуги, заметки и история ответственных. Тот же флаг.

Права проверяет сервер теми же функциями, что и переписку (`_can_view_conversation`,
`bot_scope_for`): менеджер видит и пишет только в своём направлении, чужой номер
отвечает 404 без подсказки, что такой клиент есть. Двойная отправка формы не создаёт
второй записи: у каждой формы одноразовый ключ, уникальность держит БД.

Таблицы `client_notes` и `client_intake_receipts` — на легаси-метаданных `Base`: их
создаёт тот же `create_all` при старте, что и `conversations` (Alembic их не ведёт,
см. `alembic/versions/wp1a_domain_0001_domain_foundation.py`). Только добавление.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column

from app.admin import router as ar
from app.admin.contracts import _csrf
from app.config import settings
from app.domain.models import DomainError
from app.domain.phones import normalize_phone
from app.integrations.crm.db import AuditLog, Base, get_sessionmaker
from app.integrations.panel.store import get_conversation_store

log = logging.getLogger("admin.clients")

MANUAL_FLAG = "panel_manual_lead_enabled"
CARD_FLAG = "panel_client_card_enabled"

# Откуда пришёл клиент мимо бота. Ключ пишется в `conversations.source_id`.
SOURCES = (("call", "Позвонил"), ("office", "Пришёл в офис"),
           ("instagram", "Instagram"), ("other", "Другое"))
SOURCE_LABELS = dict(SOURCES)
# Воронки, которые может выбрать менеджер для своего направления.
FUNNELS_BY_DIRECTION = {"visa": (("visa", "Визы"),),
                        "tours": (("tours", "Туры"), ("tickets", "Авиабилеты"))}
NOTE_MAX = 2000
NAME_MAX = 120
_KEY_RE = re.compile(r"[0-9a-f]{48}")
_NOTE_KEY_RE = re.compile(r"[0-9a-f]{32}")


class ClientNote(Base):
    """Внутренняя заметка менеджера к клиенту. Не редактируется и не удаляется:
    это журнал, как комментарии в таймлайне Bitrix. Удаление — решение владельца."""

    __tablename__ = "client_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(160), index=True)   # ключ переписки
    phone: Mapped[str] = mapped_column(String(64), index=True, default="")
    author: Mapped[str] = mapped_column(String(64), default="")
    text: Mapped[str] = mapped_column(Text, default="")
    # Одноразовый ключ формы: двойной клик и повтор запроса не дают второй заметки.
    request_key: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ClientIntakeReceipt(Base):
    """Квитанция формы «Новый клиент»: один ключ формы — одна запись, при повторе —
    тот же результат. `state`: pending (в работе) | created | existing."""

    __tablename__ = "client_intake_receipts"

    request_key: Mapped[str] = mapped_column(String(48), primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    payload_hash: Mapped[str] = mapped_column(String(64))
    user_id: Mapped[str] = mapped_column(String(160), index=True)
    source: Mapped[str] = mapped_column(String(16), default="")      # call|office|instagram|other
    state: Mapped[str] = mapped_column(String(16), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


def _sm():
    """Фабрика сессий для двух таблиц выше (в тестах подменяется)."""
    return get_sessionmaker()


async def _flag_on(key: str) -> bool:
    # Отдельная CRM живёт на своей базе без этих таблиц и с другими правилами владения.
    if settings.crm_standalone_enabled:
        return False
    return await ar._media_flag(key)


async def _require_flag(key: str) -> None:
    if not await _flag_on(key):
        raise HTTPException(status_code=404, detail="not found")


def _wa_bots_for(manager: dict) -> list:
    """WhatsApp-номера, на которые менеджер вправе завести клиента (его направление)."""
    from app.core.live_authz import direction_for_bot
    scope = ar._manager_bot_scope(manager)
    out = []
    for bot in settings.bots:
        if scope is not None and bot.id not in scope:
            continue
        if direction_for_bot(bot.id) in FUNNELS_BY_DIRECTION:
            out.append(bot)
    return out


def _bot_label(bot) -> str:
    direction = {"visa": "Визы", "tours": "Туры"}.get(bot.scenario, bot.scenario)
    who = f" · {bot.manager_name}" if getattr(bot, "manager_name", "") else ""
    return f"{direction} — {bot.title or bot.id}{who}"


def _check_csrf(request: Request, token: str) -> None:
    expected = request.session.get("contract_csrf", "")
    if not expected or not token or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=403, detail="Форма устарела. Откройте её заново.")


def _phone_digits(conv) -> str:
    raw = (getattr(conv, "phone", "") or "").strip()
    if not raw:
        _, _, raw = (getattr(conv, "user_id", "") or "").partition(":")
    return re.sub(r"\D", "", raw)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _bishkek(dt, fmt: str = "%d.%m.%Y %H:%M") -> str:
    """Время для менеджера — по Бишкеку (UTC+6, без перехода на летнее). SQLite отдаёт
    naive-время, оно в UTC."""
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt.astimezone(timezone.utc) + timedelta(hours=6)).strftime(fmt)


def _who(login: str) -> str:
    """Имя менеджера вместо логина, если он есть в списке менеджеров."""
    login = (login or "").strip().lower()
    for m in settings.manager_list():
        if (m.login or "").strip().lower() == login and m.name:
            return m.name
    return login


ar.templates.env.filters.setdefault("bishkek", _bishkek)
ar.templates.env.filters.setdefault("who", _who)


# ============================== Новый клиент ==============================

def _intake_signature(request: Request, actor: str, key: str) -> str:
    payload = json.dumps(["client-intake/1", actor, key, _csrf(request)],
                         separators=(",", ":")).encode()
    return hmac.new(settings.session_secret.encode(), payload, hashlib.sha256).hexdigest()


def _blank_form(request: Request, manager: dict, bots: list) -> dict:
    key = secrets.token_hex(24)
    first_bot = bots[0].id if bots else ""
    return {"request_key": key, "signature": _intake_signature(request, manager["login"], key),
            "csrf_token": _csrf(request), "name": "", "phone": "", "source": "call",
            "bot_id": first_bot, "funnel": "", "note": ""}


async def _render_new(request: Request, manager: dict, form: dict, *, error: str = "",
                existing=None, status: int = 200):
    bots = _wa_bots_for(manager)
    from app.core.live_authz import direction_for_bot
    funnels = []
    for bot in bots:
        for key, label in FUNNELS_BY_DIRECTION.get(direction_for_bot(bot.id), ()):
            funnels.append({"bot_id": bot.id, "key": key, "label": label})
    resp = ar.templates.TemplateResponse(request, "client_new.html", {
        "manager": manager, "values": form, "error": error, "existing": existing,
        "bots": [{"id": b.id, "label": _bot_label(b)} for b in bots],
        "funnels": funnels, "sources": SOURCES,
        "card_on": await _flag_on(CARD_FLAG),
    }, status_code=status, headers={"Cache-Control": "no-store"})
    resp.headers["X-Action-Outcome"] = ("existing" if existing is not None
                                        else "invalid" if error else "form")
    return resp


@ar.router.get("/clients/new", response_class=HTMLResponse)
async def client_new_form(request: Request, manager: dict = Depends(ar.require_admin)):
    await _require_flag(MANUAL_FLAG)
    bots = _wa_bots_for(manager)
    if not bots:
        raise HTTPException(status_code=403, detail="Нет доступного направления")
    return await _render_new(request, manager, _blank_form(request, manager, bots))


_INTAKE_FIELDS = {"request_key", "signature", "csrf_token", "name", "phone", "source",
                  "bot_id", "funnel", "note"}


@ar.router.post("/clients/new", response_class=HTMLResponse)
async def client_new_submit(request: Request, manager: dict = Depends(ar.require_admin)):
    await _require_flag(MANUAL_FLAG)
    if len(await request.body()) > 16384:
        raise HTTPException(status_code=413)
    submitted = await request.form()
    if not set(submitted) <= _INTAKE_FIELDS or any(len(submitted.getlist(k)) > 1 for k in submitted):
        raise HTTPException(status_code=422)
    form = {k: str(submitted.get(k, "")) for k in _INTAKE_FIELDS}
    actor = str(manager.get("login") or "").strip().lower()
    _check_csrf(request, form["csrf_token"])
    if (not _KEY_RE.fullmatch(form["request_key"]) or not hmac.compare_digest(
            _intake_signature(request, manager["login"], form["request_key"]).encode(),
            form["signature"].encode())):
        raise HTTPException(status_code=403, detail="Форма устарела. Откройте её заново.")

    # Номер — только из направления менеджера. Это проверка сервера, а не выпадающего
    # списка: подставить в форму чужой бот нельзя.
    from app.core.live_authz import direction_for_bot
    bots = {b.id: b for b in _wa_bots_for(manager)}
    bot = bots.get(form["bot_id"])
    if bot is None:
        raise HTTPException(status_code=403, detail="Нет доступа к этому номеру")
    direction = direction_for_bot(bot.id)
    allowed_funnels = [k for k, _ in FUNNELS_BY_DIRECTION.get(direction, ())]
    funnel = form["funnel"] or (allowed_funnels[0] if allowed_funnels else "")
    if funnel not in allowed_funnels:
        raise HTTPException(status_code=403, detail="Воронка не из вашего направления")

    name = form["name"].strip()
    note = form["note"].strip()
    if not 1 <= len(name) <= NAME_MAX or any(ord(c) < 32 for c in name):
        return await _render_new(request, manager, form,
                                 error=f"Укажите имя (до {NAME_MAX} символов).", status=422)
    if form["source"] not in SOURCE_LABELS:
        return await _render_new(request, manager, form, error="Выберите, откуда клиент.",
                                 status=422)
    if len(note) > NOTE_MAX:
        return await _render_new(request, manager, form,
                                 error=f"Заметка длиннее {NOTE_MAX} символов.", status=422)
    try:
        digits = normalize_phone(form["phone"].strip())
    except DomainError:
        return await _render_new(request, manager, form, status=422, error=(
            "Номер не распознан. Пример: 0555 123 456 или +7 701 123 45 67."))
    user_id = f"{bot.id}:{digits}"
    payload_hash = hashlib.sha256(json.dumps(
        [actor, bot.id, funnel, digits, name, form["source"], note],
        ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

    # 1. Квитанция — первой: повтор той же формы (двойной клик, F5) получает тот же итог.
    async with _sm()() as s:
        receipt = await s.get(ClientIntakeReceipt, form["request_key"])
        if receipt is None:
            s.add(ClientIntakeReceipt(request_key=form["request_key"], actor=actor,
                                      payload_hash=payload_hash, user_id=user_id,
                                      source=form["source"], state="pending", created_at=_now()))
            try:
                await s.commit()
            except IntegrityError:
                await s.rollback()
                receipt = await s.get(ClientIntakeReceipt, form["request_key"])
                if receipt is None:
                    raise
                if receipt.state == "pending":
                    # Параллельный дубль той же формы: работу делает первый запрос.
                    return RedirectResponse(_open_url(receipt.user_id), status_code=303)
        if receipt is not None:
            if receipt.actor != actor or receipt.payload_hash != payload_hash:
                raise HTTPException(status_code=409,
                                    detail="Эта форма уже сохранена с другими данными.")
            if receipt.state == "created":
                return RedirectResponse(_open_url(receipt.user_id), status_code=303)

    store = get_conversation_store()
    existing = await store.get(user_id)
    if existing is not None:
        # Номер уже есть: ничего не меняем у чужой или своей карточки — ни владельца,
        # ни перехвата. Заметку сохраняем: её и пришли оставить.
        if not ar._can_view_conversation(existing, manager):
            raise HTTPException(status_code=404)
        if note:
            await _insert_note(existing, actor, note, f"intake:{form['request_key']}")
        await _finish_receipt(form["request_key"], "existing")
        await store.add_audit(actor, "manual_lead_existing", user_id, form["source"])
        return await _render_new(request, manager, form, existing=_conv_row(existing))

    # 2. Владение — тем же сторожем, что и «Перехватить»: если по этому человеку уже
    # есть активный владелец в направлении (например, с другого номера), не отнимаем.
    probe = SimpleNamespace(user_id=user_id, phone=digits, channel="whatsapp",
                            bot_id=bot.id, funnel=funnel, assigned_to="")
    allowed, notice = await ar._ownership_guard(probe, manager, "claim")
    if not allowed:
        return await _render_new(request, manager, form, error=notice, status=409)

    # 3. Сама карточка. Каждый шаг идемпотентен: повтор после сбоя доводит до конца.
    await store.ensure(user_id, channel="whatsapp", bot_id=bot.id,
                       chat_id=f"{digits}@c.us", phone=digits)
    await store.update_meta(user_id, funnel=funnel, stage="manager",
                            qualification={"name": name}, assigned_to=actor)
    await ar._set_intercept(user_id, True)
    conv = await store.get(user_id)
    if note and conv is not None:
        await _insert_note(conv, actor, note, f"intake:{form['request_key']}")
    await store.add_audit(actor, "manual_lead", user_id, f"{form['source']} {funnel}")
    await _finish_receipt(form["request_key"], "created")
    return RedirectResponse(_open_url(user_id), status_code=303)


def _open_url(user_id: str) -> str:
    return "/admin?open=" + quote(user_id, safe="")


async def _finish_receipt(key: str, state: str) -> None:
    async with _sm()() as s:
        receipt = await s.get(ClientIntakeReceipt, key)
        if receipt is not None and receipt.state == "pending":
            receipt.state = state
            await s.commit()


# ================================ Заметки ================================

async def _insert_note(conv, author: str, text: str, request_key: str) -> bool:
    """Записать заметку. False — такая форма уже сохранена (повтор)."""
    async with _sm()() as s:
        s.add(ClientNote(user_id=conv.user_id, phone=_phone_digits(conv), author=author,
                         text=text, request_key=request_key, created_at=_now()))
        try:
            await s.commit()
        except IntegrityError:
            await s.rollback()
            return False
    return True


async def _notes_for(user_ids: list[str]) -> list[ClientNote]:
    if not user_ids:
        return []
    async with _sm()() as s:
        rows = await s.scalars(select(ClientNote).where(ClientNote.user_id.in_(user_ids))
                               .order_by(ClientNote.created_at.desc(), ClientNote.id.desc()))
        return list(rows.all())


async def notes_context(request: Request, conv, manager: dict) -> dict | None:
    """Блок заметок в чате. None — флаг выключен (шаблон ничего не рисует).

    Вызывается из `_render_conversation`, то есть уже после проверки видимости.
    Сбой базы не роняет чат: блок показывает, что заметки недоступны.
    """
    if not await _flag_on(CARD_FLAG):
        return None
    try:
        notes = await _notes_for([conv.user_id])
        error = ""
    except Exception:  # noqa: BLE001 — переписка важнее заметок
        log.warning("client notes: load failed", exc_info=True)
        notes, error = [], "Заметки сейчас недоступны — переписка работает."
    return {"items": notes, "error": error, "note_key": secrets.token_hex(16),
            "csrf_token": _csrf(request), "max": NOTE_MAX,
            "card_url": "/admin/client/" + quote(_phone_digits(conv) or conv.user_id, safe="")}


@ar.router.post("/conversation/{user_id}/notes", response_class=HTMLResponse)
async def add_note(user_id: str, request: Request, manager: dict = Depends(ar.require_admin)):
    await _require_flag(CARD_FLAG)
    conv = await ar._require_visible_conversation(user_id, manager)   # чужое → 404
    form = await request.form()
    _check_csrf(request, str(form.get("csrf_token", "")))
    key = str(form.get("note_key", ""))
    # Поле называется `note`, не `text`: скрипты чата ищут поле ответа клиенту по
    # `form.composer textarea[name="text"]`, и «Предложить ответ» писал бы в заметку.
    text = str(form.get("note", "")).strip()
    if not _NOTE_KEY_RE.fullmatch(key):
        raise HTTPException(status_code=422)
    notice = ""
    if not text:
        notice = "Заметка пустая — нечего сохранить."
    elif len(text) > NOTE_MAX:
        notice = f"Заметка длиннее {NOTE_MAX} символов — сократите."
    else:
        try:
            if await _insert_note(conv, manager["login"], text, f"note:{key}"):
                await get_conversation_store().add_audit(manager["login"], "note", user_id,
                                                         str(len(text)))
        except Exception:  # noqa: BLE001
            log.warning("client notes: insert failed", exc_info=True)
            notice = "Заметка не сохранилась — повторите."
    resp = await ar._render_conversation(user_id, request, manager, notice=notice)
    resp.headers["X-Action-Outcome"] = "failed" if notice else "noted"
    return resp


# ============================ Карточка клиента ============================

def _conv_row(c) -> dict:
    return {"user_id": c.user_id, "open_url": _open_url(c.user_id),
            "name": (c.qualification or {}).get("name") or "",
            "funnel": ar.FUNNEL_LABELS.get(c.funnel or "", c.funnel or "—"),
            "bot_id": c.bot_id, "stage": ar.STAGE_LABELS.get(c.stage or "", c.stage or ""),
            "assigned_to": c.assigned_to or "", "intercepted": bool(c.intercepted),
            "outcome": dict(ar.OUTCOMES).get(c.outcome or "", ""),
            "last_text": c.last_text or "", "last_sender": c.last_sender or "",
            "last_message_at": c.last_message_at, "archived": bool(c.archived)}


_HISTORY_ACTIONS = {"takeover": "взял(а) в работу", "release": "вернул(а) боту",
                    "reassign": "передал(а)", "manual_lead": "завёл(а) клиента вручную",
                    "manual_lead_existing": "повторно внёс(ла) номер",
                    "outcome": "отметил(а) исход", "stage": "сменил(а) этап",
                    "send": "написал(а) клиенту"}


async def _audit_for(user_ids: list[str]) -> list[dict]:
    """События по этим перепискам из журнала действий (для истории ответственных)."""
    store = get_conversation_store()
    wanted = set(user_ids)
    try:
        memory = getattr(store, "_audit", None)
        if memory is not None:
            rows = [r for r in memory if r.get("user_id") in wanted]
        else:
            async with _sm()() as s:
                found = await s.scalars(select(AuditLog).where(AuditLog.user_id.in_(user_ids))
                                        .order_by(AuditLog.id.desc()).limit(200))
                rows = [{"manager": r.manager, "action": r.action, "user_id": r.user_id,
                         "detail": r.detail, "created_at": r.created_at} for r in found.all()]
    except Exception:  # noqa: BLE001
        log.warning("client card: audit load failed", exc_info=True)
        return []
    out = []
    for r in rows:
        action = r.get("action", "")
        if action not in _HISTORY_ACTIONS:
            continue
        out.append({"who": r.get("manager", ""), "what": _HISTORY_ACTIONS[action],
                    "detail": r.get("detail", "") if action in ("reassign", "outcome", "stage")
                    else "", "user_id": r.get("user_id", ""), "at": r.get("created_at")})
    out.sort(key=lambda e: e["at"] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return out[:60]


async def _domain_view(digits: str, directions: set[str] | None) -> dict:
    """Владельцы и услуги из доменной схемы. Только чтение: контакт не создаётся."""
    out = {"assignments": [], "cases": []}
    try:
        from app.domain.models import Assignment, ContactIdentity, ServiceCase
        async with ar._domain_sessionmaker()() as s:
            contact_id = await s.scalar(select(ContactIdentity.contact_id).where(
                ContactIdentity.identity_type == "phone",
                ContactIdentity.normalized_value == digits).limit(1))
            if contact_id is None:
                return out
            q = select(Assignment).where(Assignment.contact_id == contact_id)
            if directions is not None:
                q = q.where(Assignment.direction.in_(directions))
            for a in (await s.scalars(q.order_by(Assignment.id.desc()).limit(30))).all():
                out["assignments"].append({
                    "direction": ar.FUNNEL_LABELS.get(a.direction, a.direction),
                    "manager": a.manager_id, "active": a.active, "by": a.assigned_by,
                    "reason": a.reason, "from": a.assigned_at, "to": a.ended_at})
            cases = (await s.scalars(select(ServiceCase).where(
                ServiceCase.contact_id == contact_id).order_by(ServiceCase.id.desc()).limit(20))).all()
            for c in cases:
                if directions is not None and c.owner_login and not await _case_visible(s, c, directions):
                    continue
                out["cases"].append({"id": c.id, "stage": c.stage, "owner": c.owner_login,
                                     "amount": c.agreed_amount, "currency": c.currency or "",
                                     "signed": bool(c.signed_at)})
    except Exception:  # noqa: BLE001 — доменная база может быть недоступна, карточка живёт
        log.warning("client card: domain view failed", exc_info=True)
    return out


async def _case_visible(session, case, directions: set[str]) -> bool:
    from app.domain.models import Product
    product = await session.get(Product, case.product_id)
    return product is not None and getattr(product, "direction", "") in directions


@ar.router.get("/client/{phone}", response_class=HTMLResponse)
async def client_card(phone: str, request: Request, manager: dict = Depends(ar.require_admin)):
    await _require_flag(CARD_FLAG)
    digits = re.sub(r"\D", "", phone or "")
    if not digits:
        raise HTTPException(status_code=404)
    store = get_conversation_store()
    convs = [c for c in await store.all_conversations_light()
             if _phone_digits(c) == digits and ar._can_view_conversation(c, manager)]
    if not convs:
        # Нет своих переписок с этим номером — 404, как будто номера нет вовсе.
        raise HTTPException(status_code=404, detail="not found")
    convs.sort(key=lambda c: c.last_message_at or datetime.min.replace(tzinfo=timezone.utc),
               reverse=True)
    ids = [c.user_id for c in convs]
    from app.core.live_authz import actor_for
    actor = actor_for(manager)
    directions = None if actor.is_full_admin else set(actor.allowed_directions)
    tasks = []
    for c in convs:
        for t in await ar._load_user_tasks(c.user_id):
            if t["active"]:
                tasks.append(t)
    origins: dict[str, str] = {}
    try:
        notes = await _notes_for(ids)
        notes_error = ""
        async with _sm()() as s:
            for r in (await s.scalars(select(ClientIntakeReceipt).where(
                    ClientIntakeReceipt.user_id.in_(ids),
                    ClientIntakeReceipt.state == "created"))).all():
                origins[r.user_id] = SOURCE_LABELS.get(r.source, "")
    except Exception:  # noqa: BLE001
        log.warning("client card: notes failed", exc_info=True)
        notes, notes_error = [], "Заметки сейчас недоступны."
    name = next(((c.qualification or {}).get("name") for c in convs
                 if (c.qualification or {}).get("name")), "")
    return ar.templates.TemplateResponse(request, "client_card.html", {
        "manager": manager, "digits": digits, "name": name,
        "convs": [dict(_conv_row(c), origin=origins.get(c.user_id, "")) for c in convs],
        "tasks": tasks, "notes": notes,
        "notes_error": notes_error, "history": await _audit_for(ids),
        "domain": await _domain_view(digits, directions),
        "manual_on": await _flag_on(MANUAL_FLAG),
    }, headers={"Cache-Control": "no-store"})
