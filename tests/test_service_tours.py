"""E2-01 — приёмка полного пути тура: AC-02, AC-03, AC-35.

Доказательство из ТЗ: сценарий D01 проходит от договора до поездки; отказ первой
брони не теряет данные и не закрывает услугу.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.domain.models import CalendarTask, Contact, DomainError, ServiceEvent
from app.domain.service_authz import Actor, PermissionDenied
from app.domain.service_cases import advance, seed_products, sign_contract
from app.domain.service_money import balance_of, correct_contract_amount, record_payment
from app.domain.service_tours import (
    active_attempt, attempts_of, cancel_booking, confirm_booking, decline_booking,
    plan_review_request, request_booking, stop_review_request,
)
from tests.test_service_cases import SYSTEM_ACTOR, run_with_db

OWNER = Actor(manager_id="manager", allowed_directions=("tours",))
PEER = Actor(manager_id="other", allowed_directions=("tours",))
VISA = Actor(manager_id="visa_manager", allowed_directions=("visa",))
CHIEF = Actor(manager_id="chief", allowed_directions=("tours",), is_full_admin=True)

TRIP_IN = date.today() + timedelta(days=60)
TRIP_OUT = TRIP_IN + timedelta(days=10)


async def tour_case(session, *, amount="100000.00"):
    """Подписанный туровый договор на 100 000 KGS."""
    contact = Contact()
    session.add(contact)
    await session.flush()
    products = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
    tour = next(p for p in products if p.code == "tour_package")
    case = await sign_contract(
        session, contact_id=contact.id, product_id=tour.id,
        owner_login=OWNER.manager_id, by=OWNER, reference="FX-TOUR-1",
        amount=Decimal(amount), currency="KGS", idempotency_key="tour-key-1")
    await session.flush()
    return case


async def events_of(session, case_id):
    return [e for e in await session.scalars(
        select(ServiceEvent).where(ServiceEvent.case_id == case_id)
        .order_by(ServiceEvent.id))]


async def tasks_of(session, case_id, *, kind=None):
    query = select(CalendarTask).where(CalendarTask.service_case_id == case_id)
    if kind is not None:
        query = query.where(CalendarTask.kind == kind)
    return list(await session.scalars(query.order_by(CalendarTask.id)))


def test_d01_full_path_from_contract_to_trip_with_a_declined_booking():
    """Сценарий D01 целиком: 100000 / 40000 / 60000, отказ, альтернатива, доплата.

    Это главное доказательство E2-01 из ТЗ. Проверяется именно то, что отказ
    первой брони не теряет данные и не закрывает услугу.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)

            # Предоплата 40 000 из 100 000 — остаток 60 000 (AC-02).
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="d01-pay-1")
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.outstanding == Decimal("60000.00")

            # Первая бронь: заявка оператору.
            first = await request_booking(
                session, case.id, operator="Pegas", country="Турция",
                hotel="Rixos Premium", check_in=TRIP_IN, check_out=TRIP_OUT,
                tourists=2, price=Decimal("100000.00"), currency="KGS", by=OWNER)
            assert first.attempt == 1 and first.status == "requested"

            # Оператор отказал.
            await decline_booking(session, case.id, attempt_id=first.id,
                                  reason="нет мест на эти даты", by=OWNER)
            await session.commit()

            # Услуга НЕ закрыта, деньги НЕ потеряны, данные первой попытки целы.
            await session.refresh(case)
            assert case.stage == "TOUR-01"
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.paid == Decimal("40000.00")
            assert balance.outstanding == Decimal("60000.00")
            await session.refresh(first)
            assert first.hotel == "Rixos Premium"
            assert first.decline_reason == "нет мест на эти даты"

            # Альтернатива: вторая попытка, своя цена, ссылка на отклонённую.
            second = await request_booking(
                session, case.id, operator="Pegas", country="Турция",
                hotel="Delphin Imperial", check_in=TRIP_IN, check_out=TRIP_OUT,
                tourists=2, price=Decimal("112000.00"), currency="KGS", by=OWNER,
                supersedes_id=first.id)
            assert second.attempt == 2
            assert second.supersedes_id == first.id

            # Подтверждение: номер и дата обязательны.
            await confirm_booking(session, case.id, attempt_id=second.id,
                                  reference="PG-99881", by=OWNER)
            await session.commit()
            await session.refresh(second)
            assert second.status == "confirmed" and second.reference == "PG-99881"
            assert second.confirmed_at is not None

            # Цена договора меняется ОТДЕЛЬНО, с основанием: альтернатива дороже.
            await correct_contract_amount(
                session, case.id, amount=Decimal("112000.00"), currency="KGS",
                by=CHIEF, reason=f"альтернатива по брони {second.reference}")
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.agreed == Decimal("112000.00")
            assert balance.outstanding == Decimal("72000.00")

            # Доплата.
            await record_payment(session, case.id, amount=Decimal("72000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="d01-pay-2")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.outstanding == Decimal("0.00")

            # Путь по этапам: бронь отправлена → подтверждена (с фактами) → …
            await advance(session, case.id, to_stage="TOUR-02", by=OWNER)
            await advance(session, case.id, to_stage="TOUR-03", by=OWNER,
                          facts={"booking_reference": second.reference,
                                 "confirmed_at": second.confirmed_at.date().isoformat()})
            for stage in ("TOUR-04", "TOUR-05", "TOUR-06"):
                await advance(session, case.id, to_stage=stage, by=OWNER)
            await session.commit()
            await session.refresh(case)
            assert case.stage == "TOUR-06"

            # История сохранила весь путь, включая отказ.
            kinds = [e.event_type for e in await events_of(session, case.id)]
            assert "booking_requested" in kinds
            assert "booking_declined" in kinds
            assert "booking_confirmed" in kinds
            assert "contract_amount_corrected" in kinds
            assert kinds.count("booking_requested") == 2

            # Обе попытки видны, действующая — вторая.
            assert [a.attempt for a in await attempts_of(session, case.id, by=OWNER)] == [1, 2]
            current = await active_attempt(session, case.id, by=OWNER)
            assert current is not None and current.id == second.id
    run_with_db(scenario)


def test_ac03_declining_keeps_money_and_history_and_allows_a_new_price():
    """AC-03: прежняя история и деньги не потеряны, новая цена с основанием."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            await record_payment(session, case.id, amount=Decimal("30000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p1")
            first = await request_booking(
                session, case.id, operator="Anex", country="ОАЭ", hotel="Atlantis",
                check_in=TRIP_IN, check_out=TRIP_OUT,
                price=Decimal("100000.00"), currency="KGS", by=OWNER)
            await decline_booking(session, case.id, attempt_id=first.id,
                                  reason="цена изменилась", by=OWNER)
            second = await request_booking(
                session, case.id, operator="Anex", country="ОАЭ", hotel="Atlantis",
                check_in=TRIP_IN, check_out=TRIP_OUT,
                price=Decimal("125000.00"), currency="KGS", by=OWNER,
                supersedes_id=first.id)
            await session.commit()
            # Деньги на месте, обе цены видны, прежняя попытка цела.
            assert (await balance_of(session, case.id, by=OWNER)).paid == Decimal("30000.00")
            assert first.price == Decimal("100000.00")
            assert second.price == Decimal("125000.00")
            # Цена договора сама не поменялась: её меняет человек с основанием.
            assert (await balance_of(session, case.id, by=OWNER)).agreed == Decimal("100000.00")
    run_with_db(scenario)


def test_only_one_active_attempt_at_a_time():
    """Двух живых броней быть не может: непонятно, по какой клиент едет."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            await request_booking(
                session, case.id, operator="A", country="Турция", hotel="H1",
                check_in=TRIP_IN, check_out=TRIP_OUT, by=OWNER)
            with pytest.raises(DomainError, match="already has an active booking"):
                await request_booking(
                    session, case.id, operator="B", country="Турция", hotel="H2",
                    check_in=TRIP_IN, check_out=TRIP_OUT, by=OWNER)
    run_with_db(scenario)


def test_only_a_failed_attempt_can_be_superseded():
    """Заменять можно только то, что не состоялось."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            first = await request_booking(
                session, case.id, operator="A", country="Турция", hotel="H1",
                check_in=TRIP_IN, check_out=TRIP_OUT, by=OWNER)
            await confirm_booking(session, case.id, attempt_id=first.id,
                                  reference="REF-1", by=OWNER)
            with pytest.raises(DomainError, match="declined or cancelled"):
                await request_booking(
                    session, case.id, operator="B", country="Турция", hotel="H2",
                    check_in=TRIP_IN, check_out=TRIP_OUT, by=OWNER,
                    supersedes_id=first.id)
    run_with_db(scenario)


def test_confirmation_requires_a_reference():
    """Подтверждение без номера брони — слово менеджера, которое нечем проверить."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            attempt = await request_booking(
                session, case.id, operator="A", country="Турция", hotel="H1",
                check_in=TRIP_IN, check_out=TRIP_OUT, by=OWNER)
            for reference in ("", "   "):
                with pytest.raises(DomainError, match="booking reference"):
                    await confirm_booking(session, case.id, attempt_id=attempt.id,
                                          reference=reference, by=OWNER)
            await session.commit()
            await session.refresh(attempt)
            assert attempt.status == "requested"
    run_with_db(scenario)


