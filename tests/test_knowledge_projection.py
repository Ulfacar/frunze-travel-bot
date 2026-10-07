"""Atomic materialization, failure recovery and sealed review boundaries in SQLite."""
import asyncio
from copy import deepcopy
import hashlib
import json
import os
import subprocess
import sys

import pytest
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.knowledge_projection import ProjectionInvalid, review_projection
from app.domain.models import (DomainError, KnowledgeProjection, KnowledgeCountryLink,
                               KnowledgeConditionLink, KnowledgeSet)
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied
from app.knowledge.bundle import preflight_bundle
from app.knowledge.country_index import CountryRuleIndex
from app.knowledge.conditions import ConditionReview
from app.knowledge.validation import load_document
from tests.test_knowledge_import import ADMIN, FIX, ROOT, bundle, change, counts, db, do_import

MODELS = (KnowledgeProjection, KnowledgeCountryLink, KnowledgeConditionLink)
BASE_FACTS = {"schema_version": "kg-entry-condition-facts/1", "document_type": "un_lp"}


@pytest.fixture
def catalog(bundle, tmp_path):
    report = preflight_bundle(bundle, FIX / "synthetic_source.txt")
    data = {"format": "kg-entry-conditions/1", "status": "draft",
            "source_hash": report.normalized_bundle["meta"]["source_hash"], "bundle_hash": report.bundle_hash,
            "source_capture_sha256": "1" * 64, "source_date": "2026-10-02", "date_basis": "source_claim",
            "publication_approved": False, "rules": [{"unit_id": "KG.SP.TEST",
                "source_locations": [{"page": 1, "section": "Synthetic"}],
                "all": [{"type": "document_type_is", "value": "un_lp"}],
                "source_outcome": {"stay_days": 7}, "unresolved": ["synthetic_unapproved"]}]}
    path = tmp_path / "catalog.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


async def projection_counts(engine):
    async with async_sessionmaker(engine)() as session:
        return tuple([await session.scalar(select(func.count()).select_from(m)) for m in MODELS])


async def review(db, version_id, **kwargs):
    return await review_projection(db[0], actor=ADMIN, set_id=db[1], version_id=version_id,
                                   country=kwargs.pop("country", "CHN"), **kwargs)


def test_import_persists_country_and_condition_candidates_without_approval(db, bundle, catalog):
    async def scenario():
        imported = await do_import(db, bundle, catalog=catalog)
        repeated = await do_import(db, bundle, catalog=catalog)
        assert imported.accepted and repeated.accepted and repeated.reused
        assert imported.version_id == repeated.version_id
        assert imported.report["country_index_built"] is True
        report = preflight_bundle(bundle, FIX / "synthetic_source.txt")
        args = report.normalized_bundle
        index = CountryRuleIndex(**args, source_hash=args["meta"]["source_hash"])
        expected = ConditionReview(load_document(catalog), **args, source_hash=args["meta"]["source_hash"])
        result = await review(db, imported.version_id, facts=BASE_FACTS)
        assert result["country"] == index.lookup("CHN")
        assert result["conditions"] == expected.evaluate(BASE_FACTS)
        assert result["catalog_hash"] == result["conditions"]["catalog_hash"] == imported.report["catalog_hash"]
        assert result["conditions"]["rules"][0]["status"] == "met"
        assert result["country"]["may_quote"] is False
        assert result["conditions"]["entry_eligibility_evaluated"] is False
        assert await projection_counts(db[0]) == (1, index.summary()["country_links"], 1)
        # No writes occur during review, including no accidental customer-facts journal.
        before = await counts(db[0])
        await review(db, imported.version_id)
        assert await counts(db[0]) == before
    asyncio.run(scenario())


