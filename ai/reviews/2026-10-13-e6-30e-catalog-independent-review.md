# E630E — independent source catalogue / pure schedule review

2026-10-13, `calculation_review`, CRITICAL / solo. **APPROVE for the bounded38-duty pure catalogue and canonical schedule component, exact module hash below; not whole-E approval.** Actual process/authority/journal/task/native integration does not yet exist in the reviewed target. Root implementation was read only. No root application import, environment, PostgreSQL, provider or production operation was used.

Read the task, actual `operator_sop_rules.py`, original PDF and adjacent process role resolver before implementation conclusions. The separate source pre-audit is complementary, not a replacement for these checks. Original source SHA256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`; inspected printed pages62–65 and78–83.

## Source assessment

The initial closed32 duties have a sound bounded purpose: selected internal review, not automatic SLA calculation. Source intervals in their descriptions are context, not derived official due dates. Keeping `calculation=not_performed`, `origin=operator_selected`, `official=False` and `calculated=False` is appropriate. An exact time is optional; null must remain a date-only task, without invented midnight.

Confirmed static source-reference corrections were sent before integration: exemption V24 is printed63, not64; the analogous V05 row is62. Work W09/W10 document reminders, W12 twice-daily status and W13 correction are §19.9 printed82; visa V17's10:00/16:00 and urgent2–3-hour wording is §19.1 printed78 and is not a literal work requirement. The subsequently captured pure module has explicit per-stage `source_refs` / overrides correcting these distinctions. References should use the actual primary section per stage, rather than combined section strings paired with only one printed page. Human labels may summarize, but must not present an operational extension as a verbatim source clause.

The closed32 catalogue is not an exhaustive mapping of §14 reminders. The following source duties need an explicit existing connected capability or a closed E duty before any catalogue-completeness claim:

| Stage | Exact source location and duty | Narrow manual purpose |
| --- | --- | --- |
| V11 | §14.2 p62, reminder to inviting party every2 working days | `INVITER_FOLLOWUP`, pending own inviting-party evidence |
| V13 | §14.2 p63 says follow-up asV10; V10 p62 listsD+1/3/7/14 | Explicitly addV13 to the corresponding document duties with both references; no `V*` wildcard |
| V14 | §14.2 p63, submit in same working day, urgent≤2hours | `READY_SUBMISSION_REVIEW`, current readiness only |
| V23 | §14.2 p63, entry-eve memo and next-day entry confirmation | Separate `ENTRY_EVE_REVIEW` and `ENTRY_CONFIRMATION_REVIEW`; selected task does not send or confirm entry |
| V25 | §14.2 p63 / §19.1 p79, feedback and repeat trip | Closed feedback / repeat-trip review purposes, successful completion only |

This is not a request to compute those SLAs or add sending. The operator can choose when to review the corresponding source obligation. Existing generic `OTHER_AFTERCARE` is not a substitute for arbitrary missing stage applicability.

## Narrow exceptions and linked roles

* `STUDENT_ANNUAL`: root visa process atV24/V25, same own current applicant/profile with study purpose, validated own S package/product context. The source's annual follow-up may survive successfulV25 only through this explicit duty exception. It cannot admit stopped/refused/X states, another student's S package, an expired authority or privacy stop. Current REG/RES dates may remain unknown: the task is to obtain/review them, not manufacture a one-year expiry.
* `ENTRY_BAN_REVIEW`: actual own settlement root reachedU09 through the exit branch/U08. Do not force the U06 registration branch into that ending. If an official ban end is absent or only reported, retain that uncertainty; `verify_missing_facts` can schedule its investigation. The chosen schedule is not ban expiry. Reported `risk.ban_until` is not automatically official evidence.
* Linked work: retain root process, its exact head/catalogue, active role and the actual linked own application. The inspected resolver uses permit beforeW16, resident atW16–W19, and successor `resident_registration` fromW20 onward; legacy `registration` applies only under its own retained/currently authorized catalogue. W17/W18 status follows the resident application; W21 tax review remains a work/employer-context duty while pinning the actual active child. Do not fall back to root or another same-person sibling when the required child is missing, stale or withdrawn.
* The catalogue also lists `OTHER_AFTERCARE` atR08. It needs a closed successful-own-registration follow-up exception or an explicit exclusion; do not accidentally create a generic terminal-stage bypass. Future V25 feedback/repeat-trip duties likewise need their own successful-completion exception.

Stage membership alone is insufficient: current payment, package, portal attempt/verification, issued delivery/receipt and handoff state must invalidate the relevant pending-review premise even before a stage advances. A current own process history is an integrity source, not proof that every retained prerequisite is still current.

## Actual pure probes and confirmed findings

Own env-free copies were built from frozen D R20's verified Git base plus72 overlays, then only the inspected new pure module was copied. This does not claim the D manifest contains E. Dependency manifest LF SHA256 `012156250f6afe5a3cac0655e2b12849fb9fbd93f7218ae3ca2f4781edfc84c3`.

* `runs/e6-30e-review-pure-r0/app/domain/operator_sop_rules.py` LF SHA256 `4123a16c192e09542421cfb848f5d2f5af14fd7bac2b4365e4c4ade4184d272c`.
* Corrective own R1 module LF SHA256 `16afd8f6c96f5b02ab712d35df6376f67cca1850d2fbb59b7aba94d15833cf48`.

**E-PURE-01 — controlled UTC-range refusal, corrected.** Canonical local `0001-01-01 00:00` was admitted by the date parser but raised uncaught `OverflowError` on conversion to UTC. Original corrected-harness run:18PASS/1 genuineFAIL,1.28s, `runs/e6-30e-review-pure-r0/runs/reviewer-operator-pure-r0-correct-harness.xml`. The parent added a narrow conversion guard yielding `operator_sop_time_out_of_range`. The unchanged test and normal boundaries pass on R1: **19PASS/1.21s**, `runs/e6-30e-review-pure-r1/runs/reviewer-operator-pure-r1.xml`, XML SHA256 `b80dd922a61443c87558e33811fb7566fd56660765fedb5d7d81d495532d5443`.

These controls include date-only versus exact-time distinction, Bishkek00:00 mapping to the previous UTC day,23:59, malformed/unpadded/seconds/full-width times, booleans/containers, invalid/noncanonical dates, unknown reason/proof/reference, closed duty membership and exact confirmed booleans. An earlier run also failed a reviewer test because the live draft prefix changed before capture; that separate stale-test-oracle failure is preserved and is not a runtime defect. Shell setup quoting failures happened before application execution and carry no runtime evidence.

**E-PURE-02 — defensive wall-time hardening; original historical oracle was not stable evidence of a runtime defect.** A standalone timezone inspection initially returned different5h/6h offsets for `2004-03-28 03:30` and `2004-10-31 02:30`. The original pure implementation had no explicit gap/fold guard; two tests expecting refusal failed on R1. However the later exact application environment, including R2, returns fixed6h for both historical dates. That environment legitimately admits those inputs, so the R1/R2 hardcoded historical expectations cannot establish a product failure. The first timezone binary hash was not captured: **no package mutation is proven**. The separate auditor confirmed no timezone writes and an earlier D artifact with the same current package hash. All original artifacts are preserved; no current2026 schedule defect is inferred.

The parent nevertheless added a narrow guard against differing fold offsets or a failed local→UTC→local round trip. This matches the pre-audit's canonical-time requirement. Own R2 `test_reviewer_operator_wall_time_pinned.py` constructs an explicitly synthetic immutable TZif in memory, demonstrates its actual gap/fold, then tests the unchanged production guard. It does not write installed timezone files or claim synthetic data is an approved Kyrgyzstan calendar. Alongside ordinary actual-time/schema/catalogue controls: **22PASS/1.25s**, `runs/e6-30e-review-pure-r2/runs/reviewer-operator-pure-r2-pinned.xml`. Earlier R2 `20PASS/2oracleFAIL` is preserved separately and is not a failed runtime correction.

## Expanded closed catalogue correction

The parent added the six exact V11/V14/V23/V25 duties listed above, plus V13 eligibility and its explicit cross-reference on the four existing document duties. The own R2 copy has38 duties, with a closed terminal-duty set whose intersection with the explicit eligible stages never admits X/WX/RX/UX. The independent test maps V11/V14/V23/V25 and distinct visa/work/exemption source pages; actual stage admission remains future integration, not something this pure catalogue enforces by itself.

Final R3 corrects the three remaining combined primary-section labels: verification24/48 now reference19.1/page78, and V24 OTHER_AFTERCARE references19.1/page79, while work/registration retain their separate correct overrides. The own source-reference test checks those actual results alongside the previously corrected stage references.

Final own env-free component copy: `runs/e6-30e-review-pure-r3/app/domain/operator_sop_rules.py`, LF SHA256 **`62691926f5cb212809d72c3b649c6875cfedf2c67f463716e74ec02ee51e974c`**. The dependency snapshot is the D R20 archive described above; no approval of another E file is implied. Final command: `python -m pytest tests/test_reviewer_operator_schedule.py tests/test_reviewer_operator_wall_time_pinned.py -q --junitxml=runs/reviewer-operator-pure-r3.xml`. Result **22PASS/1.312s, exit0, no skips**. XML SHA256 `f58f28b02b3df85deb0db1951f6ea703f7841ef9cc338967e87b733a5c337abf`. Those two files under the own R3 tests directory are promotable. The original overflow failure, stale-prefix test mistake and unsupported historical-time oracle failures remain in their separate original artifacts.

No confirmed open pure-component defect remains. The student/ban/work/terminal rules above are mandatory design boundaries for the future consumer; declaring names in the pure catalogue does not itself implement those guards. This verdict permits continuation of local integration, not marking that integration complete.

## Integration obligations remain open

Proceed with the scoped policy/evidence design after those pure corrections, but no implementation approval follows from this report. Required E evidence still includes exact current root/linked role and privacy/source/policy validation, independently retained immutable pins, old/current distinction and retry, receipt/pin/task atomicity, time in all task/CAS/source hashes, claimed and manually edited/terminal tasks, actual count/byte clear reserves, migration parity and recovery, native signed context/errors/no-JS/RU/EN and separate final audit. Any added exact time must be inspected in actual `due_tasks` consumers and retain an internal task with no external-send authority.

Final source clauses added after this32-duty draft need exact source references and separate catalogue identity. No J01/J03 point, automatic escalation, source/legal approval or release gate is awarded here.
