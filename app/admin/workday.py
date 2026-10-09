"""E2-06 — маршруты «Рабочего дня» и карточки услуги.

Отдельный модуль, а не +500 строк в `router.py` (там уже 2600). Хендлеры
регистрируются на СУЩЕСТВУЮЩЕМ роутере — так зависимость `_load_new_look` и
context_processor `_chrome` достаются бесплатно.

Два флага, и они про разное:
* `admin_workday_enabled` — показ. OFF → маршрутов нет вообще (404), ссылки в
  меню нет, панель прежняя.
* `service_cases_enabled` — ЗАПИСЬ. OFF → экран виден, кнопки заблокированы,
  попытка записи честно отвечает «выключено». Это даёт пилот в режиме
  «смотреть, не писать»: включили показ на реальных данных, посмотрели, и только
  потом открыли операции.

**Порядок `except` обязателен именно такой:**

    except PermissionDenied → 404 (нет прав, и существование услуги не раскрываем)
    except DomainError      → 200 + `invalid` (данные не те, введённое возвращаем)
    except Exception        → 200 + `failed` (реестр моргнул, панель жива)

`PermissionDenied` — подкласс `DomainError`, а в остальном роутере `except
Exception` стоит первым («domain DB may be absent»). Поставь его первым здесь —
и дыра в правах отрисуется как «база недоступна», то есть будет выглядеть
нормально работающим экраном.

Обращение к помощникам роутера — через модуль (`ar._domain_sessionmaker()`), а не
`from app.admin.router import ...`: иначе `monkeypatch.setattr(admin_router,
"_domain_sessionmaker", ...)` в тестах перестанет действовать и они пойдут в
настоящую базу.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone

from fastapi import Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select

import app.admin.router as ar
from app.core import live_authz
from app.domain.models import (
    ACTIVE_TASK_STATUSES, BookingAttempt, CalendarTask, DomainError, Product,
    ServiceCase, ServiceEvent, TicketSegment,
)
from app.domain.service_authz import (
    PermissionDenied, can_advance_case, can_correct_money, can_view_case,
)
from app.domain.service_cases import advance
from app.domain.service_day import RULES, digest_for, workday
from app.domain.service_money import (
    correct_contract_amount, correct_entry, record_payment, record_refund_due,
    record_refund_paid, void_entry,
)
from app.domain.service_tickets import itinerary
from app.domain.service_tours import attempts_of
from app.domain.task_rules import (
    case_tasks, claim_task, finish_task, release_claim, stale_claims,
)

log = logging.getLogger("admin.workday")

# Русские подписи обязательных фактов перехода. Берём имена из `requires` этапа,
# а подпись — отсюда: иначе скринридер прочитает «booking_reference».
FACT_LABELS = {
    "booking_reference": "Номер брони у оператора",
    "confirmed_at": "Дата подтверждения",
    "operator": "Оператор",
    "sent_at": "Дата отправки заявки",
}
TABS = ("path", "money", "tasks", "route")
WORK_TABS = ("all", "now", "today", "soon", "waiting", "stuck")
# Порог «сейчас»: один и тот же для счётчика и для фильтра.
NOW_WEIGHT = 80


def _require_workday(request: Request) -> None:
    """Гейт показа. OFF → маршрута нет: 404, а не редирект и не пустая страница."""
    from app.config import settings
    if not bool(getattr(request.state, "workday_on", settings.admin_workday_enabled)):
        raise HTTPException(status_code=404)


def _write_on(request: Request) -> bool:
    from app.config import settings
    return bool(getattr(request.state, "cases_write_on", settings.service_cases_enabled))


def _as_utc(value: datetime | None) -> datetime | None:
    """Момент в UTC. SQLite возвращает время без зоны — приводим явно."""
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _outcome(response: HTMLResponse, value: str) -> HTMLResponse:
    """Пометить исход действия.

    При HTTP 200 отказ внешне не отличается от успеха — различает только этот
    заголовок. Клиентский обработчик по нему решает, уводить экран или показать
    причину.
    """
    response.headers["X-Action-Outcome"] = value
    return response


async def _case_or_404(session, case_id: int, actor) -> tuple[ServiceCase, Product]:
    """Услуга, которую актору разрешено видеть. Иначе 404.

    Именно 404, а не 403: та же политика, что у `_require_visible_conversation`
    в роутере — ответ не раскрывает существование чужой услуги.
    """
    case = await session.get(ServiceCase, case_id)
    if case is None:
        raise HTTPException(status_code=404)
    product = await session.get(Product, case.product_id)
    if not can_view_case(actor, direction=product.direction if product else None,
                         owner_login=case.owner_login):
        raise HTTPException(status_code=404)
    return case, product


# --- Рабочий день ------------------------------------------------------------

async def _work_context(request: Request, manager: dict, *, tab: str,
                        mine: bool) -> dict:
    """Собрать данные экрана. Падение реестра не роняет страницу (AC-31)."""
    actor = live_authz.actor_for(manager)
    digests: list = []
    claims: list = []
    failed = True
    try:
        async with ar._domain_sessionmaker()() as session:
            digests, failed = await workday(session, by=actor, now=_now(),
                                            mine_only=mine)
            claims = await _claims_view(session, actor)
    except Exception:  # noqa: BLE001 — реестр недоступен: экран обязан отрисоваться
        log.warning("workday: domain registry unavailable", exc_info=False)
        digests, failed, claims = [], True, []

    counts = {
        "now": sum(1 for d in digests
                   if d.top_reason and d.top_reason.weight >= NOW_WEIGHT),
        "today": sum(1 for d in digests
                     if d.top_reason and d.top_reason.code == "due_today"),
        "soon": sum(1 for d in digests
                    if d.top_reason and d.top_reason.code == "soon"),
        "waiting": sum(1 for d in digests
                       if d.top_reason and d.top_reason.code == "waiting"),
        "stuck": sum(1 for d in digests if d.stuck),
        "total": len(digests),
    }
    shown = _filter_tab(digests, tab)
    return {"digests": shown, "failed": failed, "claims": claims, "counts": counts,
            "tab": tab, "mine": mine, "rules": RULES,
            "write_on": _write_on(request), "manager": manager}


def _filter_tab(digests: list, tab: str) -> list:
    """Фильтр над одним и тем же отсортированным списком, а не вторая сортировка.

    Счётчик обязан раскрываться в тот же список: иначе число и список расходятся,
    и доверие к обоим пропадает.
    """
    if tab == "today":
        return [d for d in digests if d.top_reason and d.top_reason.code == "due_today"]
    if tab == "soon":
        return [d for d in digests if d.top_reason and d.top_reason.code == "soon"]
    if tab == "waiting":
        return [d for d in digests if d.top_reason and d.top_reason.code == "waiting"]
    if tab == "stuck":
        return [d for d in digests if d.stuck]
    if tab == "now":
        # Тот же порог, что у счётчика: иначе «сейчас 1» раскрывалось в две
        # строки, и ни числу, ни списку верить было нельзя.
        return [d for d in digests if d.top_reason and d.top_reason.weight >= NOW_WEIGHT]
    return digests


async def _claims_view(session, actor) -> list[dict]:
    """Подвисшие захваты, которые актору можно видеть."""
    today = ar._bishkek_today()
    out: list[dict] = []
    for task in await stale_claims(session, now=_now()):
        if not actor.is_full_admin and str(task.manager_id or "") != actor.manager_id:
            continue
        title, case_id = "", None
        if task.service_case_id:
            case = await session.get(ServiceCase, task.service_case_id)
            if case is not None:
                product = await session.get(Product, case.product_id)
                if not can_view_case(actor,
                                     direction=product.direction if product else None,
                                     owner_login=case.owner_login):
                    continue
                case_id = case.id
                title = f"{product.name if product else ''} · {case.contract_reference or ''}".strip(" ·")
        out.append({"task": task, "ui": ar._task_ui(task, today),
                    "case_title": title, "case_id": case_id})
    return out


@ar.router.get("/work", response_class=HTMLResponse)
async def work(request: Request, tab: str = "now", mine: int = 1,
               manager: dict = Depends(ar.require_admin)):
    """Рабочий день: услуги по срочности, причина у каждой, подвисшие захваты сверху."""
    _require_workday(request)
    if tab not in WORK_TABS:
        tab = "now"
    context = await _work_context(request, manager, tab=tab,
                                  mine=bool(int(mine)) if str(mine).isdigit() else True)
    return ar.templates.TemplateResponse(request, "work.html", context,
                                         headers={"Cache-Control": "no-store"})


@ar.router.get("/work/list", response_class=HTMLResponse)
async def work_list(request: Request, tab: str = "now", mine: int = 1,
                    manager: dict = Depends(ar.require_admin)):
    """Только список — цель htmx-свопа. Тот же шаблон, что внутри страницы."""
    _require_workday(request)
    if tab not in WORK_TABS:
        tab = "now"
    context = await _work_context(request, manager, tab=tab,
                                  mine=bool(int(mine)) if str(mine).isdigit() else True)
    return ar.templates.TemplateResponse(request, "_work_list.html", context)


@ar.router.get("/work/claims", response_class=HTMLResponse)
async def work_claims(request: Request, manager: dict = Depends(ar.require_admin)):
    _require_workday(request)
    context = await _work_context(request, manager, tab="now", mine=True)
    return ar.templates.TemplateResponse(request, "_work_claims.html", context)


# --- Подвисшие захваты -------------------------------------------------------

async def _claim_action(request: Request, task_id: int, manager: dict, *,
                        reason: str, settled: bool) -> HTMLResponse:
    """Разобрать подвисший захват. Оба исхода — решение человека, не таймаут."""
    if not _write_on(request):
        return _outcome(await _claims_response(request, manager), "off")
    actor = live_authz.actor_for(manager)
    try:
        async with ar._domain_sessionmaker()() as session:
            task = await session.get(CalendarTask, task_id)
            if task is None:
                raise HTTPException(status_code=404)
            if not ar._manager_can_touch_task(manager, task):
                raise PermissionDenied("not allowed: touch task")
            if task.claimed_at is None:
                raise DomainError("task is not claimed; nothing to settle")
            mine = str(task.claimed_by or "").strip() == actor.manager_id
            if not mine:
                # Чужой захват разбирают только когда он ПОДВИСШИЙ. Снять живой
                # значит отдать задачу второму исполнителю, пока первый ещё
                # работает, — и клиент получит дубль.
                fresh = [t.id for t in await stale_claims(session, now=_now())]
                if task_id not in fresh:
                    raise DomainError(
                        "этот захват ещё свежий — процесс может работать прямо "
                        "сейчас; подождите или разберите свой")
            await release_claim(session, task_id, worker=actor.manager_id,
                                reason=reason, force=not mine)
            if settled:
                # Действие состоялось: короче нельзя — `finish_task` требует, чтобы
                # завершал тот, кто захватил, а завис чужой захват.
                await claim_task(session, task_id, worker=actor.manager_id, now=_now())
                await finish_task(session, task_id, worker=actor.manager_id,
                                  outcome=f"сверено вручную: {reason}", now=_now())
            await session.commit()
    except PermissionDenied:
        return _outcome(await _claims_response(request, manager), "denied")
    except DomainError as exc:
        log.info("claim action refused: %s", type(exc).__name__)
        return _outcome(await _claims_response(request, manager), "invalid")
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        log.warning("claim action failed", exc_info=False)
        return _outcome(await _claims_response(request, manager), "failed")
    # `add_audit` асинхронный: без await запись в журнал не происходила вовсе,
    # и ни одно действие над деньгами и услугами не оставляло следа.
    await ar.get_conversation_store().add_audit(
        str(manager.get("login") or ""), "claim_settled" if settled else "claim_released",
        "", f"task={task_id}")
    return _outcome(await _claims_response(request, manager),
                    "finished" if settled else "released")


async def _claims_response(request: Request, manager: dict) -> HTMLResponse:
    context = await _work_context(request, manager, tab="now", mine=True)
    return ar.templates.TemplateResponse(request, "_work_claims.html", context)


@ar.router.post("/work/claim/{task_id}/release", response_class=HTMLResponse)
async def claim_release(task_id: int, request: Request, reason: str = Form(""),
                        manager: dict = Depends(ar.require_admin)):
    _require_workday(request)
    return await _claim_action(request, task_id, manager, reason=reason, settled=False)


@ar.router.post("/work/claim/{task_id}/confirm", response_class=HTMLResponse)
async def claim_confirm(task_id: int, request: Request, reason: str = Form(""),
                        manager: dict = Depends(ar.require_admin)):
    _require_workday(request)
    return await _claim_action(request, task_id, manager, reason=reason, settled=True)


# --- Карточка услуги ---------------------------------------------------------

async def _case_context(request: Request, case_id: int, manager: dict, *,
                        tab: str, errors: dict | None = None,
                        echo: dict | None = None,
                        idem_key: str | None = None,
                        outcome: str = "") -> dict:
    """Данные карточки. Права считает сервер, шаблон получает два булева."""
    actor = live_authz.actor_for(manager)
    async with ar._domain_sessionmaker()() as session:
        case, product = await _case_or_404(session, case_id, actor)
        direction = product.direction if product else None
        # Те же входные данные, что у списка: иначе чип «Задача взята и не
        # завершена» ведёт в карточку, где написано «Задача на сегодня», и
        # обещание «порядок объясним» рушится на первом же переходе.
        moment = _now()
        stuck = frozenset(t.id for t in await stale_claims(session, now=moment))
        last_event = await session.scalar(
            select(func.max(ServiceEvent.occurred_at))
            .where(ServiceEvent.case_id == case.id))
        # SQLite отдаёт время БЕЗ зоны, и вычитание из tz-aware момента падает
        # TypeError. Приводим здесь же: та же ловушка уже встречалась в деньгах
        # и в задачах — наивное значение из базы записано в UTC.
        digest = await digest_for(session, case, by=actor, now=moment,
                                  stuck_task_ids=stuck,
                                  last_event_at=_as_utc(last_event))
        today = ar._bishkek_today()
        tasks = [ar._task_ui(t, today)
                 for t in await case_tasks(session, case.id, by=actor)]
        events = list(await session.scalars(
            select(ServiceEvent).where(ServiceEvent.case_id == case.id)
            .order_by(ServiceEvent.id.desc()).limit(50)))
        segments = (await itinerary(session, case.id, by=actor, include_history=True)
                    if direction == "tickets" else [])
        attempts = (await attempts_of(session, case.id, by=actor)
                    if direction == "tours" else [])
        return {
            "case": case, "d": digest, "tasks": tasks, "events": events,
            "segments": segments, "attempts": attempts, "tab": tab,
            "may_pay": can_advance_case(actor, direction=direction,
                                        owner_login=case.owner_login),
            # Возврат и исправление — полномочие руководителя, и правило знает про
            # направление: админ одного бизнеса не правит деньги другого.
            "may_correct": can_correct_money(actor, direction=direction),
            "write_on": _write_on(request), "facts_labels": FACT_LABELS,
            "idem_key": idem_key or secrets.token_hex(8),
            "errors": errors or {}, "echo": echo or {}, "manager": manager,
            # Исход нужен шаблону, чтобы назвать причину словами: «выключено»,
            # «нет прав» и «реестр недоступен» — это разные вещи для менеджера.
            "outcome": outcome,
            "kg_entry_on": ar.settings.admin_kg_entry_enabled and actor.is_full_admin and direction == "visa",
        }


@ar.router.get("/case/{case_id}", response_class=HTMLResponse)
async def case_page(case_id: int, request: Request, tab: str = "path",
                    manager: dict = Depends(ar.require_admin)):
    _require_workday(request)
    if tab not in TABS:
        tab = "path"
    try:
        context = await _case_context(request, case_id, manager, tab=tab)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001 — реестр недоступен или услуга нечитаема:
        # страница обязана открыться и сказать, что случилось (AC-31). Прежде тут
        # был необработанный 500, и нечитаемая услуга из списка роняла переход.
        log.warning("case page: registry unavailable for case=%s", case_id,
                    exc_info=False)
        return ar.templates.TemplateResponse(
            request, "case_unavailable.html",
            {"case_id": case_id, "manager": manager},
            status_code=200, headers={"Cache-Control": "no-store"})
    return ar.templates.TemplateResponse(request, "case.html", context,
                                         headers={"Cache-Control": "no-store"})


@ar.router.get("/case/{case_id}/panel/{tab}", response_class=HTMLResponse)
async def case_panel(case_id: int, tab: str, request: Request,
                     manager: dict = Depends(ar.require_admin)):
    """Партиал — самостоятельная точка входа, поэтому доступ проверяется и здесь."""
    _require_workday(request)
    if tab not in TABS:
        raise HTTPException(status_code=404)
    context = await _case_context(request, case_id, manager, tab=tab)
    return ar.templates.TemplateResponse(request, "_case_panel.html", context)


async def _panel_response(request: Request, case_id: int, manager: dict, *,
                          tab: str, outcome: str, errors: dict | None = None,
                          echo: dict | None = None,
                          idem_key: str | None = None) -> HTMLResponse:
    """Свежерендеренный блок ИЗ БАЗЫ, а не отражение присланной формы.

    Так «действие меняет следующий шаг» выполняется конструктивно: шаг выводится
    заново из этапа, задач, баланса и брони.
    """
    context = await _case_context(request, case_id, manager, tab=tab, errors=errors,
                                  echo=echo, idem_key=idem_key, outcome=outcome)
    response = ar.templates.TemplateResponse(request, "_case_panel.html", context)
    return _outcome(response, outcome)


async def _write(request: Request, case_id: int, manager: dict, *, tab: str,
                 operation, success: str, echo: dict,
                 idem_key: str | None = None) -> HTMLResponse:
    """Общая обёртка пишущих действий: права, данные, сбой — три разных исхода."""
    if not _write_on(request):
        return await _panel_response(request, case_id, manager, tab=tab,
                                     outcome="off", echo=echo, idem_key=idem_key)
    actor = live_authz.actor_for(manager)
    try:
        async with ar._domain_sessionmaker()() as session:
            case, _product = await _case_or_404(session, case_id, actor)
            await operation(session, case, actor)
            await session.commit()
    except PermissionDenied:
        # Услугу менеджер уже видит (иначе `_case_or_404` отказал бы выше), значит
        # скрывать её существование бессмысленно, а объяснить отказ нужно: 404 здесь
        # превращался в «Сервер ответил 404: Not Found» вместо человеческого текста.
        return await _panel_response(request, case_id, manager, tab=tab,
                                     outcome="denied", echo=echo,
                                     idem_key=idem_key)
    except DomainError as exc:
        # Данные не те: возвращаем форму с введённым и говорим, что именно не так.
        return await _panel_response(request, case_id, manager, tab=tab,
                                     outcome="invalid",
                                     errors={"message": str(exc)}, echo=echo,
                                     idem_key=idem_key)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        log.warning("case write failed", exc_info=False)
        return await _panel_response(request, case_id, manager, tab=tab,
                                     outcome="failed", echo=echo, idem_key=idem_key)
    await ar.get_conversation_store().add_audit(
        str(manager.get("login") or ""), success, "", f"case={case_id}")
    return await _panel_response(request, case_id, manager, tab=tab, outcome=success)


@ar.router.post("/case/{case_id}/advance", response_class=HTMLResponse)
async def case_advance(case_id: int, request: Request, to_stage: str = Form(""),
                       expected_revision: str = Form(""),
                       manager: dict = Depends(ar.require_admin)):
    _require_workday(request)
    form = await request.form()
    # Служебные поля формы и ОСНОВАНИЕ не являются фактами этапа: основание идёт
    # отдельным полем в историю, иначе лента показывала «основание: не указано»,
    # а в факты попадал мусор вида `tab`. Починить задним числом это нельзя —
    # история переходов пишется один раз.
    service_fields = {"to_stage", "expected_revision", "tab", "reason",
                      "idempotency_key"}
    facts = {key: value for key, value in form.items()
             if key not in service_fields and str(value).strip()}
    reason = str(form.get("reason") or "").strip()
    revision = int(expected_revision) if str(expected_revision).strip().isdigit() else None

    async def operation(session, case, actor):
        await advance(session, case.id, to_stage=to_stage, by=actor, facts=facts,
                      reason=reason, expected_revision=revision)

    return await _write(request, case_id, manager, tab="path", operation=operation,
                        success="advanced",
                        echo=dict(facts, to_stage=to_stage, reason=reason))


def _money_route(path: str, success: str, financial: bool, call):
    """Объявить денежный маршрут. Финансовые требуют права руководителя."""

    @ar.router.post(f"/case/{{case_id}}/money/{path}", response_class=HTMLResponse,
                    name=f"money_{success}")
    async def handler(case_id: int, request: Request,
                      amount: str = Form(""), currency: str = Form(""),
                      fx_rate: str = Form(""), reason: str = Form(""),
                      idempotency_key: str = Form(""), target_id: str = Form(""),
                      settles_id: str = Form(""), voids_id: str = Form(""),
                      corrects_id: str = Form(""),
                      manager: dict = Depends(ar.require_admin)):
        _require_workday(request)
        echo = {"amount": amount, "currency": currency, "fx_rate": fx_rate,
                "reason": reason}
        # Форма исторически называет цель по смыслу операции. Принимаем любое из
        # имён: расхождение формы и хендлера делало операцию неработающей, а
        # отказ выглядел сбоем базы.
        target = target_id or voids_id or corrects_id

        async def operation(session, case, actor):
            await call(session, case, actor, amount=amount, currency=currency,
                       fx_rate=fx_rate, reason=reason,
                       idempotency_key=idempotency_key, target_id=target,
                       settles_id=settles_id)

        return await _write(request, case_id, manager, tab="money",
                            operation=operation, success=success, echo=echo,
                            # Ключ при пере-рендере ТОТ ЖЕ: иначе повтор после
                            # неоднозначного сбоя создаст вторую оплату.
                            idem_key=idempotency_key or None)

    return handler


def _decimal(value):
    """Строку в деньги превращает домен. Здесь только пустое отбрасываем."""
    text = str(value or "").strip()
    return text or None


def _entry_id(value, field: str) -> int:
    """Номер записи журнала. Мусор — понятный отказ, а не падение.

    `int("")` бросал голый ValueError, его ловил `except Exception`, и менеджер
    видел «не сохранилось» вместо «номер записи — число».
    """
    text = str(value or "").strip()
    if not text.isdigit():
        raise DomainError(f"{field} must be a record number")
    return int(text)


async def _do_payment(session, case, actor, *, amount, currency, fx_rate,
                      reason, idempotency_key, target_id, settles_id):
    await record_payment(session, case.id, amount=_decimal(amount),
                         currency=currency, by=actor,
                         idempotency_key=idempotency_key,
                         fx_rate=_decimal(fx_rate), reason=reason)


async def _do_refund_due(session, case, actor, *, amount, currency, fx_rate,
                         reason, idempotency_key, target_id, settles_id):
    await record_refund_due(session, case.id, amount=_decimal(amount),
                            currency=currency, by=actor,
                            idempotency_key=idempotency_key, reason=reason)


async def _do_refund_paid(session, case, actor, *, amount, currency, fx_rate,
                          reason, idempotency_key, target_id, settles_id):
    await record_refund_paid(session, case.id, amount=_decimal(amount),
                             currency=currency, by=actor,
                             idempotency_key=idempotency_key,
                             fx_rate=_decimal(fx_rate), reason=reason,
                             settles_id=(_entry_id(settles_id, "settles_id")
                                         if str(settles_id or "").strip() else None))


async def _do_void(session, case, actor, *, amount, currency, fx_rate, reason,
                   idempotency_key, target_id, settles_id):
    await void_entry(session, case.id,
                     voids_id=_entry_id(target_id, "voids_id"), by=actor,
                     reason=reason, idempotency_key=idempotency_key)


async def _do_correct_entry(session, case, actor, *, amount, currency, fx_rate,
                            reason, idempotency_key, target_id, settles_id):
    await correct_entry(session, case.id,
                        corrects_id=_entry_id(target_id, "corrects_id"),
                        amount=_decimal(amount), currency=currency, by=actor,
                        idempotency_key=idempotency_key, reason=reason,
                        fx_rate=_decimal(fx_rate))


async def _do_contract_amount(session, case, actor, *, amount, currency, fx_rate,
                              reason, idempotency_key, target_id, settles_id):
    await correct_contract_amount(session, case.id, amount=_decimal(amount),
                                  currency=currency, by=actor, reason=reason)


_money_route("payment", "recorded", False, _do_payment)
_money_route("refund-due", "refund_due", True, _do_refund_due)
_money_route("refund-paid", "refunded", True, _do_refund_paid)
_money_route("void", "voided", True, _do_void)
_money_route("correct-entry", "corrected", True, _do_correct_entry)
_money_route("contract-amount", "amount_corrected", True, _do_contract_amount)


@ar.router.post("/case/{case_id}/task/{task_id}/finish", response_class=HTMLResponse)
async def case_task_finish(case_id: int, task_id: int, request: Request,
                           outcome: str = Form(""),
                           manager: dict = Depends(ar.require_admin)):
    """Закрыть задачу услуги: сначала захват, потом завершение — как в протоколе."""
    _require_workday(request)

    async def operation(session, case, actor):
        task = await session.get(CalendarTask, task_id)
        if task is None or task.service_case_id != case.id:
            raise DomainError("task does not belong to this service case")
        if not ar._manager_can_touch_task(manager, task):
            raise PermissionDenied("not allowed: touch task")
        if task.claimed_at is None:
            await claim_task(session, task_id, worker=actor.manager_id, now=_now())
        await finish_task(session, task_id, worker=actor.manager_id,
                          outcome=outcome or "выполнено из карточки", now=_now())

    return await _write(request, case_id, manager, tab="tasks", operation=operation,
                        success="finished", echo={"outcome": outcome})
