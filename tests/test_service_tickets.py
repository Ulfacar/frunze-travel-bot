"""E2-02 — приёмка билета: AC-08 и AC-09.

Доказательство из ТЗ: два сегмента с разными поясами; перенос меняет будущий
контроль нужного сегмента без универсального предположения о 24 часах.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.domain.models import CalendarTask, Contact, DomainError, ServiceEvent
from app.domain.service_authz import Actor, PermissionDenied
from app.domain.service_cases import (
    publish_version, seed_products, sign_contract,
)
from app.domain.service_tickets import (
    add_segment, cancel_segment, checkin_moment, itinerary, local_time,
    reschedule_segment, transfer_ticket,
)
from tests.test_service_cases import SYSTEM_ACTOR, run_with_db

OWNER = Actor(manager_id="manager", allowed_directions=("tickets",))
PEER = Actor(manager_id="other", allowed_directions=("tickets",))
TOURS = Actor(manager_id="tours_manager", allowed_directions=("tours",))

BISHKEK = ZoneInfo("Asia/Bishkek")      # UTC+6, без перехода на летнее время
ISTANBUL = ZoneInfo("Europe/Istanbul")  # UTC+3


def far_future(days: int = 30, hour: int = 7) -> datetime:
    """Момент в будущем: задачи ставятся только на будущее."""
    base = datetime.now(timezone.utc) + timedelta(days=days)
    return base.replace(hour=hour, minute=0, second=0, microsecond=0)


# Минимальный процесс для билетов. Настоящие этапы — бизнес-содержимое (E0-01),
# его подтверждают владельцы; выдумывать его в тестах нельзя, поэтому берём
# простейший: продан → выписан. Для E2-02 важны сегменты, а не этапы.
TICKET_STAGES = [{"code": "TKT-01", "name": "Билет продан"},
                 {"code": "TKT-02", "name": "Билет выписан"}]
TICKET_TRANSITIONS = {"TKT-01": ["TKT-02"], "TKT-02": []}


async def ticket_case(session):
    """Подписанный договор по билетам."""
    contact = Contact()
    session.add(contact)
    await session.flush()
    products = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
    flight = next(p for p in products if p.direction == "tickets")
    if flight.current_version_id is None:
        await publish_version(session, flight.id, TICKET_STAGES, TICKET_TRANSITIONS,
                              "admin", by=SYSTEM_ACTOR)
    case = await sign_contract(
        session, contact_id=contact.id, product_id=flight.id,
        owner_login=OWNER.manager_id, by=OWNER, reference="TKT-1",
        amount=Decimal("45000.00"), currency="KGS", idempotency_key="tkt-key-1")
    await session.flush()
    return case


async def tasks_of(session, segment_id: int, *, status: str | None = None):
    query = select(CalendarTask).where(CalendarTask.ticket_segment_id == segment_id)
    if status is not None:
        query = query.where(CalendarTask.status == status)
    return list(await session.scalars(query.order_by(CalendarTask.id)))


def as_utc(value: datetime | None) -> datetime | None:
    """Момент в UTC. SQLite отдаёт время без зоны — сравниваем моменты, не формы."""
    if value is None:
        return None
    return (value.replace(tzinfo=timezone.utc) if value.tzinfo is None
            else value.astimezone(timezone.utc))


async def events_of(session, case_id: int):
    return [e for e in await session.scalars(
        select(ServiceEvent).where(ServiceEvent.case_id == case_id)
        .order_by(ServiceEvent.id))]


def test_ac09_two_segments_in_different_zones_keep_their_own_moments():
    """AC-09: у каждого сегмента своё время и своя зона, задачи не путаются."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future(30, 7)                 # 07:00 UTC = 13:00 Бишкек
            first = await add_segment(
                session, case.id, position=1, carrier="Pegasus", flight_number="pc 432",
                departure_airport="fru", arrival_airport="ist",
                departure_at=depart, arrival_at=depart + timedelta(hours=6),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=48, by=OWNER)
            second = await add_segment(
                session, case.id, position=2, carrier="Pegasus", flight_number="PC 1021",
                departure_airport="IST", arrival_airport="AMS",
                departure_at=depart + timedelta(hours=10),
                arrival_at=depart + timedelta(hours=14),
                departure_tz="Europe/Istanbul", arrival_tz="Europe/Amsterdam",
                checkin_opens_hours_before=24, by=OWNER)
            await session.commit()

            # Местное время считается в своей зоне у каждого сегмента.
            assert local_time(first).tzinfo == BISHKEK
            assert local_time(first).hour == 13           # 07:00 UTC + 6
            assert local_time(second).tzinfo == ISTANBUL
            assert local_time(second).hour == 20          # 17:00 UTC + 3

            # Регистрация у второго сегмента считается от ЕГО вылета, а не от
            # начала поездки: окна у рейсов разные (48 и 24 часа).
            assert checkin_moment(first) == first.departure_at - timedelta(hours=48)
            assert checkin_moment(second) == second.departure_at - timedelta(hours=24)
            assert checkin_moment(first) != checkin_moment(second)

            # Задачи привязаны к своим сегментам, а не к билету целиком.
            for segment in (first, second):
                segment_tasks = await tasks_of(session, segment.id)
                assert segment_tasks, f"нет задач у сегмента {segment.position}"
                assert all(t.service_case_id == case.id for t in segment_tasks)
                kinds = {t.kind for t in segment_tasks}
                assert "checkin" in kinds and "departure" in kinds
    run_with_db(scenario)


