"""E2-02 — билет: сегменты, часовые зоны, перенос и отмена рейса (STANDARD).

Три правила, которые задают всё остальное.

1. **Окно регистрации не выдумывается.** У перевозчиков оно разное: от 23 до 72
   часов, у части рейсов регистрация только в аэропорту. ТЗ прямо требует «без
   универсального предположения о 24 часах». Поэтому окно — поле сегмента, и если
   его не знают, задача на регистрацию не ставится вовсе. Выдуманный срок хуже
   отсутствующего: клиент на него полагается и опаздывает.

2. **Задача принадлежит сегменту, а не билету.** У перелёта со стыковкой два и
   более сегментов, у каждого своё время и своя зона. Напоминание, привязанное к
   билету, пришло бы не к тому рейсу (AC-09).

3. **Перенос не правит сегмент, а заменяет его.** Прежнее расписание остаётся в
   истории, будущие задачи старого сегмента отменяются и считаются заново от
   нового времени (AC-08). Уже отправленные напоминания не трогаем — сказанного
   не вернуть, но будущие не должны уйти по старому времени.

Время хранится в UTC, зона лежит рядом строкой IANA. Местное время считается из
этой пары: смещение зависит от даты (переход на летнее время), и хранить его
числом нельзя.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.models import (
    ACTIVE_TASK_STATUSES, CalendarTask, DomainError, Product, ServiceCase,
    ServiceEvent, TicketSegment,
)
from app.domain.calendar_tasks import _log_event
from app.domain.service_authz import (
    Actor, PermissionDenied, can_advance_case, can_view_case, require,
)

# Виды задач по билету. `checkin` ставится только когда известно окно регистрации.
CHECKIN_TASK = "checkin"
DEPARTURE_TASK = "departure"
# Предел окна регистрации — две недели. Больше встречается только как ошибка ввода.
MAX_CHECKIN_WINDOW_HOURS = 336
# За сколько часов до вылета напоминать. Это НЕ окно регистрации — то у каждого
# перевозчика своё и живёт в самом сегменте.
DEPARTURE_NOTICE_HOURS = 3
# Календарь менеджеров живёт по Бишкеку: `scheduled_date` — местный день.
BISHKEK = ZoneInfo("Asia/Bishkek")


@dataclass(frozen=True)
class SegmentPlan:
    """Что делать с задачами сегмента: какие отменить и какие создать."""

    cancelled_task_ids: tuple[int, ...] = ()
    created_task_ids: tuple[int, ...] = ()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _zone(name: str, field: str) -> ZoneInfo:
    text = str(name or "").strip()
    if not text:
        raise DomainError(f"{field} is required")
    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        # Имя зоны проверяем сразу: иначе ошибка всплывёт при показе клиенту
        # местного времени, то есть в самый неподходящий момент.
        raise DomainError(f"{field} must be a known IANA time zone") from exc


def _moment(value, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise DomainError(f"{field} must be a datetime")
    if value.tzinfo is None:
        # Наивное время — источник ошибок на сутки: мы бы молча считали его UTC,
        # а менеджер имел в виду местное.
        raise DomainError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _text(value, field: str, limit: int) -> str:
    text = str(value or "").strip()
    if not text or len(text) > limit:
        raise DomainError(f"{field} must contain 1..{limit} characters")
    return text


def _checkin_window(value) -> int | None:
    """Окно регистрации в часах. None означает «не знаем» — и это допустимо."""
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DomainError("checkin_opens_hours_before must be a whole number of hours")
    if not 0 < value <= MAX_CHECKIN_WINDOW_HOURS:
        raise DomainError(
            f"checkin_opens_hours_before must be 1..{MAX_CHECKIN_WINDOW_HOURS} hours")
    return value


def local_time(segment: TicketSegment, *, arrival: bool = False) -> datetime:
    """Местное время вылета или прилёта — то, что видит клиент на табло."""
    zone = _zone(segment.arrival_tz if arrival else segment.departure_tz, "time zone")
    moment = segment.arrival_at if arrival else segment.departure_at
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(zone)


def checkin_moment(segment: TicketSegment) -> datetime | None:
    """Когда открывается регистрация. None — если окно неизвестно.

    Считается от времени вылета этого сегмента, а не от начала поездки: при
    стыковке регистрация на второй рейс открывается по его собственному времени.
    """
    if segment.checkin_opens_hours_before is None:
        return None
    departure = segment.departure_at
    if departure.tzinfo is None:
        departure = departure.replace(tzinfo=timezone.utc)
    return departure - timedelta(hours=int(segment.checkin_opens_hours_before))


async def _case_for_write(session: AsyncSession, case_id: int, by: Actor) -> ServiceCase:
    case = await session.get(ServiceCase, case_id)
    if case is None:
        require(by.is_full_admin, "manage ticket")
        raise DomainError(f"unknown service case {case_id}")
    product = await session.get(Product, case.product_id)
    require(can_advance_case(by, direction=product.direction if product else None,
                             owner_login=case.owner_login), "manage ticket")
    if not str(by.manager_id or "").strip():
        raise PermissionDenied("not allowed: manage ticket")
    return case


async def _cancel_tasks(session: AsyncSession, segment: TicketSegment) -> SegmentPlan:
    """Снять будущие задачи сегмента. Прошедшие не трогаются.

    Отменяются все АКТИВНЫЕ статусы, а не только `planned`: менеджер мог сдвинуть
    задачу через панель, и она стала `rescheduled` — такая задача оставалась живой
    и присылала контроль по прежнему расписанию.

    Задача, срок которой уже прошёл, не отменяется: сообщение, скорее всего, ушло
    клиенту, и помечать его отменённым — значит врать в истории.
    """
    moment = _now()
    cancelled: list[int] = []
    stale = await session.scalars(
        select(CalendarTask).where(
            CalendarTask.ticket_segment_id == segment.id,
            CalendarTask.status.in_(ACTIVE_TASK_STATUSES)))
    for task in stale:
        due = task.scheduled_at
        if due is not None and due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due is not None and due <= moment:
            continue
        previous_status = task.status
        task.status = "cancelled"
        task.cancelled_at = moment
        cancelled.append(task.id)
        await session.flush()
        await _log_event(session, task, "cancelled", actor="system",
                         from_status=previous_status, to_status="cancelled",
                         detail="рейс перенесён или отменён")
    await session.flush()
    return SegmentPlan(cancelled_task_ids=tuple(cancelled))


async def _plan_tasks(session: AsyncSession, case: ServiceCase,
                      segment: TicketSegment, *, by: Actor,
                      cancel_for_segment: TicketSegment | None = None) -> SegmentPlan:
    """Пересчитать задачи сегмента: снять старые и создать новые от нового времени."""
    cancelled: tuple[int, ...] = ()
    if cancel_for_segment is not None:
        cancelled = (await _cancel_tasks(session, cancel_for_segment)).cancelled_task_ids

    moment = _now()
    created: list[int] = []
    checkin_at = checkin_moment(segment)
    if checkin_at is not None and checkin_at > moment:
        created.append(await _add_task(
            session, case, segment, kind=CHECKIN_TASK, at=checkin_at, by=by,
            comment=f"Регистрация на {segment.carrier} {segment.flight_number}"))
    departure_at = segment.departure_at
    if departure_at.tzinfo is None:
        departure_at = departure_at.replace(tzinfo=timezone.utc)
    departure_notice_at = departure_at - timedelta(hours=DEPARTURE_NOTICE_HOURS)
    # Проверяем МОМЕНТ НАПОМИНАНИЯ, а не время вылета: если до вылета меньше трёх
    # часов, напоминание пришлось бы на прошлое — задача сразу числилась бы
    # просроченной и была неотличима от уже отправленной.
    if departure_notice_at > moment:
        created.append(await _add_task(
            session, case, segment, kind=DEPARTURE_TASK, at=departure_notice_at, by=by,
            comment=f"Вылет {segment.carrier} {segment.flight_number} "
                    f"из {segment.departure_airport}"))
    await session.flush()
    return SegmentPlan(cancelled_task_ids=cancelled, created_task_ids=tuple(created))


async def _add_task(session: AsyncSession, case: ServiceCase, segment: TicketSegment,
                    *, kind: str, at: datetime, by: Actor, comment: str) -> int:
    """Создать задачу по сегменту.

    Календарный день считается по БИШКЕКУ, а не по зоне вылета: `scheduled_date`
    это день в календаре менеджера, и остальной код (`_parse_task_when`, расчёт
    просрочки) исходит из местного дня. По зоне вылета задача уезжала на сутки:
    рейс из Амстердама в 23:30 местного — это уже следующий день в Бишкеке.
    Местное время вылета клиенту показывается отдельно, из `local_time`.
    """
    task = CalendarTask(
        contact_id=case.contact_id, request_id=case.request_id,
        manager_id=str(case.owner_login or "").strip().lower(),
        direction="tickets", kind=kind,
        comment=comment[:500], scheduled_date=at.astimezone(BISHKEK).date(),
        scheduled_at=at, created_by=by.manager_id,
        service_case_id=case.id, ticket_segment_id=segment.id)
    session.add(task)
    await session.flush()
    # Журнал задач — достоверная история: задача, созданная мимо него, в истории
    # не видна, и потом непонятно, откуда она взялась.
    await _log_event(session, task, "created", actor=by.manager_id,
                     to_status=task.status, to_at=task.scheduled_at,
                     detail=f"сегмент {segment.position}: {segment.carrier} "
                            f"{segment.flight_number}")
    return task.id


async def add_segment(session: AsyncSession, case_id: int, *, position: int,
                      carrier: str, flight_number: str, departure_airport: str,
                      arrival_airport: str, departure_at, arrival_at,
                      departure_tz: str, arrival_tz: str, by: Actor,
                      checkin_opens_hours_before: int | None = None,
                      booking_reference: str | None = None,
                      passenger_name: str | None = None) -> TicketSegment:
    """Добавить сегмент к билету и завести его задачи."""
    case = await _case_for_write(session, case_id, by)
    if not isinstance(position, int) or isinstance(position, bool) or position < 1:
        raise DomainError("position must be a positive whole number")
    departure = _moment(departure_at, "departure_at")
    arrival = _moment(arrival_at, "arrival_at")
    if arrival <= departure:
        raise DomainError("arrival_at must be later than departure_at")
    dep_zone = _zone(departure_tz, "departure_tz")
    arr_zone = _zone(arrival_tz, "arrival_tz")
    window = _checkin_window(checkin_opens_hours_before)
    taken = await session.scalar(
        select(TicketSegment).where(TicketSegment.case_id == case.id,
                                    TicketSegment.position == position,
                                    TicketSegment.superseded.is_(False),
                                    TicketSegment.status != "cancelled"))
    if taken is not None:
        # Иначе наружу уходит IntegrityError, а сессия остаётся сломанной.
        raise DomainError(f"position {position} is already taken in this ticket")

    segment = TicketSegment(
        case_id=case.id, position=position,
        carrier=_text(carrier, "carrier", 64),
        flight_number=_text(flight_number, "flight_number", 16).upper(),
        departure_airport=_text(departure_airport, "departure_airport", 8).upper(),
        arrival_airport=_text(arrival_airport, "arrival_airport", 8).upper(),
        departure_at=departure, arrival_at=arrival,
        departure_tz=str(dep_zone), arrival_tz=str(arr_zone),
        checkin_opens_hours_before=window, status="planned",
        booking_reference=(str(booking_reference).strip()[:64]
                           if booking_reference else None),
        passenger_name=(str(passenger_name).strip()[:160] if passenger_name else None))
    session.add(segment)
    await session.flush()
    plan = await _plan_tasks(session, case, segment, by=by)
    session.add(ServiceEvent(
        case_id=case.id, event_type="segment_added", actor=by.manager_id,
        to_stage=case.stage,
        payload={"segment_id": segment.id, "position": position,
                 "flight": f"{segment.carrier} {segment.flight_number}",
                 "departure_utc": departure.isoformat(),
                 "departure_local": local_time(segment).isoformat(),
                 "checkin_window_hours": window,
                 "created_task_ids": list(plan.created_task_ids)}))
    await session.flush()
    return segment


async def reschedule_segment(session: AsyncSession, case_id: int, *, segment_id: int,
                             departure_at, arrival_at, by: Actor, reason: str,
                             departure_tz: str | None = None,
                             arrival_tz: str | None = None,
                             checkin_opens_hours_before: int | None = ...,
                             ) -> TicketSegment:
    """Перенести рейс: новый сегмент вместо старого, задачи пересчитаны (AC-08).

    Старый сегмент не правится — он помечается заменённым и остаётся в истории,
    иначе на вопрос «когда рейс был изначально» ответить нечем. Будущие задачи
    старого сегмента отменяются: иначе напоминание ушло бы по прежнему времени.
    Уже прошедшие задачи не трогаются — сказанного не вернуть.
    """
    if not str(reason or "").strip():
        raise DomainError("rescheduling a flight requires a reason")
    case = await _case_for_write(session, case_id, by)
    previous = await session.get(TicketSegment, segment_id)
    if previous is None or previous.case_id != case_id:
        raise DomainError("segment must belong to the same service case")
    if previous.superseded:
        raise DomainError("this segment was already rescheduled")
    if previous.status == "cancelled":
        raise DomainError("a cancelled segment cannot be rescheduled")

    window = (previous.checkin_opens_hours_before
              if checkin_opens_hours_before is ...
              else _checkin_window(checkin_opens_hours_before))
    departure = _moment(departure_at, "departure_at")
    arrival = _moment(arrival_at, "arrival_at")
    if arrival <= departure:
        raise DomainError("arrival_at must be later than departure_at")
    if departure <= _now():
        # Перенос в прошлое снимал старые задачи и не создавал новых: клиент
        # оставался без контроля по рейсу, и никто об этом не узнавал. Если рейс
        # нужно закрыть задним числом — это отмена, а не перенос.
        raise DomainError("a flight cannot be rescheduled into the past; cancel it")

    previous.superseded = True
    previous.status = "cancelled"
    await session.flush()
    moved = TicketSegment(
        case_id=case.id, position=previous.position, carrier=previous.carrier,
        flight_number=previous.flight_number,
        departure_airport=previous.departure_airport,
        arrival_airport=previous.arrival_airport,
        departure_at=departure, arrival_at=arrival,
        departure_tz=str(_zone(departure_tz or previous.departure_tz, "departure_tz")),
        arrival_tz=str(_zone(arrival_tz or previous.arrival_tz, "arrival_tz")),
        checkin_opens_hours_before=window, status="planned",
        supersedes_id=previous.id, booking_reference=previous.booking_reference,
        passenger_name=previous.passenger_name)
    session.add(moved)
    await session.flush()
    plan = await _plan_tasks(session, case, moved, by=by, cancel_for_segment=previous)
    session.add(ServiceEvent(
        case_id=case.id, event_type="segment_rescheduled", actor=by.manager_id,
        to_stage=case.stage, reason=str(reason),
        payload={"segment_id": moved.id, "previous_segment_id": previous.id,
                 "position": previous.position,
                 "previous_departure_utc": previous.departure_at.isoformat()
                 if previous.departure_at.tzinfo
                 else previous.departure_at.replace(tzinfo=timezone.utc).isoformat(),
                 "departure_utc": departure.isoformat(),
                 "cancelled_task_ids": list(plan.cancelled_task_ids),
                 "created_task_ids": list(plan.created_task_ids)}))
    await session.flush()
    return moved


async def cancel_segment(session: AsyncSession, case_id: int, *, segment_id: int,
                         by: Actor, reason: str) -> TicketSegment:
    """Отменить рейс: будущие задачи снимаются, история остаётся."""
    if not str(reason or "").strip():
        raise DomainError("cancelling a flight requires a reason")
    case = await _case_for_write(session, case_id, by)
    segment = await session.get(TicketSegment, segment_id)
    if segment is None or segment.case_id != case_id:
        raise DomainError("segment must belong to the same service case")
    if segment.status == "cancelled":
        raise DomainError("this segment is already cancelled")
    segment.status = "cancelled"
    await session.flush()
    # Только снять будущие задачи. Прежняя версия сначала создавала новые и тут же
    # удаляла — приём лишний и хрупкий: с появлением журнала задач или триггеров
    # удаление упёрлось бы во внешний ключ.
    plan = await _cancel_tasks(session, segment)
    await session.flush()
    session.add(ServiceEvent(
        case_id=case.id, event_type="segment_cancelled", actor=by.manager_id,
        to_stage=case.stage, reason=str(reason),
        payload={"segment_id": segment.id,
                 "cancelled_task_ids": list(plan.cancelled_task_ids)}))
    await session.flush()
    return segment


async def transfer_ticket(session: AsyncSession, case_id: int, *, segment_id: int,
                          passenger_name: str, by: Actor,
                          reason: str) -> TicketSegment:
    """Передать билет другому пассажиру — с причиной и следом в истории."""
    if not str(reason or "").strip():
        raise DomainError("transferring a ticket requires a reason")
    case = await _case_for_write(session, case_id, by)
    segment = await session.get(TicketSegment, segment_id)
    if segment is None or segment.case_id != case_id:
        raise DomainError("segment must belong to the same service case")
    if segment.status == "cancelled" or segment.superseded:
        raise DomainError("a cancelled or rescheduled segment cannot be transferred")
    previous_name = segment.passenger_name
    segment.passenger_name = _text(passenger_name, "passenger_name", 160)
    await session.flush()
    session.add(ServiceEvent(
        case_id=case.id, event_type="ticket_transferred", actor=by.manager_id,
        to_stage=case.stage, reason=str(reason),
        payload={"segment_id": segment.id, "previous_passenger": previous_name,
                 "passenger": segment.passenger_name}))
    await session.flush()
    return segment


async def itinerary(session: AsyncSession, case_id: int, *, by: Actor,
                    include_history: bool = False) -> list[TicketSegment]:
    """Маршрут билета по порядку. По умолчанию — только действующие сегменты."""
    case = await session.get(ServiceCase, case_id)
    if case is None:
        require(by.is_full_admin, "view ticket")
        raise DomainError(f"unknown service case {case_id}")
    product = await session.get(Product, case.product_id)
    require(can_view_case(by, direction=product.direction if product else None,
                          owner_login=case.owner_login), "view ticket")
    query = select(TicketSegment).where(TicketSegment.case_id == case_id)
    if not include_history:
        # Ни заменённые, ни отменённые: «действующий маршрут» — это то, чем
        # клиент реально полетит. Отменённый рейс в нём выглядел бы живым.
        query = query.where(TicketSegment.superseded.is_(False),
                            TicketSegment.status != "cancelled")
    return list(await session.scalars(
        query.order_by(TicketSegment.position, TicketSegment.id)))
