# E630C conditional work-review task — independent review

**Final scoped verdict: APPROVE for the R40 domain/source/history/recovery changes reviewed here.** All nine concrete findings below have corrective evidence or exact unchanged-source mapping. This is not the final whole-adapter audit, native acceptance, PostgreSQL certification, J01/J02 completion, real source/policy approval or release authorization. Historical failing snapshots remain preserved below.

## R27 checkpoint: FIX_REQUIRED

Independent source-first review against `2026-10-13-e6-30c-deadline-task-pre-audit.md`. This is the new conditional internal review adapter only, not the aftercare consumers, all of C, J01/J02 acceptance, legal/source approval or release. Native implementation and final schema/PostgreSQL evidence remain pending at this checkpoint.

Original env-free source: `runs/e630c-review-adapter-r27`, from Git archive `7b0475b536592f6d254d607fb4baf3619a6e7fff` plus **22/22 independently hash-verified overlays** of `runs/e6-30c-r27`. Manifest raw SHA256 `b3360d1351c918c0560d2e73cd47e3607950518b064ccf70922fc0466261ebdb`. No `.env` was copied/read. Independent code/tests live only in this reviewer archive; root runtime/tests were not edited. No PostgreSQL or providers used.

Scoped LF identities:

| Input | SHA256 |
|---|---|
| `app/domain/work_review_tasks.py` | `242880bba9bb8abe689237090a5ae9803b24ed7043dbf1e0ceb60c42589e6838` |
| `app/domain/work_review_policy.py` | `0fe4e14d7b10ae5e81e93eea3f8e446d110a0e70daa7237d7f860ce5fe7e95ea` |
| `app/domain/work_deadlines.py` | `81436989aef86060cbc3a96c11de2169f6f639088e651db8c5aaf3d5c5d8f0ee` |
| `app/domain/models.py` | `1717c281df447ab69208a10bb2179bc5ecf15efe3b2da3a845580f1183f13cf4` |
| migration0041 | `f3831197cf7bfda13643b7f0b51898aba7ed8998341ab2739595cca943e4b06d` |

## Confirmed findings

**WRT-01 — MEDIUM, ordinary cancellation loses semantic identity.** Create a valid task; remove current authority; explicitly refresh and cancel the projection; restore exactly the original authority. The last cancellation-via-refresh snapshot has `semantic=None`. `new_generation` now accepts the unchanged original date/anchor/policy and creates a new task. Code: `record` stores `current['semantic']` on non-terminal refresh, while terminal-preservation compares only the last snapshot. Preserve the latest verified semantic identity across unknown refreshes. Explicit re-enablement must still distinguish genuinely changed meaning from merely disappearing/reappearing authority.

**WRT-02 — MEDIUM, retained pointer can capture another same-case task.** Create an unrelated same-case `CalendarTask` with otherwise matching internal-task fields. Alter the first immutable receipt's task pointer and snapshot task id, recomputing its ordinary content hash. `read` accepts the replacement. `_task` checks broad scope and other work-review applications but never binds the mutable projection back to its actual `work_review_bound` audit event. The accepted pointer subsequently selects the unrelated row for task actions. Validate exact receipt/event/task/application/applicant identity. This is a persisted-corruption negative control, not a claim that an unauthenticated client can edit the database.

**WRT-03 — MEDIUM, historical source claim is not verified.** Change only retained `report.source.rule_hash` and recompute the report and receipt hashes. `read` accepts the false source claim. `_history` reconstructs the calendar arithmetic and verifies selected profile/history pins, but does not compare the full report source/provenance and required semantics to retained authority and immutable source evidence. Check source/interpretation/temporal scope, fixed non-actionability fields, fact and evidence relationships. Historical verification must use the recorded source and prefix/time; today's withdrawal or expiry must not make otherwise valid receipts unreadable.