def test_declining_requires_a_reason():
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            attempt = await request_booking(
                session, case.id, operator="A", country="Турция", hotel="H1",
                check_in=TRIP_IN, check_out=TRIP_OUT, by=OWNER)
            for reason in ("", "   "):
                with pytest.raises(DomainError, match="decline reason"):
                    await decline_booking(session, case.id, attempt_id=attempt.id,
                                          reason=reason, by=OWNER)
    run_with_db(scenario)


@pytest.mark.parametrize("status_path", ["confirm", "decline", "cancel"])
def test_a_settled_attempt_cannot_be_settled_again(status_path):
    """Повторное решение по той же попытке отклоняется."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            attempt = await request_booking(
                session, case.id, operator="A", country="Турция", hotel="H1",
                check_in=TRIP_IN, check_out=TRIP_OUT, by=OWNER)
            if status_path == "confirm":
                await confirm_booking(session, case.id, attempt_id=attempt.id,
                                      reference="R1", by=OWNER)
                with pytest.raises(DomainError, match="only a requested attempt"):
                    await confirm_booking(session, case.id, attempt_id=attempt.id,
                                          reference="R2", by=OWNER)
            elif status_path == "decline":
                await decline_booking(session, case.id, attempt_id=attempt.id,
                                      reason="нет мест", by=OWNER)
                with pytest.raises(DomainError, match="only a requested attempt"):
                    await decline_booking(session, case.id, attempt_id=attempt.id,
                                          reason="снова нет", by=OWNER)
            else:
                await cancel_booking(session, case.id, attempt_id=attempt.id,
                                     reason="клиент передумал", by=OWNER)
                with pytest.raises(DomainError, match="already cancelled"):
                    await cancel_booking(session, case.id, attempt_id=attempt.id,
                                         reason="ещё раз", by=OWNER)
    run_with_db(scenario)


def test_ac35_cancellation_stops_the_review_request_and_leaves_a_manager_task():
    """AC-35: после отмены запрос отзыва не уходит, а менеджер видит задачу."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task_id = await plan_review_request(
                session, case.id, returns_on=TRIP_OUT, by=OWNER)
            await session.commit()
            planned = await tasks_of(session, case.id, kind="review_request")
            assert [t.id for t in planned] == [task_id]
            assert planned[0].status == "planned"

            result = await stop_review_request(
                session, case.id, reason="поездка отменена, клиент недоволен",
                by=OWNER, complaint=True)
            await session.commit()

            # Запрос отзыва снят.
            assert result["cancelled_task_ids"] == (task_id,)
            review = await tasks_of(session, case.id, kind="review_request")
            assert all(t.status == "cancelled" for t in review)
            # Задача менеджеру создана, с высоким приоритетом и видимой причиной.
            follow_up = await session.get(CalendarTask, result["manager_task_id"])
            assert follow_up.kind == "complaint"
            assert follow_up.priority == "high"
            assert "жалобу" in follow_up.comment
            assert "недоволен" in follow_up.comment
            # В истории видно, что именно остановлено.
            kinds = [e.event_type for e in await events_of(session, case.id)]
            assert "review_request_stopped_complaint" in kinds
    run_with_db(scenario)


