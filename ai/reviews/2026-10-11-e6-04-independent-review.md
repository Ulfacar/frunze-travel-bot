# E6-04 independent critical review

Reviewer: `/root/package_review`, independent review role, 2026-10-11 UTC. This is a review of the numbered applicant qualification slice, not a whole-project, J03, publication, or production approval.

**Current independent verdict: APPROVE for the reviewed local E6-04 applicant-profile scope with the E6-17 r1 correction.** The original FIX_REQUIRED findings and evidence below are retained. Corrective verification is recorded at the end: 48 SQLite/HTTP/browser checks and 21 PostgreSQL checks passed independently. The separately required final CRITICAL audit remains pending; this report does not authorize release.

## Scope and identity

Read the original acceptance and risk contract in `ai/tasks/2026-10-10-e6-04-applicant-profiles.md`, the requested original handoff `ai/handoffs/2026-10-10-0730-e6-04-applicant-profiles.md`, and actual implementation and tests before the builder's proposed corrective patch. Applicable protocol is CRITICAL / solo: independent review and final audit remain separate obligations.

Initial runtime snapshot: `runs/e6-15-final`, base `8f41566`, without E6-16. Independent env-free execution copy: `runs/reviewer-e604-20261011`. No application, frozen snapshot, migration, or repository test source was changed by this reviewer. Additional probes and browser artifacts were written only in the ignored execution copy; this report is the only review file written outside it.

47 relevant source/test files were compared bytewise after LF normalization between the frozen snapshot and execution copy. All matched. Manifest: `runs/reviewer-e604-20261011/runs/reviewer-e604-baseline-snapshot.json`, SHA-256 `772d750abe725c4fce7ad909d580139c1335242933e2dd1f32ba590c3b429ce2`.

Principal original hashes:

| File | LF-normalized SHA-256 |
|---|---|
| `app/domain/applicant_profiles.py` | `02cada1889d839534af1982ed079f17d268217bf35fc6d74170715bee33114ae` |
| `app/admin/kg_applicant_profiles.py` | `c003bc3dfe7d69c30b7e65434136682ea38eebab255713b0b833c62d5bed9749` |
| `alembic/versions/e6_profiles_0020.py` | `6d17d801444bd8c154418a642914b8fe04d0907b7cfc498b146bb386bf249658` |

## Initial findings and verdict

**Initial verdict: FIX_REQUIRED.** One confirmed JSON type-integrity defect has three observed manifestations; a stale browser selector also prevents the original browser checks from establishing current UI evidence.

### F1 — P2: Python equality accepts different JSON values during integrity verification

Locations in the initial snapshot: `app/domain/applicant_profiles.py:80` (previous pin), `:84` (source context), and `:154` (explicit result replay).

Reproduction with synthetic SQLite and actual service writes:

1. Save a valid applicant profile. Replace stored `result_snapshot.may_quote` from JSON `false` to JSON `0`, recompute the row's complete `snapshot_hash`, and request `read_applicant_profile(..., replay=True)`. The explicit replay succeeds rather than raising `profile_replay_result_changed`.
2. Replace `provenance.context.applicant_id` from integer `1` to JSON float `1.0`, recompute the complete row hash, and read the profile. The malformed source pin is accepted.
3. Save two revisions. Replace the second revision's `provenance.previous.id` integer with the equal-valued float, recompute its complete row hash, and read the history. The malformed predecessor pin is accepted.

Python considers `False == 0` and integer `1 == 1.0`, but these are distinct canonical JSON values. Recomputed row hashes therefore do not make the semantic verification exact. These tests deliberately use raw synthetic DB corruption to challenge the verifier; they do not demonstrate an HTTP privilege bypass, quote permission, or a cryptographic trust boundary against an arbitrary database administrator.

Evidence: `runs/reviewer-e604-20261011/runs/reviewer-provenance.xml`: **3 FAIL, 4 PASS**, 31.73 s. Each failure is `DID NOT RAISE EntryStorageInvalid` in the expected rejection. The earlier result-only probe is also preserved as `runs/reviewer-probes.xml`: **1 FAIL, 4 PASS**, 25.22 s.

