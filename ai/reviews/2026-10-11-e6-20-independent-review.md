# E6-20 independent CRITICAL review

**FINAL INDEPENDENT REVIEW: APPROVE for exact E6-20 r3 and the bounded local synthetic G01/G02 scope.** Original F1 and r2 boundary F2 are closed by source inspection and meaningful independent checks, including actual PostgreSQL. No remaining blocker was found in this review. The separate final audit and its recovery evidence remain a separate obligation; this review does not authorize deployment, real deadline policy, automatic client communication, or whole-project J03 approval.

Final source: `runs/e6-20-review-r3`, base `996059e393cb434fee4df84f5a8bb5896f9425d3` plus ten manifest overlays. Manifest raw/LF SHA256 **`7cad9f5ac9b63100fe8d7e30be98de2370c5219c7a4a32521f8b9e4d93f96947`**. All **1,144** source files in the frozen archive and independent final execution copy match after execution. The final evidence and precise r2-to-r3 applicability follow the historical findings below.

Reviewer: `/root/portal_pre_audit`, independent of the builder and separate final auditor. Requirements and actual source were examined before the historical E6-05 builder handoff. No implementation or immutable source was edited.

## Historical original source identity and requirements

- Committed runtime: `dc474d858aff9c399d37b8cf0c84ba5e5e803aed`.
- Immutable reference: `runs/e6-19-review-r2`; independent environment-free execution copy: `runs/e6-20-reviewer-r1`, created with `git archive` of the commit.
- All **715 non-ai/docs tracked files** match the commit, frozen reference and execution copy after LF normalization. They were reverified after all original checks. NUL-delimited enumeration includes non-ASCII filenames. Identity: `runs/e620-reviewer-r1-source-identity.json`; preparation: `runs/e620_prepare_reviewer.py`.
- Current external task: `ai/tasks/2026-10-11-e6-20-deadline-review.md`; original task: `ai/tasks/2026-10-10-e6-05-application-deadlines.md`; fixed G01/G02 in `docs/pdf-engineering-criteria.json`.
- PDF requirements inspected in the derived source: sections 13.1–13.3, 16.5, 18.8, 18.11 and 19.1. They require attributable actual events, versioned calendar calculation, explicit recalculation and manually confirmed dates with history; they do not authorize turning draft rules or unknown dates into legal client promises.

Actual code examined: the entire deadline journal and source binding modules, source/calculation/calendar persistence and validation, relevant application and issued/travel hooks, deadline task consequences, native controller/template, model/migration constraints, and corresponding source/domain/native/browser tests. Historical handoff was consulted only after first source assessment.

## Historical finding F1 — P2: full valid journal cannot withdraw a manual operational date

The original service permits only 250 revisions and 4 MiB of canonical history. `clear` shares those ordinary limits, even when the previous manual date is known to be wrong. Native forms disappear at revision 250 and the database constraint also caps revision at 250. The stored manual date therefore remains operational and its enabled task stays active after the clear is refused.

This is the separate auditor's independently reproduced finding, supported by this reviewer's direct source assessment, rather than a duplicated execution claim. Original probe: `runs/auditor-e620-r1/auditor_e620_capacity.py::test_valid_manual_date_can_be_withdrawn_at_ordinary_capacity[count/bytes]`. The auditor reports two expected failures on unchanged source with reduced limits, retaining a valid readable history and the active bound task. Actual PostgreSQL and default-limit results belong to the separate audit record.

Additional own original reproduction: `tests/test_reviewer_e620_terminal.py::test_literal_250_native_clear_history_251_and_original_receipts` **FAIL / 9.88 s** on the unchanged independent r1 copy. A valid 250-row linked history passes explicit replay and enables the task, but its native clear has an empty signed revision instead of `250`. XML: `runs/e6-20-reviewer-r1/runs/reviewer-terminal-original-r1.xml`. The fixture uses two genuine API commands followed by valid synthetic hash-linked rows; it does not claim 250 API writes. This exact test file is retained unchanged for corrected-source re-review.

Required bounded correction: retain ordinary limits, allow one explicitly bounded final clear after a valid manual state, and close the journal to further new operations once that terminal allowance is used. Preserve historical reads and exact durable retries. Enforce identical capacity semantics on append and replay. The copied prior snapshot must fit the reserved byte allowance. A new additive migration must change the SQL revision constraint without editing historical migration 0021; populated SQLite self/inbound foreign keys, rollback, and PostgreSQL recovery require actual evidence. Native clear/read/history must expose the final allowed revision.

