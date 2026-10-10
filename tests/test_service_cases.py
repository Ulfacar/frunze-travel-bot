"""E1-01 проверяется на синтетике: SQLite с внешними ключами и настоящими транзакциями."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, delete, event, func, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.domain.models import (
    DIRECTIONS, Contact, DomainBase, DomainError, Product, Request, ServiceCase,
    ServiceEvent, WorkflowVersion,
)
from app.domain.permissions import Actor
from app.domain.service_authz import SYSTEM_ACTOR
from app.domain.service_cases import (
    INITIAL_PRODUCTS, TOUR_STAGES, TOUR_TRANSITIONS, active_products, advance,
    archive_product, cases_for_contact, create_product, open_case, publish_version, seed_products,
)


# E1-02: операции теперь требуют актора. Тесты E1-01 проверяют МЕХАНИКУ, поэтому
# берут владельца услуги или системного актора — права проверяются отдельно
# в tests/test_service_authz.py.
OWNER = Actor(manager_id="manager", allowed_directions=frozenset({"tours", "visa", "tickets"}))
OWNER_M = Actor(manager_id="m", allowed_directions=frozenset({"tours", "visa", "tickets"}))


def run_with_db(scenario):
    async def main():
        engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)

        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite(connection, record):
            # Legacy-режим sqlite3 иначе фиксирует внешний SAVEPOINT до commit вызывающего кода.
            connection.isolation_level = None
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        @event.listens_for(engine.sync_engine, "begin")
        def begin(connection):
            connection.exec_driver_sql("BEGIN")

        try:
            async with engine.begin() as connection:
                await connection.run_sync(DomainBase.metadata.create_all)
            await scenario(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    asyncio.run(main())


async def prepare(session):
    contact = Contact()
    session.add(contact)
    await session.flush()
    products = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
    case = await open_case(session, contact_id=contact.id, product_id=products[0].id,
                           owner_login="manager", by=OWNER)
    return contact, products[0], case


async def history(session, case_id):
    return list((await session.scalars(select(ServiceEvent).where(
        ServiceEvent.case_id == case_id).order_by(ServiceEvent.id))).all())


@pytest.mark.parametrize("target, message", [
    ("UNKNOWN", "unknown stage"),          # этапа нет в версии
    ("TOUR-03", "not allowed"),            # этап есть, но переход не разрешён
    ("", "must contain"),                  # пустая строка
    ("   ", "surrounding whitespace"),    # одни пробелы: проверка на пробелы по краям
                                          # срабатывает раньше проверки на пустоту
    (" TOUR-02 ", "surrounding whitespace"),  # правильный код, но с пробелами:
                                              # коды публикуются без них, значит это
                                              # опечатка вызывающего, а не синоним
    ("TOUR-01", "not allowed"),            # переход в самого себя
])
def test_ac16_invalid_transition_changes_neither_case_nor_history(target, message):
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            before = (case.stage, case.revision, case.updated_at)
            with pytest.raises(DomainError, match=message):
                await advance(session, case.id, to_stage=target, actor="manager", by=OWNER)
            await session.refresh(case)
            assert (case.stage, case.revision) == before[:2]
            assert len(await history(session, case.id)) == 1
            await session.commit()
    run_with_db(scenario)


@pytest.mark.parametrize("field,value", [
    ("stages", [{"code": "REPLACED", "name": "Другой процесс"}]),
    ("transitions", {}),
    ("published_at", None),
    ("published_by", "other"),
    ("version", 99),
])
def test_ac17_published_version_cannot_be_rewritten_even_after_reload(field, value):
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            version_id = case.workflow_version_id
            await session.commit()
        async with sm() as session:
            version = await session.get(WorkflowVersion, version_id)
            with pytest.raises(DomainError, match="immutable"):
                setattr(version, field, value)
            assert version.stages == TOUR_STAGES
            assert version.transitions == TOUR_TRANSITIONS
    run_with_db(scenario)


@pytest.mark.parametrize("mutation", [
    lambda version: version.stages.append({"code": "X", "name": "X"}),
    lambda version: version.stages[0].update(name="Изменено"),
    lambda version: version.transitions["TOUR-01"].append("TOUR-07"),
    lambda version: version.transitions.clear(),
])
def test_ac17_nested_json_mutations_are_rejected(mutation):
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            await session.commit()
        async with sm() as session:
            version = await session.get(WorkflowVersion, case.workflow_version_id)
            with pytest.raises(DomainError, match="immutable"):
                mutation(version)
            await session.flush()
            assert version.stages == TOUR_STAGES
            assert version.transitions == TOUR_TRANSITIONS
    run_with_db(scenario)


def test_ac17_new_version_does_not_migrate_existing_case_and_copies_inputs():
    async def scenario(sm):
        async with sm() as session:
            contact, product, first = await prepare(session)
            old_id = first.workflow_version_id
            stages = [{"code": "NEW-01", "name": "Новый договор"},
                      {"code": "NEW-02", "name": "Новая бронь"}]
            transitions = {"NEW-01": ["NEW-02"]}
            second_version = await publish_version(session, product.id, stages, transitions, "admin", by=SYSTEM_ACTOR)
            stages[0]["name"] = "Мутация входного словаря"
            transitions["NEW-01"].clear()
            assert second_version.version == 2
            second = await open_case(session, contact_id=contact.id, product_id=product.id,
                                     owner_login="manager", by=OWNER)
            await advance(session, first.id, to_stage="TOUR-02", actor="manager", by=OWNER)
            await advance(session, second.id, to_stage="NEW-02", actor="manager", by=OWNER)
            assert first.workflow_version_id == old_id
            assert second.workflow_version_id == second_version.id
            assert second_version.stages[0]["name"] == "Новый договор"
            await session.commit()
    run_with_db(scenario)


def test_repeat_publication_of_same_version_is_rejected():
    async def scenario(sm):
        async with sm() as session:
            _, product, case = await prepare(session)
            with pytest.raises(DomainError, match="already published"):
                await publish_version(session, product.id, TOUR_STAGES, TOUR_TRANSITIONS, "admin",
                                      version_id=case.workflow_version_id, by=SYSTEM_ACTOR)
            assert await session.scalar(select(func.count()).select_from(WorkflowVersion)) == 1
            assert product.current_version_id == case.workflow_version_id
    run_with_db(scenario)


def test_three_products_on_one_contact_are_independent_without_requests():
    async def scenario(sm):
        async with sm() as session:
            contact, _, tour = await prepare(session)
            cases = [tour]
            for code in ("air_ticket", "visa_usa"):
                product = await session.scalar(select(Product).where(Product.code == code))
                await publish_version(session, product.id,
                                      [{"code": "START", "name": "Старт"},
                                       {"code": "DONE", "name": "Готово"}],
                                      {"START": ["DONE"]}, "admin", by=SYSTEM_ACTOR)
                cases.append(await open_case(session, contact_id=contact.id, product_id=product.id,
                                              owner_login="manager", by=OWNER))
            await advance(session, tour.id, to_stage="TOUR-02", actor="manager", by=OWNER)
            found = await cases_for_contact(session, contact.id)
            assert [case.id for case in found] == [case.id for case in cases]
            assert [(case.stage, case.revision) for case in found] == [
                ("TOUR-02", 2), ("START", 1), ("START", 1)]
            assert all(case.request_id is None for case in found)
            assert await session.scalar(select(func.count()).select_from(Request)) == 0
            assert await cases_for_contact(session, contact.id + 1) == []
    run_with_db(scenario)


def test_archiving_hides_product_but_keeps_existing_cases_usable():
    async def scenario(sm):
        async with sm() as session:
            contact, product, case = await prepare(session)
            await archive_product(session, product.id, by=SYSTEM_ACTOR)
            assert product.id not in {row.id for row in await active_products(session)}
            await advance(session, case.id, to_stage="TOUR-02", actor="manager", by=OWNER)
            with pytest.raises(DomainError, match="archived"):
                await open_case(session, contact_id=contact.id, product_id=product.id,
                                owner_login="manager", by=OWNER)
            await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
            assert not product.active
            assert len(await history(session, case.id)) == 2
    run_with_db(scenario)


def test_stale_revision_does_not_change_stage_or_write_event():
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            await advance(session, case.id, to_stage="TOUR-02", actor="manager", expected_revision=1, by=OWNER)
            with pytest.raises(DomainError, match="revision conflict"):
                await advance(session, case.id, to_stage="TOUR-03", actor="manager", expected_revision=1, by=OWNER)
            assert (case.stage, case.revision) == ("TOUR-02", 2)
            assert len(await history(session, case.id)) == 2
    run_with_db(scenario)


def test_history_keeps_actor_reason_and_every_successful_transition():
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            for target in ("TOUR-02", "TOUR-01", "TOUR-02", "TOUR-03",
                           "TOUR-04", "TOUR-05", "TOUR-06", "TOUR-07"):
                # «Бронь подтверждена» требует номер и дату — без них сервер
                # отказывает (FLOW-03), и это проверяется отдельным тестом.
                facts = ({"booking_reference": "OP-88-1734", "confirmed_at": "2026-10-06"}
                         if target == "TOUR-03" else None)
                await advance(session, case.id, to_stage=target, facts=facts,
                              reason="Бронь отклонена" if target == "TOUR-01" else "", by=OWNER)
            events = await history(session, case.id)
            assert [item.payload["revision"] for item in events] == list(range(1, 10))
            assert events[0].event_type == "case_opened"
            assert events[0].from_stage is None and events[0].to_stage == "TOUR-01"
            assert events[0].actor == "manager"
            assert all(item.event_type == "stage_changed" for item in events[1:])
            # Автор события теперь выводится из действующего менеджера, а не из
            # параметра: подписать историю чужим именем больше нельзя.
            assert events[2].actor == "manager"
            assert events[2].from_stage == "TOUR-02" and events[2].to_stage == "TOUR-01"
            assert events[2].reason == "Бронь отклонена"
            assert all(item.occurred_at is not None and item.recorded_at is not None for item in events)
    run_with_db(scenario)


@pytest.mark.parametrize("action", ["replace", "nested", "delete", "bulk_update", "bulk_delete"])
def test_service_events_are_append_only(action):
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            await session.commit()
        async with sm() as session:
            entry = (await history(session, case.id))[0]
            with pytest.raises(DomainError):
                if action == "replace":
                    entry.actor = "forged"
                elif action == "nested":
                    entry.payload["revision"] = 999
                elif action == "delete":
                    await session.delete(entry)
                    await session.flush()
                elif action == "bulk_update":
                    await session.execute(update(ServiceEvent).values(actor="forged"))
                else:
                    await session.execute(delete(ServiceEvent))
            await session.rollback()
        async with sm() as session:
            events = await history(session, case.id)
            assert len(events) == 1 and events[0].actor == "manager"
            assert events[0].payload["revision"] == 1
    run_with_db(scenario)


def test_service_case_revision_also_increases_for_non_stage_changes():
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            conn = await session.connection()
            await conn.execute(update(ServiceCase)
                               .where(ServiceCase.id == case.id)
                               .values(owner_login="another_manager"))
            await session.refresh(case)
            case.waiting_party = "client"
            case.waiting_since = datetime.now(timezone.utc)
            await session.flush()
            assert case.revision == 2
            case.outcome = "cancelled"
            await session.flush()
            assert case.revision == 3
            await session.flush()
            assert case.revision == 3
    run_with_db(scenario)


@pytest.mark.parametrize("stages,transitions", [
    ([], {}),
    ([{"code": "A", "name": "A"}, {"code": "A", "name": "Другой"}], {}),
    ([{"code": "A"}], {}),
    ([{"code": "A", "name": "A"}], {"A": ["UNKNOWN"]}),
    ([{"code": "A", "name": "A"}], {"UNKNOWN": []}),
    ([{"code": "A", "name": "A"}], {"A": "A"}),
])
def test_invalid_workflow_is_not_published(stages, transitions):
    async def scenario(sm):
        async with sm() as session:
            product = await create_product(session, code="test", name="Тест", direction="visa", by=SYSTEM_ACTOR)
            with pytest.raises(DomainError):
                await publish_version(session, product.id, stages, transitions, "admin", by=SYSTEM_ACTOR)
            assert product.current_version_id is None
            assert await session.scalar(select(func.count()).select_from(WorkflowVersion)) == 0
    run_with_db(scenario)


def test_seed_is_explicit_idempotent_and_only_tour_has_a_process():
    async def scenario(sm):
        async with sm() as session:
            assert await active_products(session) == []
            first = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
            second = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
            assert [p.id for p in first] == [p.id for p in second]
            assert {p.code for p in first} == {row[0] for row in INITIAL_PRODUCTS}
            assert len(first) == 9
            assert all(p.direction in DIRECTIONS for p in first)
            assert sum(p.current_version_id is not None for p in first) == 1
            assert await session.scalar(select(func.count()).select_from(WorkflowVersion)) == 1
    run_with_db(scenario)


def test_missing_product_contact_or_published_version_is_a_domain_error():
    async def scenario(sm):
        async with sm() as session:
            contact, product, _ = await prepare(session)
            empty = await create_product(session, code="unpublished", name="Черновик", direction="visa", by=SYSTEM_ACTOR)
            for contact_id, product_id in [(contact.id, 999), (999, product.id), (contact.id, empty.id)]:
                with pytest.raises(DomainError):
                    await open_case(session, contact_id=contact_id, product_id=product_id, owner_login="m", by=OWNER_M)
            assert await session.scalar(select(func.count()).select_from(ServiceCase)) == 1
            assert await session.scalar(select(func.count()).select_from(ServiceEvent)) == 1
    run_with_db(scenario)


def test_optional_request_must_match_contact_and_direction():
    async def scenario(sm):
        async with sm() as session:
            contact, product, _ = await prepare(session)
            another = Contact()
            session.add(another)
            await session.flush()
            requests = [Request(contact_id=contact.id, direction="tours"),
                        Request(contact_id=contact.id, direction="visa"),
                        Request(contact_id=another.id, direction="tours")]
            session.add_all(requests)
            await session.flush()
            linked = await open_case(session, contact_id=contact.id, product_id=product.id,
                                     owner_login="m", request_id=requests[0].id, by=OWNER_M)
            assert linked.request_id == requests[0].id
            for request in requests[1:]:
                with pytest.raises(DomainError, match="same contact and direction"):
                    await open_case(session, contact_id=contact.id, product_id=product.id,
                                    owner_login="m", request_id=request.id, by=OWNER_M)
    run_with_db(scenario)


def test_unique_product_code_and_workflow_version_constraints():
    async def scenario(sm):
        async with sm() as session:
            _, product, _ = await prepare(session)
            with pytest.raises(DomainError, match="already exists"):
                await create_product(session, code=product.code, name="Дубликат", direction="tours", by=SYSTEM_ACTOR)
            with pytest.raises(IntegrityError):
                async with session.begin_nested():
                    session.add(WorkflowVersion(product_id=product.id, version=1,
                                                stages=TOUR_STAGES, transitions=TOUR_TRANSITIONS))
                    await session.flush()
    run_with_db(scenario)


def test_case_and_event_roll_back_together_and_service_does_not_commit():
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            await session.commit()
        async with sm() as session:
            await advance(session, case.id, to_stage="TOUR-02", actor="manager", by=OWNER)
            await session.rollback()
        async with sm() as session:
            current = await session.get(ServiceCase, case.id)
            assert (current.stage, current.revision) == ("TOUR-01", 1)
            assert len(await history(session, case.id)) == 1
    run_with_db(scenario)


def test_history_insert_failure_rolls_back_stage_and_revision():
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)

            def fail_event(mapper, connection, target):
                raise RuntimeError("synthetic history failure")

            event.listen(ServiceEvent, "before_insert", fail_event)
            try:
                with pytest.raises(RuntimeError, match="synthetic history failure"):
                    await advance(session, case.id, to_stage="TOUR-02", actor="manager", by=OWNER)
            finally:
                event.remove(ServiceEvent, "before_insert", fail_event)
            await session.refresh(case)
            assert (case.stage, case.revision) == ("TOUR-01", 1)
            assert len(await history(session, case.id)) == 1
    run_with_db(scenario)


def test_concurrent_commit_after_read_returns_domain_conflict(monkeypatch):
    async def scenario(sm):
        async with sm() as first:
            _, _, stale = await prepare(first)
            await first.commit()
            async with sm() as second:
                await advance(second, stale.id, to_stage="TOUR-02", expected_revision=1, by=OWNER)
                await second.commit()
            original_get = first.get

            async def stale_read(entity, ident, **kwargs):
                # Воспроизводим окно гонки: другая транзакция уже записала новую ревизию
                # после нашего чтения, но до UPDATE. Проверка только в Python её пропустит.
                if entity is ServiceCase:
                    return stale
                return await original_get(entity, ident, **kwargs)

            monkeypatch.setattr(first, "get", stale_read)
            with pytest.raises(DomainError, match="revision conflict"):
                await advance(first, stale.id, to_stage="TOUR-02", expected_revision=1, by=OWNER)
            assert (stale.stage, stale.revision) == ("TOUR-02", 2)
            events = await history(first, stale.id)
            assert len(events) == 2 and events[-1].actor == "manager"
    run_with_db(scenario)


@pytest.mark.parametrize("action", ["code", "delete_product", "delete_version", "bulk_version"])
def test_product_identity_and_published_history_are_protected(action):
    async def scenario(sm):
        async with sm() as session:
            _, product, case = await prepare(session)
            await session.commit()
            version = await session.get(WorkflowVersion, case.workflow_version_id)
            with pytest.raises(DomainError):
                if action == "code":
                    product.code = "another_product"
                elif action == "delete_product":
                    await session.delete(product)
                    await session.flush()
                elif action == "delete_version":
                    await session.delete(version)
                    await session.flush()
                else:
                    await session.execute(update(WorkflowVersion).values(stages=[]))
            await session.rollback()
    run_with_db(scenario)


@pytest.mark.parametrize("stage", ["INVENTED", "TOUR-05", "TOUR-02"],
                         ids=["unknown", "far-ahead", "next-but-no-event"])
def test_direct_orm_write_cannot_change_stage_at_all(stage):
    """Этап меняется только через `advance`, даже если значение само по себе законное.

    Раньше отклонялся лишь неизвестный этап, а прямое `case.stage = "TOUR-05"`
    проходило: переход происходил без проверки допустимости и обязательных фактов,
    ревизия росла, события не возникало. Восстановить прежний этап из истории было
    нельзя — такая запись неотличима от правильной.
    """
    async def scenario(sm):
        async with sm() as session:
            _, _, case = await prepare(session)
            with pytest.raises(DomainError, match="only via advance"):
                async with session.begin_nested():
                    case.stage = stage
                    await session.flush()
            await session.refresh(case)
            assert (case.stage, case.revision) == ("TOUR-01", 1)
            # История тоже пуста: бесследного перехода не случилось.
            assert [e.event_type for e in await history(session, case.id)] == ["case_opened"]
    run_with_db(scenario)


def test_workflow_without_product_is_rejected_by_domain():
    async def scenario(sm):
        async with sm() as session:
            session.add(WorkflowVersion(product_id=123, version=1, stages=TOUR_STAGES,
                                        transitions=TOUR_TRANSITIONS))
            with pytest.raises(DomainError, match="unknown product"):
                await session.flush()
    run_with_db(scenario)


def test_infrastructure_flag_defaults_off():
    from app.config import Settings
    assert Settings.model_fields["service_cases_enabled"].default is False
    compose = (Path(__file__).resolve().parents[1] / "docker-compose.yml").read_text(encoding="utf-8")
    assert "SERVICE_CASES_ENABLED: ${SERVICE_CASES_ENABLED:-false}" in compose


def test_migration_is_additive_empty_and_reversible(tmp_path, monkeypatch):
    monkeypatch.delenv("ALEMBIC_DATABASE_URL", raising=False)
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    url = f"sqlite:///{(tmp_path / 'services.db').as_posix()}"
    cfg.set_main_option("sqlalchemy.url", url)
    # Накат идёт до head: проверяем также E2, E5 и реестр заявителей/подач E6.
    new_tables = {"products", "workflow_versions", "service_cases", "service_events",
                  "service_payments", "ticket_segments",
                  "booking_attempts", "knowledge_sets", "knowledge_versions",
                  "knowledge_units", "knowledge_imports", "knowledge_projections",
                  "knowledge_country_links", "knowledge_condition_links",
                  "stay_histories", "stay_intervals", "work_calendars", "work_calendar_days",
                  "entry_calculations", "entry_calculation_intervals", "entry_calculation_calendars",
                  "entry_qualifications", "entry_applicants", "entry_applications",
                  "entry_process_events", "entry_process_pins",
                  "entry_portal_receipts", "entry_portal_actions",
                  "entry_application_events", "entry_application_references", "entry_document_revisions", "entry_issued_revisions", "entry_applicant_profiles", "entry_deadline_revisions", "entry_deadline_tasks", "knowledge_decisions", "knowledge_publication_events", "knowledge_publication_units", "entry_document_package_events", "entry_quarantined_files"}
    engine = create_engine(url)
    try:
        command.upgrade(cfg, "bitrix_dossier_0006")
        before = set(inspect(engine).get_table_names())
        with engine.begin() as conn:
            conn.execute(text("INSERT INTO contacts (id) VALUES (123)"))
        command.upgrade(cfg, "head")
        assert set(inspect(engine).get_table_names()) == before | new_tables
        with engine.connect() as conn:
            # Сверяем с фактической последней ревизией, а не с её именем: иначе
            # каждая новая миграция ломала бы этот тест, не найдя при этом ни
            # одной настоящей ошибки. Проверяем именно «накатилось до конца».
            from alembic.config import Config as _AlembicConfig
            from alembic.script import ScriptDirectory as _ScriptDirectory
            _head = _ScriptDirectory.from_config(
                _AlembicConfig(str(Path(__file__).resolve().parents[1] / "alembic.ini"))).get_current_head()
            assert conn.scalar(text("SELECT version_num FROM alembic_version")) == _head
            for table in new_tables:
                assert conn.scalar(text(f"SELECT count(*) FROM {table}")) == 0
            assert conn.scalar(text("SELECT id FROM contacts")) == 123
        columns = {col["name"]: col for col in inspect(engine).get_columns("service_cases")}
        assert not columns["contact_id"]["nullable"]
        assert columns["request_id"]["nullable"]

        async def use_migrated_schema():
            async_engine = create_async_engine(url.replace("sqlite://", "sqlite+aiosqlite://"))
            try:
                async with async_sessionmaker(async_engine, expire_on_commit=False)() as session:
                    products = await seed_products(session, published_by="admin", by=SYSTEM_ACTOR)
                    case = await open_case(session, contact_id=123, product_id=products[0].id,
                                           owner_login="manager", by=OWNER)
                    await advance(session, case.id, to_stage="TOUR-02", actor="manager", by=OWNER)
                    await session.commit()
                    assert len(await history(session, case.id)) == 2
            finally:
                await async_engine.dispose()

        asyncio.run(use_migrated_schema())
        command.downgrade(cfg, "bitrix_dossier_0006")
        assert set(inspect(engine).get_table_names()) == before
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT id FROM contacts")) == 123
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    finally:
        engine.dispose()
