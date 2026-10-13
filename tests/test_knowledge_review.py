"""E5-02C: real read-only comparisons, corruption/authorization/CLI failure cases."""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
from sqlalchemy import event, text, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.domain.knowledge_review import SnapshotInvalid, review_versions
from app.domain.models import DomainError, KnowledgeSet, KnowledgeUnit, KnowledgeVersion
from app.domain.permissions import Actor
from app.domain.service_authz import PermissionDenied, SYSTEM_ACTOR
from app.knowledge.bundle import preflight_bundle
from app.knowledge.review import compare_snapshots
from tests.test_knowledge_import import ADMIN, FIX, ROOT, bundle, change, counts, db, do_import


def synthetic_snapshot():
    return preflight_bundle(FIX / "synthetic_bundle", FIX / "synthetic_source.txt").normalized_bundle


def test_diff_detects_add_remove_and_exact_fields_without_mutation():
    before = synthetic_snapshot()
    after = deepcopy(before)
    extra = deepcopy(next(u for u in after["units"] if u["kind"] == "escalation_trigger"))
    extra["unit_id"] = "KG.ESC.ADDED"
    after["units"].append(extra)
    after["units"] = [u for u in after["units"] if u["unit_id"] != "KG.TPL.TEST"]
    target = next(u for u in after["units"] if u["unit_id"] == "KG.REG.EXEMPT.GRC")
    target["value"]["days"] = 18
    after["countries"]["new-alias"] = "GRC"
    after["meta"]["version_label"] = "second"
    saved = deepcopy((before, after))
    result = compare_snapshots(before, after)
    assert result["summary"] == {"before_units": 14, "after_units": 14, "added": 1, "removed": 1, "changed": 1, "unchanged": 12}
    assert result["changed"][0]["unit_id"] == "KG.REG.EXEMPT.GRC"
    assert result["changed"][0]["fields"]["value"] == {
        "before_present": True, "after_present": True, "before": {"days": 17}, "after": {"days": 18}}
    assert result["added"][0]["unit_id"] == "KG.ESC.ADDED"
    assert result["removed"][0]["unit_id"] == "KG.TPL.TEST"
    assert set(result["metadata_changes"]) == {"version_label"}
    assert result["country_alias_changes"]["new-alias"]["before_present"] is False
    assert (before, after) == saved
    assert result["publication_approved"] is False and result["activation_supported"] is False


def test_order_and_missing_versus_null_are_distinguished():
    before = synthetic_snapshot()
    after = deepcopy(before)
    after["units"].reverse()
    assert compare_snapshots(before, after)["summary"]["unchanged"] == 14
    target = next(u for u in after["units"] if "effective_to" not in u)
    target["effective_to"] = None
    result = compare_snapshots(before, after)
    delta = result["changed"][0]["fields"]["effective_to"]
    assert delta == {"before_present": False, "after_present": True, "before": None, "after": None}


def test_boolean_is_not_equal_to_number_in_json_diff():
    before = synthetic_snapshot()
    after = deepcopy(before)
    next(u for u in after["units"] if u["unit_id"] == "KG.VF.TEST")["value"]["work_needs_unified_permit"] = 1
    assert compare_snapshots(before, after)["summary"]["changed"] == 1


async def review(db, candidate, **kwargs):
    return await review_versions(db[0], actor=ADMIN, set_id=db[1], candidate_id=candidate, **kwargs)


def test_database_compare_metadata_only_and_same_version(db, bundle, tmp_path):
    async def scenario():
        first = await do_import(db, bundle)
        second_bundle = tmp_path / "second"
        shutil.copytree(bundle, second_bundle)
        change(second_bundle, "meta.yaml", lambda meta: meta.update(version_label="second"))
        second = await do_import(db, second_bundle)
        result = await review(db, second.version_id, baseline_id=first.version_id)
        assert result["summary"]["unchanged"] == 14 and result["summary"]["changed"] == 0
        assert set(result["metadata_changes"]) == {"version_label"}
        same = await review(db, first.version_id, baseline_id=first.version_id)
        assert same["summary"]["unchanged"] == 14 and same["metadata_changes"] == {}
    asyncio.run(scenario())