## Independent original execution evidence

All commands below use the independent copy; PostgreSQL used guarded synthetic UUID databases on local loopback, never production. No optional skip or test failure occurred in these reviewer runs. Deprecation warnings do not affect assertions.

1. **128 PASS / 43.78 s**:

   `python -m pytest tests/test_entry_deadline_sources.py tests/test_entry_deadlines.py tests/test_admin_kg_deadlines.py tests/test_kg_deadlines.py tests/test_reviewer_e620.py -q --tb=short --junitxml=runs/reviewer-core-r1.xml --basetemp=runs/reviewer-core-r1-tmp`

2. **11 PASS / 52.42 s**, actual PostgreSQL:

   `python runs/e610_legacy_pg_probe.py runs/e6-20-reviewer-r1 tests/test_reviewer_e620_postgres.py -q --tb=short --junitxml=runs/reviewer-pg-r1.xml --basetemp=runs/reviewer-pg-r1-tmp`

3. **2 PASS / 24.10 s**, actual Chromium:

   `python -m pytest tests/browser_kg_deadlines.py -q --tb=short --junitxml=runs/reviewer-browser-r1.xml --basetemp=runs/reviewer-browser-r1-tmp`

Own probes and wrappers are `runs/e6-20-reviewer-r1/tests/test_reviewer_e620.py` and `tests/test_reviewer_e620_postgres.py`. Evidence hashes: `runs/e620-reviewer-r1-evidence.json`. XML, screenshots and PDF remain in the independent copy.

The additional independent scenarios establish:

- A signed manual form obtained before a newer actual entry cannot restore a date based on the superseded anchor: HTTP 422, unchanged stored snapshot, current operational date unknown, task cancelled. Both FK SQLite and actual PostgreSQL pass.
- A real manual PostgreSQL writer demonstrably waits on the case row lock while a newer actual-entry transaction holds it. After that transaction commits, the manual writer rejects with recalculation required; it does not use its earlier anchor or revive the cancelled task.
- The original E6-05 deadline and source modules loaded from commit `06df2a61d4fe709f4b0cc0ae9e73f001f6022057` create a genuinely old runtime binding. Current code reads the row and retries its original command exactly, rejects explicit replay under a different runtime, and permits a new current-runtime recalculation. Shared persistence/calculator dependencies are current in this focused compatibility probe; this is not a claim to have booted the whole historical application.
- Pinned calendar versions remain selectable/readable after 44 newer calendar entries move them beyond the latest-40 options window. Replay of the original pinned calculation remains unchanged.
- Exceptions immediately before or after the actual transaction commit leave manual date and dependent task mutually consistent. Retrying the original command produces one successor and the intended matching task date, on both database backends.
- Existing negative scenarios exercise foreign applicants/events, unknown rule values, draft versus operational dates, strict authority, signed native forms, competing CAS, source/calendar integrity, and exact history.

Mobile width 390 and desktop width 1365 without JavaScript pass the real flow. The result screenshots and **all one PDF page** were visually inspected. Candidate date, independently confirmed manual date, exact source label, calendar versions, draft warning and readable history are present; the desktop form has no JavaScript dependency. PDF: `runs/e6-20-reviewer-r1/runs/e6-05-deadline-browser/deadline-demo.pdf`; rendered page: `reviewer-pdf-1.png`.

## Historical scope decision on the original runtime

G01's supported actual-event/source/calendar binding is evidenced locally, including stale/unknown outcomes and immutable historic pins. Unsupported real rule mappings remain explicitly unknown. No real rule/date approval has been created.

G02 remains **FAIL / FIX_REQUIRED** because an active manual date cannot be safely withdrawn at ordinary capacity. The 141 passing checks above do not override that confirmed requirement gap. A corrected exact snapshot, independent migration/recovery evidence and separate final audit are still required before closing this scoped review obligation.

## Historical r2 source assessment and boundary F2

R2: `runs/e6-20-review-r2`, base `996059e393cb434fee4df84f5a8bb5896f9425d3` plus nine overlays. Manifest `ai/reviews/2026-10-11-e6-20-snapshot-r2.json`, raw SHA256 `29df01e8311c235c931cb7a7ae8ee0ad50202ee24bf4b76e3cc3ea3c1a2d4cb1`. All nine overlay hashes and all **1,144** tracked/overlay files matched the frozen source and independently reconstructed `runs/e6-20-reviewer-r2` before execution. Identity and preparation: `runs/e620-reviewer-r2-source-identity.json`, `runs/e620_prepare_reviewer_r2.py`.