def test_checkin_task_is_not_invented_when_the_window_is_unknown():
    """Без известного окна регистрации задача не ставится — срок не выдумывается.

    Это требование ТЗ: универсального предположения о 24 часах быть не должно.
    У перевозчиков окно от 23 до 72 часов, а часть рейсов регистрирует только в
    аэропорту. Выдуманный срок хуже отсутствующего: клиент на него полагается.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="Avia Traffic",
                flight_number="YK 801", departure_airport="FRU",
                arrival_airport="OSS", departure_at=depart,
                arrival_at=depart + timedelta(hours=1),
                departure_tz="Asia/Bishkek", arrival_tz="Asia/Bishkek",
                checkin_opens_hours_before=None, by=OWNER)
            await session.commit()
            assert checkin_moment(segment) is None
            kinds = {t.kind for t in await tasks_of(session, segment.id)}
            assert "checkin" not in kinds      # задачи на регистрацию нет
            assert "departure" in kinds        # но о вылете напомним
    run_with_db(scenario)


@pytest.mark.parametrize("hours", [23, 24, 36, 48, 72])
def test_checkin_window_is_taken_from_the_carrier_not_from_a_default(hours):
    """Окно берётся у перевозчика: 23, 36, 48 и 72 часа равно допустимы."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="DXB",
                departure_at=depart, arrival_at=depart + timedelta(hours=4),
                departure_tz="Asia/Bishkek", arrival_tz="Asia/Dubai",
                checkin_opens_hours_before=hours, by=OWNER)
            await session.commit()
            assert checkin_moment(segment) == depart - timedelta(hours=hours)
    run_with_db(scenario)