def test_no_baseline_and_active_baseline_are_explicit_and_read_only(db, bundle):
    async def scenario():
        imported = await do_import(db, bundle)
        initial = await counts(db[0])
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement.lstrip().split()[0].upper())
        event.listen(db[0].sync_engine, "before_cursor_execute", record)
        try:
            result = await review(db, imported.version_id)
        finally:
            event.remove(db[0].sync_engine, "before_cursor_execute", record)
        assert result["baseline"] is None and not result["baseline_present"]
        assert result["summary"]["added"] == 14
        assert all(stmt in {"SELECT", "PRAGMA"} for stmt in statements)
        assert await counts(db[0]) == initial
        async with db[0].begin() as conn:
            await conn.execute(update(KnowledgeVersion).where(KnowledgeVersion.id == imported.version_id).values(status="active"))
            await conn.execute(update(KnowledgeSet).where(KnowledgeSet.id == db[1]).values(active_version_id=imported.version_id))
        result = await review(db, imported.version_id)
        assert result["baseline"]["id"] == imported.version_id and result["baseline"]["status"] == "active"
        assert result["summary"]["unchanged"] == 14
    asyncio.run(scenario())


@pytest.mark.parametrize("actor", [None, Actor("manager"), SYSTEM_ACTOR, Actor("bot", True), {"is_full_admin": True}])
def test_review_authorization_precedes_io(actor):
    with pytest.raises(PermissionDenied):
        asyncio.run(review_versions(None, actor=actor, set_id=1, candidate_id=1))


@pytest.mark.parametrize("parameters", [{"set_id": True}, {"candidate_id": 0}, {"baseline_id": True}, {"baseline_id": -1}])
def test_invalid_ids_precede_engine_access(parameters):
    arguments = {"set_id": 1, "candidate_id": 1, **parameters}
    with pytest.raises(DomainError, match="identifier"):
        asyncio.run(review_versions(None, actor=ADMIN, **arguments))


def test_foreign_or_missing_version_and_set_refused(db, bundle):
    # A separate foreign draft exercises scoped lookup without violating the
    # composite FK of an already accepted import journal.
    async def scoped_scenario():
        imported = await do_import(db, bundle)
        async with async_sessionmaker(db[0]).begin() as session:
            other = KnowledgeSet(code="other", jurisdiction="KG", domain="entry", name="Other")
            session.add(other)
            await session.flush()
            other_id = other.id
            source = await session.get(KnowledgeVersion, imported.version_id)
            foreign = KnowledgeVersion(set_id=other_id, version=1, status="draft", source_document=source.source_document,
                source_hash=source.source_hash, bundle_hash=source.bundle_hash, source_prepared_by=source.source_prepared_by,
                created_by="test-admin", bundle_meta=dict(source.bundle_meta), country_aliases=dict(source.country_aliases),
                import_report={})
            session.add(foreign)
            await session.flush()
            foreign_id = foreign.id
        with pytest.raises(DomainError, match="set unavailable"):
            await review_versions(db[0], actor=ADMIN, set_id=other_id, candidate_id=imported.version_id)
        for candidate, baseline in [(99999, None), (foreign_id, None), (imported.version_id, foreign_id)]:
            with pytest.raises(DomainError, match="version unavailable"):
                await review(db, candidate, baseline_id=baseline)
    asyncio.run(scoped_scenario())


@pytest.mark.parametrize("fault", ["hash", "source", "column", "boolean", "metadata", "delete", "active_pointer",
                                  "date", "version_date", "set_date"])