Actual source delta was read before builder evidence. It preserves ordinary 250 / 4 MiB limits; allows one final clear after a valid manual prefix; bounds the final payload to the preceding canonical payload plus 1,024 bytes; validates that shape during full journal reads; and refuses later new operations while retaining exact earlier receipts. The source copies no new generic capacity budget. Actor is bounded to 64 characters, key to 64 ASCII characters and clear reason to an enum, supporting the small metadata allowance. SQL model and additive migration 0033 allow revision 251. Native query bounds and clear form availability include 251; the incidental Jinja `forms.clear` method lookup was corrected to dictionary `get`, so unavailable clear forms disappear.

**F2 — P2, narrow new terminal-revision API inconsistency:** `entry_deadline_tasks.reconcile_deadline_task(minimum_revision=...)` still caps that source watermark at `deadlines.MAX_REVISIONS`. A supported terminal revision 251 is consequently rejected before reconciliation. The builder first identified the source concern; this reviewer independently reproduced the actual failure on immutable r2 with a valid terminal clear under reduced MAX=2: `test_reviewer_e620_minimum.py::test_terminal_revision_is_accepted_as_reconciliation_watermark`, **FAIL / 9.50 s**, `runs/reviewer-minimum-original-r2.xml`. The installed native/atomic source-hook paths do not supply this optional parameter, so the observed defect is limited to the public domain reconciliation API. Required correction: accept exactly typed positive values up to MAX+1, preserve waiting semantics before that source exists, and reject MAX+2 / boolean / float values. R2 does not receive final approval while this boundary remains uncorrected.

## Final r3 assessment and applicability

The independently reconstructed final copy is `runs/e6-20-reviewer-r3`; source identity is `runs/e620-reviewer-r3-source-identity.json`; preparation is `runs/e620_prepare_reviewer_r3.py`. All ten overlay hashes and all 1,144 tracked/overlay files were checked against the immutable archive before and after execution.

The complete r2-to-r3 comparison finds exactly five changed files: task review document, migration 0033, deadline task module, and two capacity/migration test files. The actual deadline journal, source resolver, native controller/template, model and remaining runtime are byte-identical. `runs/e620_verify_r3_task_ast.py` independently verifies that the entire task module AST is unchanged apart from the single reviewed `MAX_REVISIONS+1` upper-bound expression. An initial ad-hoc AST navigator used the wrong tree path and raised AttributeError; the retained recursive verification script is the successful reproducible check. No source adjustment was made for that harness error.

The migration now refuses **every populated downgrade**. This is a conservative, justified boundary: a byte-terminal clear can occur below revision 251, and the old reader would reject that history even if the old SQL count constraint accepted it. Empty downgrade/upgrade remains testable. The new minimum-revision range accepts the final source version while retaining strict integer validation.

Therefore r2 native/browser evidence applies to the identical r3 UI and journal implementation; the optional minimum-revision path is not called by the installed browser flow. R3's changed path was separately executed on both databases, and all own actual PostgreSQL source/concurrency/retry probes were rerun on exact r3. R2 results are not relabelled as r3 executions.

## Final independent execution packet

**R2 unchanged runtime/UI evidence:**

- **136 PASS / 82.93 s**, with one deliberate deselection of the builder's repeated 250-API-write loop. The independent literal-250 native probe is included and passes; genuine 250-API-write histories and migration from the old runtime are additionally owned by the separate auditor.

  `python -m pytest tests/test_entry_deadline_sources.py tests/test_entry_deadlines.py tests/test_admin_kg_deadlines.py tests/test_kg_deadlines.py tests/test_reviewer_e620.py tests/test_reviewer_e620_terminal.py tests/test_entry_deadline_clear_capacity.py -q --tb=short -k "not actual_250" --junitxml=runs/reviewer-core-r2.xml --basetemp=runs/reviewer-core-r2-tmp`

- **3 PASS / 37.23 s**, actual Chromium, including the new no-JavaScript clear250→251 flow and complete terminal history print:

  `python -m pytest tests/browser_kg_deadlines.py tests/browser_reviewer_e620_terminal.py -q --tb=short --junitxml=runs/reviewer-browser-r2.xml --basetemp=runs/reviewer-browser-r2-tmp`