def test_ac08_rescheduling_recomputes_the_future_task_and_keeps_history():
    """AC-08: перенос рейса пересчитывает будущую задачу и сохраняет историю."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future(30, 7)
            segment = await add_segment(
                session, case.id, position=1, carrier="Pegasus",
                flight_number="PC 432", departure_airport="FRU",
                arrival_airport="IST", departure_at=depart,
                arrival_at=depart + timedelta(hours=6),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=48, by=OWNER)
            await session.commit()
            old_tasks = await tasks_of(session, segment.id, status="planned")
            assert old_tasks

            new_depart = depart + timedelta(days=2)
            moved = await reschedule_segment(
                session, case.id, segment_id=segment.id,
                departure_at=new_depart, arrival_at=new_depart + timedelta(hours=6),
                by=OWNER, reason="авиакомпания сдвинула рейс")
            await session.commit()

            # Старые будущие задачи отменены — напоминание по прежнему времени не уйдёт.
            assert await tasks_of(session, segment.id, status="planned") == []
            cancelled = await tasks_of(session, segment.id, status="cancelled")
            assert len(cancelled) == len(old_tasks)
            assert all(t.cancelled_at is not None for t in cancelled)

            # Новые задачи посчитаны от нового времени, с тем же окном 48 часов.
            fresh = await tasks_of(session, moved.id, status="planned")
            assert fresh
            checkin = next(t for t in fresh if t.kind == "checkin")
            assert as_utc(checkin.scheduled_at) == new_depart - timedelta(hours=48)

            # История: прежнее расписание сохранено, старый сегмент не стёрт.
            await session.refresh(segment)
            assert segment.superseded and segment.status == "cancelled"
            assert moved.supersedes_id == segment.id
            assert moved.position == segment.position
            event = next(e for e in await events_of(session, case.id)
                         if e.event_type == "segment_rescheduled")
            assert event.payload["previous_segment_id"] == segment.id
            assert event.payload["previous_departure_utc"].startswith(
                depart.date().isoformat())
            assert "сдвинула" in event.reason
    run_with_db(scenario)


def test_rescheduling_does_not_touch_a_reminder_whose_time_has_passed():
    """Прошедшее напоминание не отменяется: сказанного не вернуть.

    Если срок задачи уже наступил, сообщение, скорее всего, ушло клиенту. Помечать
    его отменённым — значит врать в истории.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            soon = datetime.now(timezone.utc) + timedelta(hours=10)
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=soon, arrival_at=soon + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=48, by=OWNER)
            await session.flush()
            # Окно регистрации уже прошло (вылет через 10 часов, окно 48) —
            # задачи на регистрацию и не возникло.
            assert checkin_moment(segment) < datetime.now(timezone.utc)
            assert {t.kind for t in await tasks_of(session, segment.id)} == {"departure"}
            # Подставим задачу с прошедшим сроком и убедимся, что её не трогают.
            past = CalendarTask(
                contact_id=case.contact_id, manager_id=OWNER.manager_id,
                direction="tickets", kind="checkin", comment="уже отправлено",
                scheduled_date=(datetime.now(timezone.utc) - timedelta(days=1)).date(),
                scheduled_at=datetime.now(timezone.utc) - timedelta(days=1),
                created_by=OWNER.manager_id, service_case_id=case.id,
                ticket_segment_id=segment.id)
            session.add(past)
            await session.flush()
            await reschedule_segment(
                session, case.id, segment_id=segment.id,
                departure_at=soon + timedelta(days=3),
                arrival_at=soon + timedelta(days=3, hours=5),
                by=OWNER, reason="перенос")
            await session.commit()
            await session.refresh(past)
            assert past.status == "planned"        # прошедшая задача не отменена
            assert past.cancelled_at is None
    run_with_db(scenario)


def test_a_segment_can_be_rescheduled_only_once_and_not_after_cancelling():
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            moved = await reschedule_segment(
                session, case.id, segment_id=segment.id,
                departure_at=depart + timedelta(days=1),
                arrival_at=depart + timedelta(days=1, hours=5),
                by=OWNER, reason="первый перенос")
            with pytest.raises(DomainError, match="already rescheduled"):
                await reschedule_segment(
                    session, case.id, segment_id=segment.id,
                    departure_at=depart + timedelta(days=2),
                    arrival_at=depart + timedelta(days=2, hours=5),
                    by=OWNER, reason="второй перенос того же")
            await cancel_segment(session, case.id, segment_id=moved.id, by=OWNER,
                                 reason="клиент отказался")
            with pytest.raises(DomainError, match="cancelled segment"):
                await reschedule_segment(
                    session, case.id, segment_id=moved.id,
                    departure_at=depart + timedelta(days=3),
                    arrival_at=depart + timedelta(days=3, hours=5),
                    by=OWNER, reason="перенос отменённого")
    run_with_db(scenario)


def test_cancelling_a_flight_removes_future_tasks_and_keeps_the_segment():
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=24, by=OWNER)
            await session.commit()
            assert await tasks_of(session, segment.id, status="planned")
            await cancel_segment(session, case.id, segment_id=segment.id, by=OWNER,
                                 reason="рейс снят перевозчиком")
            await session.commit()
            assert await tasks_of(session, segment.id, status="planned") == []
            await session.refresh(segment)
            assert segment.status == "cancelled"
            # Сегмент остался: маршрут с историей его показывает.
            assert segment.id in {s.id for s in await itinerary(
                session, case.id, by=OWNER, include_history=True)}
    run_with_db(scenario)


