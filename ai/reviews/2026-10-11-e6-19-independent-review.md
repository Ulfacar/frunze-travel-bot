# E6-19 independent CRITICAL review

**FINAL VERDICT: APPROVE for the exact corrected r2 and bounded local synthetic G03/G04 scope.** Original F1–F3 are closed by source inspection and independent unchanged negative probes, including actual PostgreSQL. The auditor's missing-pointer and terminal-capacity corrections also pass the scoped checks below. No remaining blocker was found in this review. This does not approve deployment, live worker activation, real source/date policy, or all-project J03.

Final source: `runs/e6-19-review-r2`, base `d1c9a38737e600d6508a6e2e1f38c0ca3a9932be` plus five manifest files. Manifest raw SHA256 **`5efce2f48f4da2aacf3d9981b90682cd7cb3680cc8e45c56a8091db0307d467e`**. All **1,130** tracked/overlay files in the frozen source and independent execution copy were verified after execution. Final evidence and detailed applicability follow the clearly historical r1 record.

Reviewer: `/root/portal_pre_audit`, separate from builder and final auditor. Scope: the existing E6-06 internal deadline-task lifecycle and bounded reconciliation, G03/G04. Requirements and actual implementation were read before the historical builder handoff. Local synthetic evidence only; no deployment, real source approval, worker activation, or messages.

## Historical r1 identity and initial verdict

**FIX_REQUIRED** for the reviewed merged r1. Three independently reproduced defects below prevent closing this review gap on r1.

- Frozen source: `runs/overnight-final-r1`.
- Git base: `bdc47f0ac6130f728bf2dd756f8742a950deb58b`, plus the 11 exact E6-18 r2 overlays.
- Manifest: `ai/reviews/2026-10-11-overnight-final-snapshot-r1.json`, LF SHA256 `2cdbb49248c49bf53067a12193a7c8dd91ab44083bf3fe9395dcf8f4cbcc9721`.
- Own execution copy: `runs/e6-19-reviewer-r1`, created independently with `git archive` of the base and individually verified overlay bytes. Initial manifest enumeration verified 1,118 files; final NUL-delimited enumeration also includes five non-ASCII filenames, verifying all **1,123** tracked/overlay files against the frozen archive after LF normalization. Complete source identity is retained in `runs/e619-reviewer-source-identity.json`; preparation script `runs/e619_prepare_reviewer.py`.
- Original requirements: `ai/tasks/2026-10-10-e6-06-deadline-tasks.md`; current external review task `ai/tasks/2026-10-11-e6-19-deadline-task-review.md`. The E6-06 handoff was consulted only after first source assessment was communicated.

Reviewed sources include `entry_deadline_tasks`, its native controller/template, `CalendarTaskService`, existing calendar and conversation mutation routes, task claim/finish/release/transfer rules, application/deadline/travel transaction hooks, binding model and migration 0022. No source or frozen archive was edited.

## Historical r1 findings, closed in r2

### F1 — P2: signed restore authorization omits the new desired source

`app/domain/entry_deadline_tasks.py::_view` hashes binding identity/revision and current task state. It does not include the currently verified desired source/owner. `_attention` does not increase the revision when `schedule_conflict` remains unchanged. The restore path validates that incomplete token before applying the latest source.

Actual HTTP reproduction: enable Oct20; externally move the task to Oct1; record corrected Oct19; obtain the signed restore form showing Oct19; record corrected Oct18; submit the old form. Both FK SQLite and actual PostgreSQL return **303** and apply Oct18, rather than returning **409** and preserving Oct1 until a fresh confirmation. The normal latest-source worker behavior does not justify reusing an operator's explicit restore authorization after the displayed source changes.

Own probe: `runs/e6-19-reviewer-r1/tests/test_reviewer_e619.py::test_restore_form_rejects_unseen_new_source`; PG wrapper `test_native_restore_cas`. Required correction: include the verified desired target in the authorization checked under existing case/application/task locks, consistently in form generation and mutation. Preserve durable exact action receipt lookup before current-state CAS checks.

### F2 — P2: typed audit identity corruption is accepted

`entry_deadline_tasks._task` compares persisted JSON binding/deadline/task identifiers using Python equality. In a valid binding 1, changing only `CalendarTaskEvent.detail.binding` from integer `1` to JSON `true` remains accepted by the task read. Both SQLite and actual PostgreSQL reproduce this. The JSON value is not the stored integer identity, so the required corrupted-history rejection is incomplete. The sibling action receipt binding and whole-command comparisons use the same equality convention.