def test_corrupted_storage_never_returns_comparison(db, bundle, fault):
    async def scenario():
        imported = await do_import(db, bundle)
        async with db[0].begin() as conn:
            if fault == "hash":
                await conn.execute(update(KnowledgeVersion).values(bundle_hash="0" * 64))
            elif fault == "source":
                await conn.execute(update(KnowledgeUnit).values(source_record={"title": "secret must not leak"}))
            elif fault == "column":
                await conn.execute(update(KnowledgeUnit).values(title="secret must not leak"))
            elif fault == "boolean":
                await conn.execute(update(KnowledgeUnit).where(KnowledgeUnit.unit_id == "KG.REG.EXEMPT.GRC").values(value={"days": True}))
            elif fault == "metadata":
                await conn.execute(update(KnowledgeVersion).values(source_prepared_by="secret must not leak"))
            elif fault == "delete":
                await conn.execute(text("DELETE FROM knowledge_units WHERE unit_id='KG.ESC.TEST'"))
            elif fault in {"date", "version_date", "set_date"}:
                table, column = {"date": ("knowledge_units", "effective_from"),
                                 "version_date": ("knowledge_versions", "effective_from"),
                                 "set_date": ("knowledge_sets", "created_at")}[fault]
                await conn.execute(text(f"UPDATE {table} SET {column}='secret must not leak'"))
            else:
                await conn.execute(update(KnowledgeSet).values(active_version_id=imported.version_id))
        with pytest.raises(SnapshotInvalid) as exc:
            await review(db, imported.version_id)
        assert "secret" not in str(exc.value)
    asyncio.run(scenario())


def test_dates_and_offsets_round_trip_in_sqlite(db, bundle):
    def add_dates(units):
        unit = next(u for u in units if u["unit_id"] == "KG.REG.EXEMPT.GRC")
        unit.update(effective_from="2026-01-01", effective_to="2026-12-31", verified_by="reviewer",
                    verified_at="2026-10-07T12:00:00+06:00", review_due_at="2026-11-07T08:00:00Z")
    change(bundle, "units.yaml", add_dates)
    async def scenario():
        imported = await do_import(db, bundle)
        assert imported.accepted
        result = await review(db, imported.version_id, baseline_id=imported.version_id)
        assert result["summary"]["unchanged"] == 14
    asyncio.run(scenario())


def test_real_draft_reports_unresolved_work_and_cli_preserves_database(db, tmp_path):
    pdf = ROOT.parent / "Kyrgyzstan-visa-knowledge-base-v1.1.pdf"
    if not pdf.is_file():
        pytest.skip("original PDF needed for real source import")
    async def scenario():
        imported = await do_import(db, ROOT / "knowledge/kg_entry/draft-v1.1", source=pdf)
        result = await review(db, imported.version_id)
        assert result["summary"]["added"] == 208 and result["baseline"] is None
        assert result["status_counts"] == {"blocked": 3, "decision_pending": 22, "needs_verification": 183}
        assert result["finding_counts"]["value_missing"] == 82
        assert result["finding_counts"]["owner_unassigned"] == 208
        assert result["finding_counts"]["not_confirmed"] == 208
        assert not result["source_reverified"] and not result["publication_approved"]
        return result
    expected = asyncio.run(scenario())
    database = Path(db[0].url.database)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    result = subprocess.run([sys.executable, "-X", "utf8", "scripts/review_kg_entry_local.py", "--db", str(database),
                             "--set-id", str(db[1]), "--candidate", "1"], cwd=ROOT, capture_output=True,
                            text=True, encoding="utf-8", timeout=30,
                            env={**os.environ, "ALEMBIC_DATABASE_URL": "postgresql+asyncpg://invalid.invalid/no"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {"ok": True, **expected}
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before


def test_cli_missing_database_does_not_create_it(tmp_path):
    missing = tmp_path / "not-created.sqlite3"
    result = subprocess.run([sys.executable, "scripts/review_kg_entry_local.py", "--db", str(missing),
                             "--set-id", "1", "--candidate", "1"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 2 and not missing.exists()
    assert json.loads(result.stdout)["code"] == "review_unavailable"
