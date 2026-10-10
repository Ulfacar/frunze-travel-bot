# E6-10 independent review — rounds 1–6

Reviewer: `/root/package_review`. CRITICAL / solo. Target: reviewed local implementation, not production. Historical r1/r2 verdicts: **FIX_REQUIRED**. Current frozen r6 code-review verdict: **APPROVE for the inspected local implementation**. Final supporting PostgreSQL/COPY recovery artifacts have now been assessed as described below; full regression and final core/browser closure remain separate pending evidence. This is not production approval. Round-specific verdicts and later findings remain recorded below.

Requirements and the explicitly requested pre-audit were read before the initial implementation assessment. The earlier findings and direct reproductions are recorded in `ai/reviews/2026-10-11-e6-10-preliminary-review.md`. This pass inspected the actual revised code before treating builder test counts as evidence. No source edits, production operations, external data, or baseline-archive changes were performed. Only synthetic data and ordinary local checks were used.

## Reviewed r1 snapshot

- Base: `f227e38ca17402d6a9350d3c28a5ee9b0171fa77`.
- Env-free archive: `runs/e6-10-review-r1`.
- Manifest: `ai/reviews/2026-10-11-e6-10-build-snapshot.json`, labelled `uncommitted E6-10 review r1`.
- Manifest SHA256, CRLF→LF: `990159d406208353eecd7bb056638a48c744aa85bc385dd2f3a2fe75bd2d5815`.
- Independently verified all 22 normalized file hashes against that archive: **PASS**.
- Relevant evidence implementation SHA256: `7d3427fd54683a2c46e7fd882da022c4b1e5ad7ae55209d17127e24a9c7a4ca8`.
- Relevant process service SHA256: `e2e533badf8e43f49dde4855879bd385747063878bef720821036ac66052a03d`.

## Earlier four findings — retested

The independent suite below passed the corrected migration JSON/model parity and PostgreSQL DDL checks, rejection of backdated stage/profile review, closed active-application readiness, and late old-timestamp quarantine/payment scenarios. The latter retain history while invalidating current readiness; quarantine coverage also checks exact retry and stop. Code inspection confirmed that process and upload writers acquire the same PostgreSQL advisory transaction lock before case locks. These checks establish the tested SQLite/DDL behavior; they are not independent PostgreSQL runtime proof.

## New confirmed P1 — package pin can refer to a different state

Location in r1: `app/domain/entry_process_evidence.py`, `Evidence.prefix` and `Evidence.package`. Historical selection accepts an arbitrary ordered subset of source IDs. Package resolution then takes `states[len(prefix)-1]` and `definitions[len(prefix)-1]`, rather than the state and definition belonging to the selected row. A non-contiguous observation therefore binds one package event's ID/hash to another event's state.

Independent real-SQLite reproduction through a valid registration workflow followed by a deliberate rehashed integrity probe:

1. Create package rows: 1=initialize, 2=consent granted, 3=consent withdrawn, 4=consent granted.
2. Complete the legitimate R02→R03 transition using row4.
3. Change only the last process event and its package pin: set observed package IDs to `[row1.id,row3.id]`; set the package source ID/hash to the real withdrawal row3; recompute the evidence digest, request hash, and process snapshot hash. No package source row is changed.
4. Read process history through the public service.

Observed result:

```json
{"forged_history_accepted":true,"stage":"R03","consent_value":true,"pinned_package_event_id":3,"pinned_actual_source_status":"withdrawn","current_ready":true}
```

The historical fact claims granted consent while its exact relational source is a withdrawal. This violates semantic source-version binding even though ordinary API writes cannot construct the forged record. The task explicitly requires rejection of rehashed wrong-source evidence.

Artifact: `runs/e6-10-review-r1/runs/reviewer-r1-rehashed-pins/domain.db`, synthetic only. A first harness attempt tried to JSON-normalize a datetime field and failed before mutation; the corrected harness preserved datetime fields and reproduced the finding.

Required correction: serial revision journals must use a valid contiguous prefix, and package row/state/definition selection must use the actual source identity. Add the complete rehashed event-plus-pin scenario, not merely a mismatched checksum. The builder accepted this finding and is preparing r2. Its fix is not yet independently tested.

## Other disclosed blockers awaiting r2

After this review's reproduction, the builder relayed two findings from the independent auditor:

