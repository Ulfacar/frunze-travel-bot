# E6-25 independent review — applications and documents

Reviewer: separate agent `calculation_review`; CRITICAL / solo, reviewed local target.

**Final independent-review verdict: APPROVE the bounded E01/E02/E03/E05/E07/F01/F02/F03 behavior on frozen R3.** The three reproduced defects below are corrected and retested. This is reviewed local behavior, not release approval or a full-PDF completion claim. The separate final auditor remains a distinct protocol gate.

## Scope and independence

Read the E6-25 task, fixed E01/E02/E03/E05/E07/F01/F02/F03 definitions, supplied PDF-derived sections 5, 14, 16 and 18, then actual domain/admin/model/migration code before prior builder conclusions. Supplied PDF identity: `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.

Original review base: `d847a254acfd54ec8aeecef529c2885f6ba39bbe`. Env-free Git archive: `runs/applications-documents-review-20261012/snapshot`. Root sources were read-only; reviewer probes live in isolated runs. R1 copy: `runs/e6-25-review-r1`, from frozen `runs/e6-25-r1`, base `693d683b9a0adcb8f76d5551bf0f121ca6824fec`, ten overlays verified against the LF-normalized hashes in its `snapshot.json`.

Approved final identity: `runs/e6-25-r3/snapshot.json`, base `693d683b9a0adcb8f76d5551bf0f121ca6824fec`, **13 overlays**. Manifest file SHA256: `4531fe3be91624460d4a01b235d913fecd9dd9b5e388edbefd882a65ee34b585`. Own env-free copy `runs/e6-25-review-r3` was reconstructed from that Git archive and every overlay verified against the manifest's LF-normalized hashes. Application runtime overlays also matched the root source at the final identity check. No runtime edits were made by the reviewer.

No live databases, real records, messages, source approval, production release, migration on live data or credentials were used. PostgreSQL was the explicitly validated temporary loopback cluster; each test used a disposable database migrated from an empty template. Credentials were read only by the existing validated fixture and were not printed.

## Confirmed findings

1. **F03: an old dated check refreshes a new passport revision.** In original `entry_document_rules.py:76–110`, `passport_change` and passport receipt increment the identity revision without retaining a date boundary for later reviews. A photo received September 1 and checked September 2 becomes `recheck` after a September 3 passport change; entering the September 2 check again marks it current under the new passport revision. Both explicit change and received passport copy reproduce. Reviewer probe: `tests/test_e625_independent.py::test_old_dated_review_cannot_clear_new_passport_invalidation`. Original result: **2 FAIL / 1 positive PASS, 13.05s**. A September 4 check is the positive control.

2. **F03/E07: an old dated client receipt confirms the new passport revision.** Original `entry_issued_rules.py:receipt` only checks the delivery date, then assigns the current passport revision. File September 3, review September 4, email delivery September 5, passport changed September 6 and back September 7, fresh review September 8: a late-entered September 5 receipt with `identity_checked=True` incorrectly yields `receipt_current_and_checked=True`. The September 9 positive receipt is valid. Reviewer probe: `test_old_dated_receipt_cannot_clear_issued_passport_invalidation`. Combined own SQLite run: **1 FAIL / 8 PASS / 3 deselected, 21.37s**; the other seven passes are interrupted-write and partial-history controls.

3. **R1 correction misses downstream process acceptance.** R1 `entry_process_evidence.py:238–245` calls package summary and effective acceptance without the newly derived passport date boundary. For a replay-valid old stale package approval, the corrected package screen returns `accepted=False`, while actual `Evidence.package(..., 'documents_accepted')` from the same database returns `value=True`. An ordinary correctly dated package returns true in both places. Reviewer probe: `runs/e6-25-review-r1/tests/test_e625_process_consumer.py`. Result: **1 FAIL / 1 positive PASS, 36.55s**. The historical reducer was unchanged; the probe emulates old admission by disabling only the new write-side date guard while constructing the old journal.

All three findings were sent immediately to the builder. Original failures and snapshots are retained. **Resolved in R3:** validated journals supply the maximum passport-change date; write-side review guards and read-side effective status reject stale dated checks without rewriting stored snapshots. Both current package acceptance and process evidence consume the boundary. A late issued receipt remains an actual fact but cannot confirm identity before the current passport date; a later distinct proof can refresh it. New process evidence pins `rules_version=2`; old unversioned evidence replays its original v1 interpretation. Explicit unsupported/downgraded versions fail closed.

## Executed evidence on original d847

| Scenario / command | Result | Environment |
|---|---|---|
| `python -m pytest tests/test_kg_document_checklist.py tests/test_entry_applications.py tests/test_entry_documents.py tests/test_entry_issued.py tests/test_entry_group_overview.py -q --tb=short` | **124 PASS**, 240.48s | Env-free archive, synthetic FK-enforced SQLite |
| `python -m pytest tests/test_admin_kg_applications.py tests/test_admin_kg_group_overview.py tests/test_admin_kg_document_inventory.py tests/test_admin_kg_documents.py tests/test_admin_kg_issued.py -q --tb=short` | **83 PASS**, 125.54s | Same archive, native HTTP routes and synthetic SQLite |
| `python -m pytest tests/test_e625_independent_postgres.py -q --tb=short` | **24 PASS / 2 harness FAIL**, 88.75s | Actual migrated temporary PostgreSQL |
| Same PG file, `-k before_insert` after correcting expected exception in reviewer harness only | **2 PASS / 24 deselected**, 14.17s | Actual migrated temporary PostgreSQL |

The initial PG failures expected `EntryStorageUnavailable` for a fault before insertion; the existing transaction layer correctly rolls back/retries three times and returns `EntryStorageConflict`. The reviewer corrected that expectation, retained the original result, and reran only those two cases. This is not claimed as a single green 26-test run. Together the executions verify all 26 selected cases.

PG coverage: same-person linked refusal retries; wrong case/person/attempt/reference; request-key reuse and stale compare-and-swap; simultaneous applicant/application creation; immutable corruption and rehashed forged snapshots; group totals and concurrent reads; six before-insert/before-commit/after-commit recovery controls for inventory/issued journals. Two additional controls actually observed `pg_stat_activity.wait_event_type='Lock'`: a paused passport invalidation blocks both a stale competing inventory review and a group reader; after release the stale writer conflicts and the reader gets a coherent snapshot. Partial application history without its initial draft event blocks both the application view and group totals. No broad repository suite was run.

## Final R3 evidence and coverage

All commands below ran sequentially in `runs/e6-25-review-r3` with synthetic SQLite. Browser traffic was restricted to the local test origin.

| Command / scenario | Actual result |
|---|---|
| `python -m pytest tests/test_e625_independent.py tests/test_e625_process_consumer.py -q --tb=short` | **14 PASS**, 58.59s. Original inventory/passport and issued-receipt negatives now pass, positive controls remain valid, process acceptance agrees with the corrected package view, interrupted writes/retries and missing initial history remain safe. |
| `tests/test_e625_version_gate.py` plus the five exact browser scenarios below in one pytest command | **11 PASS**, 60.25s: six strict version controls and five Chromium flows. |
| `python -m pytest tests/test_document_passport_dates.py -k 'legacy_stale_receipt or old_stale_package_approval or old_process_journal or dated_issued_receipt' -q --tb=short` | **7 PASS / 9 deselected**, 41.19s. Old inventory/package snapshots and request receipts remain readable; old stale approval cannot authorize current acceptance; old unversioned/new versioned process journals replay; old/same-day/later issued receipts and replacement proof behave distinctly. |

Exact browser selections:

- `browser_kg_applications.py::test_separate_applicants_correction_retry_and_independent_result[390-True]`
- `browser_kg_group_overview.py::test_group_overview_filters_navigation_focus_mobile_and_print[1365-False]`
- `browser_kg_documents.py::test_native_document_checklist_review_versions_and_print[1365-False]`
- `browser_kg_document_inventory.py::test_native_document_inventory_versions_and_history[1365-False]`
- `browser_kg_issued.py::test_native_issued_review_receipt_actual_entry_and_history[390-True]`

The desktop flows ran with JavaScript disabled and verified print behavior; mobile flows verified width/focus/navigation and persisted facts. Independently viewed the generated desktop inventory and mobile issued screenshots: text and controls are readable, historical/current context and the limits on package acceptance/admission are visible. Artifacts remain below `runs/e6-25-review-r3/runs/`, including synthetic print PDFs.

Original PostgreSQL evidence is explicitly **d847 evidence**, not a claimed R3 PG rerun. Source comparison found `entry_applications.py`, `entry_group_overview.py`, `entry_storage.py` and `models.py` unchanged byte-for-byte after line-ending normalization. AST comparison found `_history` unchanged in inventory, issued and full-package services. The parent lock, transaction ownership and journal validation paths tested on PG are preserved; R3's changed currentness/consumer behavior was directly checked above. The separate auditor is running its own bounded final R3 PG/old-archive compatibility checks; those results are not counted as the reviewer's own tests here.

| Fixed criterion | Scoped review conclusion |
|---|---|
| E01 | PASS: case-scoped numbered people, six separate procedure/document types, separate linked attempts and wrong-person/case/procedure rejection. |
| E02 | PASS: immutable dated source facts, global unique portal reference, same-attempt return/resubmission, stale/CAS and exact retry controls. |
| E03 | PASS: validated bounded whole-case totals, current versus retained historical attempts, missing applicants, filters/pagination without partial totals or false legal completion. |
| E05 | PASS: refusal/closure recovery creates a linked same-person/procedure attempt while preserving the prior attempt and facts. |
| E07 | PASS: separately verified issue/correction/delivery/receipt/actual travel facts; version/passport currentness; late receipt dates do not renew identity checks; no admission/completion assertion. |
| F01 | PASS: pinned 23-row, nine-product source matrix preserves mixed/conditional/dash content and source-review uncertainty; a checklist is not acceptance. |
| F02 | PASS: per-application immutable metadata inventory, historical replay, scoped revisions, stale/duplicate/partial/corrupt-history rejection and recovery. |
| F03 | PASS on R3: new document/passport identity invalidates old reviews; dated checks cannot rebind stale facts; old journals remain inspectable and stale approvals cannot feed current process readiness. |

All observed test warnings were dependency deprecations; they were not test failures. No required independent-review check remains UNKNOWN within this bounded local scope.

## Boundaries

These criteria concern stored, scoped, manually evidenced facts and currentness. Matrix completeness is not package acceptance; journal approval is not legal eligibility, admission permission or actual external delivery. The review does not award C05, approve source rules, replace owner/pilot acceptance, cover E6-24 intake/source archive work, or authorize a release. Bounded journals and fail-closed capacity limits remain explicit. Source approval, operational policy, full-PDF acceptance, production authorization and the separate final audit cannot be inferred from this scoped APPROVE.
