"""E1-02 / AC-33: независимая проверка прав на синтетических данных.

Цель — локальные негативные тесты; приложение не исправляем. Ожидания заданы
приёмкой, поэтому найденные нарушения остаются FAIL, без xfail. SQLite, внешние
ключи и транзакции берём из E1-01. Это проверка доменного сервера, не HTTP,
продуктового аудита или ещё не реализованной денежной операции.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, update

from app.domain.models import DomainError, Product, ServiceCase, ServiceEvent, WorkflowVersion
from app.domain.permissions import Actor
from app.domain.service_authz import (
    SYSTEM_ACTOR, PermissionDenied, can_advance_case, can_correct_money,
    can_manage_products, can_open_case, can_view_case,
)
from app.domain.service_cases import (
    TOUR_STAGES, TOUR_TRANSITIONS, advance, archive_product, create_product,
    open_case, publish_version,
)
from test_service_cases import history, prepare, run_with_db


VISA = Actor(manager_id="medina", allowed_directions=frozenset({"visa"}))
OWNER = Actor(manager_id="manager", allowed_directions=frozenset({"tours"}))
PEER = Actor(manager_id="other_manager", allowed_directions=frozenset({"tours"}))
ADMIN = Actor(manager_id="admin", is_full_admin=True)
REVOKED_OWNER = Actor(manager_id="manager")
MISSING_ID = 987654321


async def snapshot(session):
    """Содержимое таблиц, включая всю историю: одного count недостаточно."""
    result = {}
    for model in (Product, WorkflowVersion, ServiceCase, ServiceEvent):
        result[model.__tablename__] = (await session.execute(
            select(model.__table__).order_by(model.id)
        )).all()
    return result


async def denied_without_changes(session, operation):
    before = await snapshot(session)
    with pytest.raises(PermissionDenied) as caught:
        await operation()
    assert await snapshot(session) == before
    # Не маскируем побочные записи rollback-ом фикстуры: даже commit после отказа
    # не должен изменить stage, revision, владельца, продукты или историю.
    await session.commit()
    assert await snapshot(session) == before
    return caught.value


def assert_redacted(error, *sensitive_values):
    for value in sensitive_values:
        if value is not None and str(value).strip():
            assert str(value).strip().lower() not in str(error).lower()
            assert str(value).strip().lower() not in repr(error).lower()


def test_permission_denied_is_a_distinct_domain_error():
    assert PermissionDenied is not DomainError
    assert issubclass(PermissionDenied, DomainError)
    with pytest.raises(DomainError) as caught:
        raise PermissionDenied("denied")
    assert type(caught.value) is PermissionDenied
    assert not isinstance(DomainError("invalid data"), PermissionDenied)


@pytest.mark.parametrize("by,allowed", [
    pytest.param(VISA, False, id="visa-manager"),
    pytest.param(OWNER, False, id="tours-manager"),
    pytest.param(Actor("tickets", allowed_directions=frozenset({"tickets"})), False,
                 id="tickets-manager"),
    pytest.param(Actor("all", allowed_directions=frozenset({"visa", "tours", "tickets"})),
                 False, id="all-directions-not-admin"),
    pytest.param(REVOKED_OWNER, False, id="no-directions"),
    pytest.param(Actor("admin"), False, id="admin-login-is-not-a-role"),
    pytest.param(Actor("system"), False, id="system-login-is-not-a-role"),
    pytest.param(ADMIN, True, id="full-admin"),
    pytest.param(SYSTEM_ACTOR, True, id="explicit-system-is-full-admin"),
])
def test_money_and_product_administration_require_full_admin(by, allowed):
    assert can_correct_money(by) is allowed
    assert can_manage_products(by) is allowed


@pytest.mark.parametrize("by,owner_login,expected", [
    pytest.param(OWNER, "manager", (True, True, True), id="owner"),
    pytest.param(PEER, "manager", (False, True, False), id="peer"),
    pytest.param(VISA, "medina", (False, False, False), id="owner-wrong-direction"),
    pytest.param(REVOKED_OWNER, "manager", (False, False, False), id="revoked-direction"),
    pytest.param(ADMIN, "manager", (True, True, False), id="admin-not-owner"),
    pytest.param(ADMIN, "admin", (True, True, True), id="admin-is-owner"),
    pytest.param(SYSTEM_ACTOR, "manager", (True, True, False), id="system-not-owner"),
    pytest.param(OWNER, "", (False, True, False), id="empty-owner"),
    pytest.param(OWNER, None, (False, True, False), id="null-owner"),
])
def test_case_rules_require_scope_and_ownership(by, owner_login, expected):
    assert (
        can_view_case(by, direction="tours", owner_login=owner_login),
        can_open_case(by, direction="tours"),
        can_advance_case(by, direction="tours", owner_login=owner_login),
    ) == expected


@pytest.mark.parametrize("by", [OWNER, REVOKED_OWNER], ids=["scoped", "no-directions"])
@pytest.mark.parametrize("action", ["open", "view", "advance"])
def test_unknown_direction_must_fail_closed(by, action):
    # Отсутствие направления не доказывает принадлежность к разрешённой команде.
    if action == "open":
        allowed = can_open_case(by, direction=None)
    else:
        rule = can_view_case if action == "view" else can_advance_case
        allowed = rule(by, direction=None, owner_login="manager")
    assert allowed is False


@pytest.mark.parametrize("owner_login", [None, "", "   "], ids=["null", "empty", "spaces"])
def test_empty_actor_cannot_own_an_unassigned_case(owner_login):
    by = Actor(manager_id="", allowed_directions=frozenset({"tours"}))
    assert can_advance_case(by, direction="tours", owner_login=owner_login) is False
    assert can_view_case(by, direction="tours", owner_login=owner_login) is False


@pytest.mark.parametrize("by", [VISA, REVOKED_OWNER], ids=["foreign-direction", "no-directions"])
@pytest.mark.parametrize("archived", [False, True], ids=["active", "archived"])
def test_open_foreign_product_is_denied_without_case_or_event(by, archived):
    async def scenario(sm):
        async with sm() as session:
            contact, product, case = await prepare(session)
            if archived:
                await archive_product(session, product.id, by=SYSTEM_ACTOR)
            error = await denied_without_changes(session, lambda: open_case(
                session, contact_id=contact.id, product_id=product.id,
                owner_login=by.manager_id, by=by,
            ))
            assert_redacted(error, by.manager_id, contact.id, product.id, case.id)
    run_with_db(scenario)


@pytest.mark.parametrize("by", [
    pytest.param(PEER, id="peer-in-same-direction"),
    pytest.param(ADMIN, id="admin-cannot-act-for-owner"),
    pytest.param(SYSTEM_ACTOR, id="system-cannot-act-for-owner"),
    pytest.param(Actor("manager", allowed_directions=frozenset({"visa"})),
                 id="owner-in-wrong-direction"),
    pytest.param(REVOKED_OWNER, id="owner-with-revoked-directions"),
    pytest.param(Actor("Other_Manager", allowed_directions=frozenset({"tours"})),
                 id="foreign-actor-mixed-case"),
    pytest.param(Actor(" other_manager ", allowed_directions=frozenset({"tours"})),
                 id="foreign-actor-spaces"),
])
@pytest.mark.parametrize("archived", [False, True], ids=["active", "archived"])
def test_advance_foreign_case_changes_neither_stage_revision_nor_history(by, archived):
    async def scenario(sm):
        async with sm() as session:
            contact, product, case = await prepare(session)
            if archived:
                await archive_product(session, product.id, by=SYSTEM_ACTOR)
            error = await denied_without_changes(session, lambda: advance(
                session, case.id, to_stage="TOUR-02",
                # Подмена автора события на настоящего владельца не даёт прав.
                actor=case.owner_login, by=by, expected_revision=case.revision,
            ))
            assert_redacted(error, by.manager_id, case.owner_login,
                            case.id, product.id, contact.id)
    run_with_db(scenario)


@pytest.mark.parametrize("owner_login", ["", "   "], ids=["empty", "spaces"])
@pytest.mark.parametrize("by", [
    pytest.param(OWNER, id="manager"),
    pytest.param(ADMIN, id="admin"),
    pytest.param(Actor("", allowed_directions=frozenset({"tours"})), id="empty-identity"),
])
def test_unassigned_case_cannot_be_advanced(owner_login, by):
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            # Логин с пробелами и в другом регистре попадает в базу только мимо
            # доменного слоя — так и готовим: Core-соединением, в обход ORM-защиты.
            conn = await session.connection()
            await conn.execute(update(ServiceCase)
                               .where(ServiceCase.id == case.id)
                               .values(owner_login=owner_login))
            await session.refresh(case)
            await session.flush()
            await denied_without_changes(session, lambda: advance(
                session, case.id, to_stage="TOUR-02", actor="synthetic_event_author", by=by,
            ))
    run_with_db(scenario)


@pytest.mark.parametrize("owner_login", ["manager", "Manager", "  MANAGER  "])
@pytest.mark.parametrize("archived", [False, True], ids=["active", "archived"])
def test_owner_can_advance_with_normalized_stored_login(owner_login, archived):
    async def scenario(sm):
        async with sm() as session:
            _, product, case = await prepare(session)
            # Логин с пробелами и в другом регистре попадает в базу только мимо
            # доменного слоя — так и готовим: Core-соединением, в обход ORM-защиты.
            conn = await session.connection()
            await conn.execute(update(ServiceCase)
                               .where(ServiceCase.id == case.id)
                               .values(owner_login=owner_login))
            await session.refresh(case)
            await session.flush()
            if archived:
                await archive_product(session, product.id, by=SYSTEM_ACTOR)
            previous_revision = case.revision
            assert can_view_case(OWNER, direction="tours", owner_login=owner_login)
            await advance(session, case.id, to_stage="TOUR-02", actor="manager",
                          by=OWNER, expected_revision=previous_revision)
            await session.commit()
        async with sm() as session:
            saved = await session.get(ServiceCase, case.id)
            assert (saved.stage, saved.revision) == ("TOUR-02", previous_revision + 1)
            events = await history(session, case.id)
            assert len(events) == 2
            assert (events[-1].event_type, events[-1].actor,
                    events[-1].from_stage, events[-1].to_stage) == (
                "stage_changed", "manager", "TOUR-01", "TOUR-02",
            )
            assert events[-1].payload["revision"] == saved.revision
    run_with_db(scenario)


@pytest.mark.parametrize("operation", ["create", "publish", "archive"])
@pytest.mark.parametrize("garbage", [False, True], ids=["valid-data", "garbage-data"])
def test_manager_cannot_manage_products_even_with_invalid_data(operation, garbage):
    async def scenario(sm):
        async with sm() as session:
            _, product, _ = await prepare(session)
            product_id = MISSING_ID if garbage else product.id
            by = VISA if operation == "create" else OWNER

            async def attempt():
                if operation == "create":
                    return await create_product(
                        session, code="" if garbage else "authz_visa",
                        name="" if garbage else "Synthetic visa",
                        direction=None if garbage else "visa", by=by,
                    )
                if operation == "publish":
                    return await publish_version(
                        session, product_id, [] if garbage else TOUR_STAGES,
                        None if garbage else TOUR_TRANSITIONS,
                        "" if garbage else by.manager_id, by=by,
                    )
                return await archive_product(session, product_id, by=by)

            error = await denied_without_changes(session, attempt)
            assert_redacted(error, by.manager_id, product_id, "authz_visa")
    run_with_db(scenario)


def test_full_admin_can_create_publish_and_archive_product():
    async def scenario(sm):
        async with sm() as session:
            product = await create_product(session, code="authz_visa", name="Synthetic visa",
                                           direction="visa", by=ADMIN)
            version = await publish_version(session, product.id,
                                            [{"code": "START", "name": "Start"}],
                                            {"START": []}, "admin", by=ADMIN)
            assert product.active is True
            assert product.current_version_id == version.id
            assert version.published_at is not None
            await archive_product(session, product.id, by=ADMIN)
            await session.commit()
        async with sm() as session:
            saved = await session.get(Product, product.id)
            published = await session.get(WorkflowVersion, version.id)
            assert saved.active is False
            assert saved.current_version_id == published.id
            assert (published.product_id, published.published_by) == (saved.id, "admin")
            assert published.published_at is not None
    run_with_db(scenario)


@pytest.mark.parametrize("owner_login", ["", "   ", None, "x" * 65],
                         ids=["empty", "spaces", "null", "too-long"])
def test_open_checks_foreign_direction_before_owner_validation(owner_login):
    async def scenario(sm):
        async with sm() as session:
            contact, product, _ = await prepare(session)
            await denied_without_changes(session, lambda: open_case(
                session, contact_id=contact.id, product_id=product.id,
                owner_login=owner_login, by=VISA,
            ))
    run_with_db(scenario)


@pytest.mark.parametrize("field,value", [
    pytest.param("actor", "", id="empty-event-actor"),
    pytest.param("actor", None, id="null-event-actor"),
    pytest.param("to_stage", "", id="empty-stage"),
    pytest.param("to_stage", " TOUR-02 ", id="stage-whitespace"),
    pytest.param("to_stage", None, id="null-stage"),
    pytest.param("reason", {"private": "synthetic"}, id="invalid-reason"),
    pytest.param("to_stage", "UNDECLARED", id="unknown-stage"),
    pytest.param("to_stage", "TOUR-07", id="forbidden-transition"),
    pytest.param("expected_revision", -1, id="wrong-revision"),
])
def test_advance_checks_ownership_before_validating_payload(field, value):
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            payload = {"to_stage": "TOUR-02", "actor": "other_manager", "reason": "",
                       "expected_revision": case.revision}
            payload[field] = value
            await denied_without_changes(session, lambda: advance(
                session, case.id, by=PEER, **payload,
            ))
    run_with_db(scenario)


@pytest.mark.parametrize("invalid_reference", ["contact", "request", "unpublished-workflow"])
def test_foreign_direction_is_denied_before_related_data_checks(invalid_reference):
    async def scenario(sm):
        async with sm() as session:
            contact, product, _ = await prepare(session)
            if invalid_reference == "unpublished-workflow":
                product = await create_product(session, code="unpublished_tour", name="Draft",
                                               direction="tours", by=SYSTEM_ACTOR)
            await denied_without_changes(session, lambda: open_case(
                session, contact_id=MISSING_ID if invalid_reference == "contact" else contact.id,
                product_id=product.id, owner_login="medina", by=VISA,
                request_id=MISSING_ID if invalid_reference == "request" else None,
            ))
    run_with_db(scenario)


@pytest.mark.parametrize("operation", ["open", "advance"])
def test_missing_object_does_not_disclose_existence_or_id_to_unscoped_actor(operation):
    async def scenario(sm):
        async with sm() as session:
            contact, _, _ = await prepare(session)

            async def attempt():
                if operation == "open":
                    return await open_case(session, contact_id=contact.id, product_id=MISSING_ID,
                                           owner_login="manager", by=REVOKED_OWNER)
                return await advance(session, MISSING_ID, to_stage="TOUR-02",
                                     actor="manager", by=REVOKED_OWNER)

            error = await denied_without_changes(session, attempt)
            assert_redacted(error, REVOKED_OWNER.manager_id, MISSING_ID, contact.id)
    run_with_db(scenario)


@pytest.mark.parametrize("by", [OWNER, REVOKED_OWNER], ids=["owner", "owner-no-directions"])
def test_missing_product_lookup_must_not_bypass_direction_check(monkeypatch, by):
    async def scenario(sm):
        async with sm() as session:
            _, product, case = await prepare(session)
            original_get = session.get
            missing_lookups = []

            async def missing_product(entity, ident, **kwargs):
                if entity is Product and ident == product.id:
                    missing_lookups.append(ident)
                    return None
                return await original_get(entity, ident, **kwargs)

            # FK не допускает настоящую сироту. Инъекция только результата чтения
            # проверяет защитную ветку `product else None`, не отключая ограничения
            # БД и не подменяя сами права или операции записи.
            monkeypatch.setattr(session, "get", missing_product)
            await denied_without_changes(session, lambda: advance(
                session, case.id, to_stage="TOUR-02", actor="manager", by=by,
            ))
            assert missing_lookups == [product.id]
    run_with_db(scenario)
