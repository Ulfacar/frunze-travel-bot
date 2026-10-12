"""Actual isolated PostgreSQL; same publication-to-answer scenarios as SQLite."""
from tests.test_entry_process_postgres import connection, database, db_url, template, env
from tests.test_knowledge_publication import release
from tests import test_knowledge_answers as cases
from tests.test_knowledge_answers import source_clock


def test_literal_readonly_postgres(release):
    cases.test_literal_answer_retains_deadline_and_window_without_writes(release)


def test_unavailable_matrix_postgres(release):
    cases.test_mixed_unpublished_rejected_withdrawn_and_revoked_policy(release)


def test_current_version_expiry_postgres(release, tmp_path, monkeypatch):
    cases.test_current_version_and_exact_expiry_boundary(release, tmp_path, monkeypatch)


def test_corrupt_clock_postgres(release, monkeypatch):
    cases.test_corruption_and_clock_regression_never_resurrect_source(release, monkeypatch)


def test_all_semantic_families_postgres(env, tmp_path):
    cases.test_every_supported_family_is_read_from_actual_publication(env, tmp_path)


def test_draft_predicates_postgres(env, tmp_path):
    cases.test_imported_draft_condition_catalog_cannot_be_quoted(env, tmp_path)


def test_incomplete_semantics_postgres(env, tmp_path):
    cases.test_approved_incomplete_scope_anchor_and_template_fall_back(env, tmp_path)