def test_itinerary_shows_current_segments_in_order_and_hides_replaced():
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            first = await add_segment(
                session, case.id, position=1, carrier="A", flight_number="A1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            await add_segment(
                session, case.id, position=2, carrier="A", flight_number="A2",
                departure_airport="IST", arrival_airport="AMS",
                departure_at=depart + timedelta(hours=8),
                arrival_at=depart + timedelta(hours=12),
                departure_tz="Europe/Istanbul", arrival_tz="Europe/Amsterdam",
                by=OWNER)
            moved = await reschedule_segment(
                session, case.id, segment_id=first.id,
                departure_at=depart + timedelta(days=1),
                arrival_at=depart + timedelta(days=1, hours=5),
                by=OWNER, reason="перенос")
            await session.commit()
            current = await itinerary(session, case.id, by=OWNER)
            assert [s.position for s in current] == [1, 2]
            assert moved.id in {s.id for s in current}
            assert first.id not in {s.id for s in current}
            # С историей видно и заменённый сегмент.
            assert first.id in {s.id for s in await itinerary(
                session, case.id, by=OWNER, include_history=True)}
    run_with_db(scenario)


def test_transferring_a_ticket_records_the_previous_passenger():
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                passenger_name="Азамат Н.", by=OWNER)
            await transfer_ticket(session, case.id, segment_id=segment.id,
                                  passenger_name="Нургуль Т.", by=OWNER,
                                  reason="билет передан супруге")
            await session.commit()
            event = next(e for e in await events_of(session, case.id)
                         if e.event_type == "ticket_transferred")
            assert event.payload["previous_passenger"] == "Азамат Н."
            assert event.payload["passenger"] == "Нургуль Т."
    run_with_db(scenario)


@pytest.mark.parametrize("reason", ["", "   "])
def test_reschedule_cancel_and_transfer_require_a_reason(reason):
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            with pytest.raises(DomainError, match="requires a reason"):
                await reschedule_segment(
                    session, case.id, segment_id=segment.id,
                    departure_at=depart + timedelta(days=1),
                    arrival_at=depart + timedelta(days=1, hours=5),
                    by=OWNER, reason=reason)
            with pytest.raises(DomainError, match="requires a reason"):
                await cancel_segment(session, case.id, segment_id=segment.id,
                                     by=OWNER, reason=reason)
            with pytest.raises(DomainError, match="requires a reason"):
                await transfer_ticket(session, case.id, segment_id=segment.id,
                                      passenger_name="Кто-то", by=OWNER, reason=reason)
    run_with_db(scenario)


@pytest.mark.parametrize("tz", ["", "   ", "Moon/Base", "UTC+6", "Asia/Bishkekk"])
def test_unknown_time_zone_is_rejected_at_the_border(tz):
    """Неизвестная зона отклоняется сразу, а не при показе клиенту времени."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            with pytest.raises(DomainError, match="time zone|is required"):
                await add_segment(
                    session, case.id, position=1, carrier="X", flight_number="X1",
                    departure_airport="FRU", arrival_airport="IST",
                    departure_at=depart, arrival_at=depart + timedelta(hours=5),
                    departure_tz=tz, arrival_tz="Europe/Istanbul", by=OWNER)
    run_with_db(scenario)


def test_naive_datetimes_are_rejected():
    """Наивное время — источник ошибок на сутки: требуем зону явно."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            naive = datetime.now() + timedelta(days=30)
            with pytest.raises(DomainError, match="timezone-aware"):
                await add_segment(
                    session, case.id, position=1, carrier="X", flight_number="X1",
                    departure_airport="FRU", arrival_airport="IST",
                    departure_at=naive, arrival_at=naive + timedelta(hours=5),
                    departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                    by=OWNER)
    run_with_db(scenario)


def test_arrival_must_be_later_than_departure():
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            for arrival in (depart, depart - timedelta(hours=1)):
                with pytest.raises(DomainError, match="later than departure"):
                    await add_segment(
                        session, case.id, position=1, carrier="X", flight_number="X1",
                        departure_airport="FRU", arrival_airport="IST",
                        departure_at=depart, arrival_at=arrival,
                        departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                        by=OWNER)
    run_with_db(scenario)