- R2 PostgreSQL first run: **16 PASS / 98.67 s plus one reviewer harness failure**. The failing assertion assumed `current.task` always exists after a stale anchor and a later clear. Actual supported behavior retains the cancelled old task and adds a waiting generation with no task. The corrected assertion requires the original task ID to remain cancelled and every history generation to contain no active task. The affected PostgreSQL rerun is **1 PASS / 16.27 s**. Original probe copy `runs/test_reviewer_e620_terminal_postgres-initial.py` and the failed XML remain preserved. This was not a source defect or silently discarded test failure.

**Exact r3 execution:**

- **12 PASS / 32.04 s**, one deliberate deselection of the same expensive 250-API loop. Includes the unchanged original F2 reproduction, literal251 waiting/current and invalid252/bool/float/zero controls, count/byte terminal reserve, refusal of a rehashed new tail, native clear, task rollback, and three SQLite migration checks (empty cycle, populated self/inbound link preservation with conservative downgrade refusal, and FK-on connection refusal).

  `python -m pytest tests/test_reviewer_e620_minimum.py tests/test_reviewer_e620_delta.py tests/test_entry_deadline_clear_capacity.py tests/test_entry_deadline_clear_migration.py -q --tb=short -k "not actual_250" --junitxml=runs/reviewer-delta-r3.xml --basetemp=runs/reviewer-delta-r3-tmp`

- **19 PASS / 123.61 s**, actual isolated PostgreSQL, no skips or failures:

  `python runs/e610_legacy_pg_probe.py runs/e6-20-reviewer-r3 tests/test_reviewer_e620_postgres.py tests/test_reviewer_e620_terminal_postgres.py tests/test_reviewer_e620_delta_postgres.py -q --tb=short --junitxml=runs/reviewer-pg-r3.xml --basetemp=runs/reviewer-pg-r3-tmp`

The final PostgreSQL cases rerun all original source/calendar/history/old-runtime/retry scenarios. Added independent checks prove two terminal clear callers actually wait on the same case row lock: the same key returns the same durable receipt; different keys produce one success and one conflict, with one final revision. Before/after-commit failures retain date/task atomicity and exact retry. A stale actual anchor remains without an operational date, the old task stays cancelled and a waiting generation does not create a new active task. Literal250→251 native save, historical read, explicit replay and original old receipt retries pass. The original F2 probe now passes unchanged, and literal251 returns waiting before clear, current cancelled state after clear, and rejects malformed/out-of-range watermarks.

Screenshots at widths 390 and 1365, the ordinary one-page PDF and **all seven pages** of the terminal251 PDF were visually inspected. The test also verifies every revision label 1–251 in extracted PDF text. The terminal notice is visible, no new write forms remain, historical version250 is readable, and the history tail is not clipped. Artifacts: `runs/e6-20-reviewer-r2/runs/reviewer-terminal-browser/terminal-251.pdf`, `page-1.png` through `page-7.png`, `terminal-mobile.png`, `terminal-desktop.png`; baseline print in `runs/e6-05-deadline-browser/` of that same execution copy.

Final hash indexes, produced after verifying every original source identity again:

- `runs/e620-reviewer-r1-evidence.json`: `6ca7f06956cf1ada8950b4f38e7a6ebb68bf28221e5564311c4c46ec6a12c983`.
- `runs/e620-reviewer-r2-evidence.json`: `f985338e4e64d08286310143fb77b768505adc661ad7355d04267b8a0344ceca`.
- `runs/e620-reviewer-r3-evidence.json`: `43c737f0b4014f28a7d4fb6849fcbd982633e4ae3d5ea0d7738c0c983d6bfb86`.

The counts are separate scenario runs, not a claim of unique tests summed across revisions. Historical FAIL evidence and reviewer harness corrections remain labelled and retained. No builder test count is used as this reviewer's own evidence.

## Final bounded decision

**G01: PASS for the reviewed supported local actual-event/source/calendar binding. G02: PASS for the corrected manual override/recalculation/unknown/terminal-withdrawal history behavior.** The unchanged original source failed G02; that failure is closed only on the exact corrected r3 identified above. This closes this independent reviewer component of the existing G01/G02 obligation and earns no additional feature or broad J03 approval by itself.

Real source values, legal counting policy and production behavior remain outside this approval. Ordinary claimed-task and externally changed schedule conflict safeguards remain in force; the correction does not override those pre-existing attention policies. The final auditor separately owns the real old250 migration, injected rebuild rollback, PostgreSQL migration/COPY restore and final audit verdict. No deployment, real-data migration, provider activation or message was performed by this reviewer.
