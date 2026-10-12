# E6-27 — independent implementation review

**Verdict: APPROVE for the bounded local personal stay-history implementation on frozen R6.** Two observed defects are corrected and independently rechecked below. No remaining scoped blocker was found. Separate final audit is required. This does not approve real records, production migration, source/policy authority, counting policy, final qualification or C05 completion.

Reviewer: `publication_review`, 2026-10-12. Requirement and actual code were read before builder conclusions, following the separate pre-audit at `ai/reviews/2026-10-12-e6-27-pre-audit.md`. Only this report and reviewer-owned `runs/` artifacts were written. No root `.env`, production database, actual personal records or outbound integration was used.

## Exact target

Base `803eacff8209007a66b6a877e37cfe845593ce00`; final target `runs/e6-27-r6`, 21 verified overlays. Manifest LF-normalized SHA-256: `0476f1cdc4fa770a9199b153694ada30345ee0821537216b9b68c86057927fde`.

Own env-free archives: `runs/e627-review-r1/source`, `runs/e627-review-r2/source`, `runs/e627-review-r5/source`, `runs/e627-review-r6/source`. The retained Git base ZIP is `runs/e627-review-r1/source.zip`, raw SHA-256 `cec226ff80f4f928ab4eed53fbcd59e7b82237be87620233e7cf67db7cbd580b`. Each reviewer directory contains its verified `identities.json`; `freeze.py` records the reproducible overlay construction.

| Scoped runtime/migration file | R6 LF SHA-256 |
| --- | --- |
| `app/domain/applicant_stay_history.py` | `c00f1b5002572d527054e71e1626849876c41298ba234d4f800447a28c658111` |
| `app/domain/models.py` | `9a806e3eb10b099084560b881d4e81bdc54e4384d909ab355ea86f7103d654ed` |
| `alembic/versions/e6_applicant_stay_0035.py` | `28dd92f514c3ddba3b22d382bc6bf434855653183d927d183d5f6031969611f5` |
| `app/admin/kg_applicant_history.py` | `9f0160a5114a300b9605bae4bd550fb0353cdbd01184b9db34a34a26efba8afa` |
| `app/admin/kg_applicant_history_form.py` | `d085d0985dd48f593d02570a1e219a5692ba0c9fa81608d36a3cbfd7d9d9a426` |
| `app/admin/templates/kg_applicant_history.html` | `9a56dea91a59b5aac8477db96f22ddad234d382d5f1a46ff2e2608700be201ff` |
| `app/admin/router.py` | `09e81ac629316c292ffe8bf23d5836bf0ab6ca4f905e308223eff62e65f10e88` |
| `app/admin/templates/kg_entry.html` | `e45532de6831cabc0406178ad2f69d54f7441dbed4de85fe1b1d14dd6868121b` |

All eight match final root, frozen target and own R6 archive. Domain/model/migration/router/profile-link identities are unchanged from R1 through R6, so earlier runtime evidence maps exactly. R5→R6 changes only print CSS in the history template (`html,body` height/min-height reset). Native R5 evidence therefore maps to R6; the two browsers were rerun on exact R6. Associated five new test files and compatibility table/head assertions are included through the manifest. Preserved `base.html`, `boards.html`, `test_admin_new_look.py` and state/task overlays are not a general approval of unrelated work; shared UI was exercised only as used by this feature.

## Findings

**F1 P2, CLOSED — parent-case availability error escaped to HTTP 500.** In R1, both `history_form` and `history_submit` awaited `entry._case` outside their controlled error handling. A case-registry `EntryStorageUnavailable` returned an unhandled 500 instead of a safe unavailable page. Independent native GET/POST probes failed; a second run used an actual signed valid POST form and reproduced both failures. Evidence: `runs/e627-review-r1/independent-first.txt` and `independent-case-signed.txt`.

R4, retained in R6, preserves permission/HTTP status exceptions and renders an escaped, no-store 503 page for unavailable case data. POST verifies the bounded signed form first and retains its exact body as the retry form. Pending uncertain retry suppresses new operation forms. Both original failure paths pass independently on R5; the supplied recovery regression also checks original request preservation. No journal write occurs while the parent lookup fails.

**F2 P3, CLOSED — print added an empty second page.** Both independently executed R5 browser scenarios failed the PDF page-count assertion after their screen/flow/contrast checks passed: each one-page history printed with a blank second page. R6 resets inherited page-height constraints for print. Exact R6 browsers pass, each PDF has one page, and both rendered PDF pages were visually inspected. This was a presentation defect, not lost stored history.

## Acceptance assessment