**WRT-04 — MEDIUM, retained operator projection becomes independent authority.** Append a different named full administrator to `snapshot.operators`, recompute the receipt hash, then submit a fresh explicit cancellation with `authority=None` as that administrator. The cancellation succeeds despite the operator being absent from the retained review delegation. `_history` only checks that the original writer occurs in the list; `record` then treats the list as fallback authority. Derive and validate the initial operator set from the authority and its subsequent inheritance/authorized replacement from prior receipts. Compact cancellation snapshots must not grant their own operator list. The probe requires deliberately corrupted storage; it verifies the required fail-closed retained-authority boundary.

**WRT-05 — LOW, public calculation wrapper validation moved behind storage.** The extraction to `evaluate_in_session` leaves all authorization/id/type checks inside the opened transaction. `evaluate(None, actor=non_admin, ...)` and a full-admin request with case id 0 now raise the engine `TypeError`, where the prior wrapper rejects first with `PermissionDenied`/`EntryStorageInvalid`. Restore existing public validation before `_run` while keeping the same-session entry point defensive. This is an authorization-order/compatibility regression, not evidence of an unauthorized database mutation.

## Independent execution evidence

Commands run from the env-free reviewer archive, with real synthetic SQLite transactions and FK fixture:

* `python -m pytest tests/test_reviewer_work_review.py -q --junitxml=runs/reviewer-r27.xml` — **4 FAIL / 145.48s**, all four assertions are the intended original defects above; no setup/harness failure. Includes ordinary no-reopen and connected persisted-corruption controls. The fourth test reaches an actual unauthorized-by-delegation cancellation.
* `python -m pytest tests/test_reviewer_work_wrapper.py -q --junitxml=runs/reviewer-wrapper-r27.xml` — **2 FAIL / 1.27s**, both original public-wrapper ordering failures.

Original tests and artifacts are preserved. These six failures must be rerun unchanged on a later fixed snapshot, alongside ordinary positive/retry paths; no corrective PASS has been claimed yet.

## Structural assessment and still-required evidence

The separate default-empty policy, full authority digest links, same-person EP composite FK, date-only task with empty channel identity, explicit operator reconciliation, distinct conditional comment and compact reserved cancellation receipt match the intended scope. The public helper's permission flags remain non-actionable. Current case/application/person/task/publication locks hold through calculation and projection mutation, but lock-wait, concurrent source/profile withdrawal and generic-calendar races require actual PostgreSQL evidence before approval.

Bounded reads, immutable model guards, prior receipt/hash chain and uniqueness constraints are present. That does not substitute for the semantic history and projection checks found missing above. Migration0041 protects populated downgrade by inspection and lock; actual migration parity, populated preservation, receipt capacity/byte reserve, unknown current authority and terminal generation controls still need their own executed evidence. Native page, signed/CSRF/scope confirmation, outage/retry and actual calendar visibility remain pending. No scoped APPROVE or separate final GO at R27.

## R29 correction and independent follow-up: still FIX_REQUIRED

Frozen R29: same base, **23/23** overlays independently verified; manifest raw SHA256 `94de55c85f1372de8500b0e983d5b1abd61a8c47daed845d30f05a0b3452da25`. Own archive `runs/e630c-review-adapter-r29`. Relevant LF hashes: task module `b35d4921fd82dbe0fcbb7e969c20ba555aa8a552b1ebac7471f59fc1e7333736`, new historical verifier `90346f8dfc07c0d633456afd153601533aa7add6b71ef961d9136ad1ca617a5f`, public helper `0acf1bb0ad63f67fce25f5bcb6f10ff152ca866ba5d2750f1140166727e31b45`. Policy/models/migration unchanged from R27.

Corrections preserve semantic identity during an unknown refresh, validate the bound task's audit, derive retained operators, validate historical source/person/application evidence and restore early public-wrapper checks. Source read preceded the corrective run. Original assertions were retained; the copied four domain probes import only the new `review_clock` fixture, placing the receipt at 15:00:01 after its evidence at 15:00.

