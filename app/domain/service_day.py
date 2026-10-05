"""E2-06 — рабочий день: приоритет с причиной, следующий шаг, готовность.

Только ЧТЕНИЕ. Ни одной записи, ни одного `commit`: порядок услуг — бизнес-правило,
и оно обязано проверяться без HTTP и без тестового клиента.

**Логика приоритета — «что потеряем, если не тронем сегодня».** Сверху состояние,
которого система не понимает: задача взята в работу и не завершена — возможно,
клиент уже получил сообщение, а возможно нет. Дальше внешний срок, который нельзя
сдвинуть нашим решением. Дальше наша просрочка. Дальше деньги. Дальше молчащий
оператор. Потом сегодняшнее, потом простой.

У каждой позиции есть ПРИЧИНА человеческими словами и вкладка-основание. Это
требование приёмки: «на пяти услугах порядок объясним». Объяснение рисуется из
`RULES`, а не пересказывается в шаблоне — иначе таблица разойдётся с кодом.

Все функции принимают `now` — управляемые часы, как в `task_rules`: поведение на
сроках проверяется подстановкой момента, а не ожиданием трёх дней.

Чего здесь нет: правил, когда и что писать клиенту (DEC-12 не принят), и догадок
о том, кого мы ждём. `ServiceCase.waiting_party` в схеме есть, но его никто не
пишет — поэтому выводим только доказуемое: ждём оператора, если бронь отправлена
и не подтверждена; ждём клиента, если есть открытая задача касания. «Ждём
ведомство» не показываем вовсе: такого факта в базе нет, а эвристика в отчёте —
это ложь.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    ACTIVE_TASK_STATUSES, BookingAttempt, CalendarTask, Product, ServiceCase,
    ServiceEvent,
)
from app.domain.service_authz import Actor
from app.domain.service_cases import cases_for_owner, stage_plan
from app.domain.service_money import Balance, balance_of
from app.domain.service_tickets import itinerary
from app.domain.service_tours import CONFIRMED, DECLINED, REQUESTED, attempts_of
from app.domain.task_rules import case_tasks, overdue_on, stale_claims
from app.domain.models import WorkflowVersion

log = logging.getLogger("domain.service_day")

BISHKEK = ZoneInfo("Asia/Bishkek")

# Бронь без ответа оператора дольше суток — уже не «ждём», а «надо дёргать».
BOOKING_SILENT_HOURS = 24
# Трое суток без единого события по услуге: она стоит, и это видно только так.
STUCK_NO_EVENT_DAYS = 3
# «Скоро» — три дня: столько нужно, чтобы успеть что-то сделать.
SOON_DAYS = 3
# Сроки, которые НЕЛЬЗЯ сдвинуть переносом задачи: их ставит не компания.
HARD_DEADLINE_KINDS = ("checkin", "departure")

# Правила приоритета. Порядок и веса — часть договорённости с приёмщиком, поэтому
# таблица одна и живёт здесь; интерфейс рисует её из этого же списка.
RULES: tuple[dict, ...] = (
    {"code": "claim_stuck", "weight": 100, "anchor": "tasks",
     "label": "Задача взята и не завершена",
     "why": "Неизвестно, что произошло: сообщение могло уйти клиенту, а могло не уйти. "
            "Повторять слепо нельзя — уйдёт дубль."},
    {"code": "hard_deadline", "weight": 95, "anchor": "route",
     "label": "Пропущен внешний срок",
     "why": "Этот срок ставит перевозчик, а не мы: перенос задачи его не сдвигает."},
    {"code": "task_overdue", "weight": 80, "anchor": "tasks",
     "label": "Просроченная задача",
     "why": "Обещали сделать и не сделали — клиент этого ждёт."},
    {"code": "money_attention", "weight": 70, "anchor": "money",
     "label": "Деньги требуют человека",
     "why": "Система не может посчитать сама: нет курса, висит обязательство или переплата."},
    {"code": "booking_silent", "weight": 60, "anchor": "path",
     "label": "Бронь без подтверждения",
     "why": "Оператор молчит дольше суток: клиент считает, что всё идёт, а брони нет."},
    {"code": "due_today", "weight": 50, "anchor": "tasks",
     "label": "Задача на сегодня",
     "why": "Срок наступает в этот день."},
    {"code": "outstanding", "weight": 40, "anchor": "money",
     "label": "Остаток к доплате",
     "why": "Договор подписан, деньги пришли не полностью."},
    {"code": "no_next_step", "weight": 30, "anchor": "path",
     "label": "Нет следующего шага",
     "why": "Ни задач, ни доступного перехода: услуга стоит и никто об этом не знает."},
    {"code": "silent_days", "weight": 25, "anchor": "path",
     "label": "Нет событий",
     "why": "По услуге давно ничего не происходило."},
    {"code": "waiting", "weight": 10, "anchor": "path",
     "label": "Ждём сторону",
     "why": "Ход не за нами, но срок всё равно наш."},
    {"code": "soon", "weight": 5, "anchor": "tasks",
     "label": "Скоро срок",
     "why": "Задача близко — лучше не оставлять на последний день."},
)
_RULE_BY_CODE = {rule["code"]: rule for rule in RULES}


@dataclass(frozen=True)
class Reason:
    """Почему услуга стоит на этом месте. `detail` — конкретика из базы."""

    code: str
    weight: int
    label: str
    detail: str
    anchor: str

    @property
    def why(self) -> str:
        return str(_RULE_BY_CODE.get(self.code, {}).get("why") or "")


@dataclass(frozen=True)
class NextStep:
    """Одно следующее действие. `blocked_by` — пояснение, а НЕ запрет."""

    kind: str                 # task | advance | choice | final | contract
    label: str
    to_stage: str | None = None
    requires: tuple[str, ...] = ()
    choices: tuple[tuple[str, str], ...] = ()     # (код этапа, имя)
    task_id: int | None = None
    blocked_by: str = ""


@dataclass(frozen=True)
class Check:
    """Пункт готовности. `unknown` НИКОГДА не считается выполненным."""

    code: str
    label: str
    state: str                # ok | missing | unknown
    detail: str = ""


@dataclass(frozen=True)
class CaseDigest:
    case_id: int
    title: str
    product_code: str
    direction: str
    owner_login: str
    stage_code: str
    stage_name: str
    stage_index: int
    stage_total: int
    reasons: tuple[Reason, ...] = ()
    next_step: NextStep | None = None
    checks: tuple[Check, ...] = ()
    balance: Balance | None = None
    due_at: datetime | None = None
    contact_id: int | None = None

    @property
    def top_reason(self) -> Reason | None:
        """Причина, определившая место в списке. Её и показываем в строке."""
        return self.reasons[0] if self.reasons else None

    @property
    def stuck(self) -> bool:
        """Услуга зависла: есть причина из «тупиковых»."""
        stuck_codes = {"claim_stuck", "no_next_step", "silent_days", "booking_silent"}
        return any(r.code in stuck_codes for r in self.reasons)

    @property
    def ready_done(self) -> int:
        return sum(1 for c in self.checks if c.state == "ok")

    @property
    def ready_total(self) -> int:
        return len(self.checks)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc))


def _days(delta: timedelta) -> int:
    return max(0, int(delta.total_seconds() // 86400))


def _since(delta: timedelta) -> str:
    """Сколько прошло, человеческими словами.

    «1600 мин назад» арифметически верно и нечитаемо: менеджер не переводит
    минуты в сутки в голове. Единица выбирается по величине.
    """
    total = max(0, int(delta.total_seconds()))
    if total < 3600:
        return f"{total // 60} мин"
    if total < 86400:
        hours = total // 3600
        if hours % 10 == 1 and hours % 100 != 11:
            return f"{hours} час"
        if hours % 10 in (2, 3, 4) and hours % 100 not in (12, 13, 14):
            return f"{hours} часа"
        return f"{hours} часов"
    return _plural_days(total // 86400)


def _plural_days(count: int) -> str:
    if count % 10 == 1 and count % 100 != 11:
        return f"{count} день"
    if count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        return f"{count} дня"
    return f"{count} дней"


def rank(digest: CaseDigest) -> tuple:
    """Ключ сортировки. Чистая функция — проверяется без базы.

    Сначала вес самой сильной причины, затем ближайший срок, затем id. Последнее
    нужно, чтобы порядок был воспроизводим: без него две равные услуги менялись
    бы местами между обновлениями страницы, и менеджер терял бы место.
    """
    top = -(digest.reasons[0].weight if digest.reasons else 0)
    due = digest.due_at or datetime.max.replace(tzinfo=timezone.utc)
    return (top, due, digest.case_id)


def _money_detail(balance: Balance) -> str:
    """Что именно подняло денежный флаг. Без расшифровки чип — шум."""
    parts: list[str] = []
    for currency, amount in sorted(balance.unconverted.items()):
        parts.append(f"платёж {amount} {currency} без курса не зачтён")
    if balance.refund_due > 0:
        parts.append(f"обязательство вернуть {balance.refund_due} "
                     f"{balance.currency or ''}".strip())
    for currency, amount in sorted(balance.foreign_refund_due.items()):
        parts.append(f"обязательство вернуть {amount} {currency}")
    for currency, amount in sorted(balance.foreign_refunded.items()):
        parts.append(f"возврат {amount} {currency} вне валюты договора")
    if balance.agreed is not None and (balance.paid - balance.refunded) > balance.agreed:
        parts.append(f"переплата {(balance.paid - balance.refunded) - balance.agreed} "
                     f"{balance.currency or ''}".strip())
    if balance.refunded > balance.paid:
        parts.append("возвращено больше, чем получено")
    if balance.broken_entries:
        parts.append(f"{len(balance.broken_entries)} непонятных записей в журнале")
    return "; ".join(parts) or "журнал требует проверки"


async def _last_event_at(session: AsyncSession, case_ids: list[int]) -> dict[int, datetime]:
    """Момент последнего события по каждой услуге — ОДНИМ запросом.

    По одной услуге за раз это 50 запросов на страницу; группировкой — один.
    """
    if not case_ids:
        return {}
    rows = await session.execute(
        select(ServiceEvent.case_id, func.max(ServiceEvent.occurred_at))
        .where(ServiceEvent.case_id.in_(case_ids))
        .group_by(ServiceEvent.case_id))
    return {int(case_id): _as_utc(moment) for case_id, moment in rows if moment}


def _next_step(case: ServiceCase, plan: dict, tasks: list[CalendarTask],
               balance: Balance | None, attempt: BookingAttempt | None,
               today) -> NextStep:
    """Одно следующее действие. Первое совпавшее правило — и только оно.

    Задача выигрывает у перехода: её уже сформулировали правила процесса или
    операции по брони и билетам. Придумывать поверх неё второй шаг значит
    спорить с процессом.
    """
    if case.signed_at is None:
        return NextStep(kind="contract", label="Зафиксировать договор")

    urgent = [t for t in tasks
              if t.status in ACTIVE_TASK_STATUSES
              and (overdue_on(t, today=today) or t.scheduled_date == today)]
    if urgent:
        task = urgent[0]
        return NextStep(kind="task", label=f"Выполнить: {task.comment or task.kind}",
                        task_id=task.id)

    blocked = ""
    if balance is not None and balance.outstanding is not None and balance.outstanding > 0:
        # Пояснение, а не запрет: разрешён переход или нет, решает `advance` по
        # обязательным фактам этапа, а не интерфейс по остатку денег (FLOW-04).
        blocked = (f"Остаток {balance.outstanding} {balance.currency or ''}".strip()
                   + " — доплата не внесена")

    allowed = list(plan.get("next") or [])
    if not allowed:
        return NextStep(kind="final", label="Последний этап процесса — движения дальше нет",
                        blocked_by=blocked)
    if len(allowed) == 1:
        code = allowed[0]
        return NextStep(kind="advance", label=plan["next_names"].get(code, code),
                        to_stage=code,
                        requires=tuple(plan["requires"].get(code, ())),
                        blocked_by=blocked)
    return NextStep(kind="choice", label="Выбрать следующий этап",
                    choices=tuple((code, plan["next_names"].get(code, code))
                                  for code in allowed),
                    blocked_by=blocked)


def _checks(case: ServiceCase, balance: Balance | None,
            attempt: BookingAttempt | None, segments: list,
            tasks: list[CalendarTask], direction: str) -> tuple[Check, ...]:
    """Готовность по доказуемым пунктам. `unknown` не считается готовым.

    Полученный, но непроверенный факт не делает услугу готовой — поэтому три
    состояния, а не два, и в «готово N из M» попадает только `ok`.
    """
    out: list[Check] = [
        Check("contract", "Договор зафиксирован",
              "ok" if (case.signed_at and case.contract_reference) else "missing",
              str(case.contract_reference or "")),
    ]
    if case.agreed_amount is not None:
        out.append(Check("amount", "Сумма договора", "ok",
                         f"{case.agreed_amount} {case.currency or ''}".strip()))
    else:
        out.append(Check("amount", "Сумма договора", "unknown",
                         str(case.amount_unknown_reason or "не установлена")))

    if balance is not None:
        if balance.agreed is None:
            out.append(Check("paid", "Оплата", "unknown", "остаток не рассчитан"))
        elif balance.outstanding is not None and balance.outstanding > 0:
            out.append(Check("paid", "Оплата", "missing",
                             f"не хватает {balance.outstanding} {balance.currency or ''}".strip()))
        else:
            out.append(Check("paid", "Оплата", "ok", "полностью"))
        if balance.unconverted:
            shown = "; ".join(f"{amount} {currency}"
                              for currency, amount in sorted(balance.unconverted.items()))
            out.append(Check("unconverted", "Непосчитанные платежи", "unknown",
                             f"{shown} без курса"))

    if direction == "tours":
        if attempt is None:
            out.append(Check("booking", "Бронь подтверждена", "missing", "заявки нет"))
        elif attempt.status == CONFIRMED:
            out.append(Check("booking", "Бронь подтверждена", "ok",
                             str(attempt.reference or "")))
        elif attempt.status == REQUESTED:
            out.append(Check("booking", "Бронь подтверждена", "unknown",
                             f"ждём {attempt.operator}"))
        else:
            out.append(Check("booking", "Бронь подтверждена", "missing",
                             str(attempt.decline_reason or attempt.status)))

    if direction == "tickets":
        out.append(Check("route", "Маршрут", "ok" if segments else "missing",
                         f"{len(segments)} сегм." if segments else "сегментов нет"))
        if segments:
            has_checkin = any(t.kind == "checkin" for t in tasks)
            unknown_window = any(s.checkin_opens_hours_before is None for s in segments)
            if has_checkin:
                out.append(Check("checkin", "Регистрация на рейс", "ok", ""))
            elif unknown_window:
                out.append(Check("checkin", "Регистрация на рейс", "unknown",
                                 "окно регистрации не известно — задача не ставится"))
            else:
                out.append(Check("checkin", "Регистрация на рейс", "missing", ""))
    return tuple(out)


async def digest_for(session: AsyncSession, case: ServiceCase, *, by: Actor,
                     now: datetime | None = None,
                     stuck_task_ids: frozenset[int] = frozenset(),
                     last_event_at: datetime | None = None) -> CaseDigest:
    """Собрать всё, что нужно показать по одной услуге, и вычислить причины."""
    moment = _as_utc(now) or _now()
    today = moment.astimezone(BISHKEK).date()
    product = await session.get(Product, case.product_id)
    direction = str(product.direction if product else "") or ""
    version = await session.get(WorkflowVersion, case.workflow_version_id)
    plan = (stage_plan(version, case.stage) if version is not None
            else {"index": -1, "total": 0, "name": case.stage, "next": [],
                  "requires": {}, "next_names": {}})

    tasks = await case_tasks(session, case.id, by=by)
    active = [t for t in tasks if t.status in ACTIVE_TASK_STATUSES]
    balance = await balance_of(session, case.id, by=by) if case.signed_at else None
    attempt = None
    segments: list = []
    if direction == "tours":
        for a in await attempts_of(session, case.id, by=by):
            if a.status in (REQUESTED, CONFIRMED):
                attempt = a
                break
    elif direction == "tickets":
        segments = await itinerary(session, case.id, by=by)

    reasons: list[Reason] = []

    def add(code: str, detail: str) -> None:
        rule = _RULE_BY_CODE[code]
        reasons.append(Reason(code=code, weight=int(rule["weight"]),
                              label=str(rule["label"]), detail=detail,
                              anchor=str(rule["anchor"])))

    stuck_here = [t for t in active if t.id in stuck_task_ids]
    if stuck_here:
        task = stuck_here[0]
        claimed = _as_utc(task.claimed_at)
        ago = _since(moment - claimed) if claimed else "неизвестно когда"
        add("claim_stuck", f"взята {task.claimed_by or 'кем-то'} {ago} назад, "
                           "результата нет")

    hard = [t for t in active
            if t.kind in HARD_DEADLINE_KINDS and overdue_on(t, today=today)]
    if hard:
        add("hard_deadline", f"{hard[0].comment or hard[0].kind}: срок прошёл")

    overdue = [t for t in active if overdue_on(t, today=today)]
    if overdue:
        late = max(_days(moment - _as_utc(t.scheduled_at)) if t.scheduled_at else 0
                   for t in overdue)
        add("task_overdue", f"{_plural_days(late)}: {overdue[0].comment or overdue[0].kind}")

    if balance is not None and balance.needs_attention:
        add("money_attention", _money_detail(balance))

    if attempt is not None and attempt.status == REQUESTED:
        asked = _as_utc(attempt.created_at)
        if asked and (moment - asked) >= timedelta(hours=BOOKING_SILENT_HOURS):
            add("booking_silent", f"{attempt.operator}: отправлена "
                                  f"{_plural_days(_days(moment - asked))} назад")

    today_tasks = [t for t in active if t.scheduled_date == today]
    if today_tasks:
        at = _as_utc(today_tasks[0].scheduled_at)
        when = at.astimezone(BISHKEK).strftime("%H:%M") if at else "в течение дня"
        add("due_today", f"{when}: {today_tasks[0].comment or today_tasks[0].kind}")

    if (balance is not None and balance.outstanding is not None
            and balance.outstanding > 0):
        add("outstanding", f"{balance.outstanding} {balance.currency or ''}".strip())

    finished = not plan.get("next") and plan.get("index", -1) >= 0
    if not active and not plan.get("next") and not finished:
        since = last_event_at or _as_utc(case.signed_at)
        idle = _plural_days(_days(moment - since)) if since else "неизвестно сколько"
        add("no_next_step", f"стоит {idle}")
    # Услуга на ПОСЛЕДНЕМ этапе процесса не «зависла» — она доведена до конца.
    # Прежде каждая закрытая услуга висела в «зависших» навсегда и превращала
    # приоритетный список в шум.
    elif not active and plan.get("next"):
        blocking = [code for code in plan["next"] if plan["requires"].get(code)]
        if blocking and len(plan["next"]) == len(blocking):
            need = ", ".join(plan["requires"][blocking[0]])
            add("no_next_step", f"для перехода нужны факты: {need}")

    if (not finished and last_event_at
            and (moment - last_event_at) >= timedelta(days=STUCK_NO_EVENT_DAYS)):
        add("silent_days", _plural_days(_days(moment - last_event_at)) + " без событий")

    if attempt is not None and attempt.status == REQUESTED:
        add("waiting", f"оператора {attempt.operator}")
    elif active and all(not overdue_on(t, today=today) for t in active):
        soonest = min((_as_utc(t.scheduled_at) for t in active if t.scheduled_at),
                      default=None)
        if soonest and soonest <= moment + timedelta(days=SOON_DAYS):
            add("soon", soonest.astimezone(BISHKEK).strftime("%d.%m"))

    reasons.sort(key=lambda r: -r.weight)
    due_at = min((_as_utc(t.scheduled_at) for t in active if t.scheduled_at),
                 default=None)
    title = f"{product.name if product else 'услуга'} · {case.contract_reference or 'без номера'}"
    return CaseDigest(
        case_id=case.id, title=title,
        product_code=str(product.code if product else ""), direction=direction,
        owner_login=case.owner_login, stage_code=case.stage,
        stage_name=str(plan["name"]), stage_index=int(plan["index"]),
        stage_total=int(plan["total"]),
        reasons=tuple(reasons),
        next_step=_next_step(case, plan, tasks, balance, attempt, today),
        checks=_checks(case, balance, attempt, segments, tasks, direction),
        balance=balance, due_at=due_at, contact_id=case.contact_id)


def _unreadable(case) -> CaseDigest:
    """Услуга, которую не удалось разобрать. Прячем — потеряем работу."""
    rule = _RULE_BY_CODE["no_next_step"]
    return CaseDigest(
        case_id=case.id, title=f"услуга {case.id} — не удалось разобрать",
        product_code="", direction="", owner_login=str(case.owner_login or ""),
        stage_code=str(case.stage or ""), stage_name=str(case.stage or ""),
        stage_index=-1, stage_total=0,
        reasons=(Reason(code="no_next_step", weight=int(rule["weight"]),
                        label="Не удалось разобрать услугу",
                        detail="данные услуги не читаются — нужен разбор вручную",
                        anchor=str(rule["anchor"])),),
        next_step=NextStep(kind="final", label="Разобрать вручную"))


async def workday(session: AsyncSession, *, by: Actor, now: datetime | None = None,
                  mine_only: bool = True, limit: int = 50) -> tuple[list[CaseDigest], bool]:
    """Услуги в порядке срочности. Возвращает (список, признак сбоя).

    Кортеж, а не просто список: «загрузилось и пусто» и «не загрузилось» — разные
    состояния, и экран обязан их различать. С пустым списком на обеих ветках
    различить нечем, и интерфейс соврёт «работы нет» при упавшей базе.
    """
    moment = _as_utc(now) or _now()
    try:
        # «Только мои» действует и для полного админа: иначе тумблер врал
        # подписью — админ включал «только мои» и видел всех.
        owner = by.manager_id if mine_only else None
        cases = await cases_for_owner(session, by=by, owner_login=owner, limit=limit)
        if not cases:
            return [], False
        stuck = await stale_claims(session, now=moment)
        stuck_ids = frozenset(t.id for t in stuck)
        last_events = await _last_event_at(session, [c.id for c in cases])
        digests = []
        for case in cases:
            try:
                digests.append(await digest_for(
                    session, case, by=by, now=moment, stuck_task_ids=stuck_ids,
                    last_event_at=last_events.get(case.id)))
            except Exception:  # noqa: BLE001
                # Одна сбойная услуга не должна гасить весь экран: прежде она
                # давала «реестр недоступен», хотя остальные услуги целы.
                # Такую услугу показываем отдельной причиной, а не прячем.
                log.warning("service_day: case %s unreadable", case.id, exc_info=False)
                digests.append(_unreadable(case))
        digests.sort(key=rank)
        return digests[:max(1, int(limit))], False
    except Exception:  # noqa: BLE001 — реестр недоступен: экран обязан отрисоваться
        return [], True
