# E630C — independent bounded work-deadline review

Date: 2026-10-13. Reviewer: `publication_review`. CRITICAL parent task, solo protocol, independent review of the conditional EP filing-date component only. **Final verdict: scoped APPROVE on frozen R9.** Original R4 finding WD-01 is fixed and independently retested. This is not whole-C approval or a J01/J02/J03/J05 award.

## Scope and source identity

Read actual `work_deadlines.py`, its test, called current-stay/fact/profile/source readers and the working-day arithmetic before builder conclusions. Requirements: original PDF §19.11 and Б.8 UZ worker, task `ai/tasks/2026-10-13-e6-30c-source-acceptance.md`, independent pre-audit `ai/reviews/2026-10-13-e6-30c-pre-audit.md`. Original PDF SHA256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`; relevant source pages were independently verified in the pre-audit.

Target: env-free `runs/e6-30c-r4`, base `d57a0f0a8ea91358edb6e8df654d623fde06264e`, **14/14 LF overlay hashes verified**. Snapshot raw SHA256 `b18e96bef0ea640e4b15d25442112773dcb145d911b1233650bf603b38d9ac7f`. Reviewed `app/domain/work_deadlines.py` LF SHA256 `fb684450e4590fb30f74b800a50dfb1d78e6c81f840561dd2d31ccbd78e20834`; existing test LF SHA256 `9573d686f3eb0733725cf63d4f96f438207876db6f9780fc1b4e2743d1bcd392`.

Own archive `runs/e630c-deadline-review-r4` was built from Git archive plus those exact overlays using `runs/e630c-deadline-freeze.py`. No root `.env`, shared runtime/test edit, PostgreSQL, provider, real data, source approval, timer or notification was used. SQLite probes have the repository external-network guard. No production/release approval is in scope.

## Finding WD-01 — current interview purpose can contradict the narrow work scope

**Severity: MEDIUM, applicability/integrity; R4 FIX_REQUIRED, closed on R9 below.**

Trigger: a current own profile says `purpose='work_hire'`; an interview on that exact profile is started through the real API, its initial work handoff is ACKed by its owner, the owner explicitly corrects purpose to `tourism`, and the resulting card is ACKed. The supplied server factual attestation pins the exact current interview/header hashes. No stale head, malformed row or forged policy is used.

Expected: this narrow work-hire-only helper returns unknown/no date until conflicting current scope is reconciled. Actual: R4 returns `status='calculated'` rather than `unknown`.

Cause: `work_deadlines.evaluate` tests work purpose only in the saved profile. Its called `current_stay_stops._evaluate_in_session` correctly reconciles location, basis, entry/end, nationality, residence and passport facts, but is purpose-neutral and does not compare interview purpose. Thus a valid latest interview pin is mistaken for agreement on the helper's additional scope condition.

Impact is limited: output is explicitly conditional, with no work/stay permission, quotation, task or send. It nonetheless supplies an apparently applicable work filing date despite known contrary current data. Do not broaden the shared current-stay helper merely to fix this component. Validate any explicitly supplied current interview purpose in the work helper (using the real retained typed answer), and fail closed for unknown/conflicting purpose; preserve the existing exact-head, actor and consent guards.

Independent persistent repro: `runs/e630c-deadline-review-r4/tests/test_reviewer_work_deadlines.py::test_current_interview_contradicts_work_purpose`. Command from that archive:

`python -m pytest tests/test_reviewer_work_deadlines.py::test_current_interview_contradicts_work_purpose -q --tb=short --junitxml=runs/reviewer-purpose-r4.xml`

Result: **1 FAIL, 37.52s**. The assertion reached the real helper and observed `calculated`. Artifact: `runs/e630c-deadline-review-r4/runs/reviewer-purpose-r4.xml`.

## Completed verification

Command from own archive:

`python -m pytest tests/test_work_deadlines.py tests/test_reviewer_work_deadlines.py -q --tb=short --junitxml=runs/reviewer-deadlines-r4.xml`

Result: **6 PASS / 1 probe-harness failure, 270.07s**. The first contradiction probe attempted a correction before ACKing the initial work handoff, and existing code correctly rejected collection in that phase. That is not a runtime defect. Initial probe is preserved at `runs/reviewer-work-deadlines-initial-probe.py`; corrected real ACK → correction → ACK sequence produced WD-01 above. The initial test source also contained an unused incorrect lookup for the returned head; correction uses `view['history'][-1]['snapshot_hash']`. These harness fixes did not change application code.

Passing behavior:

- Existing source-clause test: exact ten working days, original deadline value remains null, threshold result five is only a lower bound, missing/changed authority and withdrawn personal history suppress the date.
- Independent arithmetic oracle: both anchor-day policies, actual synthetic holiday/working-Saturday overrides and a 2026→2027 scan match the returned date; exactly ten trace days are counted. SQL statement capture observes **no INSERT/UPDATE/DELETE/REPLACE/CREATE** during evaluations.
- Equality at the calculated day uses the separately declared inclusive/exclusive boundary; it is not silently fixed to one convention.
- A complete, correctly pinned 2026-only calendar cannot cover a 2027 anchor: unknown `calendar_missing`, no partial date/calculation.
- Wrong delegated operator, removed publication policy, absent fact, calendar approval not covering the excluded anchor, changed passport/profile/person pin, duplicate operators and integer-instead-of-boolean policies all fail closed or reject invalid input.
- A calculated date preserves a nested triggered STOP12 and `requires_specialist=True`, while permission fields remain null, `may_quote=False`, and `delivery='not_sent'`.

Source inspection additionally confirms case/person locks precede the called same-session current/publication evaluation; current time is sampled after those locks. Active source/version and exact clause hash are checked again in the same session. `_working_deadline` validates even an excluded anchor's calendar year, visits each scanned day and has an explicit scan bound. Work calendar approval dates must cover the whole trace. No old deadline journal, live source value, scheduled task or outgoing message is mutated.

## Semantic boundary and outstanding verification

Parent confirmed the conditional date may remain calculable when a current stop is triggered; `within_filing_deadline` is a date comparison, never readiness. This is acceptable for the stated read-only scope only while the stop and non-actionability remain explicit. R9 adds top-level `requires_specialist=True` / `operational_action_allowed=False`; source inspection and own positive/blocked controls below verify these fields.

The separate policy explicitly delegates the interpretation of a pinned source clause whose original `value` is null. It does not silently execute or rewrite the draft. A future non-null conflicting clause is rejected by source inspection. The approved synthetic source shape and calendar are test authority only, not real legal approval. The helper does not independently establish eligibility, legal permission, TPP concession, source-current law or an authorized EP route.

No PostgreSQL probe was run: another auditor owns that slot, and this bounded component is a read-only helper reusing existing locks. Native persistence, timer reconciliation, historical-operation retry/replay, all work lifecycle transitions and full-C acceptance are outside this helper's claimed scope; this report does not certify them. The arithmetic year-crossing probe tests a separately attested synthetic anchor; it is not evidence that that long UZ visa-free stay is legally permitted.

## Frozen R9 corrective verification and final disposition

Own env-free archive: `runs/e630c-deadline-review-r9`, same base `d57a0f0a8ea91358edb6e8df654d623fde06264e`; **17/17 overlays verified**. Snapshot raw SHA256 `845651cab1b98599c7532cc54ec666e90d5dec20a4501dddf96929391867a3fe`. Final `app/domain/work_deadlines.py` LF SHA256 `63cad5cf5d8ec36aefd739187fcbd8c8bea73fa9741b41cd28814a3146e6d0ec`.

`runs/e630c-deadline-review-r9/runs/review-identities.json` independently maps twelve scoped files: the original test and ten called current-stay/profile/history/interview/publication/arithmetic/storage helpers are unchanged from R4; only the reviewed work helper changed. Manifest raw SHA256 `d0bbac278573cabba60b3ef456e35d9e6a61ca5fe9a0383d7b724862c519b68a`. The broader process/models/migration overlays are outside this verdict. They are not implicitly approved by these SQLite fixture runs.

The actual correction rereads the validated current interview header/history in the same locked session and requires its purpose answer to be `work_hire`. Absent or explicit unknown purpose also yields `work_deadline_interview_purpose_unresolved`, with no due date. No-interview cases retain the explicit profile/own-fact authority contract. The shared purpose-neutral current-stay reader is unchanged. The only other helper delta adds the non-actionability fields described above.

Corrective command from own R9 archive:

`python -m pytest tests/test_reviewer_work_deadlines.py::test_current_interview_contradicts_work_purpose tests/test_reviewer_work_deadlines_followup.py -q --tb=short --junitxml=runs/reviewer-correction-r9.xml`

Result: the **unchanged original WD-01 reproduction PASS**; the second test reached its absent/positive/unknown/stale-purpose assertions successfully but then used a nonexistent privacy action name in the probe. Suite result **1 PASS / 1 probe-harness failure, 85.49s**. Preserved initial follow-up source at `runs/reviewer-followup-initial-probe.py`. Application correctly rejected `withdraw_consent` as an invalid action; this is not an application defect.

Corrected the probe to the existing real `interrupt(reason='consent_withdrawn')` followed by owner ACK, then reran just that sequence:

`python -m pytest tests/test_reviewer_work_deadlines_followup.py -q --tb=short --junitxml=runs/reviewer-followup-r9.xml`

Result: **1 PASS, 51.03s**. It proves all of the following through actual journal API calls and fresh exact pins: absent purpose → unknown; known `work_hire` → exact expected date and no permission/action; changed head → unknown; explicit unknown purpose → unknown; restored known purpose followed by privacy withdrawal and owner ACK → collection remains blocked and no date. The test does not mutate runtime or synthesize interview rows directly.

R4's six passing arithmetic/authority/read-only controls are mapped to the unchanged called code and unchanged calculation path; they are not falsely reported as rerun on R9. The final two corrective scenarios passed separately. Both historical harness failures and the genuine R4 runtime failure remain available.

**Scoped APPROVE:** the R9 read-only, separately delegated, conditional ten-working-day EP filing-date helper for the declared UZ ordinary single-citizenship `work_hire` profile, under exact own current evidence and source/calendar authority. No remaining defect found in that bounded review. It still requires a specialist, grants no permission or route, and creates no timer, stored receipt, quote or message. Native/persistence/integration claims, PostgreSQL concurrency certification, full-C acceptance and real policy/source/owner approval remain outside this verdict. No own test process remains active.