Own probe: `test_binding_audit_rejects_boolean_identity`; PG wrapper `test_binding_audit_type`. Required correction: strict type-sensitive canonical comparison of the consumed audit and receipt identities/commands, retaining key-order equivalence and legitimate exact retries. This is a bounded task-audit finding, not a claim about all project journals.

Additional actual SQLite confirmation: changing `deadline_action.command.binding` from `1` to `true` also leaves the original exact action retry accepted. `tests/test_reviewer_e619_receipts.py::test_existing_action_retry_rejects_typed_receipt_corruption` fails on r1.

### F3 — P1: the installed calendar writer can resurrect a source-cancelled task

`app/admin/router.py::_apply_calendar_action` obtains the ORM task through the unlocked `CalendarTaskService.get`. Its status/ownership checks and eventual update therefore use a stale row if another transaction changes the task after the read. `CalendarTaskService.reschedule` checks the cached status and writes it back as `rescheduled`.

Actual PostgreSQL reproduction uses the installed action helper: pause a calendar reschedule after its active task read; commit a real `record_deadline_operation(clear)` in another transaction, including atomic task cancellation; resume the original calendar action. The same task becomes **rescheduled** for Oct25 even though its source has **no supported due date**. This is not a manually fabricated status update: the only instrumentation pauses the existing getter, and cancellation is verified before resuming the installed writer.

Own probe: `test_reviewer_e619.py::calendar_cancellation_race`; PG wrapper `test_common_calendar_source_cancel_race`. Required correction: a narrow serialized, refreshed task read followed by current authorization/status checks in the installed calendar mutation path. Retain consistent parent-to-task order wherever parent locks are acquired, and verify claimed bound tasks do not bypass the native uncertainty safeguard.

The claimed-task bypass is also independently confirmed through actual HTTP: after a bound task has both claim fields populated, `POST /admin/calendar/task/{id}/cancel` returns 303 and cancels it. The native deadline action refuses the same uncertain state. Own probe: `test_reviewer_e619_receipts.py::test_generic_calendar_refuses_claimed_deadline_cancellation`.

## Historical independent r1 evidence

Execution environment: environment-free own archive; synthetic FK SQLite, isolated local PostgreSQL 16 at the guarded loopback runtime. The private connection configuration was read only by the existing guarded helper; no credential values are in this report. Commands below run from the own copy unless stated otherwise.

- `python -m pytest tests/test_reviewer_e619.py tests/test_entry_deadline_tasks.py tests/test_admin_kg_deadline_tasks.py tests/test_entry_deadline_tasks_migration.py -q --tb=short --junitxml=runs/reviewer-core-r1.xml --basetemp=runs/reviewer-core-tmp`: **29 PASS, 2 FAIL / 98.19 s**. The two failures are F1/F2. Ordinary explicit enable/unknown date, owner and terminal generations, multi-rule scope, source hooks, retry/rollback, bounded partial batch, native gates, and SQLite migration checks pass. The PostgreSQL migration case here proves offline DDL only, not a real PG migration.
- From root, `python runs/e610_legacy_pg_probe.py runs/e6-19-reviewer-r1 tests/test_reviewer_e619_postgres.py -q --tb=short --junitxml=runs/reviewer-pg-r1.xml --basetemp=runs/reviewer-pg-tmp`: **7 PASS, 3 FAIL / 53.66 s**. F1/F2 also reproduce on PG; F3 is the additional real concurrency failure. Actual PG passing checks cover competing enable and rollback, lost creation/action commit acknowledgements, partial batch resume, claimed task source invalidation, owner/terminal history, and independent rules.
- First core launch had a reviewer harness setup error: its requested nested artifact parent did not yet exist. No acceptance conclusion uses that attempt. The artifact directory was created by JUnit output, then the identical source/tests were rerun with the results above.
- `python -m pytest tests/test_reviewer_e619_receipts.py -q --tb=short --junitxml=runs/reviewer-receipts-r1.xml --basetemp=runs/reviewer-receipts-tmp`: **2 FAIL / 13.41 s**, independently confirming the sibling F2 receipt and F3 claimed-task paths above.
- `python -m pytest tests/browser_kg_deadline_tasks.py -q --tb=short --junitxml=runs/reviewer-browser-r1.xml --basetemp=runs/reviewer-browser-tmp`: **2 PASS / 29.47 s**. Actual Chromium mobile390 and desktop1365 with JavaScript disabled on desktop, native enable/escalate/complete/batch, keyboard focus, horizontal bounds, and one-page print. Mobile state and desktop completed screenshots plus the single rendered PDF page were independently viewed. Artifacts: own-copy `runs/e6-06-task-browser`. All 1,118 source hashes were reverified after execution; `runs/e619-reviewer-r1-evidence.json` records artifact hashes. Separate final auditor owns additional PG migration and COPY recovery evidence; no inferred PASS is assigned here.

