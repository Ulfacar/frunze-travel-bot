# E6-09 independent review — 2026-10-11

Reviewer: independent agent `/root/package_review`. Risk: CRITICAL. Protocol mode: solo. Target: reviewed local implementation, not a production release.

Final review verdict: **APPROVE for the exact local snapshot below**. Initial verdict was **FIX_REQUIRED**. Two confirmed routes could represent quarantined content as checked; both are corrected and independently retested. No remaining confirmed blocker was found within this review scope. This is an independent review, not the builder's self-review or a substitute for the separate final audit.

## Scope and independence

Read the E6-09 observable acceptance and explicit database-storage amendment before assessing implementation. The amendment supersedes the original filesystem approach: immutable database BLOB/BYTEA storage, no temporary upload files or filesystem cleanup. Inspected actual code and relevant tests before reading builder conclusions; did not read the E6-09 auditor's report. Later builder messages disclosed fixes and the auditor's integrity findings. The issued-journal question was raised by the builder and then independently reproduced by this reviewer; it is not claimed as an independently discovered issue.

Review covered policy, bounded multipart parsing, byte classification/checksum, receipt and package transaction, duplicate/retry/concurrency/quota handling, global quarantine enforcement, matrix and issued-journal integration, native forms, and additive migration. Work used only synthetic data in the env-free `runs/e6-09-local` archive. No production, external data, secrets, deployment, Git mutation, or source edits were performed. This report is the only repository file written by the reviewer.

## Exact reviewed snapshot

- Base revision: `419fe40cca04f8ed9c65e0386c48c18764c32424`.
- Reviewed revision: `4c570a3408d21d1749543c1144eabf4cdc6a20fa`, 25 source/test files. Tests ran on its identical uncommitted candidate; the builder subsequently committed it without source changes.
- Manifest: `ai/reviews/2026-10-11-e6-09-reviewed-snapshot.json`.
- Manifest SHA256, CRLF normalized to LF: `642fb94f3b085dc5510af3b22cc1eaf6306fcb62c4fb623be8ca08197ff750c4`.
- Manifest SHA256, raw bytes: `59df42952e21127ec8ae7acfd49059a0730386f2d9e1708ce0c6592f1a13ed40`.
- Independently recalculated all 25 normalized file hashes in the workspace, env-free archive, and committed Git blobs: **PASS**, all match the manifest. The final manifest update added the committed revision; the source hashes did not change.

Selected final hashes, also contained in that pinned manifest:

| File | SHA256, normalized LF |
| --- | --- |
| `app/domain/entry_document_packages.py` | `bbc6b72e761f677c33bc7e530bdfd468b3d369c1144616b633ea34b7a20fde4b` |
| `app/domain/entry_documents.py` | `4164fb1ca9b1819d64e19904c37aa15ea5874ba3d297e3bb020d9732f8c57e7b` |
| `app/domain/entry_issued.py` | `ef50eadfce8b1c45354eb8fa692df2de02a060cec5b3e91cca75ac5cb312337b` |
| `app/domain/entry_quarantine.py` | `3c5def4a7ac489c8e5a718dd3b2d53a8baed09c223d529ef4cffa05cd2e3f7a0` |
| `app/domain/entry_quarantine_policy.py` | `e40651f2353a63ac38a487249565411bf74f7fd8d738076ff328a758d472f0b8` |
| `app/admin/kg_document_quarantine.py` | `1c0e2219903977cca33fddaf6a0b5943c32a23c6096412562929b9136f7e0850` |
| `tests/test_entry_quarantine.py` | `f44fad383d8b2e95892ddd691d87f7064a5aeafc2f1d71f90e39d66819aeee8a` |

## Confirmed defects and correction evidence

### P1 — quarantine could be bypassed through another application — FIXED

Initial location: `app/domain/entry_document_packages.py`, write/read quarantine checks around lines 203–209 and 239–248 in the initial candidate. The fingerprint set came only from the selected application's binary metadata.

Trigger: upload a PDF to application A, then manually record the same SHA256 as a document in application B, check it, and approve B's complete package. The initial synthetic reproduction returned accepted=true for B while A's receipt remained quarantined. This defeats the requirement that retained quarantined bytes cannot acquire review/approval through metadata re-entry.

Correction: `quarantined_fingerprints` at final lines 137–153 queries bounded exact fingerprints against immutable reserved upload receipts across applications. It exposes no other application's identity or binary content. Public metadata writes cannot use reserved upload keys. Package review/approval and current acceptance use this guard; historical snapshots remain intact. Matrix review and effective read state use the same guard. A surviving upload receipt continues to deny acceptance if its binary row is lost.

Independent retest: the original synthetic database at `runs/e6-09-local/reviewer-quarantine-scope-data/domain.db` was reopened after the fix. Its previously persisted approval remains present historically, but current acceptance is exactly `accepted=false, reason=document_in_quarantine`. Cross-application, legacy matrix, and missing-binary regression tests also passed. An independent in-memory probe with no package-event table returned an empty quarantine set, preserving pre-0025 compatibility.

### P1 — issued journal could mark quarantined bytes checked and delivered — FIXED

Initial location: `app/domain/entry_issued.py`, `record_issued_operation` around lines 60–86 and `_view`/`read_issued_history`. These paths had no quarantine guard.

Trigger: upload a PDF to application A; in an approved application B, register the same fingerprint as the issued file, confirm all review checks, record all three delivery channels, and record an identity-checked receipt. Independently reproduced in `runs/e6-09-local/reviewer-quarantine-issued-probe/domain.db`: A remained quarantined while B returned `verification_current=true`, `delivery_complete=true`, and `receipt_current_and_checked=true`.