Correction: compare canonical JSON values or their existing `_hash` digests for these comparisons. Do not change saved results, flags, source policy, subject identity, or the old-runtime read contract.

### F2 — stale original browser selector

`tests/browser_kg_applicant_profiles.py:40` and `:63` locate `Анкета заявителя №…`, while the current register's `app/admin/templates/kg_applications.html:34` links to `Квалификация заявителя №…`. Both original browser cases time out. The qualification route itself remains available.

Correction: update the selector to the actual visible qualification link or its exact subject-scoped href, retaining the flow assertions. An independent browser probe using the actual href passes at 390 px with JavaScript and 1365 px without JavaScript. This is test maintenance, not permission or product behavior expansion.

## Pre-audit of the narrow correction

**GO for implementation of the narrow correction**, not final approval of an unreviewed patch. The builder has authorization to correct F1 and the obsolete browser selector.

Use canonical equality for `result`, `provenance.previous`, and `provenance.context`; canonicalizing runtime comparison consistently is also safe (the current runtime fields are strings). Leave database scalar checks, input schemas, actor boundaries, and source policy unchanged. Changing this module necessarily changes its runtime fingerprint: old valid profiles must remain readable and exact old requests must remain reusable; explicit replay must still reject an old runtime. No rewriting, automatic recomputation, migration, or fabricated historical runtime compatibility is needed.

Required corrective checks:

- Rehashed result booleans versus numbers and integer identifiers versus booleans/floats fail exact replay.
- Rehashed source-context and predecessor identifier type changes fail read, exact retry, and new successor save.
- Correct fresh histories and their exact retries remain valid.
- Ordinary historical reads and exact retries survive a runtime change, while explicit replay returns `profile_replay_runtime_changed`.
- Both existing native browser flows run using their actual links and preserve all substantive assertions.

No business decision or permission expansion is required for this correction. Broader strengthening of the inherited authentication/session model or legacy payer journal is outside this narrowly authorized fix.

## Independent evidence on the initial snapshot

All data synthetic; no client messages, deployed writes, production access, or real personal data. PostgreSQL used only the existing guarded ephemeral localhost:55971 fixture; connection material was neither printed nor copied into reports. Each PG database was uniquely named and removed by the guarded fixture. These are this reviewer's runs, not builder counts.

All commands ran from `runs/reviewer-e604-20261011`; artifacts below are relative to that directory.

| Check / command | Actual result | Artifact |
|---|---|---|
| `python -m pytest tests/test_applicant_profiles.py tests/test_applicant_profiles_migration.py tests/test_admin_kg_applicant_profiles.py tests/browser_kg_applicant_profiles.py -q --tb=short -ra --basetemp runs/reviewer-e604-tmp --junitxml runs/reviewer-e604-baseline.xml` | **26 PASS, 2 FAIL**, 177.53 s; failures are F2 selectors | `runs/reviewer-e604-baseline.xml` |
| `python -m pytest tests/test_reviewer_e604.py -q --tb=short --basetemp runs/reviewer-provenance-tmp --junitxml runs/reviewer-provenance.xml` | **4 PASS, 3 FAIL**, 31.73 s; F1 expected rejections fail | `runs/reviewer-provenance.xml` |
| `python -m pytest tests/test_reviewer_e604.py -q -k same_payer --tb=short --basetemp runs/reviewer-samepayer-tmp --junitxml runs/reviewer-samepayer.xml` | **1 PASS**, 9.05 s: two real service cases sharing one payer retain separate subject facts, request keys, and historical IDs | `runs/reviewer-samepayer.xml` |
| `python -m pytest tests/test_reviewer_e604_postgres.py -q --tb=short --basetemp runs/reviewer-pg-tmp --junitxml runs/reviewer-pg.xml` | **5 PASS**, 33.51 s: payer/person/application separation, competing CAS, simultaneous same-request reuse, actual native lost-ACK/reread failure and exact retry, old/current retries | `runs/reviewer-pg.xml` |
| `python -m pytest tests/test_reviewer_e604_postgres.py -q -k migration --tb=short --basetemp runs/reviewer-pg-migration-tmp --junitxml runs/reviewer-pg-migration.xml` | **1 PASS**, 10.57 s: actual PostgreSQL 0019→0020→0019→0020, model/table parity, domain replay, five invalid scope/predecessor/cap inserts rejected, populated downgrade refused with row/version preserved | `runs/reviewer-pg-migration.xml` |
| `python -m pytest tests/browser_reviewer_e604_v2.py -q --tb=short --basetemp runs/reviewer-browser2-tmp --junitxml runs/reviewer-browser2.xml` | **2 PASS**, 27.55 s: actual register→profile→two saves→old read-only version→separate empty child profile; mobile JS and desktop no-JS | `runs/reviewer-browser2.xml` |