def test_review_request_is_a_manager_task_not_an_automatic_message():
    """Запрос отзыва — задача человеку: шаблоны и моменты сообщений не согласованы."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            task_id = await plan_review_request(
                session, case.id, returns_on=TRIP_OUT, by=OWNER)
            await session.commit()
            task = await session.get(CalendarTask, task_id)
            # Это задача менеджеру, привязанная к услуге, а не отправка клиенту.
            assert task.manager_id == OWNER.manager_id
            assert task.service_case_id == case.id
            assert task.kind == "review_request"
            # Срок — через три дня после возвращения, по календарю Бишкека.
            assert task.scheduled_date == TRIP_OUT + timedelta(days=3)
    run_with_db(scenario)


def test_stopping_does_not_cancel_a_review_task_whose_time_has_passed():
    """Прошедшую задачу не отменяем: менеджер мог уже написать клиенту."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            past = CalendarTask(
                contact_id=case.contact_id, manager_id=OWNER.manager_id,
                direction="tours", kind="review_request", comment="уже спросили",
                scheduled_date=date.today() - timedelta(days=2),
                scheduled_at=datetime.now(timezone.utc) - timedelta(days=2),
                created_by=OWNER.manager_id, service_case_id=case.id)
            session.add(past)
            await session.flush()
            result = await stop_review_request(session, case.id, reason="жалоба",
                                               by=OWNER, complaint=True)
            await session.commit()
            await session.refresh(past)
            assert past.status == "planned"
            assert result["cancelled_task_ids"] == ()
    run_with_db(scenario)