def test_no_catalog_is_explicit_sql_null_and_cannot_evaluate_facts(db, bundle):
    async def scenario():
        imported = await do_import(db, bundle)
        result = await review(db, imported.version_id)
        assert result["catalog_status"] == "absent" and result["conditions"] is None
        async with db[0].connect() as connection:
            assert await connection.scalar(text("SELECT condition_catalog IS NULL FROM knowledge_projections")) == 1
        with pytest.raises(ProjectionInvalid, match="catalog unavailable"):
            await review(db, imported.version_id, facts=BASE_FACTS)
    asyncio.run(scenario())


@pytest.mark.parametrize("action", ["omit", "add", "change"])
def test_retry_cannot_replace_drop_or_attach_catalog(db, bundle, catalog, action):
    async def scenario():
        first = await do_import(db, bundle, catalog=None if action == "add" else catalog)
        if action == "change":
            data = load_document(catalog)
            data["rules"][0]["source_outcome"]["stay_days"] = 8
            catalog.write_text(json.dumps(data), encoding="utf-8")
        before = await projection_counts(db[0])
        other = await do_import(db, bundle, catalog=None if action == "omit" else catalog)
        assert first.accepted and not other.accepted
        assert other.report["errors"][0]["code"] == "semantic.existing_projection"
        assert other.report["country_index_built"] is False
        assert await projection_counts(db[0]) == before
        assert (await counts(db[0]))[::2] == (1, 2)
    asyncio.run(scenario())


@pytest.mark.parametrize("fault", ["source", "bundle", "reference", "duplicate", "syntax", "null", "missing"])
def test_bad_catalog_only_records_rejection(db, bundle, catalog, fault):
    data = load_document(catalog)
    if fault in ("source", "bundle"):
        data[fault + "_hash"] = "0" * 64
    elif fault == "reference":
        data["rules"][0]["unit_id"] = "KG.RULE.TEST"
    elif fault == "duplicate":
        data["rules"].append(deepcopy(data["rules"][0]))
    catalog.write_text("bad: [" if fault == "syntax" else "null" if fault == "null" else json.dumps(data), encoding="utf-8")
    if fault == "missing":
        catalog = catalog.parent / "not-present.json"
    result = asyncio.run(do_import(db, bundle, catalog=catalog))
    assert not result.accepted and result.version_id is None
    assert asyncio.run(counts(db[0])) == (0, 0, 1)
    assert asyncio.run(projection_counts(db[0])) == (0, 0, 0)


@pytest.mark.parametrize("table", ["knowledge_projections", "knowledge_country_links", "knowledge_condition_links", "knowledge_imports"])
def test_partial_insert_rolls_back_all_materialized_rows(db, bundle, catalog, table):
    fired = False
    def fail(conn, cursor, statement, parameters, context, many):
        nonlocal fired
        if not fired and statement.startswith("INSERT INTO " + table):
            fired = True
            raise RuntimeError("private payload")
    event.listen(db[0].sync_engine, "before_cursor_execute", fail)
    try:
        rejected = asyncio.run(do_import(db, bundle, catalog=catalog))
    finally:
        event.remove(db[0].sync_engine, "before_cursor_execute", fail)
    assert fired and not rejected.accepted and "private" not in json.dumps(rejected.report)
    assert asyncio.run(counts(db[0])) == (0, 0, 1)
    assert asyncio.run(projection_counts(db[0])) == (0, 0, 0)
    assert asyncio.run(do_import(db, bundle, catalog=catalog)).accepted


