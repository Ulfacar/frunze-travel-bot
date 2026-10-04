"""E2-03 — приёмка денег: AC-02, AC-04, AC-05, AC-06.

Доказательство из ТЗ: 100000 − 40000 = 60000 KGS; дубль не удваивает сумму;
USD без курса не зачитывается; отмена не создаёт ложный долг.
"""
from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError

from app.domain.models import (
    Contact, DomainError, ServiceEvent, ServicePayment,
)
from app.domain.service_authz import Actor, PermissionDenied
from app.domain.service_cases import seed_products, sign_contract
from app.domain.service_money import (
    CORRECTION, REFUND_PAID, Balance, _effective_kind, balance_of,
    correct_contract_amount, correct_entry, record_payment, record_refund_due,
    record_refund_paid, void_entry,
)
from tests.test_contract_signing import migration_config
from tests.test_service_cases import SYSTEM_ACTOR, run_with_db

OWNER = Actor(manager_id="manager", allowed_directions=("tours",))
PEER = Actor(manager_id="other", allowed_directions=("tours",))
VISA = Actor(manager_id="visa_manager", allowed_directions=("visa",))
# Возврат и исправление суммы — полномочие руководителя: до решения DEC-11
# право закрыто всем, кроме полного администратора (can_correct_money).
CHIEF = Actor(manager_id="chief", allowed_directions=("tours", "visa"),
              is_full_admin=True)


async def contract(session, *, amount="100000.00", currency="KGS"):
    """Подписанный туровый договор на заданную сумму."""
    contact = Contact()
    session.add(contact)
    await session.flush()
    products = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
    tour = next(p for p in products if p.code == "tour_package")
    case = await sign_contract(
        session, contact_id=contact.id, product_id=tour.id,
        owner_login=OWNER.manager_id, by=OWNER, reference="SYN-MONEY-1",
        amount=Decimal(amount) if amount else None, currency=currency,
        amount_unknown_reason="" if amount else "уточняет оператор",
        idempotency_key="money-case-1")
    await session.flush()
    return case


async def rows(session):
    return list(await session.scalars(select(ServicePayment).order_by(ServicePayment.id)))


def test_ac02_partial_payment_leaves_the_remainder_computed_separately():
    """AC-02 и доказательство ТЗ: 100000 − 40000 = 60000 KGS."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="pay-1")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.agreed == Decimal("100000.00")
            assert balance.paid == Decimal("40000.00")
            assert balance.outstanding == Decimal("60000.00")
            # Бронь не двигается от самого факта оплаты: этап меняет только advance.
            assert case.stage == "TOUR-01"
    run_with_db(scenario)


def test_ac05_same_request_twice_does_not_double_the_amount():
    """AC-05: дубль одного запроса не начисляется второй раз."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            first = await record_payment(session, case.id, amount=Decimal("40000.00"),
                                         currency="KGS", by=OWNER,
                                         idempotency_key="pay-dup")
            again = await record_payment(session, case.id, amount=Decimal("40000.00"),
                                         currency="KGS", by=OWNER,
                                         idempotency_key="pay-dup")
            await session.commit()
            assert again.id == first.id
            assert len(await rows(session)) == 1
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.paid == Decimal("40000.00")
            assert balance.outstanding == Decimal("60000.00")
    run_with_db(scenario)


def test_ac05_same_key_with_different_amount_is_an_explicit_conflict():
    """Тот же ключ с другой суммой — конфликт, а не тихий возврат старой записи."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="pay-x")
            with pytest.raises(DomainError, match="different money data"):
                await record_payment(session, case.id, amount=Decimal("50000.00"),
                                     currency="KGS", by=OWNER, idempotency_key="pay-x")
            await session.commit()
            assert len(await rows(session)) == 1
    run_with_db(scenario)


def test_ac05_stale_revision_is_an_explicit_conflict_not_a_lost_write():
    """AC-05: конкурентное исправление даёт явный конфликт версии."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            with pytest.raises(DomainError, match="revision conflict"):
                await record_payment(session, case.id, amount=Decimal("10000.00"),
                                     currency="KGS", by=OWNER,
                                     idempotency_key="pay-stale",
                                     expected_revision=case.revision + 5)
            await session.commit()
            assert await rows(session) == []
    run_with_db(scenario)