@pytest.mark.parametrize("window", [0, -5, 337, 1000, True, 24.5, "24"])
def test_impossible_checkin_windows_are_rejected(window):
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            with pytest.raises(DomainError, match="checkin_opens_hours_before"):
                await add_segment(
                    session, case.id, position=1, carrier="X", flight_number="X1",
                    departure_airport="FRU", arrival_airport="IST",
                    departure_at=depart, arrival_at=depart + timedelta(hours=5),
                    departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                    checkin_opens_hours_before=window, by=OWNER)
    run_with_db(scenario)


@pytest.mark.parametrize("by", [PEER, TOURS, Actor(manager_id="", allowed_directions=())],
                         ids=["peer", "foreign-direction", "no-identity"])
def test_tickets_of_another_manager_are_closed(by):
    """Чужой билет недоступен: ни добавить сегмент, ни посмотреть маршрут."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            await session.commit()
            with pytest.raises(PermissionDenied):
                await add_segment(
                    session, case.id, position=1, carrier="X", flight_number="X1",
                    departure_airport="FRU", arrival_airport="IST",
                    departure_at=depart, arrival_at=depart + timedelta(hours=5),
                    departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=by)
            with pytest.raises(PermissionDenied):
                await itinerary(session, case.id, by=by)
    run_with_db(scenario)


def test_segment_must_belong_to_the_given_case():
    async def scenario(sm):
        async with sm() as session:
            first = await ticket_case(session)
            contact = Contact()
            session.add(contact)
            await session.flush()
            second = await sign_contract(
                session, contact_id=contact.id, product_id=first.product_id,
                owner_login=OWNER.manager_id, by=OWNER, reference="TKT-2",
                amount=Decimal("1000.00"), currency="KGS", idempotency_key="tkt-key-2")
            depart = far_future()
            segment = await add_segment(
                session, first.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            with pytest.raises(DomainError, match="same service case"):
                await cancel_segment(session, second.id, segment_id=segment.id,
                                     by=OWNER, reason="чужой сегмент")
    run_with_db(scenario)


def test_segment_identity_cannot_be_reassigned():
    """Услугу и позицию сегмента нельзя переписать: это другой перелёт."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            await session.commit()
            for field_name, value in (("case_id", 999), ("position", 7)):
                with pytest.raises(DomainError, match="cannot be reassigned"):
                    setattr(segment, field_name, value)
    run_with_db(scenario)


def test_every_ticket_action_leaves_an_event():
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            moved = await reschedule_segment(
                session, case.id, segment_id=segment.id,
                departure_at=depart + timedelta(days=1),
                arrival_at=depart + timedelta(days=1, hours=5),
                by=OWNER, reason="перенос")
            await transfer_ticket(session, case.id, segment_id=moved.id,
                                  passenger_name="Новый", by=OWNER, reason="передача")
            await cancel_segment(session, case.id, segment_id=moved.id, by=OWNER,
                                 reason="отмена")
            await session.commit()
            kinds = {e.event_type for e in await events_of(session, case.id)}
            assert {"segment_added", "segment_rescheduled", "ticket_transferred",
                    "segment_cancelled"} <= kinds
    run_with_db(scenario)


def test_rescheduled_task_is_also_cancelled_on_a_flight_change():
    """Задача, сдвинутая менеджером, тоже снимается при переносе рейса.

    Отменялись только задачи в статусе `planned`. Менеджер сдвигает задачу через
    панель, и она становится `rescheduled` — такая задача оставалась живой и
    присылала контроль по прежнему расписанию, то есть AC-08 не выполнялся.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future(30, 7)
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=48, by=OWNER)
            await session.flush()
            # Менеджер сдвинул обе задачи — статус стал `rescheduled`.
            for task in await tasks_of(session, segment.id):
                task.status = "rescheduled"
            await session.flush()
            await reschedule_segment(
                session, case.id, segment_id=segment.id,
                departure_at=depart + timedelta(days=2),
                arrival_at=depart + timedelta(days=2, hours=5),
                by=OWNER, reason="перенос рейса")
            await session.commit()
            statuses = {t.status for t in await tasks_of(session, segment.id)}
            assert statuses == {"cancelled"}, statuses
    run_with_db(scenario)


def test_a_flight_can_be_rescheduled_several_times_in_a_row():
    """Рейс двигают по нескольку раз — цепочка переносов должна проходить.

    Уникальность по (услуга, позиция, заменён) ломала второй перенос: заменённый
    сегмент занимал ключ навсегда. Теперь позиция уникальна только среди
    действующих сегментов.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future(30, 7)
            current = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=24, by=OWNER)
            chain = [current.id]
            for shift in (1, 2, 3):
                current = await reschedule_segment(
                    session, case.id, segment_id=current.id,
                    departure_at=depart + timedelta(days=shift),
                    arrival_at=depart + timedelta(days=shift, hours=5),
                    by=OWNER, reason=f"перенос {shift}")
                await session.commit()
                chain.append(current.id)
            # Действующий сегмент один, а вся цепочка видна в истории.
            active = await itinerary(session, case.id, by=OWNER)
            assert [s.id for s in active] == [chain[-1]]
            history = await itinerary(session, case.id, by=OWNER, include_history=True)
            assert {s.id for s in history} == set(chain)
            # Ссылки образуют цепочку: каждый новый заменяет предыдущего.
            assert current.supersedes_id == chain[-2]
    run_with_db(scenario)


