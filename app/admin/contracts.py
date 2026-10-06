"""E1-03/E2-06: подтверждённый договор из доступной переписки.

GET ничего не создаёт. POST не принимает contact_id, владельца или автора от
браузера; идентичность и актуальное владение проверяются до sign_contract.
Старый fail-open гейт перехвата здесь неприменим: это договор и деньги.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timezone
from urllib.parse import quote
from zoneinfo import ZoneInfo

from fastapi import Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, text

import app.admin.router as ar
from app.admin.workday import _require_workday, _write_on
from app.core import live_authz
from app.domain import live_assign
from app.domain.models import ContactIdentity, DomainError, Product, WorkflowVersion
from app.domain.phones import normalize_phone
from app.domain.service_authz import PermissionDenied, can_open_case
from app.domain.service_cases import sign_contract
from app.domain.services import ContactService

log = logging.getLogger("admin.contracts")
BISHKEK = ZoneInfo("Asia/Bishkek")
FIELDS = ("product_id", "reference", "signed_at", "amount", "currency",
          "amount_unknown_reason", "confirmed", "idempotency_key", "key_signature")


def _csrf(request: Request) -> str:
    if not request.session.get("contract_csrf"):
        request.session["contract_csrf"] = secrets.token_hex(32)
    return request.session["contract_csrf"]


def _signature(request: Request, user_id: str, login: str, key: str) -> str:
    payload = "\n".join(("contract-v1", login, user_id, key, _csrf(request))).encode("utf-8")
    # CSRF-токен виден браузеру: он связывает форму с сессией, но не может быть
    # секретом подписи. Ключ сервера в HTML не отдаётся.
    return hmac.new(ar.settings.session_secret.encode(), payload, hashlib.sha256).hexdigest()


def _identity(conv) -> tuple[str, str]:
    """Не допускаем молчаливую склейку по неверному phone или Telegram ID."""
    channel = (conv.channel or "").lower()
    prefix, sep, tail = conv.user_id.partition(":")
    if sep and prefix != conv.bot_id:
        raise DomainError("Идентификатор переписки не совпадает с каналом. Нужна проверка администратора.")
    raw_key = tail if sep else conv.user_id
    # Старый рендер чата подставляет целый user_id в пустой phone. Это подпись
    # интерфейса, а не другая идентичность; префикс бота уже проверен выше.
    raw_phone = raw_key if not conv.phone or conv.phone == conv.user_id else conv.phone
    if channel == "telegram":
        if not re.fullmatch(r"[1-9][0-9]*", raw_key) or raw_phone != raw_key:
            raise DomainError("Идентификатор Telegram требует проверки администратора.")
        return "telegram", raw_key
    if channel not in ("whatsapp", "wappi"):
        raise DomainError("Канал клиента не определён. Сначала проверьте переписку.")
    for value in (raw_key, raw_phone):
        if "@g.us" in value or not re.fullmatch(r"\+?[0-9 ()-]+(?:@c\.us|@s\.whatsapp\.net)?", value):
            raise DomainError("Номер клиента требует проверки администратора.")
    try:
        key_phone = normalize_phone(raw_key, assume_e164=True)
        field_phone = normalize_phone(raw_phone, assume_e164=True)
    except DomainError as exc:
        raise DomainError("Номер клиента требует проверки администратора.") from exc
    if key_phone != field_phone:
        raise DomainError("Номер клиента не совпадает с ключом переписки. Нужна проверка администратора.")
    return "phone", key_phone


async def _conversation(user_id, manager):
    conv = await ar._require_visible_conversation(user_id, manager)
    actor = live_authz.actor_for(manager)
    direction = conv.funnel if conv.funnel in ("tours", "visa", "tickets") else ar._authz_direction(conv)
    if not direction or not can_open_case(actor, direction=direction):
        raise HTTPException(404)
    # Предварительная проверка до доступа к доменным идентичностям.
    if not actor.is_full_admin and conv.assigned_to and conv.assigned_to.strip().lower() != actor.manager_id:
        raise HTTPException(404)
    return conv, actor, direction


async def _owner(session, conv, actor, direction, contact, *, lock=False):
    if contact is not None and lock:
        await live_assign.lock_contact(session, contact.id)
    assignment = (await live_assign.active_assignment(session, contact.id, direction)
                  if contact is not None else None)
    domain_owner = (assignment.manager_id or "").strip().lower() if assignment else ""
    panel_owner = (conv.assigned_to or "").strip().lower()
    if domain_owner and not actor.is_full_admin and domain_owner != actor.manager_id:
        raise HTTPException(404)
    if domain_owner and panel_owner and domain_owner != panel_owner:
        raise DomainError("Назначения в переписке и реестре расходятся. Сначала подтвердите владельца у администратора.")
    owner = domain_owner or panel_owner
    if not owner:
        raise DomainError("Сначала закрепите диалог за менеджером через действие «Перехватить».")
    configured = next((m for m in ar.settings.manager_list() if m.login.strip().lower() == owner), None)
    if configured is None:
        raise DomainError("Ведущий менеджер больше не настроен. Сначала переназначьте диалог.")
    owner_actor = live_authz.actor_for({"login": owner, "admin": configured.admin})
    if not can_open_case(owner_actor, direction=direction):
        raise DomainError("У ведущего менеджера нет доступа к направлению услуги. Сначала проверьте назначение.")
    return owner


async def _find_contact(session, identity):
    kind, value = identity
    # Только чтение: ContactService.find_or_create на GET создавал бы клиентов.
    ident = await session.scalar(select(ContactIdentity).where(
        ContactIdentity.identity_type == kind,
        ContactIdentity.normalized_value == value,
        ContactIdentity.provider_scope == ""))
    if ident is None:
        return None
    from app.domain.models import Contact
    return await session.get(Contact, ident.contact_id)


async def _products(session, direction):
    return list(await session.scalars(select(Product).join(
        WorkflowVersion, Product.current_version_id == WorkflowVersion.id).where(
        Product.direction == direction, Product.active.is_(True),
        WorkflowVersion.product_id == Product.id,
        WorkflowVersion.published_at.is_not(None)).order_by(Product.name)))


def _form_values(request, conv, manager):
    key = secrets.token_hex(24)
    return {"product_id": "", "reference": "", "amount": "", "currency": "",
            "amount_unknown_reason": "", "confirmed": "",
            "signed_at": datetime.now(BISHKEK).strftime("%Y-%m-%dT%H:%M"),
            "idempotency_key": key,
            "key_signature": _signature(request, conv.user_id, manager["login"], key)}


async def _render(request, conv, manager, direction, values, *, error="", status=200):
    products, owner = [], ""
    try:
        identity = _identity(conv)
        async with ar._domain_sessionmaker()() as session:
            contact = await _find_contact(session, identity)
            owner = await _owner(session, conv, live_authz.actor_for(manager), direction, contact)
            products = await _products(session, direction)
    except HTTPException:
        raise
    except DomainError as exc:
        error, status = error or str(exc), max(status, 422)
    except Exception:
        log.warning("contract form: registry unavailable")
        error, status = error or "Реестр услуг временно недоступен. Попробуйте ещё раз.", 503
    response = ar.templates.TemplateResponse(request, "contract.html", {
        "manager": manager, "c": conv, "products": products, "owner": owner,
        "values": values, "error": error, "csrf_token": _csrf(request),
        "write_on": _write_on(request),
        "form_url": f"/admin/conversation/{quote(conv.user_id, safe='')}/contract",
    }, status_code=status, headers={"Cache-Control": "no-store"})
    response.headers["X-Action-Outcome"] = "failed" if status == 503 else ("invalid" if error else "form")
    return response


@ar.router.get("/conversation/{user_id}/contract", response_class=HTMLResponse)
async def contract_form(user_id: str, request: Request, manager: dict = Depends(ar.require_admin)):
    _require_workday(request)
    conv, actor, direction = await _conversation(user_id, manager)
    return await _render(request, conv, manager, direction, _form_values(request, conv, manager))


def _validate_submission(request, user_id, manager, form):
    token = str(form.get("csrf_token", ""))
    expected = request.session.get("contract_csrf", "")
    if not expected or not secrets.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(403, "Форма устарела. Откройте её заново.")
    key = str(form.get("idempotency_key", ""))
    signature = str(form.get("key_signature", ""))
    if not re.fullmatch(r"[0-9a-f]{48}", key) or not secrets.compare_digest(
            signature.encode(), _signature(request, user_id, manager["login"], key).encode()):
        raise HTTPException(403, "Ключ формы недействителен. Откройте форму заново.")


def _error_message(exc):
    message = str(exc)
    if "idempotency" in message or "contract conflict" in message:
        return "Эта форма уже сохранена с другими данными. Откройте услугу или начните новый договор.", 409
    if "amount" in message or "currency" in message:
        return "Укажите положительную сумму с точностью до двух знаков и валюту из трёх латинских букв, либо оставьте сумму пустой и укажите причину уточнения.", 422
    if "reference" in message:
        return "Укажите номер договора длиной от 1 до 128 символов.", 422
    if "product" in message or "workflow" in message:
        return "Продукт недоступен или для него не опубликован процесс. Обновите форму.", 422
    if any("а" <= c.lower() <= "я" for c in message):
        return message, 422
    return "Договор не сохранён. Проверьте поля формы и повторите отправку.", 422


@ar.router.post("/conversation/{user_id}/contract", response_class=HTMLResponse)
async def contract_submit(user_id: str, request: Request, manager: dict = Depends(ar.require_admin)):
    _require_workday(request)
    conv, actor, direction = await _conversation(user_id, manager)
    form = await request.form()
    _validate_submission(request, user_id, manager, form)
    values = {field: str(form.get(field, "")) for field in FIELDS}
    if not _write_on(request):
        return await _render(request, conv, manager, direction, values,
                             error="Запись услуг выключена. Договор не сохранён.", status=409)
    try:
        identity = _identity(conv)
        async with ar._domain_sessionmaker()() as session:
            async with session.begin():
                # SQLite legacy transaction mode не начинает транзакцию на SELECT;
                # первый SAVEPOINT тогда переживёт rollback. PostgreSQL BEGIN делает сам.
                if session.bind.dialect.name == "sqlite":
                    await session.execute(text("BEGIN"))
                contact = await _find_contact(session, identity)
                owner = await _owner(session, conv, actor, direction, contact, lock=True)
                try:
                    product_id = int(values["product_id"])
                except ValueError as exc:
                    raise DomainError("Выберите продукт.") from exc
                product = await session.get(Product, product_id)
                if product is None or product.direction != direction:
                    raise HTTPException(404)
                if values["confirmed"] != "yes":
                    raise DomainError("Подтвердите, что договор уже подписан клиентом.")
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", values["signed_at"]):
                    raise DomainError("Укажите дату и время подписания по Бишкеку.")
                try:
                    signed_at = datetime.fromisoformat(values["signed_at"]).replace(
                        tzinfo=BISHKEK).astimezone(timezone.utc)
                except ValueError as exc:
                    raise DomainError("Проверьте дату и время подписания.") from exc
                if contact is None:
                    kind, value = identity
                    # Номер уже нормализован; '+' сохраняет международную семантику.
                    contact = await ContactService.find_or_create_by_identity(
                        session, kind, "+" + value if kind == "phone" else value)
                    owner = await _owner(session, conv, actor, direction, contact, lock=True)
                case = await sign_contract(
                    session, contact_id=contact.id, product_id=product.id,
                    owner_login=owner, by=actor, reference=values["reference"],
                    signed_at=signed_at, amount=values["amount"].strip() or None,
                    currency=values["currency"], amount_unknown_reason=values["amount_unknown_reason"],
                    idempotency_key=values["idempotency_key"])
                case_id = case.id
        # PRG работает без JS; потеря ответа безопасна благодаря тому же ключу.
        return RedirectResponse(f"/admin/case/{case_id}", status_code=303,
                                headers={"X-Action-Outcome": "contract_signed", "Cache-Control": "no-store"})
    except (HTTPException, PermissionDenied) as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(404) from exc
    except DomainError as exc:
        error, status = _error_message(exc)
    except Exception:
        log.warning("contract submission: registry unavailable")
        error, status = "Договор не подтверждён системой. Повторите эту же форму: повтор не создаст вторую услугу.", 503
    return await _render(request, conv, manager, direction, values, error=error, status=status)
