"""Независимая проверка E1-03 / FLOW-02 / AC-01, AC-16, AC-17.

Цель: проверенный локальный снимок, не выпуск. Риск: CRITICAL (права, деньги).
Меняется только этот файл; обнаруженные дефекты намеренно не xfail.
SQLite/транзакции — как в test_service_cases; данные только синтетические.
Настоящая конкурентная проверка PostgreSQL включается TEST_POSTGRES_DSN и
использует собственную временную схему. Без DSN это UNKNOWN, а не PASS.
Тесты stale_lookup отдельно воспроизводят ветку конфликта: подменяется только
первое чтение ключа; INSERT/UPDATE, unique violation и rollback настоящие.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from io import StringIO
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Numeric, create_engine, event, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.models import (
    CalendarTask, Contact, DomainError, Product, ServiceCase, ServiceEvent,
    WorkflowVersion,
)
from app.domain.permissions import Actor
from app.domain.service_authz import SYSTEM_ACTOR, PermissionDenied, can_view_case
from app.domain.service_cases import (
    TOUR_STAGES, TOUR_TRANSITIONS, advance, archive_product, create_product,
    open_case, publish_version, sign_contract,
)
from test_service_cases import history, run_with_db


ROOT = Path(__file__).resolve().parents[1]
OWNER = Actor("manager", allowed_directions=frozenset({"tours"}))
PEER = Actor("peer", allowed_directions=frozenset({"tours"}))
VISA = Actor("visa_manager", allowed_directions=frozenset({"visa"}))
UNSCOPED = Actor("manager")
SIGNED_AT = datetime(2026, 10, 5, 6, 30, tzinfo=timezone.utc)
CONTRACT_COLUMNS = {
    "contract_reference", "signed_at", "signed_by", "agreed_amount", "currency",
    "amount_unknown_reason", "idempotency_key",
}
PG_DSN = os.environ.get("TEST_POSTGRES_DSN")
requires_pg = pytest.mark.skipif(
    not PG_DSN,
    reason="Нет TEST_POSTGRES_DSN: PostgreSQL migration/race не проверены",
)


async def prepare_contract(session, *, code="contract_tour", direction="tours"):
    # В отличие от prepare() E1-01 здесь не создаём услугу до подписания.
    contact = Contact()
    session.add(contact)
    await session.flush()
    product = await create_product(session, code=code, name="Synthetic product",
                                   direction=direction, by=SYSTEM_ACTOR)
    await publish_version(session, product.id, TOUR_STAGES, TOUR_TRANSITIONS,
                          "system", by=SYSTEM_ACTOR)
    await session.commit()
    return contact.id, product.id


def payload(contact_id, product_id, **changes):
    values = dict(contact_id=contact_id, product_id=product_id,
                  owner_login=OWNER.manager_id, by=OWNER, reference="SYN-001",
                  signed_at=SIGNED_AT, amount=Decimal("1234.56"), currency="KGS",
                  idempotency_key="synthetic-contract-1")
    values.update(changes)
    return values


async def snapshot(session):
    result = {}
    for model in (Contact, Product, WorkflowVersion, ServiceCase, ServiceEvent, CalendarTask):
        result[model.__tablename__] = (await session.execute(
            select(model.__table__).order_by(model.id))).all()
    return result


async def rejected_without_changes(session, values, *, error=DomainError, match=None):
    before = await snapshot(session)
    with pytest.raises(error, match=match) as caught:
        await sign_contract(session, **values)
    assert str(caught.value).strip(), "Отказ должен объяснять причину"
    # Не прячем частичные записи rollback-ом теста: отказ обязан быть атомарным.
    await session.commit()
    assert await snapshot(session) == before, "Отказ оставил услугу/событие в БД"


def test_ac01_replay_after_commit_has_one_contract_case_and_signed_event():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            first = await sign_contract(session, **payload(*ids))
            first_id = first.id
            await session.commit()
        async with sm() as session:
            before = await snapshot(session)
            repeated = await sign_contract(session, **payload(*ids))
            assert repeated.id == first_id
            await session.commit()
            assert await snapshot(session) == before
            assert await session.scalar(select(func.count()).select_from(ServiceCase)) == 1
            events = await history(session, first_id)
            assert [e.event_type for e in events] == ["case_opened", "contract_signed"]
            assert events[-1].actor == OWNER.manager_id
            assert events[-1].payload["amount"] == "1234.56"
    run_with_db(scenario)


def test_ac01_replay_inside_same_uncommitted_transaction_is_also_idempotent():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            first = await sign_contract(session, **payload(*ids))
            before = await snapshot(session)
            repeated = await sign_contract(session, **payload(*ids))
            assert repeated.id == first.id
            await session.commit()
            assert await snapshot(session) == before
    run_with_db(scenario)


def test_ac01_initial_tasks_exist_and_replay_does_not_duplicate_them():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            await sign_contract(session, **payload(*ids))
            await session.commit()
            tasks = (await session.execute(select(CalendarTask.__table__))).all()
            assert tasks, "AC-01: после договора не создано ни одной начальной задачи"
            await sign_contract(session, **payload(*ids))
            await session.commit()
            assert (await session.execute(select(CalendarTask.__table__))).all() == tasks
    run_with_db(scenario)


@pytest.mark.parametrize("changed", ["product", "amount", "contact", "reference", "currency"])
def test_reused_key_with_different_contract_is_rejected(changed):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            other_ids = await prepare_contract(session, code="other_tour")
            values = payload(*ids)
            await sign_contract(session, **values)
            await session.commit()
            changes = {"product": ("product_id", other_ids[1]),
                       "contact": ("contact_id", other_ids[0]),
                       "amount": ("amount", Decimal("999.99")),
                       "reference": ("reference", "SYN-DIFFERENT"),
                       "currency": ("currency", "USD")}
            field, value = changes[changed]
            values[field] = value
            # Возврат старого договора как успеха скрывает неподписанный новый.
            await rejected_without_changes(session, values)
    run_with_db(scenario)


@pytest.mark.parametrize("key", [None, "", "   "], ids=["null", "empty", "spaces"])
def test_absent_key_is_rejected_because_exactly_once_depends_on_it(key):
    """Ключ обязателен: без него два вызова подряд создавали два договора.

    Прежде схема разрешала NULL и операция принимала пустой ключ — то есть
    повторный клик менеджера превращался во вторую услугу с отдельной задачей.
    Колонка остаётся NULL-able для переноса старых данных (E4), но завести договор
    без ключа через операцию нельзя.
    """
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            before = await snapshot(session)
            with pytest.raises(DomainError, match="idempotency key"):
                await sign_contract(session, **payload(*ids, idempotency_key=key))
            await session.commit()
            assert await snapshot(session) == before
    run_with_db(scenario)


@pytest.mark.parametrize("key", ["x" * 129, "x" * 4096], ids=["129-chars", "4096-chars"])
def test_oversized_key_is_domain_error_before_any_write(key):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            await rejected_without_changes(session, payload(*ids, idempotency_key=key))
    run_with_db(scenario)


def test_key_whitespace_normalization_and_128_character_boundary():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(*ids, idempotency_key="x" * 128))
            await session.commit()
            replay = await sign_contract(session, **payload(*ids, idempotency_key=" x" + "x" * 127 + " "))
            assert replay.id == case.id
            assert replay.idempotency_key == "x" * 128
    run_with_db(scenario)


@pytest.mark.parametrize("by", [VISA, UNSCOPED, PEER], ids=["foreign-direction", "revoked", "peer"])
def test_key_does_not_grant_read_access_to_someone_elses_case(by):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(*ids))
            await session.commit()
            assert not can_view_case(by, direction="tours", owner_login=case.owner_login)
            await rejected_without_changes(session, payload(*ids, by=by), error=PermissionDenied)
    run_with_db(scenario)


@pytest.mark.parametrize("by", [VISA, UNSCOPED], ids=["foreign-direction", "no-directions"])
@pytest.mark.parametrize("changes", [
    {}, {"amount": "bad"}, {"amount": "-1"}, {"amount": None},
    {"currency": None}, {"reference": ""}, {"owner_login": ""},
], ids=["valid", "bad-amount", "negative", "missing-amount", "missing-currency",
        "missing-reference", "missing-owner"])
def test_authorization_precedes_payload_validation(by, changes):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            await rejected_without_changes(session, payload(*ids, by=by, **changes),
                                           error=PermissionDenied)
    run_with_db(scenario)


def test_system_actor_is_explicitly_recorded_as_system():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(*ids, by=SYSTEM_ACTOR))
            await session.commit()
            assert case.signed_by == "system"
            assert (await history(session, case.id))[-1].actor == "system"
    run_with_db(scenario)


@pytest.mark.parametrize("login", ["", "   "], ids=["empty", "spaces"])
def test_actor_without_identity_cannot_attest_signature(login):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            by = Actor(login, allowed_directions=frozenset({"tours"}))
            await rejected_without_changes(session, payload(*ids, by=by), error=PermissionDenied)
    run_with_db(scenario)


# Нуля в списке нет: сумма договора 0 отклоняется как опечатка (решение 05.10),
# для этого есть отдельная проверка ниже.
@pytest.mark.parametrize("amount", [Decimal("0.01"), Decimal("0.29"),
                                   Decimal("123456789012.34"), Decimal("999999999999.99")])
def test_money_round_trip_is_decimal_without_lost_cents(amount):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(*ids, amount=amount, currency=" usd "))
            case_id = case.id
            await session.commit()
        async with sm() as session:
            case = await session.get(ServiceCase, case_id)
            assert isinstance(case.agreed_amount, Decimal)
            assert case.agreed_amount == amount
            assert case.currency == "USD"
            assert Decimal((await history(session, case_id))[-1].payload["amount"]) == amount
    run_with_db(scenario)



def test_zero_amount_and_amount_with_unknown_reason_are_rejected():
    """Решения 05.10: нуль в сумме — опечатка; сумма и причина её незнания исключают друг друга."""
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            before = await snapshot(session)
            with pytest.raises(DomainError):
                await sign_contract(session, **payload(*ids, amount=Decimal("0.00")))
            with pytest.raises(DomainError):
                await sign_contract(session, **payload(*ids, amount=Decimal("100.00"),
                                                       amount_unknown_reason="уточняет оператор"))
            await session.commit()
            assert await snapshot(session) == before
    run_with_db(scenario)

def test_amount_column_is_numeric_14_2_not_float():
    column = ServiceCase.__table__.c.agreed_amount
    assert isinstance(column.type, Numeric)
    assert (column.type.precision, column.type.scale, column.type.asdecimal) == (14, 2, True)


@pytest.mark.parametrize("changes", [
    {"amount": "-0.01"}, {"amount": "not-money"}, {"currency": None},
    {"currency": ""}, {"currency": "   "}, {"amount": None},
    {"amount": None, "amount_unknown_reason": "   "},
], ids=["negative", "invalid-number", "currency-null", "currency-empty",
        "currency-spaces", "unknown-without-reason", "unknown-blank-reason"])
def test_invalid_money_is_rejected_without_writes(changes):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            await rejected_without_changes(session, payload(*ids, **changes))
    run_with_db(scenario)


@pytest.mark.parametrize("amount", ["NaN", "sNaN", "Infinity", "-Infinity", "1000000000000.00"])
def test_nonfinite_or_out_of_numeric_range_is_clear_domain_error(amount):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            await rejected_without_changes(session, payload(*ids, amount=amount))
    run_with_db(scenario)


def test_subcent_amount_is_rejected_or_normalized_consistently_with_history():
    # Способ округления — бизнес-решение. Допустим отказ либо единая сумма в
    # результате, БД и аудите; молчаливое расхождение 1.001 / 1.00 недопустимо.
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            before = await snapshot(session)
            try:
                case = await sign_contract(session, **payload(*ids, amount="1.001"))
            except DomainError:
                await session.commit()
                assert await snapshot(session) == before
                return
            returned = case.agreed_amount
            case_id = case.id
            await session.commit()
        async with sm() as session:
            saved = await session.get(ServiceCase, case_id)
            recorded = Decimal((await history(session, case_id))[-1].payload["amount"])
            assert saved.agreed_amount == recorded == returned
    run_with_db(scenario)


def test_unknown_amount_with_reason_remains_null_after_reload():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(
                *ids, amount=None, currency=None, amount_unknown_reason="  Ждём расчёт  "))
            await session.commit()
            await session.refresh(case)
            assert case.agreed_amount is None
            assert case.amount_unknown_reason == "Ждём расчёт"
            signed = (await history(session, case.id))[-1]
            assert signed.payload["amount"] is None
            assert signed.reason == "Ждём расчёт"
    run_with_db(scenario)


@pytest.mark.parametrize("changes", [
    {"reference": ""}, {"reference": "   "}, {"reference": "r" * 129},
    {"currency": 123}, {"amount": None, "amount_unknown_reason": {"reason": "pending"}},
    {"signed_at": "not-a-date"}, {"currency": "TOOLONG"},
    {"amount": None, "amount_unknown_reason": "r" * 256},
], ids=["empty-reference", "spaces-reference", "long-reference", "nontext-currency",
        "nontext-reason", "invalid-signed-at", "long-currency", "long-unknown-reason"])
def test_invalid_contract_fields_do_not_leave_half_open_case(changes):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            await rejected_without_changes(session, payload(*ids, **changes))
    run_with_db(scenario)


def test_signed_by_comes_from_actor_not_requested_owner_and_cannot_be_injected():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            before = await snapshot(session)
            with pytest.raises((TypeError, DomainError)):
                await sign_contract(session, **payload(*ids, signed_by="forged_admin"))
            assert await snapshot(session) == before
            # Чужого владельца теперь нельзя указать вовсе: менеджер подписывает
            # договор только на себя, передача — отдельная операция переназначения.
            with pytest.raises(PermissionDenied):
                await sign_contract(session, **payload(*ids, owner_login="other_manager"))
            assert await snapshot(session) == before
            case = await sign_contract(session, **payload(*ids))
            await session.commit()
            await session.refresh(case)
            assert case.signed_by == OWNER.manager_id
            assert case.signed_at.replace(tzinfo=timezone.utc) == SIGNED_AT
            assert (await history(session, case.id))[-1].actor == OWNER.manager_id
    run_with_db(scenario)


def test_open_or_sent_contract_does_not_claim_signature():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await open_case(session, contact_id=ids[0], product_id=ids[1],
                                   owner_login=OWNER.manager_id, by=OWNER)
            # Отправка представлена только событием: отдельного send API пока нет.
            case.contract_reference = "SYN-SENT-ONLY"
            session.add(ServiceEvent(case_id=case.id, event_type="contract_sent",
                                     actor=OWNER.manager_id, payload={}))
            await session.commit()
            await session.refresh(case)
            assert case.signed_at is None and case.signed_by is None
            assert "contract_signed" not in [e.event_type for e in await history(session, case.id)]
    run_with_db(scenario)


def test_signing_is_rolled_back_with_callers_transaction():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            before = await snapshot(session)
            await sign_contract(session, **payload(*ids))
            await session.rollback()
        async with sm() as session:
            assert await snapshot(session) == before
    run_with_db(scenario)


def test_signed_event_revision_matches_committed_case_revision():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(*ids))
            await session.commit()
            await session.refresh(case)
            signed = (await history(session, case.id))[-1]
            assert signed.payload["revision"] == case.revision
    run_with_db(scenario)


@pytest.mark.parametrize("currency", [None, "", "   "], ids=["null", "empty", "spaces"])
def test_database_rejects_amount_without_real_currency_even_bypassing_domain(currency):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(*ids, amount=None,
                                      currency=None, amount_unknown_reason="Pending quote"))
            await session.commit()
            # Core Connection намеренно обходит запрет ORM bulk writes.
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    connection = await session.connection()
                    await connection.execute(update(ServiceCase.__table__)
                        .where(ServiceCase.id == case.id)
                        .values(agreed_amount=Decimal("10.00"), currency=currency))
    run_with_db(scenario)


def test_unique_index_enforces_keys_but_allows_multiple_nulls():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            # Операция ключ требует, поэтому NULL в колонке создаём не через неё:
            # индекс обязан остаться частичным ради переноса старых данных (E4),
            # где ключа у исторических записей нет.
            first = await sign_contract(session, **payload(*ids, idempotency_key="k-1"))
            second = await sign_contract(session, **payload(*ids, reference="SYN-002",
                                                            idempotency_key="k-2"))
            await session.flush()
            connection0 = await session.connection()
            await connection0.execute(update(ServiceCase.__table__)
                                      .where(ServiceCase.id.in_([first.id, second.id]))
                                      .values(idempotency_key=None))
            await session.commit()
            connection = await session.connection()
            indexes = await connection.run_sync(lambda conn: inspect(conn).get_indexes("service_cases"))
            index = next(i for i in indexes if i["name"] == "uq_service_case_idempotency")
            assert index["unique"]
            assert "IS NOT NULL" in str(index["dialect_options"]["sqlite_where"]).upper()
            await connection.execute(update(ServiceCase.__table__).where(ServiceCase.id == first.id)
                                     .values(idempotency_key="db-only-key"))
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    await connection.execute(update(ServiceCase.__table__).where(ServiceCase.id == second.id)
                                             .values(idempotency_key="db-only-key"))
    run_with_db(scenario)


def stale_lookup_once(monkeypatch, session):
    original = session.scalar
    reads = []

    async def scalar(statement, *args, **kwargs):
        if "service_cases.idempotency_key =" in str(statement):
            reads.append(statement)
            if len(reads) == 1:
                return None
        return await original(statement, *args, **kwargs)

    monkeypatch.setattr(session, "scalar", scalar)
    return reads


def test_stale_lookup_conflict_uses_unique_index_without_duplicate_cases(monkeypatch):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            first = await sign_contract(session, **payload(*ids))
            first_id = first.id
            await session.commit()
        async with sm() as session:
            before = await snapshot(session)
            reads = stale_lookup_once(monkeypatch, session)
            twin = await sign_contract(session, **payload(*ids))
            assert len(reads) == 2, "Должна сработать именно ветка IntegrityError"
            assert twin.id == first_id
            await session.commit()
            assert await snapshot(session) == before
    run_with_db(scenario)


def test_stale_lookup_conflict_does_not_rollback_unrelated_callers_work(monkeypatch):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            await sign_contract(session, **payload(*ids))
            await session.commit()
        async with sm() as session:
            pending = Contact()
            session.add(pending)
            await session.flush()
            pending_id = pending.id
            stale_lookup_once(monkeypatch, session)
            await sign_contract(session, **payload(*ids))
            await session.commit()
        async with sm() as session:
            assert await session.get(Contact, pending_id) is not None, "sign_contract откатил транзакцию вызывающего"
    run_with_db(scenario)


@pytest.mark.parametrize("different_direction", [False, True], ids=["peer", "foreign-direction"])
def test_stale_lookup_conflict_rechecks_access_before_returning_twin(monkeypatch, different_direction):
    async def scenario(sm):
        async with sm() as session:
            foreign_ids = await prepare_contract(session, code="foreign_product",
                                                direction="visa" if different_direction else "tours")
            own_ids = await prepare_contract(session)
            foreign_by = VISA if different_direction else PEER
            await sign_contract(session, **payload(*foreign_ids, by=foreign_by,
                                                  owner_login=foreign_by.manager_id))
            await session.commit()
        async with sm() as session:
            stale_lookup_once(monkeypatch, session)
            await rejected_without_changes(session, payload(*own_ids), error=PermissionDenied)
    run_with_db(scenario)


@pytest.mark.parametrize("stage", ["UNKNOWN", "TOUR-03", " TOUR-02 "])
def test_ac16_bad_transition_does_not_damage_signed_contract(stage):
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(*ids))
            await session.commit()
            before = await snapshot(session)
            with pytest.raises(DomainError) as error:
                await advance(session, case.id, to_stage=stage, by=OWNER)
            assert str(error.value).strip()
            await session.commit()
            assert await snapshot(session) == before
    run_with_db(scenario)


def test_ac16_confirming_booking_requires_number_and_date():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(*ids))
            await advance(session, case.id, to_stage="TOUR-02", by=OWNER)
            await session.commit()
            before = await snapshot(session)
            with pytest.raises(DomainError):
                await advance(session, case.id, to_stage="TOUR-03", by=OWNER)
            await session.commit()
            assert await snapshot(session) == before
    run_with_db(scenario)


def test_ac17_signed_cases_and_replay_keep_old_workflow_after_publication():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            old = await sign_contract(session, **payload(*ids))
            old_id, old_version = old.id, old.workflow_version_id
            new_version = await publish_version(session, ids[1],
                [{"code": "NEW-01", "name": "New start"}, {"code": "NEW-02", "name": "New next"}],
                {"NEW-01": ["NEW-02"]}, "system", by=SYSTEM_ACTOR)
            fresh = await sign_contract(session, **payload(*ids, reference="SYN-002", idempotency_key="new-key"))
            fresh_id, fresh_version = fresh.id, new_version.id
            await session.commit()
        async with sm() as session:
            repeated = await sign_contract(session, **payload(*ids))
            assert (repeated.id, repeated.workflow_version_id) == (old_id, old_version)
            with pytest.raises(DomainError, match="unknown stage"):
                await advance(session, old_id, to_stage="NEW-02", by=OWNER)
            await advance(session, old_id, to_stage="TOUR-02", by=OWNER)
            await advance(session, fresh_id, to_stage="NEW-02", by=OWNER)
            await session.commit()
            assert (await session.get(ServiceCase, old_id)).workflow_version_id == old_version
            assert (await session.get(ServiceCase, fresh_id)).workflow_version_id == fresh_version
            assert (await history(session, old_id))[-1].payload["workflow_version_id"] == old_version
    run_with_db(scenario)


def test_archived_product_rejects_new_contract_but_preserves_existing_replay():
    async def scenario(sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            case = await sign_contract(session, **payload(*ids))
            await archive_product(session, ids[1], by=SYSTEM_ACTOR)
            await session.commit()
            assert (await sign_contract(session, **payload(*ids))).id == case.id
            await rejected_without_changes(session, payload(*ids, idempotency_key="new-key"))
    run_with_db(scenario)


def migration_config(url="sqlite://"):
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    return cfg


def test_migration_revision_chain_has_expected_parent_and_single_head():
    scripts = ScriptDirectory.from_config(migration_config())
    revision = scripts.get_revision("e1_contract_0008")
    assert revision.down_revision == "e1_services_0007"
    # Голова ОДНА — это и проверяем. Имя не закрепляем: следующая миграция (E2-03
    # и дальше) сдвигает голову, и жёсткое имя ломало бы тест на каждом шаге,
    # ничего при этом не защищая. Важна единственность, а не название.
    assert len(scripts.get_heads()) == 1
    # Ревизия договора остаётся в цепочке, ведущей к голове.
    head = scripts.get_heads()[0]
    chain = {rev.revision for rev in scripts.walk_revisions("base", head)}
    assert "e1_contract_0008" in chain


def test_postgresql_migration_emits_seven_additions_index_check_and_reverse(monkeypatch):
    # Компиляция DDL не подменяет применение на сервере: runtime PG ниже.
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    cfg = migration_config("postgresql://")
    cfg.output_buffer = StringIO()
    command.upgrade(cfg, "e1_services_0007:e1_contract_0008", sql=True)
    sql = cfg.output_buffer.getvalue()
    assert sql.count("ALTER TABLE service_cases ADD COLUMN") == 7
    assert "NUMERIC(14, 2)" in sql
    assert "CREATE UNIQUE INDEX uq_service_case_idempotency" in sql
    assert "WHERE idempotency_key IS NOT NULL" in sql
    assert "ADD CONSTRAINT ck_service_case_amount_needs_currency CHECK" in sql
    assert "DROP COLUMN" not in sql
    cfg.output_buffer = StringIO()
    command.downgrade(cfg, "e1_contract_0008:e1_services_0007", sql=True)
    sql = cfg.output_buffer.getvalue()
    assert sql.count("ALTER TABLE service_cases DROP COLUMN") == 7
    assert "DROP INDEX uq_service_case_idempotency" in sql
    assert "DROP CONSTRAINT ck_service_case_amount_needs_currency" in sql


@pytest.mark.parametrize("enforce_fk", [False, True], ids=["legacy-fixture", "foreign-keys-on"])
def test_sqlite_migration_is_additive_preserves_rows_and_is_reversible(tmp_path, monkeypatch, enforce_fk):
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    if enforce_fk:
        # Применяем и к соединениям Alembic, которые создаются внутри env.py.
        from sqlalchemy.engine import Engine

        def enable_foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

        event.listen(Engine, "connect", enable_foreign_keys)
    url = f"sqlite:///{(tmp_path / 'e1-contract.db').as_posix()}"
    cfg = migration_config(url)
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "e1_services_0007")
        before_tables = set(inspect(engine).get_table_names())
        before_columns = {c["name"] for c in inspect(engine).get_columns("service_cases")}
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO contacts (id) VALUES (500)"))
            conn.execute(text("INSERT INTO products (id, code, name, direction, active, created_at, updated_at) "
                              "VALUES (500, 'synthetic', 'Synthetic', 'tours', true, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            conn.execute(text("INSERT INTO workflow_versions (id, product_id, version, stages, transitions, "
                              "published_at, published_by, created_at) VALUES "
                              "(500, 500, 1, '[]', '{}', CURRENT_TIMESTAMP, 'system', CURRENT_TIMESTAMP)"))
            conn.execute(text("INSERT INTO service_cases (id, contact_id, product_id, workflow_version_id, "
                              "owner_login, stage, created_at, updated_at) VALUES "
                              "(500, 500, 500, 500, 'manager', 'LEGACY', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            legacy = conn.execute(text("SELECT * FROM service_cases")).all()
            conn.execute(text("INSERT INTO service_events (id, case_id, event_type, actor, "
                              "occurred_at, recorded_at, payload) VALUES "
                              "(500, 500, 'case_opened', 'manager', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '{}')"))
        command.upgrade(cfg, "e1_contract_0008")
        assert set(inspect(engine).get_table_names()) == before_tables
        columns = {c["name"]: c for c in inspect(engine).get_columns("service_cases")}
        assert set(columns) - before_columns == CONTRACT_COLUMNS
        assert all(columns[c]["nullable"] for c in CONTRACT_COLUMNS)
        indexes = inspect(engine).get_indexes("service_cases")
        index = next(i for i in indexes if i["name"] == "uq_service_case_idempotency")
        assert index["unique"]
        assert "IS NOT NULL" in str(index["dialect_options"]["sqlite_where"]).upper()
        assert "ck_service_case_amount_needs_currency" in {
            c["name"] for c in inspect(engine).get_check_constraints("service_cases")}
        with engine.begin() as conn:
            assert conn.scalar(text("SELECT signed_at FROM service_cases WHERE id=500")) is None
            with pytest.raises(IntegrityError):
                with conn.begin_nested():
                    conn.execute(text("UPDATE service_cases SET agreed_amount=10, currency=NULL WHERE id=500"))
            # Это схема после настоящего upgrade, а не metadata.create_all().
            conn.execute(text("INSERT INTO service_cases (id, contact_id, product_id, workflow_version_id, "
                              "owner_login, stage, created_at, updated_at) VALUES "
                              "(501, 500, 500, 500, 'manager', 'LEGACY', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"))
            conn.execute(text("UPDATE service_cases SET idempotency_key='migration-key' WHERE id=500"))
            with pytest.raises(IntegrityError):
                with conn.begin_nested():
                    conn.execute(text("UPDATE service_cases SET idempotency_key='migration-key' WHERE id=501"))
            conn.execute(text("DELETE FROM service_cases WHERE id=501"))
        command.downgrade(cfg, "e1_services_0007")
        assert {c["name"] for c in inspect(engine).get_columns("service_cases")} == before_columns
        with engine.connect() as conn:
            assert conn.execute(text("SELECT * FROM service_cases")).all() == legacy
        command.upgrade(cfg, "e1_contract_0008")
        command.downgrade(cfg, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
        command.upgrade(cfg, "e1_contract_0008")
    finally:
        engine.dispose()
        if enforce_fk:
            event.remove(Engine, "connect", enable_foreign_keys)


async def with_postgres_schema(scenario):
    """Только явно заданная тестовая БД, только новая случайная схема."""
    dsn = PG_DSN.replace("postgresql://", "postgresql+asyncpg://", 1)
    if dsn.startswith("postgres://"):
        dsn = "postgresql+asyncpg://" + dsn[len("postgres://"):]
    schema = "test_e1_contract_" + uuid4().hex
    engine = create_async_engine(dsn, connect_args={"server_settings": {"search_path": schema}})
    created = False
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True

        def upgrade(conn):
            scripts = ScriptDirectory.from_config(migration_config())
            # Runtime scenarios call today's service and ORM (including the
            # calendar-task links introduced after the contract migration).
            # Apply the current schema; the focused 0008 downgrade/upgrade
            # assertions below still verify that revision's own contract.
            revisions = list(scripts.iterate_revisions("head", "base"))
            with Operations.context(MigrationContext.configure(conn)):
                for revision in reversed(revisions):
                    revision.module.upgrade()

        async with engine.begin() as conn:
            await conn.run_sync(upgrade)
        await scenario(engine, async_sessionmaker(engine, expire_on_commit=False))
    finally:
        try:
            if created:
                async with engine.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            await engine.dispose()


@requires_pg
@pytest.mark.parametrize("collision", ["same-request", "other-contact", "foreign-direction"])
def test_postgresql_parallel_sessions_never_duplicate_or_return_someone_elses_case(collision, monkeypatch):
    async def scenario(engine, sm):
        async with sm() as session:
            first_ids = await prepare_contract(session)
            second_ids = first_ids
            if collision != "same-request":
                second_ids = await prepare_contract(session, code="second_product",
                    direction="visa" if collision == "foreign-direction" else "tours")
        both_read = asyncio.Event()
        read_count = 0

        async def worker(ids, by):
            nonlocal read_count
            async with sm() as session:
                original = session.scalar
                first_read = True

                async def barrier(statement, *args, **kwargs):
                    nonlocal read_count, first_read
                    result = await original(statement, *args, **kwargs)
                    if first_read and "service_cases.idempotency_key =" in str(statement):
                        first_read = False
                        assert result is None
                        read_count += 1
                        if read_count == 2:
                            both_read.set()
                        await asyncio.wait_for(both_read.wait(), 10)
                    return result

                monkeypatch.setattr(session, "scalar", barrier)
                try:
                    case = await sign_contract(session, **payload(*ids, by=by, owner_login=by.manager_id))
                    result = (case.id, case.contact_id, case.product_id, case.owner_login)
                    await session.commit()
                    return result
                except DomainError as exc:
                    await session.rollback()
                    return exc

        second_actor = VISA if collision == "foreign-direction" else OWNER
        results = await asyncio.wait_for(asyncio.gather(
            worker(first_ids, OWNER), worker(second_ids, second_actor)), 20)
        assert read_count == 2
        async with sm() as session:
            assert await session.scalar(select(func.count()).select_from(ServiceCase)) == 1
            assert await session.scalar(select(func.count()).select_from(ServiceEvent).where(
                ServiceEvent.event_type == "contract_signed")) == 1
        if collision == "same-request":
            assert not any(isinstance(result, Exception) for result in results)
            assert results[0] == results[1]
        else:
            for result, ids, by in zip(results, (first_ids, second_ids), (OWNER, second_actor)):
                if not isinstance(result, DomainError):
                    assert result[1:] == (*ids, by.manager_id), "Гонка вернула чужой договор"
            assert sum(isinstance(result, DomainError) for result in results) == 1
    asyncio.run(with_postgres_schema(scenario))


@requires_pg
def test_postgresql_applied_migration_constraints_and_roundtrip():
    async def scenario(engine, sm):
        async with sm() as session:
            ids = await prepare_contract(session)
            first = await sign_contract(session, **payload(*ids, amount=Decimal("999999999999.99")))
            second = await sign_contract(session, **payload(*ids, idempotency_key="second-key"))
            await session.commit()
            await session.refresh(first)
            assert first.agreed_amount == Decimal("999999999999.99")
            connection = await session.connection()
            indexes = await connection.run_sync(lambda conn: inspect(conn).get_indexes("service_cases"))
            index = next(i for i in indexes if i["name"] == "uq_service_case_idempotency")
            assert index["unique"]
            assert "IS NOT NULL" in str(index["dialect_options"]["postgresql_where"]).upper()
            for values in ({"idempotency_key": first.idempotency_key}, {"currency": None}):
                with pytest.raises(IntegrityError):
                    # This intentionally tests DB constraints through the
                    # connection, bypassing the separately tested ORM guard.
                    # Own its savepoint on that same connection: a session
                    # savepoint starts lazily and would not enclose this SQL.
                    async with connection.begin_nested():
                        await connection.execute(update(ServiceCase.__table__)
                            .where(ServiceCase.id == second.id).values(**values))
            await session.commit()
        revision = ScriptDirectory.from_config(migration_config()).get_revision("e1_contract_0008")

        def roundtrip(conn):
            with Operations.context(MigrationContext.configure(conn)):
                revision.module.downgrade()
                assert CONTRACT_COLUMNS.isdisjoint({c["name"] for c in inspect(conn).get_columns("service_cases")})
                assert conn.scalar(text("SELECT count(*) FROM service_cases")) == 2
                revision.module.upgrade()
                assert CONTRACT_COLUMNS <= {c["name"] for c in inspect(conn).get_columns("service_cases")}
        async with engine.begin() as conn:
            await conn.run_sync(roundtrip)
    asyncio.run(with_postgres_schema(scenario))