def test_price_of_an_attempt_never_changes_the_contract_amount():
    """Цена попытки не переписывает цену договора автоматически."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            attempt = await request_booking(
                session, case.id, operator="A", country="Турция", hotel="H1",
                check_in=TRIP_IN, check_out=TRIP_OUT,
                price=Decimal("150000.00"), currency="KGS", by=OWNER)
            await confirm_booking(session, case.id, attempt_id=attempt.id,
                                  reference="R1", by=OWNER,
                                  price=Decimal("160000.00"), currency="KGS")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            # Договор остался на своих 100 000: деньги меняет человек с причиной.
            assert balance.agreed == Decimal("100000.00")
            await session.refresh(attempt)
            assert attempt.price == Decimal("160000.00")
    run_with_db(scenario)


@pytest.mark.parametrize("price,currency", [
    (100000.0, "KGS"), (Decimal("0"), "KGS"), (Decimal("-5"), "KGS"),
    (Decimal("1.001"), "KGS"), (Decimal("1e13"), "KGS"),
    (Decimal("NaN"), "KGS"), (Decimal("100"), "КГС"), (Decimal("100"), "KG"),
    (Decimal("100"), None), (None, "KGS"),
])
def test_impossible_prices_are_rejected(price, currency):
    """float, ноль, минус, третий знак, кириллица в валюте — всё отклоняется."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            with pytest.raises(DomainError):
                await request_booking(
                    session, case.id, operator="A", country="Турция", hotel="H1",
                    check_in=TRIP_IN, check_out=TRIP_OUT,
                    price=price, currency=currency, by=OWNER)
            await session.commit()
            assert await attempts_of(session, case.id, by=OWNER) == []
    run_with_db(scenario)