def test_task_calendar_day_follows_bishkek_not_the_departure_zone():
    """Календарный день задачи — по Бишкеку, иначе она уезжает на сутки.

    `scheduled_date` это день в календаре менеджера. Рейс из Амстердама в 23:30
    местного — это уже следующий день в Бишкеке, и по зоне вылета задача попадала
    не в тот день.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            # Нью-Йорк, UTC-5 зимой и UTC-4 летом. Вылет 23:00 UTC: там это ещё
            # тот же день (18:00 или 19:00), а в Бишкеке уже 05:00 следующего.
            # Разница в сутки сохраняется при ЛЮБОМ переходе на летнее время,
            # поэтому тест не ослепнет со временем — прежний вариант с Амстердамом
            # ловил дефект только зимой и с 28.03.2027 перестал бы.
            depart = (datetime.now(timezone.utc) + timedelta(days=40)).replace(
                hour=23, minute=30, second=0, microsecond=0)
            segment = await add_segment(
                session, case.id, position=1, carrier="DL", flight_number="DL 1",
                departure_airport="JFK", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=9),
                departure_tz="America/New_York", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=24, by=OWNER)
            # Проверяем, что дни ДЕЙСТВИТЕЛЬНО расходятся: иначе тест ничего не
            # доказывает, даже когда проходит.
            assert (depart.astimezone(ZoneInfo("America/New_York")).date()
                    != depart.astimezone(ZoneInfo("Asia/Bishkek")).date())
            await session.commit()
            for task in await tasks_of(session, segment.id):
                moment = as_utc(task.scheduled_at)
                expected = moment.astimezone(ZoneInfo("Asia/Bishkek")).date()
                assert task.scheduled_date == expected, (
                    f"{task.kind}: день {task.scheduled_date} вместо {expected}")
    run_with_db(scenario)


def test_departure_task_is_not_created_when_the_notice_moment_has_passed():
    """Напоминание о вылете не ставится в прошлое.

    Проверялось время вылета, а не момент напоминания: при вылете через час
    задача создавалась с датой на два часа раньше текущего момента — сразу
    просроченная и неотличимая от уже отправленной.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            soon = datetime.now(timezone.utc) + timedelta(hours=1)
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=soon, arrival_at=soon + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            await session.commit()
            created = await tasks_of(session, segment.id)
            assert created == [], [(t.kind, t.scheduled_at) for t in created]
    run_with_db(scenario)


