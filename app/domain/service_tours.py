"""E2-01 — полный путь пакетного тура: попытки брони, подтверждение, отказ (STANDARD).

Сценарий, который этот модуль обслуживает (D01 из ТЗ): договор → предоплата →
оператор ОТКАЗАЛ → клиент выбрал альтернативу → вторая бронь подтверждена →
доплата → документы → поездка → отзыв.

Три правила.

1. **Отказ оператора ничего не закрывает.** Услуга остаётся открытой, деньги
   остаются на месте, прежняя попытка сохраняется в истории. Отказ — обычная
   жизнь: нет мест, цена выросла, отель снят с продажи. Клиент выбирает другое,
   и это новая попытка со своей ценой и своим отелем (AC-03).

2. **Цена попытки — не цена договора.** Альтернатива может быть дороже. Договор
   меняется отдельной операцией с причиной (`service_money.correct_contract_amount`),
   и в её событии видно, какая попытка стала основанием. Автоматически цену
   договора не переписываем: это деньги, их меняет человек с правом.

3. **Запрос отзыва — задача менеджеру, а не автоотправка.** Моменты и лимиты
   клиентских сообщений не определены (DEC-12), поэтому модуль ничего клиенту не
   посылает. При отмене поездки или жалобе запланированная задача на отзыв
   снимается, а менеджеру ставится задача разобраться (AC-35): автоматический
   «как вам понравилось?» после жалобы — худшее, что можно сделать.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    ACTIVE_TASK_STATUSES, BookingAttempt, CalendarTask, DomainError, Product,
    ServiceCase, ServiceEvent,
)
from app.domain.service_authz import (
    Actor, PermissionDenied, can_advance_case, can_view_case, require,
)

REQUESTED = "requested"
CONFIRMED = "confirmed"
DECLINED = "declined"
CANCELLED = "cancelled"

REVIEW_TASK = "review_request"
COMPLAINT_TASK = "complaint"
BISHKEK = ZoneInfo("Asia/Bishkek")
# Через сколько дней после возвращения просить отзыв. Это срок ЗАДАЧИ менеджеру,
# а не момент автоотправки: отправку по шаблону бизнес ещё не согласовал (DEC-12).
REVIEW_AFTER_DAYS = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _text(value, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise DomainError(f"{field} must contain 1..{limit} characters")
    return text


def _day(value, field: str) -> date:
    if isinstance(value, datetime):
        raise DomainError(f"{field} must be a date, not a datetime")
    if not isinstance(value, date):
        raise DomainError(f"{field} must be a date")
    return value


def _price(value, currency) -> tuple[Decimal | None, str | None]:
    """Цена попытки. Либо есть вместе с валютой, либо нет вовсе."""
    if value is None:
        if currency:
            raise DomainError("currency without a price is meaningless")
        return None, None
    if isinstance(value, float):
        # float на деньгах теряет копейки — тот же запрет, что в `service_money`.
        raise DomainError("price must be Decimal or string, not float")
    try:
        price = Decimal(str(value))
    except (InvalidOperation, ValueError, ArithmeticError) as exc:
        raise DomainError("price must be a decimal number") from exc
    if not price.is_finite() or price <= 0:
        raise DomainError("price must be a positive finite number")
    if price.as_tuple().exponent < -2:
        raise DomainError("price cannot have more than two decimal places")
    if price >= Decimal("10") ** 12:
        raise DomainError("price is out of range")
    code = str(currency or "").strip().upper()
    if len(code) != 3 or not code.isalpha() or not code.isascii():
        raise DomainError("currency must be a three-letter code")
    return price.quantize(Decimal("0.01")), code


async def _case_for_write(session: AsyncSession, case_id: int, by: Actor) -> ServiceCase:
    case = await session.get(ServiceCase, case_id)
    if case is None:
        require(by.is_full_admin, "manage booking")
        raise DomainError(f"unknown service case {case_id}")
    product = await session.get(Product, case.product_id)
    require(can_advance_case(by, direction=product.direction if product else None,
                             owner_login=case.owner_login), "manage booking")
    if not str(by.manager_id or "").strip():
        raise PermissionDenied("not allowed: manage booking")
    return case


async def _attempt_of(session: AsyncSession, case_id: int,
                      attempt_id: int) -> BookingAttempt:
    attempt = await session.get(BookingAttempt, attempt_id)
    if attempt is None or attempt.case_id != case_id:
        raise DomainError("booking attempt must belong to the same service case")
    return attempt


async def request_booking(session: AsyncSession, case_id: int, *, operator: str,
                          country: str, hotel: str, check_in, check_out,
                          by: Actor, tourists: int = 1, price=None, currency=None,
                          supersedes_id: int | None = None) -> BookingAttempt:
    """Отправить заявку оператору — новая попытка брони.

    `supersedes_id` указывает попытку, которую эта заменяет после отказа. Прежняя
    не трогается: её данные и причина отказа остаются в истории (AC-03).
    """
    case = await _case_for_write(session, case_id, by)
    first_day = _day(check_in, "check_in")
    last_day = _day(check_out, "check_out")
    if last_day <= first_day:
        raise DomainError("check_out must be later than check_in")
    if not isinstance(tourists, int) or isinstance(tourists, bool) or tourists < 1:
        raise DomainError("tourists must be a positive whole number")
    amount, code = _price(price, currency)

    previous: BookingAttempt | None = None
    if supersedes_id is not None:
        previous = await _attempt_of(session, case_id, supersedes_id)
        if previous.status not in (DECLINED, CANCELLED):
            # Заменять можно только то, что не состоялось: иначе у услуги оказались
            # бы две живые брони, и непонятно, по какой клиент едет.
            raise DomainError("only a declined or cancelled attempt can be superseded")

    live = await session.scalar(
        select(func.count()).select_from(BookingAttempt).where(
            BookingAttempt.case_id == case_id,
            BookingAttempt.status.in_((REQUESTED, CONFIRMED))))
    if live:
        raise DomainError("this service case already has an active booking attempt")

    highest = await session.scalar(
        select(func.max(BookingAttempt.attempt)).where(
            BookingAttempt.case_id == case_id))
    attempt = BookingAttempt(
        case_id=case.id, attempt=int(highest or 0) + 1,
        operator=_text(operator, "operator", 128),
        country=_text(country, "country", 64),
        hotel=_text(hotel, "hotel", 255),
        check_in=first_day, check_out=last_day, tourists=tourists,
        price=amount, currency=code, status=REQUESTED,
        supersedes_id=previous.id if previous else None,
        requested_by=by.manager_id)
    session.add(attempt)
    await session.flush()
    session.add(ServiceEvent(
        case_id=case.id, event_type="booking_requested", actor=by.manager_id,
        to_stage=case.stage,
        payload={"attempt_id": attempt.id, "attempt": attempt.attempt,
                 "operator": attempt.operator, "hotel": attempt.hotel,
                 "check_in": first_day.isoformat(), "check_out": last_day.isoformat(),
                 "price": str(amount) if amount is not None else None,
                 "currency": code,
                 "supersedes_id": previous.id if previous else None}))
    await session.flush()
    return attempt


async def confirm_booking(session: AsyncSession, case_id: int, *, attempt_id: int,
                          reference: str, by: Actor, confirmed_at=None,
                          price=None, currency=None) -> BookingAttempt:
    """Оператор подтвердил бронь. Номер и дата обязательны (FLOW-03).

    Без номера и даты «подтверждено» — это слово менеджера, которое потом нечем
    подтвердить. Если оператор подтвердил по другой цене, она записывается здесь,
    но цену ДОГОВОРА не меняет: это отдельная операция с причиной.
    """
    case = await _case_for_write(session, case_id, by)
    attempt = await _attempt_of(session, case_id, attempt_id)
    if attempt.status != REQUESTED:
        raise DomainError(f"only a requested attempt can be confirmed, not {attempt.status!r}")
    moment = confirmed_at or _now()
    if not isinstance(moment, datetime):
        raise DomainError("confirmed_at must be a datetime")
    if moment.tzinfo is None:
        raise DomainError("confirmed_at must be timezone-aware")
    attempt.reference = _text(reference, "booking reference", 128)
    attempt.confirmed_at = moment.astimezone(timezone.utc)
    if price is not None or currency is not None:
        attempt.price, attempt.currency = _price(price, currency)
    attempt.status = CONFIRMED
    await session.flush()
    session.add(ServiceEvent(
        case_id=case.id, event_type="booking_confirmed", actor=by.manager_id,
        to_stage=case.stage,
        payload={"attempt_id": attempt.id, "attempt": attempt.attempt,
                 "reference": attempt.reference,
                 "confirmed_at": attempt.confirmed_at.isoformat(),
                 "price": str(attempt.price) if attempt.price is not None else None,
                 "currency": attempt.currency}))
    await session.flush()
    return attempt


async def decline_booking(session: AsyncSession, case_id: int, *, attempt_id: int,
                          reason: str, by: Actor) -> BookingAttempt:
    """Оператор отказал. Услуга остаётся открытой, деньги не трогаем (AC-03).

    Причина обязательна: именно она объясняет клиенту, почему предлагаем другое,
    и она же нужна, чтобы потом разобрать, с каким оператором так регулярно.
    """
    case = await _case_for_write(session, case_id, by)
    attempt = await _attempt_of(session, case_id, attempt_id)
    if attempt.status != REQUESTED:
        raise DomainError(f"only a requested attempt can be declined, not {attempt.status!r}")
    attempt.decline_reason = _text(reason, "decline reason", 500)
    attempt.status = DECLINED
    await session.flush()
    session.add(ServiceEvent(
        case_id=case.id, event_type="booking_declined", actor=by.manager_id,
        to_stage=case.stage, reason=attempt.decline_reason,
        payload={"attempt_id": attempt.id, "attempt": attempt.attempt,
                 "operator": attempt.operator, "hotel": attempt.hotel}))
    await session.flush()
    return attempt


async def cancel_booking(session: AsyncSession, case_id: int, *, attempt_id: int,
                         reason: str, by: Actor) -> BookingAttempt:
    """Отменить бронь по нашей стороне (клиент передумал, сроки не сошлись)."""
    case = await _case_for_write(session, case_id, by)
    attempt = await _attempt_of(session, case_id, attempt_id)
    if attempt.status in (DECLINED, CANCELLED):
        raise DomainError(f"attempt is already {attempt.status}")
    attempt.decline_reason = _text(reason, "cancel reason", 500)
    attempt.status = CANCELLED
    await session.flush()
    session.add(ServiceEvent(
        case_id=case.id, event_type="booking_cancelled", actor=by.manager_id,
        to_stage=case.stage, reason=attempt.decline_reason,
        payload={"attempt_id": attempt.id, "attempt": attempt.attempt}))
    await session.flush()
    return attempt


async def plan_review_request(session: AsyncSession, case_id: int, *, returns_on,
                              by: Actor) -> int:
    """Запланировать ЗАДАЧУ менеджеру попросить отзыв после возвращения.

    Это задача человеку, а не автоматическое сообщение клиенту: моменты, шаблоны
    и лимиты клиентских сообщений бизнес не согласовал (DEC-12). Отправлять
    «как вам понравилось?» по таймеру, ничего не зная о поездке, нельзя.
    """
    case = await _case_for_write(session, case_id, by)
    back = _day(returns_on, "returns_on")
    due = back + timedelta(days=REVIEW_AFTER_DAYS)
    task = CalendarTask(
        contact_id=case.contact_id, request_id=case.request_id,
        manager_id=str(case.owner_login or "").strip().lower(),
        direction="tours", kind=REVIEW_TASK,
        comment="Попросить отзыв о поездке",
        scheduled_date=due,
        scheduled_at=datetime.combine(due, datetime.min.time(), tzinfo=BISHKEK)
        .astimezone(timezone.utc) + timedelta(hours=10),
        created_by=by.manager_id, service_case_id=case.id)
    session.add(task)
    await session.flush()
    session.add(ServiceEvent(
        case_id=case.id, event_type="review_request_planned", actor=by.manager_id,
        to_stage=case.stage,
        payload={"task_id": task.id, "due": due.isoformat()}))
    await session.flush()
    return task.id


async def stop_review_request(session: AsyncSession, case_id: int, *, reason: str,
                              by: Actor, complaint: bool = False) -> dict:
    """Снять запрос отзыва и поставить задачу менеджеру (AC-35).

    Поездка отменена или клиент пожаловался — запрос отзыва уходить не должен.
    Автоматический «как вам понравилось?» после жалобы разрушает отношения с
    клиентом надёжнее, чем сама проблема. Вместо него менеджер получает задачу
    разобраться, и она видна в его дне.
    """
    case = await _case_for_write(session, case_id, by)
    explanation = _text(reason, "reason", 500)
    moment = _now()
    stopped: list[int] = []
    planned = await session.scalars(
        select(CalendarTask).where(
            CalendarTask.service_case_id == case.id,
            CalendarTask.kind == REVIEW_TASK,
            CalendarTask.status.in_(ACTIVE_TASK_STATUSES)))
    for task in planned:
        due = task.scheduled_at
        if due is not None and due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due is not None and due <= moment:
            # Срок прошёл — менеджер, возможно, уже написал клиенту. Не трогаем:
            # отменять то, что произошло, значит врать в истории.
            continue
        task.status = "cancelled"
        task.cancelled_at = moment
        stopped.append(task.id)

    follow_up = CalendarTask(
        contact_id=case.contact_id, request_id=case.request_id,
        manager_id=str(case.owner_login or "").strip().lower(),
        direction="tours", kind=COMPLAINT_TASK if complaint else "call",
        priority="high" if complaint else "normal",
        comment=("Разобрать жалобу клиента: " if complaint
                 else "Связаться с клиентом: ") + explanation[:400],
        scheduled_date=moment.astimezone(BISHKEK).date(),
        scheduled_at=moment, created_by=by.manager_id, service_case_id=case.id)
    session.add(follow_up)
    await session.flush()
    session.add(ServiceEvent(
        case_id=case.id,
        event_type="review_request_stopped" + ("_complaint" if complaint else ""),
        actor=by.manager_id, to_stage=case.stage, reason=explanation,
        payload={"cancelled_task_ids": stopped, "manager_task_id": follow_up.id,
                 "complaint": complaint}))
    await session.flush()
    return {"cancelled_task_ids": tuple(stopped), "manager_task_id": follow_up.id}


async def attempts_of(session: AsyncSession, case_id: int, *,
                      by: Actor) -> list[BookingAttempt]:
    """Все попытки брони по услуге, от первой к последней."""
    case = await session.get(ServiceCase, case_id)
    if case is None:
        require(by.is_full_admin, "view booking")
        raise DomainError(f"unknown service case {case_id}")
    product = await session.get(Product, case.product_id)
    require(can_view_case(by, direction=product.direction if product else None,
                          owner_login=case.owner_login), "view booking")
    return list(await session.scalars(
        select(BookingAttempt).where(BookingAttempt.case_id == case_id)
        .order_by(BookingAttempt.attempt)))


async def active_attempt(session: AsyncSession, case_id: int, *,
                         by: Actor) -> BookingAttempt | None:
    """Действующая попытка: запрошенная или подтверждённая. Их не больше одной."""
    for attempt in await attempts_of(session, case_id, by=by):
        if attempt.status in (REQUESTED, CONFIRMED):
            return attempt
    return None