def test_ac06_foreign_currency_without_a_rate_creates_no_false_remainder():
    """AC-06: USD при договоре в KGS без курса не зачитывается в остаток."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("500.00"),
                                       currency="USD", by=OWNER,
                                       idempotency_key="pay-usd")
            await session.commit()
            assert row.fx_rate is None
            balance = await balance_of(session, case.id, by=OWNER)
            # Остаток как будто оплаты не было — ложной суммы к доплате нет.
            assert balance.paid == Decimal("0.00")
            assert balance.outstanding == Decimal("100000.00")
            # Но платёж виден, и видно, что он требует человека.
            assert balance.unconverted == {"USD": Decimal("500.00")}
            assert balance.needs_attention
    run_with_db(scenario)


def test_ac06_foreign_currency_with_a_rate_is_credited():
    """С курсом платёж зачитывается: 500 USD × 89.50 = 44750.00 KGS."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("500.00"),
                                       currency="USD", by=OWNER,
                                       idempotency_key="pay-usd-rate",
                                       fx_rate=Decimal("89.50"))
            await session.commit()
            assert row.fx_rate == Decimal("89.50")
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.paid == Decimal("44750.00")
            assert balance.outstanding == Decimal("55250.00")
            assert balance.unconverted == {}
    run_with_db(scenario)


def test_rate_for_the_contract_currency_is_rejected_as_meaningless():
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            with pytest.raises(DomainError, match="must not be given"):
                await record_payment(session, case.id, amount=Decimal("100.00"),
                                     currency="KGS", by=OWNER, idempotency_key="k",
                                     fx_rate=Decimal("1.0"))
    run_with_db(scenario)


def test_ac04_refund_decision_is_an_obligation_not_a_returned_payment():
    """AC-04: решение вернуть деньги видно как обязательство, деньги не «возвращены»."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p1")
            await record_refund_due(session, case.id, amount=Decimal("40000.00"),
                                    currency="KGS", by=CHIEF, idempotency_key="rd1",
                                    reason="клиент отказался от поездки")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            # Деньги ещё у компании: «возвращено» пусто, обязательство видно.
            assert balance.refunded == Decimal("0.00")
            assert balance.refund_due == Decimal("40000.00")
            # Остаток не вырос: отмена не создаёт ложный долг клиента.
            assert balance.outstanding == Decimal("60000.00")
            assert balance.needs_attention
    run_with_db(scenario)


def test_actual_refund_increases_the_outstanding_again():
    """Фактический возврат возвращает клиента в состояние «не доплатил»."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p1")
            await record_refund_paid(session, case.id, amount=Decimal("40000.00"),
                                     currency="KGS", by=CHIEF, idempotency_key="rp1",
                                     reason="перевод сделан")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.paid == Decimal("40000.00")
            assert balance.refunded == Decimal("40000.00")
            assert balance.outstanding == Decimal("100000.00")
    run_with_db(scenario)


def test_correction_replaces_the_entry_instead_of_adding_to_it():
    """Исправление заменяет строку, а не удваивает сумму."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            wrong = await record_payment(session, case.id, amount=Decimal("4000.00"),
                                         currency="KGS", by=OWNER,
                                         idempotency_key="p-wrong")
            await correct_entry(session, case.id, corrects_id=wrong.id,
                                amount=Decimal("40000.00"), currency="KGS", by=CHIEF,
                                idempotency_key="p-fix",
                                reason="ошибка ввода: пропущен ноль")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.paid == Decimal("40000.00")
            assert balance.outstanding == Decimal("60000.00")
            # Обе строки в журнале: исправление не стирает историю.
            assert len(await rows(session)) == 2
    run_with_db(scenario)


def test_correction_without_a_reason_is_rejected():
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("100.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            for reason in ("", "   "):
                with pytest.raises(DomainError, match="requires a reason"):
                    await correct_entry(session, case.id, corrects_id=row.id,
                                        amount=Decimal("200.00"), currency="KGS",
                                        by=CHIEF, idempotency_key="f", reason=reason)
    run_with_db(scenario)


def test_money_rows_are_append_only():
    """Правка строки на месте запрещена: сумма не меняется бесследно."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("100.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            with pytest.raises(DomainError, match="append-only"):
                row.amount = Decimal("999.00")
    run_with_db(scenario)