`python -m pytest tests/test_reviewer_work_review.py tests/test_reviewer_work_wrapper.py tests/test_work_review_tasks.py -q --junitxml=runs/reviewer-r29.xml` — **8 PASS / 297.55s**: six original corrective assertions plus two ordinary positive/retry/restore/terminal controls. This closes those concrete original reproductions on R29; it does not prove the new historical verifier complete.

The new task-audit check can reject a rehashed receipt during `read()` even when historical validation would accept it. Therefore the independent follow-up calls **exact retry**, which validates `_history` and returns before reading the mutable projection.

**WRT-06 — MEDIUM, remaining nested historical evidence/type gaps (R29).** Exact original retry accepts (a) a substituted `current_stay.calendar.hash`, and (b) `current_stay.case_id=True` for integer case id 1, after recomputing nested and outer evidence hashes. The new verifier omits the nested calendar comparison and relies on Python's bool/int equality for that scope. These are retained-integrity negative controls, not fresh authority bypasses. Require derived nested metadata and strict/canonical typed comparisons. R31 source changes address these two specific checks; execution is pending below.

**WRT-07 — LOW, later equal-time source review invalidates exact old retry.** Save the valid receipt and calculation at 15:00, then independently reject STOP12 at the same timestamp in a later transaction. Exact original retry fails `work_review_evidence_integrity_failed` at the call to `context.availability`: it selects the newest decision with timestamp `<= at`, including the later decision. This differs from `head()`'s intentional allowance for later equal-time immutable revisions. Preserve the selected historical review prefix/identity while keeping a fresh current calculation blocked. This is a deterministic clock-resolution recovery control, not a claim about frequent production clock collisions.

`python -m pytest tests/test_reviewer_work_history.py -q --junitxml=runs/reviewer-history-r29.xml` — **1 PASS, 3 FAIL / 143.54s**. The positive uses a real later profile correction and later source rejection at 16:00 and verifies original receipt/read preservation. The failures are the two WRT-06 exact-retry corruptions and WRT-07 equal-time recovery; no harness failures. Original artifacts remain unchanged.

## R31 original terminal-time finding and R34 corrections

**WRT-08 — MEDIUM, a normal explicit cancellation makes its own journal unreadable (R31).** Create the conditional task, then reschedule it using the real `CalendarTaskService` to a different date with an explicit timezone-aware time. The adapter correctly shows `schedule_conflict`. Explicit cancellation succeeds and preserves that external time in the terminal snapshot, but the next exact retry fails `_history` because retained task validation unconditionally requires `at=None`. This is an ordinary connected action sequence, without corrupted storage. Terminal snapshots must preserve and validate a canonical external time; active calculated reminders must still be date-only.

Own R31 archive has **29/29** verified overlays and raw manifest SHA256 `3cface06ca6c1b101dfb5aa03864f9c3924424593ca61b43f3fac0a19704404f`. Command `python -m pytest tests/test_reviewer_work_history.py tests/test_reviewer_work_projection.py -q --junitxml=runs/reviewer-history-projection-r31.xml` — **3 PASS, 2 FAIL / 210.81s**. WRT-06's nested calendar/type guards now pass and later non-equal-time profile/source changes preserve history; WRT-07 and WRT-08 remain genuine failures. Original artifacts and assertions are preserved in `runs/e630c-review-adapter-r31`.

R34, **34/34** verified overlays, raw manifest SHA256 `faf418ea2f4f2b47daf6194897630975fb32135354e9bd95053a8893fa712cfe`, corrects both remaining paths. `work_review_evidence.py` selects each historical unit decision by the immutable publication manifest's id/hash, checks its original-time availability, and rejects omitted successors strictly earlier than observation. A serially later equal-time review does not rewrite the old observation. A new equal-time interview header similarly cannot rewrite an originally absent interview. `work_review_tasks.py` validates a retained terminal timestamp as canonical aware UTC, while active calculated tasks still require `at=None`.