The first attempt to adapt the independent browser selector via a PowerShell text substitution did not change the Cyrillic selector and reproduced the same two timeouts (`runs/reviewer-browser.xml`). It is not counted as successful evidence. The passing `v2` probe selects the subject-scoped href and preserves the original assertions.

Visually inspected `runs/reviewer-profile-browser-v2/profile-390.png` and `profile-1365.png`. The numbered subject, payer separation explanation, draft source warning, saved revision/date, questions, and history links are visible without horizontal clipping. Keyboard focus and historical read-only controls are asserted in the browser run. The browser never accesses external hosts.

## Scope assessment and limits

The inspected implementation binds rows to `(case_id, applicant_id)`, validates immutable applicant identity, and locks the applicant before profile CAS. The migrated schema enforces subject/predecessor scope and unique revision/request identity. No parent/contact history is passed into individual qualification, including the primary applicant. Family summaries remain summaries rather than auto-created people. Existing payer-level qualification is preserved. Partial facts are replaced rather than merged, preventing stale answers from silently surviving a save.

The native form uses existing full-admin/workday/OFF/write gates before storage and actor/session/case/applicant/source/revision signatures. Existing tests cover anonymous and scoped manager denial, scope/session/legacy-signature swaps, unsigned fields, malformed/oversized forms, read-only GET, stale CAS, and failure recovery. The domain API accepts a trusted server `Actor`; it is not a public authentication endpoint. This review does not certify the broader shared cookie/session or manager-configuration lifecycle.

Exact retry is actor- and content-bound and returns the original revision after later saves. Capacity behavior was independently checked with a reduced test-only revision bound: history and exact retries remain available at the bound, and a further revision is rejected. The production constants remain 250 revisions / 4 MiB; no production limit was changed. Runtime changes intentionally preserve saved-result reads and refuse explicit recomputation.

Qualification outputs continue to be draft review material: no eligibility, exact days/deadlines, source publication, fee authority, or permission to quote. Independent identified-person stay-history and full dossier/PII policy are not implemented by this slice. Full B03/B04 interview coverage and other CRITICAL tasks are not certified here. No release, production migration/recovery, or business acceptance is claimed.

Final corrective snapshot review and final audit: **UNKNOWN / pending** at this initial report stage. Initial known defects above must be resolved before changing the E6-04 scoped verdict.

## Corrective re-review — E6-17 r1

Reviewed `ai/tasks/2026-10-11-e6-17-profile-integrity.md` and the actual frozen correction before relying on builder test results. Frozen archive: `runs/e6-17-review-r1`, base `fca93ad8ed7d6a5fcdf53b741b254ba1241ad03e`. Five-file manifest `ai/reviews/2026-10-11-e6-17-snapshot-r1.json` has LF-normalized SHA-256 `dcf20adaf989dadf3143a4720e9e31198c7328247198d4968490475da5a9b5c2`. All five hashes were verified against the frozen archive. Runtime module `app/domain/applicant_profiles.py` now has SHA-256 `760d5c9885ba6f4edb2ca90790bfc19e95125945417701b3f631bcb9121c630f`.