## Historical r1 acceptance position

The local processor correctly consumes verified current source state and retains terminal generations in the tested ordinary cases. It does not invent legal dates or recipients. Actual task mutations and recovery were exercised on PostgreSQL, not inferred from DDL. However, the three reproduced failures keep E6-19 at **FIX_REQUIRED** until corrected frozen-source re-review and separate audit. G03/G04 closure is not approved on r1; no new score is awarded. Autonomous scheduling, real worker permissions, production operations, legal/source policy, and all-project J03 remain outside this review.

## Corrected r2 source identity and review

The corrected source was inspected before the builder's final results. Own clean archive `runs/e6-19-reviewer-r2` was constructed from the exact Git base and all five verified overlay files. All three original own probe files were copied byte-identically from r1, including the PostgreSQL cancellation-race instrumentation. New probes exist only in the ignored execution copy. No implementation, configuration or frozen source was edited.

Manifest raw CRLF SHA256 is `5efce2f48f4da2aacf3d9981b90682cd7cb3680cc8e45c56a8091db0307d467e`; LF-normalized manifest SHA256 is `2f7a3b267c3b0fcbef0475b360803d07e7e596c108008cd5e51726a7d38026d7`. The manifest's source hashes describe LF-normalized files. Final source identity: `runs/e619-reviewer-r2-source-identity.json`, SHA256 `bc6283a6be5b123e495313ecbdd4deba51c3b727624afcbadbc07de1898a82c8`. Final evidence index: `runs/e619-reviewer-r2-evidence.json`, SHA256 `739b1577ea5e7be7794a56c588ce4f47085ccc577cd8afcc5359558619cf82d8`.

The initial source enumerator used newline-delimited Git paths and omitted five quoted non-ASCII filenames from its identity map. The actual files had already been extracted by `git archive`. The enumerator was corrected to `git ls-tree -r -z --name-only`; `runs/e619_refresh_full_identity.py` then verified every file in both historical and corrected copies against their frozen targets. This is an evidence enumeration correction, with no source changes or reclassification of test results. Final r2 count is 1,130 files in each target/copy.

- **F1 CLOSED:** desired source/owner target participates in the token; both rendering and locked restore/action validation use the current verified target. The unchanged stale-source HTTP probe now returns409 and preserves the manual date. Source-owner change and fresh restore controls also pass.
- **F2 CLOSED:** consumed JSON binding, deadline and task identities and receipt commands use type-sensitive canonical comparison. Original bool audit and bool exact-retry receipt probes reject corruption; integral-float controls pass. Ordinary reordered JSON keys remain valid.
- **F3 CLOSED:** both installed calendar and conversation helpers refresh under `FOR UPDATE` before checking current ownership and invoking lifecycle operations. Original actual PostgreSQL source-cancel/reschedule race leaves the task cancelled. Claimed bound tasks are refused by both helpers. Real concurrent case reassignment and claim operations are also covered, including four observed PostgreSQL row-lock waits; no speculative scheduling or worker authority is introduced.
- **Auditor A1 supported:** a missing task pointer is valid only with a null expected date and a legitimate waiting attention. Single-pointer and both-null active-binding corruption fail closed; real unknown-date/missing-owner placeholders remain readable and idempotent.
- **Auditor A2 supported:** the ordinary action limit retains a bounded extra terminal receipt. Completion/cancellation and exact retry at capacity work; an extra sentinel detects over-capacity history before any retry. No historical rewrite is required.

The calendar helpers acquire the task lock without later acquiring case/application locks. Their subsequent binding lookup is a normal read, so this change does not reverse the existing parent-to-task lock order. The existing calendar owner/full-admin permission model remains unchanged. Ordinary unbound calendar routes pass their regression suite.

## Independent corrected r2 execution evidence

Commands are shown without credentials. Own-copy commands ran in `runs/e6-19-reviewer-r2`; PG helper commands ran from repository root. All jobs were serialized.

