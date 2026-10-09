# Fixed baseline evidence — PDF/CRM engineering

- Revision: `f0d9efa2a63c62dbfe34c239ec4a9b529c65ca01`.
- Branch: `fix/tours-search-quality`; environment: Windows / Python 3.12,
  isolated Git archive `runs/pdf-to70-baseline`, synthetic SQLite only, no env files.
- Definition digest: `3a26373ae606cb6bba64adf1bd41fd8efb7a767663523d328cbd166aca219f4a`.
- Measurement is prospective and fixed; historical “about30%” was an estimate.
  Evidence records test execution observed through the tool, not a CI run.

## Observed checks

1. `python -m pytest tests/test_kg_search_corpus.py tests/test_kg_entry_validation.py tests/test_kg_entry_source_bundle.py tests/test_kg_retrieval.py tests/test_kg_stay_days.py tests/test_kg_deadlines.py tests/test_knowledge_import.py tests/test_knowledge_review.py tests/test_knowledge_projection.py tests/test_entry_storage.py tests/test_qualification_storage.py tests/test_qualification_card.py tests/test_entry_applications.py tests/test_entry_group_overview.py tests/test_kg_document_checklist.py -q --tb=short`
   — **752 passed, 3 skipped, 1 warning, 247.32s** (tool session36939).
   Selected passing cases cover extraction/source integrity/schema/retrieval,
   calendar and interval arithmetic, pinned calculation/qualification histories,
   import/index, application facts/group overview and typed document matrix.
   Skips provide no PostgreSQL evidence.
2. `python -m pytest tests/test_admin_kg_entry.py tests/test_admin_kg_intake.py tests/test_admin_kg_knowledge.py tests/test_kg_intake.py tests/test_kg_qualification.py -q --tb=short`
   — **166 passed, 1 warning, 116.46s** (tool session48944).
   Passing cases exercise native search/citations and RU/EN qualification storage
   with source uncertainty, guards, invalid input, stale versions and retry.

## Acceptance mapping

Fully supported technical criteria: A01–A04 (14), B01 (3), C01–C03 (6),
D01–D02 (4), E01–E03 (6), E05 (2), F01 (2): **37 /100 points**.
E05 is demonstrated by `test_revision_loop_same_attempt_refusal_linked_retry_and_independent_new_root`,
scope/previous-link rejection, immutable history and exact retry tests; it does
not claim all four complete procedural workflows or source rule approval.
Other criteria remain UNKNOWN, including publication, applicant-specific intake,
complete conditional document packs, files, tasks, dialog and integrations.

This is a technical baseline assessment, **not independent critical review**.
Review fields stay UNKNOWN; prior critical slices remain PARTIALLY_READY.
No source approval, PostgreSQL runtime, deployment or owner acceptance is inferred.
Docker daemon checked locally2026-10-10: Linux engine pipe absent. PostgreSQL
runtime/recovery remains UNKNOWN; DDL compilation is not a substitute.
