# Independent review packet — E5-03E

- CRITICAL / solo; completion target local implementation, no release.
- Base `6d24227b2e206308bb8921dc8efc5130c5174c7a`, branch `fix/tours-search-quality`.
- Target: current uncommitted snapshot; manifest `2026-10-09-e5-03e-qualification-snapshot.json`.
- Reviewer / final auditor **UNKNOWN**. Read builder SELF_REVIEW/handoff only after own assessment.

Requirement: task `ai/tasks/2026-10-09-e5-03e-qualification-storage.md` A1–7;
original PDF physical page 2 (IT instruction), §2.1, slots Б.3/block18; E5-02 schema
EntryQualification design and E5-03D input contract. Actual contract:
`docs/e5-03e-qualification-storage.md`. Evaluate this bounded partial-profile scope,
not full handoff or client eligibility. No independent approval is supplied here.

Inspect `app/domain/qualification_storage.py`, refactor `entry_qualification.py`,
new `EntryQualification` and immutable guard in `models.py`, static migration
`e5_qualification_0016.py`, new storage/migration tests and legacy metadata expectations.
Include neighbouring `_transaction`, `_history`, `_bundle`, projection verification,
strict request schema and qualification evaluator.

| Acceptance | Adversarial checks |
|---|---|
| A1/A2 | latest and explicit id, previous revision, complete replacement, unknown vs false, recomputed result |
| A3 | retry after later revision, changed payload/history/KB, CAS, concurrent same/different keys, partial failure and uncertain commit |
| A4 | authorize before engine/input, two-contact isolation including DB FK, no arbitrary PII/decision/history input |
| A5 | request/result/author/time/previous/source integrity; read old result vs replay runtime/result drift |
| A6 | additive DDL and schema parity, populated/offline downgrade refuses before drop, migrated DB API |
| A7 | shared domain and full suite regressions, baseline distinction |

Review permission is read-only plus isolated synthetic local tests. No production,
real client imports, deployment, external messages or transfer of private repository data.
PostgreSQL runtime/concurrency requires a separately approved disposable environment;
offline SQL compilation does not establish those claims. Secret values must not enter evidence.

Suggested command: `python -m pytest tests/test_qualification_storage.py tests/test_qualification_migration.py tests/test_kg_qualification.py -q`.
Record actual revision/commands and findings; manifest and builder results are not approval.