Independent execution copy: `runs/reviewer-e604-fix-r1`. Comparing all 47 original review manifest entries showed only three changed files: the profile domain module, its domain test file, and the original browser test. The only runtime change is four canonical JSON comparisons, for previous pin, source context, runtime, and replay result. The other two manifest entries are the new guarded PG test wrapper and corrective task. No E6-16 runtime was present. The administrative profile handler, model, migration, evaluator, parser, templates, source loading, scope locks, and authority checks were unchanged.

Independent final 48-file source/test manifest: `runs/reviewer-e604-fix-r1/runs/reviewer-e604-fix-snapshot.json`, SHA-256 `32d3d6ae72f9aa1617709ba13aba103a5da62d1a5392ada9959ee0c09f80b432`. Frozen source and execution-copy hashes were rechecked after testing. Both independent probe files were copied byte-for-byte unchanged from the initial review copy:

- `tests/test_reviewer_e604.py`: `b5566247f4507ea1fa4448d82f6694a625f00835b8d9e41837c95daf31d8389d`.
- `tests/test_reviewer_e604_postgres.py`: `e1487eb58e3c2006426c7e053b6ee03cf1836bcdb4a6ad1aa506f14dc5152f37`.

### Independent corrective runtime evidence

Both commands below ran in `runs/reviewer-e604-fix-r1` with separate artifacts, using synthetic data only. PostgreSQL connection fixture is restricted to the known local cluster. A separate read-only probe confirmed server version **16.15**, address **127.0.0.1/32** (`runs/reviewer-pg-runtime.json`); no connection secret was emitted.

| Command | Actual result | Artifact |
|---|---|---|
| `python -m pytest tests/test_reviewer_e604.py tests/test_applicant_profiles.py tests/test_applicant_profiles_migration.py tests/test_admin_kg_applicant_profiles.py tests/browser_kg_applicant_profiles.py -q --tb=short -ra --basetemp runs/reviewer-e604-fix-tmp --junitxml runs/reviewer-e604-fix.xml` | **48 PASS**, 229.47 s | `runs/reviewer-e604-fix.xml` |
| `python -m pytest tests/test_reviewer_e604_postgres.py tests/test_applicant_profile_integrity_postgres.py -q --tb=short --basetemp runs/reviewer-e604-fix-pg-tmp --junitxml runs/reviewer-e604-fix-pg.xml` | **21 PASS**, 176.05 s | `runs/reviewer-e604-fix-pg.xml` |

F1 is fixed: all three unchanged original reproductions now reject the malformed JSON types, and the expanded bool/int/float matrix passes on SQLite and real PostgreSQL. Invalid source and predecessor pins block read, exact retry, and successor save. Correct histories still replay. Old valid receipts remain readable and exactly retryable when the runtime fingerprint changes; explicit replay still refuses the changed runtime. No historical result or receipt is rewritten.

F2 is fixed: both original browser tests now pass using the actual subject-scoped qualification href. All substantive original assertions remain: two saves, language and stop/question behavior, keyboard focus, overflow width, old version without a save button, and an independent empty child profile. The corrected run's `runs/e6-04-profile-browser/profile-390.png` and `profile-1365.png` were also visually inspected. The same subject/payer/source warnings remain visible and readable.

The independent PG migration probe was rerun on this corrected runtime: actual empty 0019/0020 roundtrip, model parity, real profile save/replay, cross-case/cross-person/broken predecessor/duplicate revision/out-of-range inserts, and populated downgrade refusal with preserved row/version all pass. CAS and same-request concurrency, old/current retry identity, and HTTP lost-commit-ack recovery also pass on PostgreSQL.

### Final scoped verdict

**APPROVE — independent implementation review for E6-04's local numbered applicant profiles, including the narrowly scoped E6-17 r1 correction.** No unresolved correctness finding was identified within that reviewed scope. F1 and F2 are closed by actual source changes and independent runtime evidence; the initial failing evidence remains preserved above.

This closes the previously missing independent review evidence for this slice, including actual scoped PostgreSQL runtime evidence. It does not close the separately assigned final CRITICAL audit, general shared authentication/session review, full applicant dossier/PII decisions, identified-person stay-history integration, source approval, production backup/restore, production migration, deployment, or business acceptance. No whole-project or all-CRITICAL/J03 claim follows from this verdict.