- `exit_visa_issued` is absent from retained live prerequisites, allowing later issued-document invalidation to escape current readiness.
- A 101st payment causes the complete ledger limit to fail before observed historical IDs are selected, making prior process history and stop unavailable.

These are disclosed auditor findings, not claimed as independently discovered or independently reproduced here. The relevant code paths were inspected, and their fixes require r2 verification. No final verdict can ignore them.

## Independently executed evidence

Environment: Windows / Python3.12 / env-free archive / synthetic SQLite / pytest network guard. Command run from `runs/e6-10-review-r1`:

```text
python -m pytest tests/test_entry_processes.py tests/test_entry_process_migration.py tests/test_admin_kg_process_journal.py -q --basetemp runs/reviewer-r1-core-tmp --junitxml runs/reviewer-r1-core.xml --tb=short
```

Result: **64 PASS**, 160.55s; one Starlette/httpx deprecation warning. Artifact: `runs/e6-10-review-r1/runs/reviewer-r1-core.xml`. The independent rehashed-source probe above demonstrates a missing integrity check despite this passing suite.

Additional read-only assessment covered manual versus authoritative fact scope, named-operator policy/expiry, exact retry before fresh-write checks, source and parent FK binding, bounded events/pins/evidence, stop capacity reservation, same-session resolution, case/application/applicant lock ordering, and immutable historical versus current readiness. No further confirmed defect was found in that pass; this is not a claim of exhaustive adversarial coverage.

Builder-reported PostgreSQL16 scenario results, earlier broad suites, and browser results are separate evidence. This reviewer has not independently run PostgreSQL or Playwright for E6-10. Runtime/recovery PASS will only be recorded against actual artifacts and an identified snapshot. Business execution policy remains absent by default; no real policy or production activation is approved.

## Remaining work

Review the new frozen r2 manifest; independently rerun the complete rehashed-source probe and relevant negative tests; verify live exit-visa invalidation and readable history/exact retry/stop with ledger overflow; assess the final PostgreSQL migration, concurrency, and recovery evidence without treating earlier-snapshot counts as final-snapshot proof. The r1 verdict remains **FIX_REQUIRED** until this work is complete.

## Round 2 — FIX_REQUIRED

Reviewed env-free archive: `runs/e6-10-review-r2`, same base `f227e38ca17402d6a9350d3c28a5ee9b0171fa77`. All 22 source/test files independently match `ai/reviews/2026-10-11-e6-10-r2-snapshot.json`. Manifest raw SHA256: `795e02ab66544fc33c3656b33e1504347cf6b2725b53b8c3e489f948952f39b4`; normalized-LF SHA256: `319d785b0020cddbe9fc9031bd72c111c7007c482c3c0c61bdd7b80e709c3403`.

Actual code now enforces contiguous observed prefixes for serial journals and selects package state/definition by the exact source row. The original persisted r1 forged SQLite database was read with r2 code and correctly rejected with `process_observed_prefix_invalid`: **PASS**. The existing source rows and forged event were not changed for this retest.

Independently executed from r2:

```text
python -m pytest tests/test_entry_processes.py tests/test_entry_process_dependencies.py tests/test_admin_kg_process_journal.py -q -k 'rehashed_package_observation or later_money_stream_growth or exit_visa_verification or large_application_list' --basetemp runs/reviewer-r2-fixes-tmp --junitxml runs/reviewer-r2-fixes.xml --tb=short
```

Result: **7 PASS**, 64 deselected, 105.09s; one Starlette/httpx deprecation warning. The suite covers rehashed package observations, historical money/contract growth, retained exit-visa verification after passport/quarantine changes, and history/link/stop with more than 100 application candidates. Artifact: `runs/e6-10-review-r2/runs/reviewer-r2-fixes.xml`. Read-only inspection confirms retained `exit_visa_issued`, exact scoped historical ledger queries, bounded live ledger reads, and the scoped numeric application selector.

### New confirmed P1 — a corrective transition stores unreplayable overflow evidence

Locations in r2: `app/domain/entry_process_evidence.py:283`–286 returns `process_money_evidence_limit` before recording payment/contract observations; `:119`–123 requires both observations on historical replay. `app/domain/entry_process_rules.py:149` deliberately permits corrective targets to proceed while retained premises are no longer true. These individually reasonable branches combine into an ordinary-write history failure.

