# E6-07A — recorded knowledge review evidence

- STATUS **PARTIALLY_READY**, CRITICAL / solo, local target. Branch `fix/tours-search-quality`; code `29c27ab3a26be9eb075e53645050e5308678d785`.
- Task `ai/tasks/2026-10-10-e6-07a-knowledge-decisions.md`: immutable version/unit-scoped confirmation, rejection and correction evidence. Typed proof/reference/reason/date, explicit next-review date, expired-state indication, actor/hash/CAS/exact retry. New source versions do not inherit findings; recording a finding never edits original values/labels/conflicts or publishes them.
- Native catalog/version/search/pagination, source/review history, readonly past decisions, lost-ack retry even after failed reread, mobile390/desktop1365 without JS and one-page print. Existing full-admin/KG-OFF/workday/write/CSRF gates retained. No roles, automatic review period, source truth or legal approval invented.
- Additive `e6_kb_decisions_0023`; composite source/previous FK, immutable ORM/bulk protection, model parity and populated/offline downgrade refusal. All real208 source units remain drafts;22 actual typed deadline values remain NULL.

## Evidence

Exact Git archive `runs/e6-07a-final`, no env files. Command:

`python -m pytest tests/test_knowledge_decisions.py tests/test_admin_kg_knowledge_decisions.py tests/test_knowledge_decisions_migration.py tests/test_knowledge_import.py tests/test_knowledge_review.py tests/test_knowledge_projection.py tests/test_knowledge_migration.py tests/test_knowledge_projection_migration.py tests/test_admin_kg_knowledge.py tests/test_alembic_domain_migration.py tests/test_service_cases.py tests/browser_kg_knowledge_decisions.py -q --tb=short -ra`

**PASS:229 passed /4 skipped /3 deprecation warnings /122.07s.** Initial skips:2 missing relative original-PDF fixtures and2 unavailable PostgreSQL runtime. Raw local `final-check.log` is PowerShell UTF16.

Then copied the provided source PDF read-only into ignored `runs/` at the relative fixture path, without changing source/code; SHA matches `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`. Ran only those two skipped cases:

`python -m pytest tests/test_knowledge_import.py::test_real_pdf_bundle_round_trip tests/test_knowledge_review.py::test_real_draft_reports_unresolved_work_and_cli_preserves_database -q --tb=short -ra`

**PASS:2 passed /6.09s**, `runs/e6-07a-final/real-pdf-check.log`. This verifies lossless208-unit import/diff and preserves draft marks (3 blocked/22 decision_pending/183 needs_verification), not legal source validity. PostgreSQL remains untested.

Manifest `ai/reviews/2026-10-10-e6-07a-knowledge-decisions-snapshot.json`:14 files match Git/workspace/archive after CRLF→LF normalization, raw hashes retained. Cold imports `app.admin.kg_knowledge_decisions`, `app.admin.kg_knowledge`, `app.main` exit0. Syntax/whitespace PASS. Mobile, desktop and one-page source/history print inspected. Initial development21 domain +5 HTTP +5 migration/browser pass; no runtime defects were found in that focused cycle.

## Review and continuation

SELF_REVIEW packet `ai/reviews/2026-10-10-e6-07a-knowledge-decisions-packet.md`; independent reviewer/final auditor UNKNOWN, PostgreSQL runtime/recovery UNKNOWN. No production/publication/client data/messages/permissions changes. Full suite not rerun; known earlier tour-date baseline failure remains.

D03 technical acceptance +2, fixed score57/100. Parent70-point goal ACTIVE; do not stop here. Next `ai/tasks/2026-10-10-e6-07b-knowledge-publication.md`: atomic review/approval/activation/rollback, explicit absent-by-default publication authority and runtime per-rule eligibility. KB-04 requires other still-confirmed rules to keep working when one becomes stale; no blanket promotion or disabling of the whole source because one unit fails. Current report PDF still records the previous51-point checkpoint; consolidate it before the final goal report.