Source-first corrective command on `runs/e630c-review-adapter-r34`: `python -m pytest tests/test_reviewer_work_history.py tests/test_reviewer_work_projection.py -q --junitxml=runs/reviewer-history-projection-r34.xml` — **5 PASS / 201.20s**. Original defect assertions remain unchanged. The equal-time source scenario additionally proves that a fresh read is ineligible after rejection, a later equal-time interview header preserves the old receipt, explicit no-authority reconciliation cancels the task, and retry of the original operation still returns the original receipt. Thus preserving historical evidence does not restore fresh source authority.

## Final domain identity mapping: R36 to R38

R36 independent archive `runs/e630c-review-adapter-r36` was constructed from Git archive `0398bfdd372ecc9e946787913f5b849535075034` plus **32/32** independently verified LF overlays. Raw manifest SHA256 `90d4ffab9ded18519acf496bea5a1fa07486e67e307c57be8c2d1298e3fdc708`. It contains no `.env`. R38 uses the same base and 32 overlays, raw manifest SHA256 `4e9a1b1139cba5c68686498a7c2f750bf026d8ee934325d661c35f73bdc086a3`.

All six scoped files below were independently read/hash-checked against both manifests. The R36-to-R38 changes are only native template, state and source-scenario tests; they do not alter these scoped runtime/schema files.

| File | Final LF SHA256, identical R36/R38 |
|---|---|
| `app/domain/work_review_tasks.py` | `762ad4ffa6219d2c0e52d210df8e0dd676e1a67e391c6b70eb18e33391416f2f` |
| `app/domain/work_review_evidence.py` | `4640b70e47bb02425ce9a415ddae6f3bb8b1ca1b46568fac6b0931c1ff1b469b` |
| `app/domain/work_review_policy.py` | `0fe4e14d7b10ae5e81e93eea3f8e446d110a0e70daa7237d7f860ce5fe7e95ea` |
| `app/domain/work_deadlines.py` | `0acf1bb0ad63f67fce25f5bcb6f10ff152ca866ba5d2750f1140166727e31b45` |
| `app/domain/models.py` | `1717c281df447ab69208a10bb2179bc5ecf15efe3b2da3a845580f1183f13cf4` |
| `alembic/versions/e6_work_review_events_0041.py` | `f3831197cf7bfda13643b7f0b51898aba7ed8998341ab2739595cca943e4b06d` |

The actual R34-to-R36 task diff was separately inspected. It requires a non-null retained task, refuses `restore`/`new_generation` without current eligibility and an owner, checks receipt time against previous receipt and calculation observation before commit, and refuses eligibility when the current application/header event lies after the calculation observation. Historical evidence, authority parser, helper, models and migration are otherwise byte-identical to the tested corrective path.

Own R36 command `python -m pytest tests/test_reviewer_work_final.py -q --junitxml=runs/reviewer-final-r36.xml` — **1 PASS / 88.36s**. The connected control rejects unknown-authority restore/new-generation, then actually enters task completion with a rolled-back receipt clock. The transaction rejects the clock, leaves the task planned and journal unchanged, and still returns the exact original receipt on retry. This is executed rollback evidence, not just an exception assertion.

## R36/R38 exact-retry follow-up: FIX_REQUIRED

**WRT-09 — MEDIUM, immutable projection binding was checked only for fresh reads.** The builder raised this extension of WRT-02 during final review; I independently inspected and reproduced it. Save a valid receipt, create another ordinary same-case follow-up task, replace the saved receipt's `task_id` and `snapshot.task.id` with the unrelated id and recompute its content hash. Exact retry of the original command with no current authority returns the malformed receipt instead of refusing it. `_history` only checks the pointer's internal shape; the actual `work_review_bound` event check lives in `_task`, after the early duplicate return. Fresh `read()` refuses the same corruption. This is a retained-storage integrity control, not a remotely available task substitution exploit.

Original R36 command `python -m pytest tests/test_reviewer_work_retry_pointer.py -q --junitxml=runs/reviewer-retry-pointer-r36.xml` — **1 genuine FAIL / 38.03s**, no fixture failure. Test and artifact preserved in `runs/e630c-review-adapter-r36`.