Independent synthetic reproduction used normal domain services only, without SQL modification:

1. Build a valid visa process through V12, including accepted documents and full case payment.
2. Receive a new photo version and record its review outcome as `correction`.
3. Add payments through the normal money service until the case has 101 payment rows.
4. Readiness correctly reports current readiness false, but the corrective V12→V13 edge is ready. Commit that transition.
5. Read the resulting history, then call stop directly with the known committed revision and no active policy.

Observed result:

```json
{"before":{"current_ready":false,"correction_transition_ready":true},"saved":{"revision":22,"stage":"V13","payment_value":null,"payment_reason":"process_money_evidence_limit","observed_streams":["events:1","identity:1","packages:1","profiles","successors:1"]},"read_error":"process_observation_invalid","stop_error":"process_observation_invalid"}
```

The successful write contains no `payments` or `contracts` observation. Both public history read and direct stop fail during replay. This violates readable immutable history and the guaranteed stop path; it does not require privileged storage tampering. Artifact: `runs/e6-10-review-r2/runs/reviewer-r2-overflow-correction/domain.db`, synthetic only. An earlier harness attempt used a received photo without a correction review and was correctly rejected by the edge guard; adding the actual correction review produced the defect above.

Required correction: every persisted unknown overflow fact needs a bounded, reproducible observation. The discussed exact first-101 scoped-ID witness can prove overflow without creating payment-approval pins; historical selection must accept that bounded witness and still reject missing/wrong-scope/future source rows. Verify fresh overflow→corrective transition→history→exact retry→stop and both 100/101 boundaries for payments and contracts. Do not reinterpret overflow as confirmed payment.

Round 2 final audit: r1 integrity and availability fixes tested above are accepted for the exercised cases, but this newly confirmed normal-write defect blocks local approval. **r2 verdict: FIX_REQUIRED**. PostgreSQL runtime/recovery and final full-suite evidence are still pending this review's artifact assessment; parent-reported counts are not promoted to independently executed PASS. No production authorization is implied.

## Round 3 — local code review APPROVE

Frozen env-free archive: `runs/e6-10-review-r3`, same base `f227e38ca17402d6a9350d3c28a5ee9b0171fa77`. Independently verified all 22 files against `ai/reviews/2026-10-11-e6-10-r3-snapshot.json`: **PASS**. Manifest raw SHA256: `004ce31680af45fb7c5d11c2c85f313efebcff8591f958f26373144c8a7b70fe`; normalized-LF SHA256: `93028a3bbcac4fd81afe7e06602dd4cd9b449fa4666e2811678e2e3bd304ec6c`.

The exact r2→r3 delta contains three files: `app/domain/entry_process_evidence.py`, `tests/test_entry_processes.py`, and `tests/test_entry_process_postgres.py`. All other manifest hashes are unchanged. Evidence implementation normalized SHA256: `9ef4bb3c70d890253250638606c46c19e06e17c6dedcd02be6709e85e19dfb49`.

Code assessment: historical ledger selection now admits a maximum of 101 exact scoped IDs per stream; live selection remains capped at 101. Both streams pass through the existing source-ID/timestamp validation and observation recording before overflow returns unknown. The overflow branch cannot produce paid=true or payment/contract approval pins. The new SQLite regression exercises V17→V18 for each overflowing stream, and the PostgreSQL suite delegates the same behavioral scenario to its real runtime fixture.

### Independent fresh V12→V13 retest

A separate stdin Python harness was executed from r3 using the repository's synthetic fixture and normal application/package/money/process APIs. It did not modify source or forge database rows. Two fresh databases exercised `payments` and `contracts` separately:

1. Construct a valid visa workflow through V12 with full payment.
2. Grow the selected ledger to exactly 100 rows and verify monetary evidence still uses `full_case_reconciled_balance`, rather than the overflow sentinel.
3. Add the 101st row. Receive a replacement photo and record an actual correction review.
4. Save the permitted V12→V13 transition. Assert both observed streams exist, the overflowing stream has exactly 101 IDs, and the payment fact is unknown with `process_money_evidence_limit` and no payment/contract pins.
5. Read the exact stored revision and compare its snapshot and evidence with the successful receipt.
6. Add a 102nd row, retry the identical original command, and compare event ID, snapshot hash and evidence with the original receipt. Current readiness remains false.
7. Stop directly using the known revision and `policy=None`, then read the final stopped history.