```text
python -m pytest tests/test_reviewer_e619.py tests/test_reviewer_e619_receipts.py tests/test_reviewer_e619_delta.py tests/test_entry_deadline_tasks.py tests/test_admin_kg_deadline_tasks.py tests/test_calendar_admin.py tests/test_entry_deadline_task_integrity.py -q --tb=short --junitxml=runs/reviewer-core-r2.xml --basetemp=runs/reviewer-core-r2-tmp
63 PASS, 2 reviewer-probe errors reported as test failures / 222.35 s.

python -m pytest tests/test_reviewer_e619_delta.py -k claim -q --tb=short --junitxml=runs/reviewer-claim-r2.xml --basetemp=runs/reviewer-claim-r2-tmp
4 PASS, 1 deselected / 17.53 s.

python runs/e610_legacy_pg_probe.py runs/e6-19-reviewer-r2 tests/test_reviewer_e619_postgres.py tests/test_reviewer_e619_delta_postgres.py tests/test_reviewer_e619_wait_postgres.py -q --tb=short --junitxml=runs/reviewer-pg-r2.xml --basetemp=runs/reviewer-pg-r2-tmp
21 PASS / 103.39 s.

python -m pytest tests/browser_kg_deadline_tasks.py -q --tb=short --junitxml=runs/reviewer-browser-r2.xml --basetemp=runs/reviewer-browser-r2-tmp
2 PASS / 25.22 s.
```

The two first-run failures were solely in the new reviewer claim probe: it read nonexistent `ClaimResult.acquired` instead of the existing `ClaimResult.claimed`. The ignored probe was corrected; all four owner/claim cases then passed. The first failing XML is retained. Original r1 negative probes and all manifest files remained unchanged. Thus the 65 named core cases have passing coverage after the focused correction, with two owner cases repeated; this is not represented as an originally green single run. No acceptance test was skipped; the explicit `-k` rerun deselected the already-passing old-receipt case.

The 21 actual PostgreSQL checks cover unchanged F1/F2/F3, audit and exact-retry receipt corruption, claimed HTTP mutation, competing enable/rollback, creation/action lost acknowledgements, partial batch recovery, terminal generations/ownership and independent rules. Additional own cases establish:

- A dynamically loaded exact **r1 domain module** creates a genuine old-token action receipt. The r2 runtime reads it and accepts the original exact request, including after JSON key reordering and a newly recorded deadline source. Only one action receipt remains. The returned current-view token can change; the historical request still resolves without a duplicate action.
- Both installed helper paths pause after their old task read while the real case reassignment service or atomic claim service commits. Current owner/claim is rechecked and the task is not completed by the stale request.
- In four separate scenarios, a real owner-change or claim transaction retains the task row lock while the installed writer starts. `pg_stat_activity` in the same isolated database confirms the writer actually waits on a lock; after commit, the writer refuses based on the refreshed owner/claim. Task status remains planned. This proves the waiting boundary rather than only a sequential reread.

Native Chromium passes mobile390 and desktop1365 with JavaScript disabled on desktop, enable/escalate/complete/batch, keyboard focus, horizontal bounds and print. Own mobile and desktop screenshots plus the sole PDF page were visually inspected. Artifacts remain in `runs/e6-19-reviewer-r2/runs/e6-06-task-browser`. The printed state, generation and audit are legible; there is no blank extra page. All 1,130 frozen/copy source identities were reverified after execution.

## Separate audit reconciliation and final scope

After reaching the source/test conclusion above, the separate auditor's packet was read and reconciled. Its corrected r2 evidence covers original pointer/default250-limit probes, actual scoped migration constraints and populated downgrade refusal, independent concurrent enables, and binary COPY recovery into a fresh migrated PostgreSQL database. Its recovery JSON SHA256 was independently checked as `4ed0a5717fb8d870cca18b78d456c50e4275a7397f7b3f5aafde354bf768c06a`. It reports equality of all56 tables/19 populated, restored sequences, old completion retry/history, native conflict restoration and subsequent new task generation. These are attributed auditor results, not added to the reviewer's own counts. Native pg_dump and production recovery remain unclaimed. The separate auditor retains responsibility for its final signed GO.

The builder's later116PASS report is corroboration only and is not counted as independent reviewer evidence. A broader suite still running is not treated as PASS or as a substitute for the bounded checks.

**APPROVE** the corrected r2 for the existing fixed G03/G04 local criteria: durable assigned internal tasks with completion/cancellation/escalation and deduplication; and a bounded transactional processor handling changes, ordering, retries, duplicates and partial recovery. This closes the independent-review portion of E6-19 for this exact snapshot. No new score, changed criterion, autonomous scheduler, worker policy, production release, real-data operation, external send, or global J03 certification follows from this approval.