The reviewed corrective R40 diff adds one bounded audit query for the retained task ids and validates every receipt's unique bound event against its task id, actor, receipt id/hash, own application and person. Historical retry does not read current mutable task state, and each row uses its own retained event rather than the newest binding. Existing current-projection validation remains. R40 archive is independently frozen from base `0398bfdd372ecc9e946787913f5b849535075034` with **32/32** verified overlays, raw manifest SHA256 `e27e229e2339d75aafe0d5a7bf9254b1fdb4a89e58483fc5394c54c3d519f50f`. Corrective execution is pending at this checkpoint; no final APPROVE yet.

## Final R40 corrective evidence and scoped verdict

The only runtime change from R38 to R40 is the inspected per-row binding check in `app/domain/work_review_tasks.py`, final LF SHA256 **`5731922c686fdcacc68c14fbb8c82deb45994ca47bd132fff88039393c711511`**. The other five runtime/schema identities in the table above remain exact. All 32 R40 overlay identities were checked again before this verdict.

Own command from `runs/e630c-review-adapter-r40`:

`python -m pytest tests/test_reviewer_work_retry_pointer.py tests/test_reviewer_work_direct_evidence.py tests/test_reviewer_work_projection.py tests/test_reviewer_work_history.py::test_later_review_with_same_timestamp_preserves_original_receipt -q --junitxml=runs/reviewer-corrective-r40.xml`

**4 PASS / 210.96s.** This executes the unchanged original WRT-09 pointer control and both important historical positives: terminal cancellation after a legitimate exact-time calendar change, and equal-time later source/interview changes followed by a second receipt on the same task and exact retry of the first receipt. The separate direct-evidence test calls the actual `verify_report` with the valid retained report, then with rehashed nested calendar metadata and a bool substituted for case id. The valid report passes and both substitutions fail. Thus the new audit check has not merely hidden a still-missing historical semantic check.

**APPROVE, scoped to the domain adapter and historical evidence contract at R40.** The reviewed behavior creates only a conditional internal review reminder on the exact person's EP application under explicit separate authority. Its calendar row is date-only, uses an empty channel identity and a conditional comment; it does not approve filing, work/stay eligibility or client communication. Loss of authority is visible and can be explicitly reconciled/cancelled; no automatic revocation watcher is claimed. Old commands retain exact receipts without restoring current authority or requiring today's mutable task state. A changed terminal meaning and a fresh explicit operation are required before a new generation.

Limitations and distinct gates:

* All own executions here used synthetic SQLite with the existing FK fixture, on env-free immutable source archives. No production, real personal records, provider requests, root `.env`, source approval or deployment was used.
* Actual PostgreSQL concurrency, source/profile withdrawal races, calendar claim/cancel races, real 64-row/4-MiB terminal reserve, migration round trip/populated refusal and backup/restore belong to the separately coordinated builder/final-auditor evidence. This report does not claim to have executed those checks. In particular the future application-head clock scenario is independently audited elsewhere; its R36 correction was source-inspected here.
* Native signed forms, access/CSRF, 409/422/503 recovery, browser presentation and final whole-adapter GO are separate review/audit scopes. Their absence from this report is not a waiver of the task's completion requirements.
* The adapter supports the separately delegated ten-working-day conditional UZ ordinary single-citizenship work-hire date. It does not complete the other source −5/−7/−10 anchors, all fourteen SOPs, broader source acceptance or any parent score criterion.

Root implementation/tests were not edited by this reviewer. Parent may promote the preserved probes; keep their assertion semantics and fixture imports. Relevant files are the R34 `test_reviewer_work_review.py`, `test_reviewer_work_history.py`, `test_reviewer_work_projection.py`; R36 `test_reviewer_work_final.py`, `test_reviewer_work_retry_pointer.py`; and R40 `test_reviewer_work_direct_evidence.py`. The original R27/R29/R31/R36 failures must remain distinguishable from corrective evidence.