Actual result: **2 independent scenarios PASS**, with both successful V13 records at revision 22. This is a direct harness result, not an additional pytest suite count. The existing Starlette/httpx deprecation warning was emitted. Persistent synthetic artifacts and exact result JSON:

- `runs/e6-10-review-r3/runs/reviewer-r3-v13-payments/domain.db` and `review-result.json`.
- `runs/e6-10-review-r3/runs/reviewer-r3-v13-contracts/domain.db` and `review-result.json`.

Both result records report `witness_count=101`, `fact_value=null`, `history=true`, `retry_after_102_rows=true`, and `stop=true`. The invalid r2 record was deliberately not repaired or represented as recoverable; r2 is an unreleased candidate and its original failing artifact remains intact.

### Final independent assessment and limits

The confirmed migration, chronology, active-attempt readiness, transaction-visibility replay, rehashed wrong-source package binding, exit-visa invalidation, ledger/list growth availability and corrective-overflow defects are now addressed in the inspected implementation and exercised scenarios. Source-scope enforcement, manual-fact restrictions, policy expiry/default-off behavior, immutable retry and stop behavior remain intact under this minimal delta. No further confirmed source defect remains from this independent review. **Frozen r3 local code-review verdict: APPROVE.**

Evidence is cumulative and snapshot-specific: this reviewer executed 64 pytest checks on r1, 7 targeted pytest checks on r2, the original persisted forged-source rejection on r2, and the two fresh corrective-overflow scenarios on r3. The 19 unchanged manifest files allow the earlier relevant code assessment to carry forward; these counts are not claimed as a full r3 regression. Final PostgreSQL concurrency/migration/COPY recovery, full-suite and browser artifacts have not yet been independently assessed here. Their final status is **UNKNOWN in this review**, pending actual evidence supplied by the builder. Production backup certification, native pg_dump support, business-policy approval and production release are outside this local review's authorization and are not approved.

## Round 4 — consumed manual evidence and renewal

After the r3 review, the builder and independent auditor found a further omission: U03 consumed `protocol_received`, but withdrawing that attestation still left U04 ready and writable because this manual milestone was not retained. This was not discovered in this reviewer's r3 pass. The historical r3 approval above is superseded by that finding and this subsequent r4 assessment.

Frozen archive: `runs/e6-10-review-r4`, same base `f227e38ca17402d6a9350d3c28a5ee9b0171fa77`. All 22 manifest hashes independently verified: **PASS**. Manifest: `ai/reviews/2026-10-11-e6-10-r4-snapshot.json`; raw SHA256 `a54558b2898357a18520a3c91d2b06e9ad51d6c5090080b5acd260cbf13a87b4`; normalized-LF SHA256 `447946e742a72528d2d84441329a50620cd735b0a618dc689190a3150a3d45cf`.

The actual seven-file delta is limited to process rules/service/admin UI and four test files. Every consumed non-authoritative manual fact now retains its exact expected value and type; a subsequent explicit source edge can update that expectation before validation. Existing current authoritative prerequisites still use `LIVE_FACTS`. Authoritative occurrence facts such as application decision/submission/travel are not added to the retained set by this change. Edge readiness now checks the same pin count as submission. Renewal forms include retained facts after withdrawal, map `profile_complete` back to its profile-bound manual review, and continue filtering by the configured manual-source permission.

Independent commands from r4:

```text
python -m pytest tests/test_entry_process_dependencies.py tests/test_admin_kg_process_journal.py tests/test_entry_processes.py -q -k 'consumed_official_manual_evidence or withdrawn_consumed_milestone or pin_limit_is_visible' --basetemp runs/reviewer-r4-retained-tmp --junitxml runs/reviewer-r4-retained.xml --tb=short
```

Result: **6 PASS**, 73 deselected, 31.64s. Covers withdrawal, false replacement, expiry, reduced source scope, pin-limit visibility with stop, and the native withdrawal→renewal→U04 form flow. Artifact: `runs/e6-10-review-r4/runs/reviewer-r4-retained.xml`.

