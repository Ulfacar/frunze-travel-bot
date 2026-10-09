# HANDOFF: E6-02B — document metadata inventory

- STATUS: **PARTIALLY_READY** (required independent critical review/audit UNKNOWN).
- CLASS / MODE: CRITICAL / solo. Task `ai/tasks/2026-10-10-e6-02b-document-inventory.md`.
- Branch `fix/tours-search-quality`; code `5feb4e03da07b98a9526b0433738634cfb903494`;
  fixed goal/baseline commit `3d68d42`. Completion target: local implementation and review packet.
- Parent70-point goal remains ACTIVE. Do not finish the overall task at this checkpoint.

## Outcome and files

Per-application immutable inventory now records exact checklist definition,
received file fingerprints/versions, review/correction/withdrawal, conditional
applicability and passport-change invalidation. Native CRM has history/print,
safe conflict/error handling and exact retry after uncertain commit. One additive
table; no actual files, personal data, new permissions or production migration.

Receipt is not review. Whole package is never accepted by this slice; complete
supplemental requirements and publication policy remain separate work. Historical
checks stay reproducible without relying on the current source catalog.

## Evidence

Windows/Python3.12; isolated Git archive `runs/e6-02b-inventory-final`, no env files.
Command:

`python -m pytest tests/test_entry_documents.py tests/test_entry_documents_migration.py tests/test_admin_kg_document_inventory.py tests/test_entry_applications.py tests/test_admin_kg_applications.py tests/test_entry_group_overview.py tests/test_admin_kg_group_overview.py tests/test_alembic_domain_migration.py tests/test_service_cases.py tests/test_pdf_engineering_progress.py tests/browser_kg_document_inventory.py -q --tb=short -ra`

**210 passed /2 skipped /3 dependency deprecation warnings /242.76s**. Both skips
explicitly require a dedicated PostgreSQL test DSN. No PG runtime PASS claimed.
Scenarios cover real SQLite FK enforcement, cross-case access, stale edits,
duplicate/concurrent writes, lost commit acknowledgement, malformed/oversized
history, rehashed forged review, source unavailability, gates/CSRF/body limits,
native mobile390 and desktop1365 without JavaScript, history and print.

Snapshot manifest `ai/reviews/2026-10-10-e6-02b-inventory-snapshot.json`: **22/22**
changed files match Git/workspace/archive after explicit CRLF/LF normalization;
raw Git/archive hashes retained. Staged whitespace/token-shape scan/compilation PASS.
Initial three-page print visually inspected; final browser unchanged apart from
validation-error selected-option preservation, which is tested through native HTTP.

Full suite at `5feb4e0`: `python -m pytest tests -q --tb=short -ra` —
**3732 PASS /3 FAIL /13 SKIP /1 warning /1092.43s**. Raw local log:
`runs/e6-02b-inventory-final/full-suite.log`. Two failures are legacy shell smoke
lists expecting200 from OFF process/document preview routes; both reproduced at
baseline `f0d9efa` (2 FAIL /17.23s), then fixed in `8e9ab4f` with explicit OFF/ON
coverage (7 PASS /26.61s). Third is the known tour-date fixture in
`tests/test_facts_live_errors.py::test_still_reads_a_plain_request`; outside this
scope; reproduced at baseline `f0d9efa` (1 FAIL /0.47s). No unrelated runtime behavior changed. The original full suite remains
recorded as FAIL; selected fixes do not turn it into a claimed all-green rerun.

## Review and remaining gates

SELF_REVIEW packet `ai/reviews/2026-10-10-e6-02b-inventory-packet.md` documents the
actual challenges and reason-preservation fix. Not an independent review.
Required independent reviewer, final auditor and PostgreSQL runtime/recovery UNKNOWN.
Docker Linux engine pipe absent at local check. Real-data DEC-06 and approved
source/process/role decisions remain unresolved. Hash checking is not protection
against a database administrator replacing the entire chain.

## Resume

F02/F03 now have technical evidence: fixed engineering score **41/100**; critical
slice still PARTIALLY_READY. F04/F05/F06/F07 remain UNKNOWN. Continue source-template
rendering (E6-03A), then complete conditional documents/package evidence and linked
workflow/deadline tasks. Preserve unrelated untracked user artifacts. No production
release, environment change, external messages or real client-data use authorized.