@pytest.mark.parametrize("amount", [1000.0, 0, Decimal("0"), Decimal("-5"), None, "",
                                    "много", Decimal("1.001"), Decimal("1e13"),
                                    Decimal("NaN"), Decimal("Infinity")])
def test_only_sane_decimal_amounts_are_accepted(amount):
    """float, ноль, минус, третий знак, мусор и бесконечность отклоняются."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            with pytest.raises(DomainError):
                await record_payment(session, case.id, amount=amount, currency="KGS",
                                     by=OWNER, idempotency_key="p")
            await session.commit()
            assert await rows(session) == []
    run_with_db(scenario)


@pytest.mark.parametrize("by", [PEER, VISA, Actor(manager_id="", allowed_directions=())],
                         ids=["peer", "foreign-direction", "no-identity"])
def test_money_cannot_be_recorded_by_someone_without_rights(by):
    """Деньги чужой услуги недоступны: ни записать, ни посмотреть."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await session.commit()
            with pytest.raises(PermissionDenied):
                await record_payment(session, case.id, amount=Decimal("100.00"),
                                     currency="KGS", by=by, idempotency_key="p")
            with pytest.raises(PermissionDenied):
                await balance_of(session, case.id, by=by)
            await session.commit()
            assert await rows(session) == []
    run_with_db(scenario)


def test_every_money_row_leaves_an_event_in_the_history():
    """Деньги без следа в истории не двигаются."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("1000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p1")
            await record_refund_due(session, case.id, amount=Decimal("500.00"),
                                    currency="KGS", by=CHIEF, idempotency_key="rd",
                                    reason="частичный отказ")
            await session.commit()
            events = [e.event_type for e in await session.scalars(
                select(ServiceEvent).where(ServiceEvent.case_id == case.id)
                .order_by(ServiceEvent.id))]
            assert "money_payment" in events and "money_refund_due" in events
    run_with_db(scenario)


def test_contract_without_an_amount_has_no_outstanding_and_credits_nothing():
    """Сумма договора неизвестна — остаток не выдумывается."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session, amount=None, currency=None)
            row = await record_payment(session, case.id, amount=Decimal("5000.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.agreed is None and balance.outstanding is None
            assert balance.unconverted == {"KGS": Decimal("5000.00")}
    run_with_db(scenario)


def test_payment_rows_survive_a_failed_neighbour_without_half_records():
    """Отказ одной записи не оставляет половины: ни строки, ни события."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("1000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="ok")
            with pytest.raises(DomainError):
                await record_payment(session, case.id, amount=Decimal("-1"),
                                     currency="KGS", by=OWNER, idempotency_key="bad")
            await session.commit()
            assert len(await rows(session)) == 1
            assert await session.scalar(
                select(func.count()).select_from(ServiceEvent)
                .where(ServiceEvent.event_type == "money_payment")) == 1
    run_with_db(scenario)


def test_prepayment_before_the_contract_amount_is_credited_later():
    """Предоплата, внесённая до появления суммы в договоре, зачитывается потом.

    Это был самый опасный дефект: зачёт фиксировался в момент платежа, и такая
    предоплата навсегда выпадала из остатка — менеджер называл клиенту полную
    сумму вместо остатка. Теперь зачёт считается при расчёте.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session, amount=None, currency=None)
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="pre-1")
            await session.flush()
            # Сумма договора появилась позже — так бывает, когда оператор уточнял
            # цену. Ставится операцией: прямое присваивание закрыто, иначе цена
            # менялась бы без прав, причины и следа в истории.
            await correct_contract_amount(session, case.id, amount=Decimal("100000.00"),
                                          currency="KGS", by=CHIEF,
                                          reason="оператор подтвердил цену")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.paid == Decimal("40000.00")
            assert balance.outstanding == Decimal("60000.00")
            assert balance.unconverted == {}
    run_with_db(scenario)