```text
python -m pytest tests/test_entry_processes.py::test_visa_rework_requires_new_approval_and_new_submission_then_post_issue tests/test_entry_process_dependencies.py::test_work_permit_resident_registration_have_distinct_scoped_decisions -q --basetemp runs/reviewer-r4-phase-tmp --junitxml runs/reviewer-r4-phase.xml --tb=short
```

Result: **2 PASS**, 239.64s. These scenarios reach visa V23 after a return/new submission/new acceptance and work W22 across distinct permit/resident/registration decisions. They exercise the boundary between retained manual evidence and later authoritative phase changes. Both pytest runs emitted the existing Starlette/httpx deprecation warning.

An additional fresh ordinary-API harness independently checked consumed values that are not simply true: after reaching V08, change `manager_review_required` from false to true, then separately change `eligibility` from eligible to ineligible. Each change makes current readiness false and rejects V09, while the historical selected receipt and exact retry ID/hash remain unchanged. Restoring the original attestation restores readiness; V09 subsequently succeeds. **Both direct scenarios PASS**. Artifact: `runs/e6-10-review-r4/runs/reviewer-r4-false-enum/domain.db` and `review-result.json`. These are harness results, not additional pytest test counts.

No further confirmed source defect was found in this r4 pass. **r4 independent code-review verdict: APPROVE for the inspected local implementation.** The verified results do not establish overall completion: the builder separately disclosed six failures in its full r2 run, reporting two metadata-table allowlists and four older optional PostgreSQL contract fixtures as suspected causes. This reviewer has not yet verified that classification against baseline/final fixes, and does not label those failures harmless, pre-existing, or resolved. A further frozen test-only snapshot and actual final regression/runtime/recovery artifacts remain pending. Overall release/readiness approval is not issued by this report.

## Round 5 — test setup corrections, source unchanged

Frozen archive: `runs/e6-10-review-r5`; manifest `ai/reviews/2026-10-11-e6-10-r5-snapshot.json`; same base `f227e38ca17402d6a9350d3c28a5ee9b0171fa77`. All **24** normalized file hashes independently match. Manifest raw SHA256: `5f5400ef3a19656ce9b9e146253e64628d671cca607f63bc1b030283e5d9c52d`; normalized-LF SHA256: `2dfb9b090bb0834ba57537ae05dd887646d615df9c58daf247c5b0e5dd1e1875`. All 22 r4 manifest hashes are identical in r5; there is no runtime code change.

The two additions were compared directly with the base Git blobs:

- `tests/test_alembic_domain_migration.py` adds only `entry_process_events` and `entry_process_pins` to the expected domain-table set. Exact metadata equality and exclusion of legacy tables are unchanged. This addresses a real test expectation omission introduced by the two new tables.
- `tests/test_contract_signing.py` changes only the runtime PostgreSQL fixture's migration target from 0008 to head, with an explanatory comment. Current service operations require later calendar-task columns. Assertions for contract idempotency, scope/collision behavior, precision, database constraints, and the specific 0008 downgrade/upgrade roundtrip remain intact; they were not weakened or removed.

Actual supplied artifacts inspected: `runs/e6-10-baseline-f227e38/runs/legacy-pg-baseline.xml` and `runs/e6-10-review-r4/runs/legacy-pg-probe.xml`. Each records one failing `test_postgresql_parallel_sessions_never_duplicate_or_return_someone_elses_case[same-request]`, with the same `UndefinedColumnError`: column `service_case_id` of relation `calendar_tasks` does not exist. This independently verifies the supplied baseline evidence for that first PostgreSQL scenario. It does not itself prove the cause or resolution of all four reported PostgreSQL failures.

Independently executed from r5:

```text
python -m pytest tests/test_alembic_domain_migration.py::test_target_metadata_is_limited_to_domain_base tests/test_alembic_domain_migration.py::test_upgrade_does_not_create_any_legacy_table -q --basetemp runs/reviewer-r5-metadata-tmp --junitxml runs/reviewer-r5-metadata.xml --tb=short
```

Result: **2 PASS**, 1.98s. Artifact: `runs/e6-10-review-r5/runs/reviewer-r5-metadata.xml`.

**r5 independent code-review verdict: APPROVE for the inspected local implementation.** The source review and r4 behavioral checks carry forward by identical hashes, and the two test changes are justified without reduced assertions. Final corrected PostgreSQL execution, process runtime/recovery artifacts and the complete regression result remain pending this report's artifact assessment. No final suite success, production backup certification or production authorization is inferred.