def test_competing_identical_and_different_catalogs(db, bundle, catalog, tmp_path):
    changed = load_document(catalog)
    changed["rules"][0]["source_outcome"]["stay_days"] = 9
    other = tmp_path / "other.json"
    other.write_text(json.dumps(changed), encoding="utf-8")
    async def scenario():
        results = await asyncio.gather(do_import(db, bundle, catalog=catalog), do_import(db, bundle, catalog=catalog),
                                       do_import(db, bundle, catalog=other))
        assert sum(r.accepted and not r.reused for r in results) == 1
        assert any(not r.accepted for r in results)
        assert len({r.version_id for r in results if r.accepted}) == 1
        assert (await counts(db[0]))[::2] == (1, 3)
        assert (await projection_counts(db[0]))[::2] == (1, 1)
    asyncio.run(scenario())


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("operation", ["update", "delete", "insert"])
def test_projection_orm_is_sealed(db, bundle, catalog, model, operation):
    async def scenario():
        imported = await do_import(db, bundle, catalog=catalog)
        async with async_sessionmaker(db[0])() as session:
            row = await session.scalar(select(model))
            if operation == "delete":
                await session.delete(row)
            elif operation == "insert":
                fields = {c.name: json.loads(json.dumps(getattr(row, c.name))) for c in model.__table__.columns}
                session.expunge(row)
                session.add(model(**fields))
            else:
                field = {KnowledgeProjection: "projection_hash", KnowledgeCountryLink: "association",
                         KnowledgeConditionLink: "unit_id"}[model]
                setattr(row, field, "changed")
            with pytest.raises(DomainError, match="immutable|sealed"):
                await session.flush()
            await session.rollback()
        assert (await review(db, imported.version_id))["integrity_checked"] is True
    asyncio.run(scenario())


@pytest.mark.parametrize("sql", [
    "UPDATE knowledge_projections SET projection_hash='" + "0" * 64 + "'",
    "UPDATE knowledge_projections SET country_summary='{}'",
    "UPDATE knowledge_projections SET condition_catalog='{}'",
    "DELETE FROM knowledge_condition_links",
    "INSERT INTO knowledge_condition_links VALUES (1, 'KG.VF.TEST')",
    "DELETE FROM knowledge_country_links",
    "UPDATE knowledge_country_links SET association='evidence_country' WHERE association='value_country'",
    "UPDATE knowledge_units SET title='private corrupt title'",
])
def test_read_and_retry_refuse_tampered_materialization(db, bundle, catalog, sql):
    async def scenario():
        result = await do_import(db, bundle, catalog=catalog)
        async with db[0].begin() as conn:
            await conn.execute(text(sql))
        with pytest.raises(DomainError) as error:
            await review(db, result.version_id)
        assert "private" not in str(error.value)
        retry = await do_import(db, bundle, catalog=catalog)
        assert not retry.accepted
    asyncio.run(scenario())


def test_historical_version_without_projection_is_never_backfilled(db, bundle):
    async def scenario():
        result = await do_import(db, bundle)
        async with db[0].begin() as conn:
            await conn.execute(text("DELETE FROM knowledge_country_links"))
            await conn.execute(text("DELETE FROM knowledge_projections"))
        with pytest.raises(ProjectionInvalid, match="missing"):
            await review(db, result.version_id)
        retry = await do_import(db, bundle)
        assert not retry.accepted and await projection_counts(db[0]) == (0, 0, 0)
    asyncio.run(scenario())


@pytest.mark.parametrize("sql", [
    "INSERT INTO knowledge_country_links VALUES (1, 'USA', 'UNKNOWN.UNIT', 'value_country')",
    "INSERT INTO knowledge_condition_links VALUES (1, 'UNKNOWN.UNIT')",
    "INSERT INTO knowledge_condition_links VALUES (999, 'KG.SP.TEST')",
    "UPDATE knowledge_country_links SET association='eligibility_approved'",
    "UPDATE knowledge_projections SET catalog_hash=NULL",
    "UPDATE knowledge_projections SET format_version=2",
])
def test_projection_sql_constraints(db, bundle, catalog, sql):
    async def scenario():
        await do_import(db, bundle, catalog=catalog)
        with pytest.raises(IntegrityError):
            async with db[0].begin() as conn:
                await conn.execute(text(sql))
    asyncio.run(scenario())