def test_correcting_a_refund_stays_a_refund():
    """Исправление возврата остаётся возвратом, а не превращается в оплату.

    Иначе поправка опечатки в возврате исключала исходную строку и записывала
    сумму как приход: фактический возврат исчезал, оплата росла, остаток падал.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p1")
            wrong = await record_refund_paid(session, case.id, amount=Decimal("1000.00"),
                                             currency="KGS", by=CHIEF,
                                             idempotency_key="rp-wrong",
                                             reason="перевод сделан")
            await correct_entry(session, case.id, corrects_id=wrong.id,
                                amount=Decimal("1500.00"), currency="KGS", by=CHIEF,
                                idempotency_key="rp-fix", reason="ошибка в сумме")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.paid == Decimal("40000.00")
            assert balance.refunded == Decimal("1500.00")
            assert balance.outstanding == Decimal("61500.00")
    run_with_db(scenario)


def test_an_entry_can_be_corrected_only_once():
    """Вторая поправка к той же строке отклоняется: иначе обе суммировались бы."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("1000.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p1")
            await correct_entry(session, case.id, corrects_id=row.id,
                                amount=Decimal("2000.00"), currency="KGS", by=CHIEF,
                                idempotency_key="fix-1", reason="первая поправка")
            with pytest.raises(DomainError, match="already corrected"):
                await correct_entry(session, case.id, corrects_id=row.id,
                                    amount=Decimal("3000.00"), currency="KGS", by=CHIEF,
                                    idempotency_key="fix-2", reason="вторая поправка")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.paid == Decimal("2000.00")
    run_with_db(scenario)


def test_foreign_refund_and_obligation_are_visible_separately():
    """Возврат и обязательство в чужой валюте видны и не гасят платёж.

    В одном словаре обязательство вычиталось из платежа, сумма схлопывалась в
    ноль и сигнал «нужен человек» пропадал — хотя деньги никуда не делись.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("500.00"),
                                 currency="USD", by=OWNER, idempotency_key="p-usd")
            await record_refund_due(session, case.id, amount=Decimal("500.00"),
                                    currency="USD", by=CHIEF, idempotency_key="rd-usd",
                                    reason="клиент отказался")
            await record_refund_paid(session, case.id, amount=Decimal("200.00"),
                                     currency="USD", by=CHIEF, idempotency_key="rp-usd",
                                     reason="часть вернули")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.unconverted == {"USD": Decimal("500.00")}
            assert balance.foreign_refund_due == {"USD": Decimal("500.00")}
            assert balance.foreign_refunded == {"USD": Decimal("200.00")}
            assert balance.needs_attention
    run_with_db(scenario)


@pytest.mark.parametrize("by", [OWNER, PEER, VISA], ids=["owner", "peer", "foreign"])
def test_refunds_and_corrections_require_a_chief(by):
    """Возврат и исправление суммы — полномочие руководителя (MONEY-05, DEC-11)."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("100.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            with pytest.raises(PermissionDenied):
                await record_refund_due(session, case.id, amount=Decimal("50.00"),
                                        currency="KGS", by=by, idempotency_key="rd",
                                        reason="отказ")
            with pytest.raises(PermissionDenied):
                await record_refund_paid(session, case.id, amount=Decimal("50.00"),
                                         currency="KGS", by=by, idempotency_key="rp",
                                         reason="перевод")
            with pytest.raises(PermissionDenied):
                await correct_entry(session, case.id, corrects_id=row.id,
                                    amount=Decimal("200.00"), currency="KGS", by=by,
                                    idempotency_key="f", reason="правка")
            await session.commit()
            assert len(await rows(session)) == 1
    run_with_db(scenario)


