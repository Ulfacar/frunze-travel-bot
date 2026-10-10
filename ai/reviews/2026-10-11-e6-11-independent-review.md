# E6-11 — independent review of frozen r2

- Task: `ai/tasks/2026-10-11-e6-11-portal-notifications.md`.
- Reviewer: `/root/portal_pre_audit`; builder: `/root`; **INDEPENDENT**. Requirements, prior findings and actual frozen code were examined before relying on runtime evidence. Test results below were produced by this reviewer, not inherited from builder.
- Base: `e9e7c351b493aeb5d78e09f3ccf907107c73a919`.
- Target: uncommitted 19-file snapshot `runs/e6-11-review-r2`.
- Manifest: `ai/reviews/2026-10-11-e6-11-r2-snapshot.json`, SHA256 `27ca58e04330ab3be8eb4a7cf9b7a5fe69fa1f3cd4f7f2a686f6f83621f285a8`.
- All **19/19 LF-normalized hashes match**, before testing and after domain/runtime checks. Snapshot root contains no `*.env`. Reviewer did not edit source, frozen archive files, policy, production, Git or server. Writes were review artifacts, synthetic local test data and this report.

## Verdict

**APPROVE for the reviewed local synthetic E6-11 scope (I03/I04/I05).** No blocking defect remains in this snapshot based on the inspections and independent checks below. Both preliminary findings are closed with positive and negative runtime evidence.

This is an independent implementation review, not the separate final audit required by the protocol. It does not approve real source mappings, privacy/retention policy, real mailbox integration, customer sending or production release. Those remain **UNKNOWN / outside this review's authorized scope**. No deployment was performed.

## Preliminary findings closed

| Finding | Final implementation | Independent evidence | Result |
|---|---|---|---|
| Distinct same-day manual correction cycles collide | Canonical manual observation retains channel and explicit archive reference/proof. Applied-content identity uses the structured observation and archive proof, excluding the renameable archive location and transport ID. Pasted notifications retain exact-byte content dedup | SQLite and PostgreSQL `test_distinct_manual_source_evidence_can_confirm_new_same_day_cycle`: different evidence on a new cycle succeeds; old proof with renamed archive/transport is blocked. Original exact pasted-content duplicate test also passes | **PASS** |
| Public writer opens engine/session before authorization | Public `record_application_event` calls shared `_validated_event_input` before `_run`; same-session helper repeats that defense before locks/reads | All five `test_named_full_admin_precedes_engine_access` actors pass in the independent application regression run; helper still preserves event validation, case/application locks and task sync | **PASS** |

## Requirement and risk coverage

| Requirement / failure mode | Evidence and conclusion |
|---|---|
| I03: correlate imported notification and retain evidence | Bounded literal parser captures reference/kind/date without storing the full message body; policy snapshot, source namespace, transport ID, archive reference/proof and content hash are immutable. Global reference claim is checked against the requested case and validated application history. Unknown/ambiguous/foreign/unclaimed input remains unbound. Five observation kinds do not themselves create application/payment/process facts. **PASS, synthetic source policy only** |
| I04: duplicates and out-of-order recovery | DB transport/content uniqueness; exact-key content matching before fresh policy/CAS; current head and submission-cycle pins; terminal-state rejection; late return cannot regress an approved application; same-byte notification cannot apply again after resubmission. Manual evidence identity correction is covered above. **PASS** |
| I05: manual fallback | Manual source has explicit channel authority independently of paste enablement; recording an observation remains separate from named full-admin confirmation with date, verification reference/proof and current-cycle assertion. It works with paste disabled and no mailbox. Verification/payment observations do not become monetary or submission facts. **PASS** |
| Atomic confirmation | Existing application helper, enabled deadline-task hook and receipt action share an owned transaction with case/application locks. Faults after either half and after the actual enabled task hook roll back all effects. Before/after commit failures recover through original request. **PASS on SQLite and PostgreSQL** |
| Competing ordinary writer | Reviewer-owned PostgreSQL race runs ordinary `record_application_event(refused)` against portal `confirm(approval)` at the same expected application head. Exactly one succeeds, one conflicts; application has one new revision and receipt has no partial confirmation. **PASS** |
| Semantic replay and later advancement | Current binding is checked before new confirmation; historical binding reconstructs the pinned head/cycle. Reviewer rehashed a correlation command/snapshot to use the wrong existing submission cycle: read rejects it. Old applied confirmation retry after a new submission and policy removal returns the original result and leaves the new head unchanged. **PASS** |
| Bounds / recovery | Parser input limits, 64-action limit, reserved final disposition, keyset growth, and bounded history. Reviewer forced the byte limit below the action limit: write rejects before unreadable history and policy-free authorized dismissal still succeeds. **PASS** |
| Domain authorization and native gates | Named full admin; no system/bot identity; existing KG OFF, workday and write gates precede action; signed case/target/revision/policy/namespace/binding envelope; strict fields, duplicate rejection and body bounds. Default real policy is empty. **PASS** |
| Native failure/retry UI | Actual form receive → correlate → confirm; exact repeat; no-JS desktop and mobile. Lost-ACK form retains the exact envelope even when reread also fails. Empty/unavailable/foreign-record and tampered-form paths checked. **PASS** |
| Schema and recovery | Additive JSON tables, scoped application/head/cycle/event FKs, uniqueness and immutable guards. SQLite and PG migration/model parity, empty cycle and populated downgrade refusal. Populated PostgreSQL binary COPY restore to fresh migrated DB preserves receipt/action/application/task histories and sequence state, then supports exact retry, native read and a new receipt/action. **PASS for this local recovery method** |

