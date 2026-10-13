# FINAL AUDIT: E6-23 — C01/C02/C03 calculation and retained replay

- Task: `ai/tasks/2026-10-12-e6-23-calculation-review.md`.
- Risk/mode/target: CRITICAL / solo / reviewed local behavior.
- Auditor: separate agent `/root/publication_review`; independent arithmetic reviewer: `/root/calculation_review`; implementation owner: `/root`.
- Independence: **INDEPENDENT**. This auditor did not build or perform the first arithmetic review. Task, fixed criteria, source contracts and actual arithmetic/storage code were inspected before the independent review report and its conclusions.
- Final verdict: **GO**, scoped to C01, C02 and C03 at the identities below. No confirmed blocker within those three fixed criteria.

## Target and source identity

Auditor-created env-free Git archive: revision `87ad9e7`, extracted to `runs/calculation-final-audit-20261012/source`. Archive SHA-256: `37c4fc3a60c4a766cce1ebe4bba3bfadd8f5b52732de4c33859475cd212fe24d`. No `.env` was copied. Reviewer/auditor probe files are confined to ignored `runs` directories; no application, configuration or repository test files were changed by this audit.

Verified 14 full files against both `8062f80` and the current working tree using LF-normalized content: stay/deadline arithmetic, their schemas, work calendar, storage schema, history/calculation storage, source snapshot validation, bundle/review validation helpers and migration `e5_calculation_0015`. The calculation runtime is unchanged. Eleven relevant model classes/immutability hooks were separately compared by their parsed syntax trees and are also unchanged; the unrelated publication constraint explains the different whole-model-file revision. Exact identities are recorded in `runs/calculation-final-audit-20261012/identities.json`.

Requirements inspected: CALC-02/03/05 and AC-19/20/21/22 in `docs/spec-crm-frunze-getvisa-2026-10-03.md`, the E5-03A/B/C scoped contracts, and supplied-source corpus fragments `KG.KB.2.1`, `KG.KB.2.9`, `KG.KB.13.2`, `KG.KB.13.3`. Their text hashes match their stored identities. The actual sibling file `Kyrgyzstan-visa-knowledge-base-v1.1.pdf` was present; its computed SHA-256 matches the corpus: `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`. Evidence is in `runs/calculation-final-audit-20261012/source-identities.json`. This proves artifact identity, not legal currency or owner approval.

## Critical acceptance and recovery

| Criterion / risk | Audit result | Evidence and interpretation |
|---|---|---|
| C01 — overlaps and rolling-window boundaries | PASS | Inclusive union counts a calendar date once. Each planned date is tested, including an intermediate excess that can disappear by the final date. The auditor's independent materialized-day-set oracle covers 64 additional closed-history scenarios with overlaps, mixed legal bases, uncertain confirmation/passport context and all entry/exit inclusion combinations. |
| C01 — incomplete or malformed context | PASS | Strict schemas and chronology reject malformed snapshots and contradictory open visits. Missing history completeness and passport/basis uncertainty remain visible. Proposed arithmetic never sets exact remaining days, selects a regime or grants quote permission. Open continuation evidence was inspected in the independent review's additional 120-case oracle. |
| C02 — calendar and unit semantics | PASS | Calendar versions and overrides are explicit; no office-week fallback substitutes for a missing year. The auditor's 40-case independent workdate-list oracle uses a nonstandard Friday/Saturday rest pattern, overrides and before/after calculations across New Year. Provisional coverage returns no partial result. Month vectors distinguish direct calendar addition from thirty-day arithmetic or iterative clamping; elapsed-hour vectors verify UTC arithmetic and Bishkek display. |
| C03 — pinned immutable history and sources | PASS | Named administrator boundary, contact-scoped source links, strict stored requests, immutable snapshots and source/calendar hashes were inspected. Both old stay and old deadline results replay unchanged after new history/calendar revisions in the auditor's SQLite and PostgreSQL runs. Caller facts cannot silently replace stored facts. |
| C03 — retry and transaction recovery | PASS | Actual PostgreSQL rerun verifies competing history revisions, identical calculation requests, a lost calculation commit acknowledgment reconciled without duplication, and rollback when a child calendar-link insert fails. These tests use fresh migrated synthetic databases, not production data. |
| C03 — changed runtime/result | PASS | Runtime drift refuses verified replay while preserving the integrity-checked original readable result. An unannounced arithmetic output change also refuses verified replay. This prevents silently presenting a recalculation under changed code as the historical result. |
| Retention / migration recovery | PASS within local scope | Migration and model constraints were inspected. Populated downgrade refuses to remove stored calculation data; independent reviewer migration/negative evidence is recorded separately. Audit PG cases start from the actual migrated schema. No production restoration or backup claim is made. |

The technical boundaries match the fixed criteria: this is deterministic scenario arithmetic and retained replay, not a personal admission decision. The supplied source also requests approved examples and specialist handling; approval of counting conventions and the executable individual qualification workflow remain separate work.

## Evidence actually executed by this auditor

Environment: Windows, Python 3.12, env-free archived code, synthetic SQLite and explicitly configured PostgreSQL 16 on `127.0.0.1:55971`. The validated fixture uses fresh uniquely named migrated databases and cleans up only those databases. No credentials, personal records, customer messages or production services were used. Suites ran sequentially.

Commands from `runs/calculation-final-audit-20261012/source`:

| Command | Actual result | Coverage limit |
|---|---|---|
| `python -m pytest tests/test_calculation_final_audit.py -q --basetemp=../pytest-audit --tb=short` | **12 passed**, 15.63 seconds | Auditor-authored arithmetic oracles/vectors and bounded SQLite source/replay scenarios; not the whole repository suite. |
| `python -m pytest tests/test_calculation_final_audit_pg.py -q --basetemp=../pytest-audit-pg --tb=short`, with `FRUNZE_LOCAL_PG_CONNECTION` explicitly naming the private local rehearsal file | **5 passed**, 28.65 seconds | Actual PG concurrency, lost acknowledgment, partial-write rollback and old history/calendar replay. One existing Starlette/httpx deprecation warning, no failures or skips. |

Auditor total: **17 passed**, zero failures/skips. New probe files and identity reports remain under `runs/calculation-final-audit-20261012`.

## Independent review evidence assessed

Read `ai/reviews/2026-10-12-calculation-independent-review.md` after the first source/code assessment. Its reported **246 existing checks + 1 additional oracle + 31 actual PostgreSQL checks = 278 passed** are the reviewer's evidence, not additional executions by this auditor. Both reviewer probe-file SHA-256 identities were independently verified before their contents/fixtures were used to assess the claim. The reviewer reported no implementation correction or confirmed open defect, consistent with this audit's code inspection and bounded reruns.

## GO boundary and remaining limitations

**GO for reviewed local C01/C02/C03 behavior.** Separate independent review and final audit now exist for those criteria; no source/runtime correction was necessary.

- Contact-scoped history is not an individual applicant history bridge. C05 is not assessed, completed or scored by this audit.
- Real source/calendar approval, counting policy, rule applicability and owner-approved legal examples remain unapproved. Tests use proposed policies and synthetic calendars; computation does not make them authoritative.
- Hashes and ORM immutability provide consistency checks within the trusted storage boundary, not protection against an administrator rewriting both data and all matching evidence through privileged SQL.
- No full repository/browser suite, production backup/restore, deployment, pilot authorization or business acceptance is claimed. The local review target does not require those actions.

Any later change to the identified arithmetic, schemas, storage/replay code or their model constraints needs a new scoped assessment. This GO does not authorize release.