def test_bulk_update_and_delete_cannot_erase_money():
    """Массовый UPDATE/DELETE по журналу денег запрещён.

    Валидатор поля ловит только присваивание через ORM, а bulk-DML обходит
    события — и суммы стирались бесследно.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("1000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            for statement in (update(ServicePayment).values(amount=Decimal("1.00")),
                              delete(ServicePayment)):
                with pytest.raises(DomainError, match="bulk writes"):
                    await session.execute(statement)
            await session.rollback()
            assert len(await rows(session)) == 1
    run_with_db(scenario)


def test_deleting_a_money_row_through_the_orm_is_rejected():
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("1000.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            with pytest.raises(DomainError, match="append-only"):
                await session.delete(row)
                await session.flush()
            await session.rollback()
            assert len(await rows(session)) == 1
    run_with_db(scenario)


@pytest.mark.parametrize("field_name,value", [
    ("reason", "подделка"), ("recorded_by", "someone_else"),
])
def test_reason_and_author_of_a_money_row_cannot_be_rewritten(field_name, value):
    """Причину и автора записи тоже нельзя переписать: иначе подделывается аудит."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("1000.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            with pytest.raises(DomainError, match="append-only"):
                setattr(row, field_name, value)
    run_with_db(scenario)


def test_same_key_with_a_different_rate_is_a_conflict():
    """Тот же ключ с другим курсом — конфликт: иначе провели бы платёж по старому."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("500.00"),
                                 currency="USD", by=OWNER, idempotency_key="k",
                                 fx_rate=Decimal("89.00"))
            with pytest.raises(DomainError, match="different money data"):
                await record_payment(session, case.id, amount=Decimal("500.00"),
                                     currency="USD", by=OWNER, idempotency_key="k",
                                     fx_rate=Decimal("90.00"))
    run_with_db(scenario)


@pytest.mark.parametrize("rate", [Decimal("0.000001"), Decimal("1e30"), Decimal("0"),
                                  Decimal("-1"), 89.5, Decimal("NaN")])
def test_unusable_rates_are_rejected_with_a_domain_error(rate):
    """Крайние курсы отклоняются понятным отказом, а не падением внутри Decimal."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            with pytest.raises(DomainError):
                await record_payment(session, case.id, amount=Decimal("100.00"),
                                     currency="USD", by=OWNER, idempotency_key="k",
                                     fx_rate=rate)
            await session.commit()
            assert await rows(session) == []
    run_with_db(scenario)


@pytest.mark.parametrize("code", ["КГС", "K S", "12", "KG", "KGSX", ""])
def test_currency_must_be_three_latin_letters(code):
    """«КГС» кириллицей проходил как валюта и молча не совпадал с «KGS»."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            with pytest.raises(DomainError, match="three-letter"):
                await record_payment(session, case.id, amount=Decimal("100.00"),
                                     currency=code, by=OWNER, idempotency_key="k")
    run_with_db(scenario)


def test_repeat_after_a_successful_write_is_idempotent_even_with_a_stale_revision():
    """Повтор того же запроса остаётся идемпотентным, а не даёт конфликт версии."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            first = await record_payment(session, case.id, amount=Decimal("100.00"),
                                         currency="KGS", by=OWNER, idempotency_key="k",
                                         expected_revision=case.revision)
            again = await record_payment(session, case.id, amount=Decimal("100.00"),
                                         currency="KGS", by=OWNER, idempotency_key="k",
                                         expected_revision=case.revision - 1)
            await session.commit()
            assert again.id == first.id
            assert len(await rows(session)) == 1
    run_with_db(scenario)