def test_foreign_version_unit_cannot_be_linked(db, bundle):
    async def scenario():
        first = await do_import(db, bundle)
        change(bundle, "units.yaml", lambda rows: next(r for r in rows if r["unit_id"] == "KG.SP.TEST").update(unit_id="KG.SP.SECOND"))
        second = await do_import(db, bundle)
        assert first.accepted and second.accepted
        with pytest.raises(IntegrityError):
            async with db[0].begin() as conn:
                await conn.execute(text("INSERT INTO knowledge_condition_links VALUES (:id, 'KG.SP.SECOND')"),
                                   {"id": first.version_id})
    asyncio.run(scenario())


def test_cancel_during_projection_has_no_false_journal_and_recovers(db, bundle, catalog):
    def cancel(conn, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO knowledge_country_links"):
            raise asyncio.CancelledError()
    event.listen(db[0].sync_engine, "before_cursor_execute", cancel)
    try:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(do_import(db, bundle, catalog=catalog))
    finally:
        event.remove(db[0].sync_engine, "before_cursor_execute", cancel)
    assert asyncio.run(counts(db[0])) == (0, 0, 0)
    assert asyncio.run(projection_counts(db[0])) == (0, 0, 0)
    assert asyncio.run(do_import(db, bundle, catalog=catalog)).accepted


def test_commit_failure_reconciles_complete_projection(db, bundle, catalog):
    from app.domain.knowledge_import import ImportUnavailable
    def fail(conn):
        raise RuntimeError("private transport")
    event.listen(db[0].sync_engine, "commit", fail)
    try:
        with pytest.raises(ImportUnavailable, match="commit outcome unknown"):
            asyncio.run(do_import(db, bundle, catalog=catalog))
    finally:
        event.remove(db[0].sync_engine, "commit", fail)
    # This fault happens before physical commit; lost acknowledgement can also leave accepted data.
    recovered = asyncio.run(do_import(db, bundle, catalog=catalog))
    repeated = asyncio.run(do_import(db, bundle, catalog=catalog))
    assert recovered.accepted and repeated.accepted and repeated.reused
    assert (asyncio.run(projection_counts(db[0])))[::2] == (1, 1)
    assert asyncio.run(review(db, recovered.version_id))["integrity_checked"] is True


@pytest.mark.parametrize("actor", [None, Actor("manager"), Actor("bot", True), {"is_full_admin": True}])
def test_read_auth_precedes_storage(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(review_projection(None, actor=actor, set_id=1, version_id=1, country="CHN"))


def test_cross_set_and_invalid_ids_denied(db, bundle):
    async def scenario():
        imported = await do_import(db, bundle)
        async with async_sessionmaker(db[0]).begin() as session:
            other = KnowledgeSet(code="other", jurisdiction="KG", domain="entry", name="Other")
            session.add(other)
            await session.flush()
            other_id = other.id
        for set_id, version_id in [(other_id, imported.version_id), (db[1], 999), (True, 1), (1, False)]:
            with pytest.raises(DomainError):
                await review_projection(db[0], actor=ADMIN, set_id=set_id, version_id=version_id, country="CHN")
    asyncio.run(scenario())


def test_local_cli_read_is_self_contained_and_byte_preserving(db, bundle, catalog, tmp_path):
    imported = asyncio.run(do_import(db, bundle, catalog=catalog))
    database = tmp_path / "knowledge.sqlite3"
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    facts = tmp_path / "facts.json"
    facts.write_text(json.dumps(BASE_FACTS), encoding="utf-8")
    env = {**os.environ, "ALEMBIC_DATABASE_URL": "postgresql://invalid.invalid/no", "PYTHONIOENCODING": "utf-8"}
    args = [sys.executable, "scripts/review_kg_projection_local.py", "--db", str(database),
            "--set-id", str(db[1]), "--version-id", str(imported.version_id), "--country", "China", "--facts", str(facts)]
    result = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    output = json.loads(result.stdout)
    assert output["country"]["country_iso3"] == "CHN" and output["conditions"]["rules"][0]["status"] == "met"
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
    facts.write_text('{"private":"customer data"}', encoding="utf-8")
    rejected = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
    assert rejected.returncode == 2 and "customer" not in rejected.stdout
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before
