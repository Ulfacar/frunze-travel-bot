"""Чтение денежных итогов отчёта: журнал остаётся единственным источником сумм."""
from collections import defaultdict
from decimal import Decimal

from app.domain.service_money import balance_from_rows, is_fully_paid
from app.core.pilot_summary import _aware


def summarize(cases, payments):
    """Снимок доступных договоров. Валюты не складываются между собой.

    Вход уже ограничен правами вызывающим кодом. Оплаты — зачтённые суммы,
    возвраты отдельно; остаток и доплата учитывают возвраты. Неизвестная
    сумма договора не подменяется нулём.
    """
    ledger = defaultdict(list)
    for row in payments:
        ledger[row.case_id].append(row)
    totals = {}
    unknown = unconverted = broken = 0
    for case in cases:
        balance = balance_from_rows(case, ledger[case.id])
        unknown += balance.agreed is None
        unconverted += bool(balance.unconverted or balance.foreign_refunded)
        broken += bool(balance.broken_entries)
        if not balance.currency:
            continue
        row = totals.setdefault(balance.currency, {
            "paid": Decimal(0), "refunded": Decimal(0),
            "remaining": Decimal(0), "additional": Decimal(0)})
        row["paid"] += balance.paid
        row["refunded"] += balance.refunded
        if balance.agreed is not None:
            net = balance.paid - balance.refunded
            remaining = max(Decimal(0), balance.agreed - net)
            row["remaining"] += remaining
            if 0 < net < balance.agreed:
                row["additional"] += remaining
    return {"currencies": [{"currency": key, **row} for key, row in sorted(totals.items())],
            "unknown_contracts": unknown, "unconverted_contracts": unconverted,
            "broken_contracts": broken}


async def load(sessionmaker, direction, owner, end):
    """Доменные суммы с серверным ограничением направления и владельца.

    owner обязателен для персонального отчёта; None допускается только для
    руководителя с полным доступом к направлению. Вызывающий проверяет это.
    """
    from sqlalchemy import select
    from app.domain.models import ServiceCase, Product, ServicePayment, CalendarTask, ACTIVE_TASK_STATUSES, ContactIdentity, ServiceEvent
    async with sessionmaker() as session:
        scope = [Product.direction == direction, ServiceCase.signed_at < end]
        if owner is not None:
            scope.append(ServiceCase.owner_login == owner)
        cases = list(await session.scalars(select(ServiceCase).join(Product).where(*scope)))
        payments = list(await session.scalars(select(ServicePayment).join(ServiceCase).join(Product).where(
            *scope, ServicePayment.recorded_at < end)))
        task_query = select(CalendarTask.id).where(CalendarTask.direction == direction,
                                                  CalendarTask.status.in_(ACTIVE_TASK_STATUSES))
        if owner is not None:
            task_query = task_query.where(CalendarTask.manager_id == owner)
        tasks = len((await session.execute(task_query)).all())
        identities = list(await session.scalars(select(ContactIdentity).join(
            ServiceCase, ServiceCase.contact_id == ContactIdentity.contact_id).join(Product).where(
                *scope, ContactIdentity.provider_scope == "")))
        amendments = list(await session.scalars(select(ServiceEvent).join(ServiceCase).join(Product).where(
            *scope, ServiceEvent.event_type == "contract_amount_corrected")))
    ledger = defaultdict(list)
    for payment in payments:
        ledger[payment.case_id].append(payment)
    first_payments, full_payments = sale_dates(cases, ledger, end, amendments)
    prepayments = {(i.identity_type, i.normalized_value): (i.contact_id, first_payments[i.contact_id])
                   for i in identities if i.contact_id in first_payments}
    full = {(i.identity_type, i.normalized_value): (i.contact_id, full_payments[i.contact_id])
            for i in identities if i.contact_id in full_payments}
    return {**summarize(cases, payments), "open_tasks": tasks,
            "prepayments": prepayments, "full_payments": full}


def sale_dates(cases, ledger, end, amendments=()):
    from types import SimpleNamespace
    first_payments, full_payments = {}, {}
    for case in cases:
        changes = sorted((e for e in amendments if e.case_id == case.id),
                         key=lambda e: (_aware(e.recorded_at), e.id))
        amount, currency = case.agreed_amount, case.currency
        if changes:
            initial = changes[0].payload
            amount = Decimal(initial["previous_amount"]) if initial.get("previous_amount") is not None else None
            currency = initial.get("previous_currency")
        moments = {_aware(p.recorded_at) for p in ledger[case.id]}
        moments.update(_aware(e.recorded_at) for e in changes)
        moments.add(_aware(case.signed_at))
        for at in sorted(t for t in moments if t < end):
            for change in changes:
                if _aware(change.recorded_at) == at:
                    amount = Decimal(change.payload["amount"])
                    currency = change.payload["currency"]
            if at < _aware(case.signed_at):
                continue
            prefix = [p for p in ledger[case.id] if _aware(p.recorded_at) <= at]
            balance = balance_from_rows(SimpleNamespace(agreed_amount=amount, currency=currency), prefix)
            if not balance.broken_entries and balance.paid - balance.refunded > 0:
                first_payments[case.contact_id] = min(
                    first_payments.get(case.contact_id, end),
                    at)
            if is_fully_paid(balance) and balance.agreed > 0:
                full_payments[case.contact_id] = min(
                    full_payments.get(case.contact_id, end),
                    at)
    return first_payments, full_payments