def test_overpayment_raises_the_attention_flag():
    """Оплата больше договора — либо возврат, либо ошибка; молчать нельзя."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session, amount="1000.00")
            await record_payment(session, case.id, amount=Decimal("1500.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.outstanding == Decimal("-500.00")
            assert balance.needs_attention
    run_with_db(scenario)


@pytest.mark.parametrize("by", [PEER, VISA], ids=["peer", "foreign-direction"])
def test_correction_does_not_disclose_which_payments_exist(by):
    """Отказ одинаков для существующего и несуществующего платежа.

    По разнице ответов («нет прав» против «нет такой строки») чужой менеджер
    перебором узнавал, какие id платежей принадлежат услуге.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("100.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            errors = []
            for corrects_id in (row.id, 999999):
                with pytest.raises(PermissionDenied) as caught:
                    await correct_entry(session, case.id, corrects_id=corrects_id,
                                        amount=Decimal("200.00"), currency="KGS",
                                        by=by, idempotency_key=f"f{corrects_id}",
                                        reason="правка")
                errors.append(str(caught.value))
            # Один и тот же текст: существование платежа не выдаётся.
            assert errors[0] == errors[1]
    run_with_db(scenario)


def test_rate_is_not_applied_when_the_contract_currency_changed():
    """Курс не применяется к валюте, к которой он не давался.

    Курс задавался к валюте договора на момент платежа. Если валюта договора
    станет другой, прежний курс дал бы ложный зачёт: 100 USD по курсу 89 к сомам
    это не 8900 евро.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("100.00"),
                                       currency="USD", by=OWNER, idempotency_key="p",
                                       fx_rate=Decimal("89.00"))
            await session.flush()
            assert row.fx_to == "KGS"
            # Сменить валюту договора, пока есть зачтённые платежи, нельзя: их курс
            # давался к прежней валюте, и после смены они зачлись бы по чужому.
            with pytest.raises(DomainError, match="void them first"):
                await correct_contract_amount(session, case.id,
                                              amount=Decimal("1000.00"),
                                              currency="EUR", by=CHIEF,
                                              reason="переводим договор в евро")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            # Платёж остался зачтённым по своему курсу: 100 USD × 89 = 8900 KGS.
            assert balance.paid == Decimal("8900.00")
    run_with_db(scenario)


def test_a_self_correcting_row_is_rejected_by_the_database():
    """Строка не исправляет сама себя: иначе исключает себя из расчёта."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("100.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            connection = await session.connection()
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await connection.execute(
                        ServicePayment.__table__.insert().values(
                            id=999, case_id=case.id, kind="correction",
                            amount=Decimal("1.00"), currency="KGS",
                            idempotency_key="self", corrects_id=999,
                            reason="сама себя", recorded_by="x"))
            await session.rollback()
            assert len(await rows(session)) == 1
    run_with_db(scenario)


def test_a_cycle_of_corrections_is_reported_not_silently_dropped():
    """Круговая ссылка исправлений видна как аномалия, а не теряется.

    Такое возможно только правкой базы мимо домена (база запрещает лишь ссылку
    строки на саму себя), но деньги в этих строках реальные: раньше обе строки
    молча выпадали из расчёта, и оплата превращалась в нуль. Проверяем чистую
    логику: поднять настоящий цикл через домен нельзя, и это правильно.
    """
    first = ServicePayment(id=1, case_id=1, kind=CORRECTION, amount=Decimal("90.00"),
                           currency="KGS", idempotency_key="a", corrects_id=2,
                           recorded_by="x")
    second = ServicePayment(id=2, case_id=1, kind=CORRECTION, amount=Decimal("95.00"),
                            currency="KGS", idempotency_key="b", corrects_id=1,
                            recorded_by="x")
    by_id = {1: first, 2: second}
    # Вид неопределим — обе строки объявляются непонятными, а не пропускаются.
    assert _effective_kind(first, by_id) is None
    assert _effective_kind(second, by_id) is None
    # Исправление без цели — тоже аномалия.
    orphan = ServicePayment(id=3, case_id=1, kind=CORRECTION, amount=Decimal("5.00"),
                            currency="KGS", idempotency_key="c", corrects_id=404,
                            recorded_by="x")
    assert _effective_kind(orphan, {3: orphan}) is None
    # Обычная цепочка по-прежнему наследует вид исправляемой строки.
    base = ServicePayment(id=4, case_id=1, kind=REFUND_PAID, amount=Decimal("1.00"),
                          currency="KGS", idempotency_key="d", recorded_by="x")
    fix = ServicePayment(id=5, case_id=1, kind=CORRECTION, amount=Decimal("2.00"),
                         currency="KGS", idempotency_key="e", corrects_id=4,
                         recorded_by="x")
    assert _effective_kind(fix, {4: base, 5: fix}) == REFUND_PAID


def test_broken_entries_always_raise_the_attention_flag():
    """Непонятная строка журнала обязана требовать человека."""
    assert Balance(broken_entries=(7,)).needs_attention
    assert not Balance(agreed=Decimal("10.00"), paid=Decimal("10.00")).needs_attention


def test_migration_schema_matches_the_models_for_the_money_ledger():
    """Схема журнала из миграции совпадает со схемой из моделей.

    Проверяется схема ИЗ МИГРАЦИИ, а не из `create_all`: тесты на индекс
    проходили бы, даже если убрать его из миграции.
    """
    import tempfile
    from pathlib import Path

    from alembic import command
    from sqlalchemy import create_engine, inspect as sa_inspect

    from app.domain.models import DomainBase

    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{(Path(tmp) / 'money.db').as_posix()}"
        cfg = migration_config()
        cfg.set_main_option("sqlalchemy.url", url)
        command.upgrade(cfg, "head")
        migrated = create_engine(url)
        from_migration = sa_inspect(migrated)
        cols_migration = {c["name"]: c for c in
                          from_migration.get_columns("service_payments")}
        indexes_migration = {i["name"] for i in
                             from_migration.get_indexes("service_payments")}
        migrated.dispose()

        url2 = f"sqlite:///{(Path(tmp) / 'models.db').as_posix()}"
        built = create_engine(url2)
        DomainBase.metadata.create_all(built, tables=[ServicePayment.__table__])
        from_models = sa_inspect(built)
        cols_models = {c["name"]: c for c in from_models.get_columns("service_payments")}
        indexes_models = {i["name"] for i in from_models.get_indexes("service_payments")}
        built.dispose()

    assert set(cols_migration) == set(cols_models)
    for name, column in cols_models.items():
        assert cols_migration[name]["nullable"] == column["nullable"], name
        assert str(cols_migration[name]["default"]) == str(column["default"]), name
    # Уникальный индекс по corrects_id обязан быть в обеих схемах.
    assert "uq_service_payment_corrects" in indexes_migration
    assert indexes_migration == indexes_models


def test_contract_amount_cannot_be_changed_by_direct_assignment():
    """Цену договора нельзя поменять прямым присваиванием.

    Это была главная дыра: журнал платежей закрыт от правок, а сама цена менялась
    из любой сессии без прав, причины и события — и ретроактивно переписывала все
    остатки. Отчёт за прошлый месяц сверить было нечем.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await session.commit()
            for field_name, value in (("agreed_amount", Decimal("50000.00")),
                                      ("currency", "USD")):
                with pytest.raises(DomainError, match="correct_contract_amount"):
                    setattr(case, field_name, value)
            await session.refresh(case)
            assert case.agreed_amount == Decimal("100000.00")
            assert case.currency == "KGS"
    run_with_db(scenario)


def test_correcting_the_contract_amount_requires_a_chief_and_a_reason():
    """Исправление цены — полномочие руководителя, и причина обязательна."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await session.commit()
            for by in (OWNER, PEER, VISA):
                with pytest.raises(PermissionDenied):
                    await correct_contract_amount(session, case.id,
                                                  amount=Decimal("90000.00"),
                                                  currency="KGS", by=by,
                                                  reason="скидка")
            for reason in ("", "   "):
                with pytest.raises(DomainError, match="requires a reason"):
                    await correct_contract_amount(session, case.id,
                                                  amount=Decimal("90000.00"),
                                                  currency="KGS", by=CHIEF,
                                                  reason=reason)
            await session.commit()
            await session.refresh(case)
            assert case.agreed_amount == Decimal("100000.00")
    run_with_db(scenario)


def test_correcting_the_contract_amount_leaves_the_previous_value_in_history():
    """Исправление цены сохраняет прежнее значение в истории — иначе не сверить."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p")
            await correct_contract_amount(session, case.id, amount=Decimal("90000.00"),
                                          currency="KGS", by=CHIEF,
                                          reason="согласована скидка 10000")
            await session.commit()
            event = (await session.scalars(
                select(ServiceEvent)
                .where(ServiceEvent.event_type == "contract_amount_corrected"))).one()
            assert event.payload["previous_amount"] == "100000.00"
            assert event.payload["amount"] == "90000.00"
            assert "скидка" in event.reason
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.outstanding == Decimal("50000.00")
    run_with_db(scenario)


def test_an_actual_refund_closes_the_obligation():
    """Фактический возврат гасит обязательство, а не живёт рядом с ним вечно.

    Иначе услуга после настоящего возврата показывала одновременно «вернули» и
    «обязаны вернуть», и флаг «нужен человек» превращался в постоянный шум.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p")
            due = await record_refund_due(session, case.id, amount=Decimal("40000.00"),
                                          currency="KGS", by=CHIEF,
                                          idempotency_key="rd", reason="отказ клиента")
            await session.commit()
            assert (await balance_of(session, case.id, by=OWNER)).refund_due == Decimal("40000.00")
            await record_refund_paid(session, case.id, amount=Decimal("40000.00"),
                                     currency="KGS", by=CHIEF, idempotency_key="rp",
                                     reason="перевод сделан", settles_id=due.id)
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.refund_due == Decimal("0.00")
            assert balance.refunded == Decimal("40000.00")
            # Долга компании больше нет, и шумного флага тоже.
            assert not balance.needs_attention
    run_with_db(scenario)


def test_only_an_obligation_can_be_settled():
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            payment = await record_payment(session, case.id, amount=Decimal("100.00"),
                                           currency="KGS", by=OWNER,
                                           idempotency_key="p")
            with pytest.raises(DomainError, match="only a refund obligation"):
                await record_refund_paid(session, case.id, amount=Decimal("100.00"),
                                         currency="KGS", by=CHIEF,
                                         idempotency_key="rp", reason="перевод",
                                         settles_id=payment.id)
    run_with_db(scenario)


def test_a_wrong_entry_can_be_voided_without_faking_a_refund():
    """Ошибочную запись можно аннулировать: её не было.

    Без аннулирования единственным способом убрать оплату, которой не приходило,
    был «возврат» — то есть запись, что деньги вернули клиенту, хотя их не
    получали. Отчёт становился ложным дважды.
    """
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("40000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="real")
            ghost = await record_payment(session, case.id, amount=Decimal("7000.00"),
                                         currency="KGS", by=OWNER,
                                         idempotency_key="ghost")
            await session.commit()
            assert (await balance_of(session, case.id, by=OWNER)).paid == Decimal("47000.00")
            await void_entry(session, case.id, voids_id=ghost.id, by=CHIEF,
                             idempotency_key="void-ghost",
                             reason="оплата не поступала, ошибка ввода")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.paid == Decimal("40000.00")
            assert balance.refunded == Decimal("0.00")   # никакого ложного возврата
            assert balance.outstanding == Decimal("60000.00")
            # Обе строки остались в журнале: история не стирается.
            assert len(await rows(session)) == 3
    run_with_db(scenario)


def test_voiding_requires_a_chief_and_a_reason():
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("100.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            await session.commit()
            with pytest.raises(PermissionDenied):
                await void_entry(session, case.id, voids_id=row.id, by=OWNER,
                                 idempotency_key="v", reason="ошибка")
            with pytest.raises(DomainError, match="requires a reason"):
                await void_entry(session, case.id, voids_id=row.id, by=CHIEF,
                                 idempotency_key="v", reason="  ")
            await session.commit()
            assert len(await rows(session)) == 1
    run_with_db(scenario)


def test_a_void_cannot_itself_be_voided():
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            row = await record_payment(session, case.id, amount=Decimal("100.00"),
                                       currency="KGS", by=OWNER, idempotency_key="p")
            void = await void_entry(session, case.id, voids_id=row.id, by=CHIEF,
                                    idempotency_key="v1", reason="ошибка ввода")
            with pytest.raises(DomainError, match="already annulled"):
                await void_entry(session, case.id, voids_id=void.id, by=CHIEF,
                                 idempotency_key="v2", reason="передумали")
    run_with_db(scenario)


def test_refunding_more_than_was_paid_raises_the_attention_flag():
    """Вернули больше, чем получили — это всегда требует человека."""
    async def scenario(sm):
        async with sm() as session:
            case = await contract(session)
            await record_payment(session, case.id, amount=Decimal("1000.00"),
                                 currency="KGS", by=OWNER, idempotency_key="p")
            await record_refund_paid(session, case.id, amount=Decimal("5000.00"),
                                     currency="KGS", by=CHIEF, idempotency_key="rp",
                                     reason="перевод по старой оплате")
            await session.commit()
            balance = await balance_of(session, case.id, by=OWNER)
            assert balance.refunded > balance.paid
            assert balance.needs_attention
    run_with_db(scenario)