def test_a_position_taken_by_an_active_segment_is_refused_clearly():
    """Занятая позиция — понятный отказ, а не нарушение уникальности."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            with pytest.raises(DomainError, match="already taken"):
                await add_segment(
                    session, case.id, position=1, carrier="Y", flight_number="Y1",
                    departure_airport="FRU", arrival_airport="DXB",
                    departure_at=depart, arrival_at=depart + timedelta(hours=4),
                    departure_tz="Asia/Bishkek", arrival_tz="Asia/Dubai", by=OWNER)
            # Сессия жива: следующая операция проходит.
            assert len(await itinerary(session, case.id, by=OWNER)) == 1
    run_with_db(scenario)


def test_a_cancelled_segment_frees_its_position():
    """После отмены рейса позицию занимает новый сегмент.

    Перевозчик снял рейс — клиента переписывают на другой, и он встаёт на то же
    место в маршруте. Прежняя версия держала позицию занятой навсегда: новый
    сегмент приходилось вешать на позицию 3, и порядок маршрута ломался.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            first = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            await cancel_segment(session, case.id, segment_id=first.id, by=OWNER,
                                 reason="рейс снят перевозчиком")
            replacement = await add_segment(
                session, case.id, position=1, carrier="Y", flight_number="Y1",
                departure_airport="FRU", arrival_airport="DXB",
                departure_at=depart, arrival_at=depart + timedelta(hours=4),
                departure_tz="Asia/Bishkek", arrival_tz="Asia/Dubai", by=OWNER)
            await session.commit()
            # В действующем маршруте только новый рейс, на первой позиции.
            current = await itinerary(session, case.id, by=OWNER)
            assert [(s.id, s.position) for s in current] == [(replacement.id, 1)]
            # Отменённый виден только в истории.
            assert first.id in {s.id for s in await itinerary(
                session, case.id, by=OWNER, include_history=True)}
    run_with_db(scenario)


def test_an_active_position_is_still_protected_from_a_duplicate():
    """Занятая ДЕЙСТВУЮЩИМ рейсом позиция по-прежнему защищена."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul", by=OWNER)
            with pytest.raises(DomainError, match="already taken"):
                await add_segment(
                    session, case.id, position=1, carrier="Y", flight_number="Y1",
                    departure_airport="FRU", arrival_airport="DXB",
                    departure_at=depart, arrival_at=depart + timedelta(hours=4),
                    departure_tz="Asia/Bishkek", arrival_tz="Asia/Dubai", by=OWNER)
    run_with_db(scenario)


def test_rescheduling_into_the_past_is_refused():
    """Перенос в прошлое отклоняется: это отмена, а не перенос.

    Иначе старые задачи снимались, новых не возникало, и клиент оставался без
    контроля по рейсу — молча.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=24, by=OWNER)
            await session.commit()
            past = datetime.now(timezone.utc) - timedelta(days=5)
            with pytest.raises(DomainError, match="into the past"):
                await reschedule_segment(
                    session, case.id, segment_id=segment.id,
                    departure_at=past, arrival_at=past + timedelta(hours=5),
                    by=OWNER, reason="задним числом")
            await session.commit()
            # Задачи исходного рейса не тронуты.
            assert await tasks_of(session, segment.id, status="planned")
    run_with_db(scenario)


def test_cancelling_creates_no_tasks_at_all():
    """Отмена только снимает задачи и ни одной не создаёт.

    Прежняя версия сначала создавала задачи, а потом удаляла их — лишний и
    хрупкий приём.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = far_future()
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=24, by=OWNER)
            await session.commit()
            before = len(await tasks_of(session, segment.id))
            await cancel_segment(session, case.id, segment_id=segment.id, by=OWNER,
                                 reason="рейс снят")
            await session.commit()
            after = await tasks_of(session, segment.id)
            # Число задач не выросло, и ни одной активной не осталось.
            assert len(after) == before
            assert all(t.status == "cancelled" for t in after)
    run_with_db(scenario)


@pytest.mark.parametrize("hours_before", [1, 5, 10])
def test_checkin_window_wider_than_time_to_departure_creates_no_task(hours_before):
    """Окно регистрации шире, чем осталось до вылета — задачи нет, а не в прошлом."""
    async def scenario(sm):
        async with sm() as session:
            case = await ticket_case(session)
            depart = datetime.now(timezone.utc) + timedelta(hours=hours_before)
            segment = await add_segment(
                session, case.id, position=1, carrier="X", flight_number="X1",
                departure_airport="FRU", arrival_airport="IST",
                departure_at=depart, arrival_at=depart + timedelta(hours=5),
                departure_tz="Asia/Bishkek", arrival_tz="Europe/Istanbul",
                checkin_opens_hours_before=48, by=OWNER)
            await session.commit()
            kinds = {t.kind for t in await tasks_of(session, segment.id)}
            assert "checkin" not in kinds
            for task in await tasks_of(session, segment.id):
                assert as_utc(task.scheduled_at) > datetime.now(timezone.utc)
    run_with_db(scenario)