- **Scope and invariants PASS:** new case/applicant/profile and predecessor composite FKs; immutable model and bulk-write guards; actor-bound normalized commands; ordered, contiguous, bounded full-chain checks; profile/applicant/previous hashes; predecode and canonical byte limits. Existing contact history and profile contracts are unchanged. Two people sharing payer/case remain separate; missing history does not mean zero visits.
- **Evidence semantics PASS:** nullable completeness/current passport and uncertain intervals remain explicit. Profile change, old as-of date, future record time, unknown basis/country and passport mismatch remain findings. Current tokens are opaque and native choices are scoped to the selected person's snapshot; no raw number/upload control is accepted. Changing visits clears completeness. Closed overlapping records are preserved for the existing union arithmetic. Saving remains `eligibility_evaluated=False` and `may_quote=False`.
- **Recovery PASS:** original commands are returned before new-write CAS, profile/current-day and capacity checks. Delayed original withdrawal after reactivation, newer profile and next day leaves the reactivated current history unchanged. Actor/body conflicts, stale requests and corrupted history fail closed. Count/byte limits reserve a terminal withdrawal while retaining historical reads and exact receipts.
- **Composition/concurrency PASS:** writer locks case then applicant and samples time afterward. Readers hold the applicant shared lock; `current_in_session` is explicitly for callers already owning the parent locks, and returns this person's validated pinned evidence without opening a new transaction. Actual PostgreSQL probes observed blocked writers in `pg_stat_activity`, coherent repeated reads inside a held transaction, and date/clock behavior after lock waits.
- **Native flow PASS:** server-side one-row operations preserve undisplayed rows; the maximal 1,000-row native regression passes after comparing records by their canonical identity/order. Cross-person/session metadata, duplicate/extra fields, content/body limits, no-write/feature/full-admin gates, validation echo, uncertain commit retry, historical read-only pages and no-DML GETs are covered. Printing explicitly states its 25-visits-per-page scope; the parent profile determines RU/EN when readable.
- **Migration PASS for local rehearsal:** additive table, real PostgreSQL model parity/FKs, empty downgrade/upgrade and populated-downgrade refusal preserve existing profile receipts. SQLite foreign-key/parity and old-profile replay coverage are evidenced by the builder's actual R2 migration tests, not inferred from PostgreSQL DDL text.

## Executed evidence

Commands run from each named reviewer archive's `source/`; output paths below are relative to the repository. All fixtures were synthetic. Review suites ran serially; actual PostgreSQL used the guarded private connection-file opt-in for `127.0.0.1:55971`, with uniquely named disposable migrated databases. Credentials are not recorded here.

1. **R1 independent source-driven negatives:** `python -X utf8 -m pytest tests/test_reviewer_applicant_history.py -q` → **6 PASS, 2 FAIL /18.08s**, the two failures being F1. The six passes include actor-bound retries, same-session scope/unknown preservation, profile changes, 40-row removal preserving 39 rows and history, overlap preservation, and delayed original withdrawal after reactivation. Output `runs/e627-review-r1/independent-first.txt`.
2. **R1 valid signed F1 reproduction:** same command selecting `::test_native_case_unavailable_is_controlled` → **2 FAIL /7.35s**, both HTTP 500. Output `runs/e627-review-r1/independent-case-signed.txt`.
3. **R2 actual PostgreSQL:** `python -X utf8 -m pytest tests/test_reviewer_applicant_history_postgres.py tests/test_applicant_stay_history_postgres.py::test_actual_count_limit_and_withdrawal tests/test_applicant_stay_history_postgres.py::test_bytes_and_predecode_bound tests/test_applicant_stay_history_postgres.py::test_migration_cycle_real_constraints_profile_preservation_and_populated_refusal -q` → **6 PASS /39.49s**. Three independently authored probes cover forward day change while waiting on the case lock, clock reversal after waiting with exact-retry preservation, and same-session profile coherence against a blocked writer. Three supplied probes were independently executed for capacity and migrated schema. Output `runs/e627-review-r2/postgres-independent.txt`.
4. **R5 native and original repros:** `python -X utf8 -m pytest tests/test_reviewer_applicant_history.py::test_native_case_unavailable_is_controlled tests/test_reviewer_applicant_history.py::test_native_delayed_withdraw_retry_preserves_reactivated_history tests/test_admin_kg_applicant_history.py tests/browser_kg_applicant_history.py -q` → **16 PASS, 2 FAIL /48.57s**. All native checks pass, including both F1 cases; only the browser blank-page assertions fail (F2). Output `runs/e627-review-r5/native-browser-independent.txt`.
5. **Final R6 browsers:** `python -X utf8 -m pytest tests/browser_kg_applicant_history.py -q` → **2 PASS /21.32s**. Chromium real forms on 390px RU/dark and 1365px EN/light without application JavaScript; new-look enabled, only loopback requests allowed. Covers entry, completeness reset/reconfirmation, passport change, historical view, keyboard focus, no horizontal overflow, button contrast ≥4.5 and rendered one-page print. Output `runs/e627-review-r6/browser-independent.txt`.

Count-limit evidence uses a real 249-row chain seeded through model inserts with valid commands/hashes, followed by service read/rejection/terminal withdrawal/retries at revision 250; it is not 249 separate native submissions. The byte-capacity test reduces the configured total limit around actual serialized row sizes; the oversized predecode negative uses the real event-size limit. These are bounded acceptance checks, not load benchmarks.

Visual evidence inspected from `runs/e627-review-r6/source/runs/e627-browser`: dark mobile and light desktop screenshots plus `pdf-390.png` and `pdf-1365.png`. PDFs raw SHA-256: RU `415f72fe63001228144da9cbcde3b195404a75e6917cc194be14eed4a82dd765`; EN `5200cefe176d338a2680043ce5b91229c4f9d13834270207f0a5332bd455df0d`. Both are readable, preserve dates, state the current-versus-historical distinction and contain no extra blank page.

Supplementary builder evidence was inspected after source assessment: `runs/e6-27-r2/runs/e627-r2.xml` records **46 tests, 0 failures/errors/skips**, including three SQLite/offline migration tests and actual PostgreSQL coverage. This is identified separately from reviewer executions. Final runs have only existing Starlette/httpx and websockets deprecation warnings.

## Scope limit

This supplies a personal factual journal and internal read seam. It does not yet connect the history to approved stay/registration calculations or reconcile the typed interview, and `recorded_inputs` is not a legal eligibility decision. No full-suite-green, production recovery, real-source confirmation, deployment or full C05 claim is made. Final audit should use these exact R6 identities.