## Round 6 — PostgreSQL test savepoint and inspected final artifacts

Frozen archive: `runs/e6-10-review-r6`; manifest `ai/reviews/2026-10-11-e6-10-r6-snapshot.json`; same base `f227e38ca17402d6a9350d3c28a5ee9b0171fa77`. All **24** file hashes independently verified: **PASS**. Manifest raw SHA256: `6ed0930fd3de41cd6a8fe7927605a50a568b0f66355df63d8e021962af409379`; normalized-LF SHA256: `9630525d7d812f7d6c17de570cd92dbfd9049f22881cbe3caeaaa4b0bb7fb5cd`.

The sole r5→r6 change is `tests/test_contract_signing.py`: the intentional database-constraint probe now opens `connection.begin_nested()` on the same connection that executes its SQL. The formerly used session savepoint did not enclose the direct connection operation. Both expected `IntegrityError` checks, transaction continuation, and all contract migration roundtrip assertions remain unchanged. Current runtime source remains byte-identical to the reviewed r4 source. Final contract test-file normalized SHA256: `a9c317f875cc50f2db9d880b4174a731427e670d8d75c1eae2d5a1b6d3bf93fe`.

Actual supplied artifacts inspected, distinguished from this reviewer's own executions:

- `runs/e6-10-review-r5/runs/legacy-pg-fixed-valid.xml`: 100 tests, 1 failure, 0 errors, 0 skipped, 47.373s. The sole remaining failure is the contract roundtrip's `InFailedSQLTransactionError`, consistent with the direct-connection savepoint issue. The earlier `legacy-pg-fixed.xml` additionally records setup errors and is not used as the valid regression result.
- `runs/e6-10-local/runs/legacy-pg-savepoint2.xml`: 1 PASS, 2.328s. The inspected development test file currently has the same normalized SHA as r6, but this is supporting developer-run evidence, not an independent execution or a replacement for the frozen result.
- **Frozen r6** `runs/e6-10-review-r6/runs/legacy-pg-final.xml`: **100 PASS**, 0 failures/errors/skips, 40.155s. The three real PostgreSQL collision scenarios and applied-migration constraint/roundtrip scenario are present and passed. This closes the six disclosed failures within the affected two-file rerun; it does not make the earlier whole-suite run green retroactively.
- `runs/e6-10-review-r3/runs/process-final-r3-valid-regression.xml`: **277 PASS**, 0 failures/errors/skips, 880.068s. This is supporting earlier-snapshot evidence. The adjacent zero-test XML is not counted as a successful test run.
- `runs/e6-10-review-r4/runs/auditor-process-r4-pg.xml`: **8 PASS**, 0 failures/errors/skips, 361.338s. Cases cover distinct work dependencies, both regularization branches, all four manual-evidence invalidations, and COPY recovery. The runtime source and this test module are identical in r6.
- `runs/e6-10-review-r4/runs/auditor-process-r4-ui.xml`: **2 PASS**, 14.862s, for renewal and pre-submit pin-limit visibility. These overlap cases this reviewer separately executed and are not added to an aggregate independent test count.

Recovery evidence was assessed against both the actual test implementation and `runs/e6-10-review-r4/runs/process-postgres-recovery.json`. The synthetic PostgreSQL16 rehearsal copies all public-table data under a read-only repeatable-read transaction, reconstructs the same schema through Alembic0027 in a fresh database, verifies copy payload hashes/counts, restores sequences, and then checks exact process-history equality, quarantine verification, the native V02 page and a new write with a greater event ID/revision. The recorded backup is 28,587 bytes, SHA256 `fe7bb01dd907eb3a1e398795bbe516eec1ca4f68081e87802b0c18d2f6702fb6`. **Scoped synthetic COPY recovery evidence: PASS (supplied runtime artifacts independently inspected).** This reviewer did not execute that PostgreSQL run. Native `pg_dump` remains UNKNOWN because Windows App Control4551 blocked it; no production backup or recovery certification is inferred.

**r6 independent code-review verdict: APPROVE for the inspected local implementation.** No runtime-code change or assertion weakening was introduced by the test corrections. The remaining evidence boundary is the final whole-suite/core/browser accounting, which is not claimed complete here. Production release, real business policy and external actions remain unapproved and outside this local review.
