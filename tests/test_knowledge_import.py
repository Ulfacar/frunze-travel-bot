"""E5-02B: transactional draft import, isolated SQLite with FK enforcement."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import shutil

import pytest
from sqlalchemy import event, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.knowledge_import import ImportUnavailable, create_kg_entry_set, import_bundle
from app.domain.models import (DomainBase, DomainError, KnowledgeImport, KnowledgeSet,
                               KnowledgeUnit, KnowledgeVersion)
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied, SYSTEM_ACTOR
from app.knowledge.bundle import preflight_bundle
from app.knowledge.validation import load_document

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests/fixtures/kg_entry"
ADMIN = Actor("test-admin", is_full_admin=True)
TABLES = [KnowledgeVersion.__table__, KnowledgeSet.__table__, KnowledgeUnit.__table__, KnowledgeImport.__table__]


@pytest.fixture
def db(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'knowledge.sqlite3').as_posix()}")

    @event.listens_for(engine.sync_engine, "connect")
    def enable_fk(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(lambda c: DomainBase.metadata.create_all(c, tables=TABLES))
        return await create_kg_entry_set(engine, actor=ADMIN)
    set_id = asyncio.run(setup())
    yield engine, set_id
    asyncio.run(engine.dispose())


@pytest.fixture
def bundle(tmp_path):
    target = tmp_path / "bundle"
    shutil.copytree(FIX / "synthetic_bundle", target)
    return target


async def do_import(db, directory, **kwargs):
    engine, set_id = db
    return await import_bundle(engine, actor=ADMIN, set_id=set_id, directory=directory,
                               source=kwargs.pop("source", FIX / "synthetic_source.txt"), **kwargs)


def change(directory, filename, transform):
    data = load_document(directory / filename)
    transform(data)
    (directory / filename).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


async def counts(engine):
    async with async_sessionmaker(engine)() as session:
        return tuple([await session.scalar(select(func.count()).select_from(model))
                      for model in (KnowledgeVersion, KnowledgeUnit, KnowledgeImport)])


async def activate_fixture(db, bundle):
    """Only synthetic fixture bootstrap, privileged SQL; no publication API exists."""
    result = await do_import(db, bundle)
    async with db[0].begin() as connection:
        await connection.execute(update(KnowledgeVersion).where(KnowledgeVersion.id == result.version_id).values(status="active"))
        await connection.execute(update(KnowledgeSet).where(KnowledgeSet.id == db[1]).values(active_version_id=result.version_id))
    return result.version_id


def test_repeat_is_one_draft_and_separate_journal_attempts(db, bundle):
    async def scenario():
        first = await do_import(db, bundle)
        second = await do_import(db, bundle)
        expected = preflight_bundle(bundle, FIX / "synthetic_source.txt")
        assert first.accepted and second.accepted and not first.reused and second.reused
        assert first.version_id == second.version_id and first.import_id != second.import_id
        assert await counts(db[0]) == (1, len(expected.normalized_bundle["units"]), 2)
        async with async_sessionmaker(db[0])() as session:
            version = await session.get(KnowledgeVersion, first.version_id)
            assert version.status == "draft" and version.bundle_hash == expected.bundle_hash
            assert version.source_hash == expected.normalized_bundle["meta"]["source_hash"]
            records = (await session.scalars(select(KnowledgeUnit).order_by(KnowledgeUnit.unit_id))).all()
            assert [u.source_record for u in records] == expected.normalized_bundle["units"]
            assert version.country_aliases == expected.normalized_bundle["countries"]
            assert version.bundle_meta == expected.normalized_bundle["meta"]
            knowledge_set = await session.get(KnowledgeSet, db[1])
            assert knowledge_set.active_version_id is None and knowledge_set.review_period_days is None
            assert await session.scalar(text("SELECT value IS NULL FROM knowledge_units WHERE unit_id='KG.REG.EXEMPT.MDA'")) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("actor", [None, Actor("manager", allowed_directions=frozenset({"visa"})),
                                  Actor("" , True), Actor("a" * 65, True), SYSTEM_ACTOR, Actor("bot", True),
                                  Actor("user", 1), {"is_full_admin": True}])
def test_authorization_precedes_files_and_engine(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(import_bundle(None, actor=actor, set_id=1, directory=Path("missing"), source=Path("missing")))
    with pytest.raises(PermissionDenied):
        asyncio.run(create_kg_entry_set(None, actor=actor))


@pytest.mark.parametrize("fault,stage", [("syntax", "syntax"), ("schema", "schema"),
                                        ("semantic", "semantic"), ("source", "semantic")])
def test_invalid_import_only_adds_rejection_and_preserves_active(db, bundle, fault, stage):
    async def scenario():
        active_id = await activate_fixture(db, bundle)
        before = await counts(db[0])
        if fault == "syntax":
            (bundle / "units.yaml").write_text("bad: [", encoding="utf-8")
        elif fault == "schema":
            change(bundle, "units.yaml", lambda units: units[0].update(label="UNRECOGNIZED"))
        elif fault == "semantic":
            change(bundle, "units.yaml", lambda units: units.append(deepcopy(units[0])))
        else:
            change(bundle, "meta.yaml", lambda meta: meta.update(source_hash="0" * 64))
        result = await do_import(db, bundle)
        assert not result.accepted and result.version_id is None
        after = await counts(db[0])
        assert after == (before[0], before[1], before[2] + 1)
        async with async_sessionmaker(db[0])() as session:
            journal = await session.get(KnowledgeImport, result.import_id)
            assert journal.result == "rejected" and journal.error_stage == stage and journal.error_location
            assert (await session.get(KnowledgeSet, db[1])).active_version_id == active_id
    asyncio.run(scenario())


def test_existing_active_is_not_cloned_or_downgraded(db, bundle):
    async def scenario():
        active_id = await activate_fixture(db, bundle)
        result = await do_import(db, bundle)
        assert not result.accepted and result.report["errors"][0]["code"] == "semantic.existing_not_draft"
        assert (await counts(db[0]))[0] == 1
        async with async_sessionmaker(db[0])() as session:
            assert (await session.get(KnowledgeVersion, active_id)).status == "active"
    asyncio.run(scenario())


@pytest.mark.parametrize("table", ["knowledge_units", "knowledge_imports"])
def test_failure_after_writes_rolls_back_and_journals(db, bundle, table):
    async def scenario():
        active_id = await activate_fixture(db, bundle)
        before = await counts(db[0])
        change(bundle, "meta.yaml", lambda meta: meta.update(version_label="next"))
        fired = False

        def fail_write(conn, cursor, statement, parameters, context, executemany):
            nonlocal fired
            if not fired and statement.startswith(f"INSERT INTO {table}"):
                fired = True
                raise RuntimeError("secret payload must not be reported")
        event.listen(db[0].sync_engine, "before_cursor_execute", fail_write)
        try:
            result = await do_import(db, bundle)
        finally:
            event.remove(db[0].sync_engine, "before_cursor_execute", fail_write)
        assert fired and not result.accepted
        assert "secret" not in json.dumps(result.report)
        assert await counts(db[0]) == (before[0], before[1], before[2] + 1)
        async with async_sessionmaker(db[0])() as session:
            assert (await session.get(KnowledgeSet, db[1])).active_version_id == active_id
            assert (await session.get(KnowledgeImport, result.import_id)).error_stage == "db"
        recovered = await do_import(db, bundle)
        assert recovered.accepted and recovered.version_id != active_id
        async with async_sessionmaker(db[0])() as session:
            assert (await session.get(KnowledgeSet, db[1])).active_version_id == active_id
            assert (await session.get(KnowledgeVersion, active_id)).status == "active"
    asyncio.run(scenario())


def test_missing_journal_is_an_explicit_unavailable_outcome(db, bundle):
    def fail_write(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO knowledge_imports"):
            raise IntegrityError("private", {}, Exception("secret"))
    event.listen(db[0].sync_engine, "before_cursor_execute", fail_write)
    try:
        with pytest.raises(ImportUnavailable, match="journal unavailable"):
            asyncio.run(do_import(db, bundle))
    finally:
        event.remove(db[0].sync_engine, "before_cursor_execute", fail_write)
    assert asyncio.run(counts(db[0])) == (0, 0, 0)


def test_commit_failure_is_unknown_and_retry_reconciles(db, bundle):
    def fail_commit(conn):
        raise RuntimeError("secret transport error")
    event.listen(db[0].sync_engine, "commit", fail_commit)
    try:
        with pytest.raises(ImportUnavailable, match="commit outcome unknown"):
            asyncio.run(do_import(db, bundle))
    finally:
        event.remove(db[0].sync_engine, "commit", fail_commit)
    # This injected failure precedes the physical commit; a true lost acknowledgement
    # can leave accepted data, so the production contract always reports UNKNOWN.
    assert asyncio.run(do_import(db, bundle)).accepted


def test_competing_same_bundle_is_deduplicated(db, bundle):
    async def scenario():
        results = await asyncio.gather(*(do_import(db, bundle) for _ in range(3)))
        assert all(r.accepted for r in results)
        assert len({r.version_id for r in results}) == 1
        assert sum(not r.reused for r in results) == 1
        assert (await counts(db[0]))[::2] == (1, 3)
    asyncio.run(scenario())


def test_foreign_and_unknown_set_refused_without_audit(db, bundle):
    async def scenario():
        async with async_sessionmaker(db[0]).begin() as session:
            other = KnowledgeSet(code="other", jurisdiction="KG", domain="entry", name="Other")
            session.add(other)
            await session.flush()
            other_id = other.id
        for set_id in (other_id, 9999, True):
            with pytest.raises(DomainError):
                await import_bundle(db[0], actor=ADMIN, set_id=set_id, directory=bundle, source=FIX / "synthetic_source.txt")
        assert await counts(db[0]) == (0, 0, 0)
    asyncio.run(scenario())


def test_different_bundles_get_distinct_sequential_versions(db, bundle, tmp_path):
    other = tmp_path / "next-bundle"
    shutil.copytree(bundle, other)
    change(other, "meta.yaml", lambda meta: meta.update(version_label="next"))
    async def scenario():
        results = await asyncio.gather(do_import(db, bundle), do_import(db, other))
        assert all(r.accepted for r in results) and len({r.version_id for r in results}) == 2
        async with async_sessionmaker(db[0])() as session:
            numbers = (await session.scalars(select(KnowledgeVersion.version).order_by(KnowledgeVersion.version))).all()
            assert numbers == [1, 2]
        async with db[0].begin() as connection:
            # Bulk SQL bypasses ORM; the partial UNIQUE still allows only one active.
            await connection.execute(update(KnowledgeVersion).where(KnowledgeVersion.id == results[0].version_id).values(status="active"))
            with pytest.raises(IntegrityError):
                await connection.execute(update(KnowledgeVersion).where(KnowledgeVersion.id == results[1].version_id).values(status="active"))
    asyncio.run(scenario())


def test_cancelled_import_rolls_back_without_false_completion(db, bundle):
    def cancel(conn, cursor, statement, parameters, context, executemany):
        if statement.startswith("INSERT INTO knowledge_units"):
            raise asyncio.CancelledError()
    event.listen(db[0].sync_engine, "before_cursor_execute", cancel)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(do_import(db, bundle))
    finally:
        event.remove(db[0].sync_engine, "before_cursor_execute", cancel)
    assert asyncio.run(counts(db[0])) == (0, 0, 0)
    assert asyncio.run(do_import(db, bundle)).accepted


@pytest.mark.parametrize("model", [KnowledgeSet, KnowledgeVersion, KnowledgeUnit, KnowledgeImport])
@pytest.mark.parametrize("operation", ["update", "delete"])
def test_snapshots_and_journal_reject_orm_mutation(db, bundle, model, operation):
    async def scenario():
        await do_import(db, bundle)
        async with async_sessionmaker(db[0])() as session:
            row = await session.scalar(select(model).limit(1))
            if operation == "delete":
                await session.delete(row)
            else:
                field = {KnowledgeSet: "name", KnowledgeVersion: "source_document",
                         KnowledgeUnit: "title", KnowledgeImport: "filename"}[model]
                setattr(row, field, "tampered")
            with pytest.raises(DomainError, match="immutable"):
                await session.flush()
            await session.rollback()
    asyncio.run(scenario())


def test_nested_json_immutable_and_sealed_draft_cannot_gain_units(db, bundle):
    async def scenario():
        result = await do_import(db, bundle)
        async with async_sessionmaker(db[0])() as session:
            row = await session.scalar(select(KnowledgeUnit).where(KnowledgeUnit.unit_id == "KG.VF.TEST"))
            with pytest.raises(DomainError, match="immutable"):
                row.value["countries"].append("FRA")
            with pytest.raises(DomainError, match="immutable"):
                row.source_record["value"]["days"] = 999
            record = json.loads(json.dumps(row.source_record))
            record["unit_id"] = "KG.VF.EXTRA"
            session.add(KnowledgeUnit(version_id=result.version_id, source_record=record, **record))
            with pytest.raises(DomainError, match="sealed"):
                await session.flush()
    asyncio.run(scenario())


@pytest.mark.parametrize("statement", [
    "UPDATE knowledge_units SET value='{}' WHERE confirmation_status='blocked'",
    "UPDATE knowledge_units SET conflict_ref=NULL WHERE confirmation_status='blocked'",
    "UPDATE knowledge_units SET effective_from='2026-10-08', effective_to='2026-10-07'",
    "UPDATE knowledge_units SET verified_by='someone' WHERE verified_at IS NULL",
    "UPDATE knowledge_units SET label='INVALID'",
    "UPDATE knowledge_imports SET result='rejected'",
    "UPDATE knowledge_versions SET version=0",
    "UPDATE knowledge_sets SET active_version_id=999999",
])
def test_database_constraints_cannot_be_bypassed_by_bulk_sql(db, bundle, statement):
    async def scenario():
        await do_import(db, bundle)
        async with db[0].begin() as conn:
            with pytest.raises(IntegrityError):
                await conn.execute(text(statement))
    asyncio.run(scenario())


def test_cross_set_active_pointer_and_import_reference(db, bundle):
    async def scenario():
        result = await do_import(db, bundle)
        async with async_sessionmaker(db[0]).begin() as session:
            other = KnowledgeSet(code="other", jurisdiction="KG", domain="entry", name="Other")
            session.add(other)
            await session.flush()
            other_id = other.id
        for sql, params in [
            ("UPDATE knowledge_sets SET active_version_id=:v WHERE id=:s", {"v": result.version_id, "s": other_id}),
            ("UPDATE knowledge_imports SET set_id=:s WHERE id=:i", {"s": other_id, "i": result.import_id}),
        ]:
            async with db[0].begin() as conn:
                with pytest.raises(IntegrityError):
                    await conn.execute(text(sql), params)
    asyncio.run(scenario())


def test_real_pdf_bundle_round_trip(db):
    pdf = ROOT.parent / "Kyrgyzstan-visa-knowledge-base-v1.1.pdf"
    if not pdf.is_file():
        pytest.skip("original local PDF required for source hash verification")
    async def scenario():
        bundle = ROOT / "knowledge/kg_entry/draft-v1.1"
        result = await do_import(db, bundle, source=pdf)
        assert result.accepted and result.bundle_hash == "bf9faa537ae600c433a064ab21b8d5969aa63ba99fc39ead224dc6fa5256dea5"
        assert result.report["status_counts"] == {"blocked": 3, "decision_pending": 22, "needs_verification": 183}
        assert await counts(db[0]) == (1, 208, 1)
        async with async_sessionmaker(db[0])() as session:
            assert await session.scalar(text("SELECT count(*) FROM knowledge_units WHERE value IS NULL")) == 82
            records = (await session.scalars(select(KnowledgeUnit).order_by(KnowledgeUnit.unit_id))).all()
            expected = preflight_bundle(bundle, pdf).normalized_bundle["units"]
            assert [u.source_record for u in records] == expected
            assert all(u.blocked_value["source"] for u in records)
    asyncio.run(scenario())
