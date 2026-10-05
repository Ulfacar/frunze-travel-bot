#!/usr/bin/env python3
"""E2-06 — пять демонстрационных услуг: доказательство «порядок объясним».

Каждая услуга поднята СВОИМ правилом приоритета, поэтому на экране видно, что
порядок не случаен и объясним без чтения кода:

    1. подвисший захват       — задача взята и не завершена
    2. просроченная регистрация — внешний срок, его не сдвинуть
    3. просроченный звонок      — наша просрочка
    4. платёж без курса         — деньги требуют человека
    5. молчащая бронь           — оператор не ответил больше суток

Это НЕ прод-скрипт. На боевой базе он создаст мусорные записи, поэтому требует
явного адреса базы и отказывается работать без `--yes`. Для демонстрации заводите
отдельную базу:

    python scripts/seed_service_demo.py --dsn "sqlite+aiosqlite:///demo.db" --yes

Сидер девяти настоящих продуктов — отдельное решение владельцев (бизнес-содержимое),
этот скрипт его не заменяет: он публикует минимальные процессы под демонстрацию.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402

from app.domain.models import CalendarTask, Contact, DomainBase  # noqa: E402
from app.domain.service_authz import Actor  # noqa: E402
from app.domain.service_cases import (  # noqa: E402
    publish_version, seed_products, sign_contract,
)
from app.domain.service_day import workday  # noqa: E402
from app.domain.service_money import record_payment  # noqa: E402
from app.domain.service_tickets import add_segment  # noqa: E402
from app.domain.service_tours import request_booking  # noqa: E402
from app.domain.task_rules import claim_task  # noqa: E402

OWNER = Actor(manager_id="manager", allowed_directions=("tours", "tickets"))
SYSTEM = Actor(manager_id="system", is_full_admin=True)
TICKET_STAGES = [{"code": "TKT-01", "name": "Билет продан"},
                 {"code": "TKT-02", "name": "Билет выписан"}]
TICKET_TRANSITIONS = {"TKT-01": ["TKT-02"], "TKT-02": []}


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _case(session: AsyncSession, *, reference: str, direction: str,
                amount: str = "100000.00") -> object:
    contact = Contact()
    session.add(contact)
    await session.flush()
    products = await seed_products(session, published_by="demo", by=SYSTEM)
    product = next(p for p in products if p.direction == direction)
    if product.current_version_id is None:
        await publish_version(session, product.id, TICKET_STAGES, TICKET_TRANSITIONS,
                              "demo", by=SYSTEM)
    case = await sign_contract(
        session, contact_id=contact.id, product_id=product.id,
        owner_login=OWNER.manager_id, by=OWNER, reference=reference,
        amount=Decimal(amount), currency="KGS",
        idempotency_key=f"demo-{reference}")
    await session.flush()
    return case


async def _task(session: AsyncSession, case, *, at: datetime, kind: str,
                comment: str) -> CalendarTask:
    task = CalendarTask(
        contact_id=case.contact_id, manager_id=case.owner_login,
        direction="tours" if kind != "checkin" else "tickets",
        kind=kind, comment=comment, scheduled_date=at.date(), scheduled_at=at,
        created_by="demo", service_case_id=case.id)
    session.add(task)
    await session.flush()
    return task


async def build(dsn: str) -> int:
    engine = create_async_engine(dsn)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(DomainBase.metadata.create_all)
        async with AsyncSession(engine) as session:
            now = _now()

            # 1. Подвисший захват: система не знает, ушло ли сообщение.
            one = await _case(session, reference="DEMO-1", direction="tours")
            stuck = await _task(session, one, at=now - timedelta(hours=3),
                                kind="call", comment="Подтвердить вылет с клиентом")
            await claim_task(session, stuck.id, worker="worker-A",
                             now=now - timedelta(minutes=40))

            # 2. Просроченная регистрация: внешний срок, его не сдвинуть переносом.
            two = await _case(session, reference="DEMO-2", direction="tickets",
                              amount="45000.00")
            depart = now + timedelta(days=10)
            await add_segment(session, two.id, position=1, carrier="Pegasus",
                              flight_number="PC 432", departure_airport="FRU",
                              arrival_airport="IST", departure_at=depart,
                              arrival_at=depart + timedelta(hours=6),
                              departure_tz="Asia/Bishkek",
                              arrival_tz="Europe/Istanbul",
                              checkin_opens_hours_before=48, by=OWNER)
            await _task(session, two, at=now - timedelta(days=1), kind="checkin",
                        comment="Регистрация на рейс PC 432")

            # 3. Просроченный звонок: обещали и не сделали.
            three = await _case(session, reference="DEMO-3", direction="tours")
            await _task(session, three, at=now - timedelta(days=2), kind="call",
                        comment="Позвонить клиенту по доплате")

            # 4. Платёж в чужой валюте без курса: зачесть нельзя, нужен человек.
            four = await _case(session, reference="DEMO-4", direction="tours")
            await record_payment(session, four.id, amount=Decimal("500.00"),
                                 currency="USD", by=OWNER,
                                 idempotency_key="demo-4-usd")

            # 5. Бронь отправлена и молчит дольше суток.
            five = await _case(session, reference="DEMO-5", direction="tours")
            attempt = await request_booking(
                session, five.id, operator="Pegas", country="Турция",
                hotel="Rixos Premium", check_in=(now + timedelta(days=40)).date(),
                check_out=(now + timedelta(days=50)).date(), tourists=2,
                price=Decimal("100000.00"), currency="KGS", by=OWNER)
            # Момент создания ставит база; для демонстрации сдвигаем явно.
            attempt.created_at = now - timedelta(days=2)
            await session.flush()
            await session.commit()

            digests, failed = await workday(session, by=OWNER, now=now)
            print(f"создано услуг: {len(digests)}, сбой загрузки: {failed}\n")
            for position, digest in enumerate(digests, 1):
                reason = digest.top_reason
                print(f"{position}. [{reason.weight:3d}] {digest.title}")
                print(f"     причина: {reason.label} — {reason.detail}")
                print(f"     основание: вкладка «{reason.anchor}»")
                print(f"     следующий шаг: {digest.next_step.label}")
                if digest.next_step.blocked_by:
                    print(f"     внимание: {digest.next_step.blocked_by}")
                print(f"     готовность: {digest.ready_done} из {digest.ready_total}")
            expected = ["claim_stuck", "hard_deadline", "task_overdue",
                        "money_attention", "booking_silent"]
            actual = [d.top_reason.code for d in digests]
            print()
            if actual == expected:
                print("порядок совпал с ожидаемым: каждая услуга поднята своим правилом")
                return 0
            print(f"ПОРЯДОК РАСХОДИТСЯ\n  ожидали: {expected}\n  вышло:   {actual}")
            return 1
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dsn", default="", help="адрес базы для демонстрации")
    parser.add_argument("--yes", action="store_true",
                        help="подтвердить запись: скрипт создаёт тестовые записи")
    args = parser.parse_args()
    if not args.dsn:
        print("нужен --dsn: скрипт пишет данные и не угадывает базу", file=sys.stderr)
        return 2
    if not args.yes:
        print("скрипт создаёт тестовые услуги. Повторите с --yes", file=sys.stderr)
        return 2
    return asyncio.run(build(args.dsn))


if __name__ == "__main__":
    raise SystemExit(main())