def test_check_out_must_be_later_than_check_in():
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            for check_out in (TRIP_IN, TRIP_IN - timedelta(days=1)):
                with pytest.raises(DomainError, match="later than check_in"):
                    await request_booking(
                        session, case.id, operator="A", country="Турция", hotel="H1",
                        check_in=TRIP_IN, check_out=check_out, by=OWNER)
    run_with_db(scenario)


def test_datetime_instead_of_date_is_rejected():
    """Дата заезда — именно дата: время заселения оператор не гарантирует."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            with pytest.raises(DomainError, match="must be a date, not a datetime"):
                await request_booking(
                    session, case.id, operator="A", country="Турция", hotel="H1",
                    check_in=datetime.now(timezone.utc), check_out=TRIP_OUT, by=OWNER)
    run_with_db(scenario)


@pytest.mark.parametrize("tourists", [0, -1, True, 1.5, "2"])
def test_tourists_must_be_a_positive_whole_number(tourists):
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            with pytest.raises(DomainError, match="tourists"):
                await request_booking(
                    session, case.id, operator="A", country="Турция", hotel="H1",
                    check_in=TRIP_IN, check_out=TRIP_OUT, tourists=tourists, by=OWNER)
    run_with_db(scenario)


@pytest.mark.parametrize("by", [PEER, VISA, Actor(manager_id="", allowed_directions=())],
                         ids=["peer", "foreign-direction", "no-identity"])
def test_bookings_of_another_manager_are_closed(by):
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            await session.commit()
            with pytest.raises(PermissionDenied):
                await request_booking(
                    session, case.id, operator="A", country="Турция", hotel="H1",
                    check_in=TRIP_IN, check_out=TRIP_OUT, by=by)
            with pytest.raises(PermissionDenied):
                await attempts_of(session, case.id, by=by)
            await session.commit()
            assert await attempts_of(session, case.id, by=OWNER) == []
    run_with_db(scenario)


def test_attempt_of_another_case_is_refused():
    async def scenario(sm):
        async with sm() as session:
            first = await tour_case(session)
            contact = Contact()
            session.add(contact)
            await session.flush()
            second = await sign_contract(
                session, contact_id=contact.id, product_id=first.product_id,
                owner_login=OWNER.manager_id, by=OWNER, reference="FX-TOUR-2",
                amount=Decimal("50000.00"), currency="KGS",
                idempotency_key="tour-key-2")
            attempt = await request_booking(
                session, first.id, operator="A", country="Турция", hotel="H1",
                check_in=TRIP_IN, check_out=TRIP_OUT, by=OWNER)
            with pytest.raises(DomainError, match="same service case"):
                await decline_booking(session, second.id, attempt_id=attempt.id,
                                      reason="чужая попытка", by=OWNER)
    run_with_db(scenario)


def test_attempt_numbers_grow_and_identity_is_fixed():
    """Номера попыток растут, услугу и номер нельзя переписать."""
    async def scenario(sm):
        async with sm() as session:
            case = await tour_case(session)
            numbers = []
            for index in range(3):
                attempt = await request_booking(
                    session, case.id, operator="A", country="Турция",
                    hotel=f"H{index}", check_in=TRIP_IN, check_out=TRIP_OUT,
                    by=OWNER)
                numbers.append(attempt.attempt)
                await decline_booking(session, case.id, attempt_id=attempt.id,
                                      reason="нет мест", by=OWNER)
            await session.commit()
            assert numbers == [1, 2, 3]
            last = (await attempts_of(session, case.id, by=OWNER))[-1]
            for field_name, value in (("case_id", 999), ("attempt", 7)):
                with pytest.raises(DomainError, match="cannot be reassigned"):
                    setattr(last, field_name, value)
    run_with_db(scenario)