Hashes validate stored consistency, not authenticity of an external sender or the truth of an operator assertion. The interface explicitly separates incoming information from a confirmed application fact. Independent proof fields are operator-recorded evidence, not a portal digital-signature verification system.

## Independent commands and results

Unless stated otherwise, commands ran with cwd `runs/e6-11-review-r2` on Windows / Python 3.12. SQLite and browser tests used repository synthetic fixtures and network guard. PostgreSQL commands used the existing guarded harness with fresh random databases on **127.0.0.1:55971**, actual PostgreSQL 16; no production DSN or data was used. No credentials were printed or written to this report.

| Command / scenario | Result | Artifact |
|---|---|---|
| Manifest SHA256 and 19 source comparisons; repeated source identity check after runtime work | **PASS 19/19** | Manifest above |
| `python -m pytest tests/test_entry_portal.py tests/test_entry_portal_parser.py tests/test_entry_applications.py tests/test_admin_kg_portal.py tests/test_entry_portal_migration.py tests/browser_kg_portal.py -q --basetemp=../../runs/e611-independent-r2-sqlite --junitxml=../../runs/e611-independent-r2-sqlite.xml` | **117 passed, 0 failed/skipped, 3 deprecation warnings, 219.42 s** | `runs/e611-independent-r2-sqlite.xml` |
| From repo root: `python runs/e610_legacy_pg_probe.py runs/e6-11-review-r2 tests/test_entry_portal_postgres.py -q --basetemp=../../runs/e611-independent-r2-pg --junitxml=../../runs/e611-independent-r2-pg.xml` | **12 passed, 0 failed/skipped, 1 deprecation warning, 81.84 s** | `runs/e611-independent-r2-pg.xml` |
| From repo root: `python runs/e610_legacy_pg_probe.py runs/e6-11-review-r2 ../../runs/e611_independent_adversarial.py -q --basetemp=../../runs/e611-independent-adversarial --junitxml=../../runs/e611-independent-adversarial.xml` | **4 passed, 0 failed/skipped, 1 deprecation warning, 36.82 s** | Reviewer-owned `runs/e611_independent_adversarial.py`; `runs/e611-independent-adversarial.xml` |
| Fresh subprocess imports `app.admin.kg_portal`, `app.domain.entry_portal`, `app.main` | **PASS, all exit 0** | Actual cold-import command; not inferred from pytest imports |
| Browser artifacts viewed by reviewer | **PASS** | `runs/e6-11-review-r2/runs/e6-11-portal-browser/`: `portal-confirm-390.png`, `portal-retry-390.png`, `portal-390.png`, `portal-1365.png`, `portal-print-1.png` |

Total independently executed tests: **133 passed**. These are focused E6-11 and affected-path checks, not a claim that the entire repository suite was run in this review. Warnings concern existing Starlette/httpx and websockets deprecations.

The native print is **one nonempty A4 page**, visually read and legible. Mobile 390 and desktop 1365/no-JS preserve the completed state, retry action, source summary and history without horizontal overflow. The full-page screenshot taken after focusing the mobile confirmation form shows the existing sticky navigation at the current scroll offset; completed/retry screenshots and actual browser flow remain usable.

## Local recovery evidence

The independently generated sanitized packet is `runs/e6-11-review-r2/runs/portal-postgres-recovery.json`:

- Method: PostgreSQL binary COPY from a consistent read-only snapshot, fresh Alembic schema, foreign keys enabled, restored sequences.
- Archive size **18,368 bytes**, SHA256 `34b96410ee8e6d9ace98bb980717f42e06067bf99a42d36afbcd104087659bde`.
- All restored table counts match; receipt/action history and enabled deadline-task history compare equal.
- Original confirmation retry with missing current policy returns the original result.
- Fresh native read returns HTTP 200 **and the expected confirmed state text**; a new receipt and confirmation can be appended after restoration.
- Native `pg_dump` was **not run by this reviewer**; this report does not claim pg_dump or production backup verification. The test packet's pre-existing App Control note is not independent evidence of that cause.

## Nonblocking usability follow-ups

The server correctly rejects already-applied content, but `can_confirm` does not precompute that duplicate reason; an operator may discover it on submit and then close the duplicate. Consider showing that known reason before submission. Also, historical verification reference/proof is preserved by the domain API but the compact native history currently displays only disposition/actor/time; exposing those details would improve operational audit convenience. Neither issue changes a fact, weakens the server checks, or blocks the agreed local acceptance paths.

Real source phrase approval, actual archive/privacy authority, mailbox connectivity, production performance, real-user acceptance and a release decision remain **UNKNOWN**. No approval for those is implied by this **APPROVE**.