Correction: new issued review/delivery/receipt operations reject globally quarantined file or passport fingerprints. The shared async `_effective_view` overlays quarantine on every service result, including fresh writes, exact retries, and historical reads, without changing snapshots or their hashes. This also prevents an allowed travel-fact write from returning stale effective verification. Native issued forms omit review/delivery/receipt and explain the quarantine state; correction remains available.

Independent retest of the original persisted reproduction: all three effective flags are false; the factual receipt remains recorded; historical review snapshot and hash are unchanged; exact retry returns the same historical revision without appending. On a copy of that synthetic database, a permitted travel fact returned quarantined/verification=false, and a fresh review was rejected without adding a revision. The file/passport parameterized regressions and their native UI unavailable-state assertions passed.

One initial retest harness attempt passed the ORM's immutable mapping directly into an API that requires a plain dict and received `invalid_issued_operation`; converting through the existing `_plain` helper corrected the harness. This was not a product defect or a passing test.

## Other material review observations

- Policy is absent by default and explicitly binds authorized full-admin identities, validity, media types, bounded storage limits, database storage, and privacy/retention references and proofs. No new business permission or retention period is inferred.
- Multipart parsing bounds headers, fields, parts, file bytes, and aggregate body. Malformed/incomplete uploads fail before persistence. Filename validation does not turn client input into a path. Type signatures classify bytes; they do not establish harmlessness.
- Package receipt and binary metadata are created in one domain transaction, with exact retry and compare-and-swap versions. Retained quota counts historical files. Metadata views do not load deferred BLOBs. There is no content download, preview, opening, release, or approval route.
- Independently inspected and retested the auditor-reported pair-integrity fixes: receipt and binary metadata form an exact one-to-one set; missing row/table fails closed; document version and event timestamp match replayed receipt state. These findings were disclosed by the builder, not independently discovered here.
- Inspected the late import correction: shared document UI constants have no router side effects; quarantine resolves package policy at request time. Three cold imports and the final native quarantine UI suite passed independently.
- Migration 0026 is additive. SQLite foreign-key/model parity, PostgreSQL DDL generation, and refusal of populated/offline downgrade were tested. No binary deletion or recovery policy is implemented implicitly.

## Independently executed verification

Environment: Windows, Python 3.12, env-free archive, synthetic SQLite; pytest's network guard enabled. Artifact paths below are relative to `runs/e6-09-local`. Results are separate runs with overlapping coverage, not a count of distinct tests.

1. Initial candidate suite — **PASS, 63 tests**, 53.33s. One existing Starlette/httpx deprecation warning.

   `python -m pytest tests/test_entry_quarantine.py tests/test_admin_kg_document_quarantine.py tests/test_quarantine_multipart.py tests/test_entry_quarantine_migration.py -q --basetemp reviewer-quarantine-tmp --junitxml reviewer-quarantine.xml --tb=short`

2. Corrected global guard, integrity, transaction, and migration checks — **PASS, 13 tests, 26 deselected**, 24.92s. One deprecation warning.

   `python -m pytest tests/test_entry_quarantine.py tests/test_entry_quarantine_migration.py -q -k "laundered_through_another_application or legacy_inventory_also or rehashed or missing_binary or rollback_lost_ack or atomic_receipt or additive_empty or migrated_upload or postgresql_ddl" --basetemp reviewer-quarantine-final-tmp --junitxml reviewer-quarantine-final.xml --tb=short`

3. Latest quarantine UI after import correction — **PASS, 10 tests**, 20.03s. Includes policy/access gates before parsing, scope/CSRF/stale policy, lost acknowledgement, reread failure, and exact same-file retry. One deprecation warning.

   `python -m pytest tests/test_admin_kg_document_quarantine.py -q --basetemp reviewer-quarantine-ui-final-tmp --junitxml reviewer-quarantine-ui-final.xml --tb=short`

4. Final issued file/passport integration — **PASS, 2 tests, 36 deselected**, 9.60s. Includes blocked fresh operations, preserved historical snapshot, exact retry, explicit quarantine notice, and omitted native action forms. One deprecation warning.

   `python -m pytest tests/test_entry_quarantine.py -q -k issued_document_cannot_reuse_quarantined_content --basetemp reviewer-quarantine-issued-final-tmp --junitxml reviewer-quarantine-issued-final.xml --tb=short`

5. Reviewer-owned direct probes — **PASS**: original persisted cross-application acceptance reproduction; original persisted issued reproduction and exact retry; travel-result overlay on a copied synthetic database; pre-0025 missing-table lookup; PostgreSQL dialect compilation of the global JSON fingerprint lookup; separate cold imports of quarantine, package, and inventory UI under the network guard. PostgreSQL compilation is not PostgreSQL runtime evidence.

6. Snapshot identity — **PASS**, all 25 normalized file hashes match in workspace, archive, and committed Git blobs. No later source change is covered without checking its new hash and relevant behavior.

## Limits and remaining gates

- Real PostgreSQL transactions, concurrency, database backup/restore, production migration, and production recovery: **UNKNOWN / not exercised**. SQLite and generated PostgreSQL DDL do not establish those claims.
- Real storage/privacy/retention authorization: **UNKNOWN**; actual policy remains absent/off. No production activation or release is approved by this review.
- Browser test code for mobile/desktop, no-JavaScript multipart, invalid type, lost acknowledgement, retry, and print was inspected. The reviewer did not independently execute Playwright or inspect rendered screenshots; builder browser results are separate evidence and are not claimed here as independent PASS.
- Malware assessment/release, file opening/download, and real customer files: **N/A to this bounded quarantine implementation** and intentionally unavailable; future release policy remains a separate decision.
- Separate final audit and the builder's final broad regression record remain separate artifacts. This review approves the pinned local implementation only.
