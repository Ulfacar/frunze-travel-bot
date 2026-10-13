# E6-29B current-stay checks — independent implementation review

Reviewer `/root/calculation_review`, 2026-10-12. CRITICAL / solo.
Requirement: `ai/tasks/2026-10-12-e6-29b-current-stay-stops.md` and the parent
E6-29 pre-audit's current-stop addendum. Reviewed scope is a local read-only
component, not complete H02, source approval or release.

Final independent verdict: **APPROVE exact R6 for the reviewed local E6-29B component**.
The original history/interview/source corrections passed eight own controls.
The builder then raised a shared-validator narrowing concern; this reviewer
confirmed an actual normal-flow bypass on a separately imported synthetic
source variant. The retained current source has disjoint relevant country
sets, so this is not a claim of a false positive on that unchanged source.
The builder's narrow R6 correction passed the same paired repro and an
original-source positive control. The final builder authority and two legacy
compatibility controls also pass. No open reviewer runtime finding remains.
Separate final audit remains an independent completion gate. This verdict is
not full H02 approval, source approval, permission to remain or release approval.

## Source-first inspection and identity

Read task/addendum and actual `current_stay_policy.py`, `current_stay_stops.py`,
`current_stay_checks.py`, mechanical regime-guard extraction, relevant actual
interview catalog/reducer, personal-history current read, publication time/lock
checks and WorkCalendars before builder conclusions. No runtime source edits.

Env-free own archives R1/R2/R3 use base
`3efc7cc2cdb6f947c3588980ca02dc4a1a74536b`; every frozen overlay LF hash was
verified. Own R1 was created/inspected but not executed: builder's first fixture
used a string for a list-valued WINDOW_ANCHOR parameter. R2 corrected that
synthetic-source shape and exact source interpretation. No real source changed.

Own R2 archive: `runs/e6-29b-review-r2`.
Own R3 archive: `runs/e6-29b-review-r3`, 13 verified overlays; frozen R3 manifest
LF SHA256 `f30afa37752af916dce6225422fef79a8805d7951d5de160b63b39d648abe306`.
R3 to R4 is independently verified test-only; runtime/migration identical.
R4 manifest LF SHA256:
`aad2fbfe41ca8a76f7c2dedd361d98f0f35a8950bc30c99b6133a9a680738ce6`.

The source-availability correction candidate is `runs/e6-29b-r5`; own delta archive is
`runs/e6-29b-review-r5`. R5 manifest LF SHA256:
`c622a668044eaf112245e181944ef27f91a2ae1e286e3e32177cc7366a778f2c`.
All 13 frozen overlay and root LF hashes match that manifest. This includes
three preserved unrelated UI files, the parent pre-audit and an unchanged
0036 migration; their presence does not extend this review's approval scope.
Eight scoped implementation/test files are the four runtime files named below,
the three current-stay test files and the optional fixture changes in
`test_connected_qualification.py`.

R3 to R5 changes only `current_stay_stops.py` and its test file. The runtime
delta moves abroad applicability after current source checks and requires
STOP12 availability before visa non-applicability. The six own R3 controls all
run in-KG against available STOP12 and unchanged paths; two own R5 controls
exercise the actual delta. This mapping is explicit, not a claim that the
whole original R2 suite ran unchanged on the final runtime.

Final guard-hardening candidate is `runs/e6-29b-r6`, with own archive
`runs/e6-29b-review-r6`. R6 manifest LF SHA256:
`530d95106027a21ac391f9435740194ac10585bbf825c028c4f6f5329491fffa`.
All 13 frozen overlay and root LF hashes match. Relative to R5, the only
runtime change is six lines in `assessment_rules.validate_regimes`, rejecting
unsupported narrowing predicates in non-catalog literal manual country
guards. The other changed overlays are the pre-audit and bounded test cases.
Current-stay clock, locks, history, interview, calendar and arithmetic paths
are unchanged. No new PG repetition is needed for this validation-only delta.

All own runtime probes use actual domain APIs and synthetic SQLite, one suite
at a time. No private environment, real records, external calls, live source
approval, production or PG was used by this reviewer.

## Confirmed findings and corrections

1. **Visa branch bypassed personal history and passport conflicts (R2).**
   An ordinary current visa fixture first returns three not-triggered checks.
   Changing the current open history basis to visa_free, changing the fact's
   passport token, or withdrawing the latest history then still returns three
   not-triggered checks and `requires_specialist=False`. The branch returns
   before reading current history. These are three separate normal-flow probes
   with asserted positive baselines, not corrupted artificial rows.

   R3 reads and validates current history before either visa or abroad early
   return. Every attestation includes an exact nullable latest-history pin;
   append/withdraw/correction changes invalidate the old fact. Existing current
   open history must agree on basis, entry date, country and passport. Initial
   missing history plus an explicit null pin may support an independently
   attested visa permission-end fact; it is never complete-empty VF history.
   Withdrawn/stale history conservatively yields unknown.

2. **Known typed interview history was ignored (R2).**
   A normal saved interview pinned to the current profile, acknowledged and
   corrected by its owner, reports a past RUS visit on 2026-01-01–10 absent
   from the personal journal. The fact pins the actual latest interview head.
   The checker nevertheless returns visa-free headroom4/not-triggered.

   R3 explicitly refuses supplied D1/D2 rows/counts/reported totals pending
   approved reconciliation, rather than silently ignoring them. An asserted
   no-previous-visits answer requires known current history without closed
   visits. It still does not require a completed interview to detect urgency.

Root also removed comparison of historical `violations.overstay` with today's
permission-end result. The actual catalog asks whether there **have been**
overstays; that field is not a claim that current permission has expired.
Removal is semantically appropriate, not a lost current-expiry safeguard.

3. **Abroad applicability bypassed current source availability (R3/R4).**
   This reviewer flagged the early return statically for a paired audit probe.
   The separate auditor independently confirmed it through normal actual-PG
   publication withdrawal: abroad continued to return not-triggered after the
   publication became unavailable. The runtime proof belongs to that auditor.

   R5 moves the abroad return after current source, version, authority pins
   and publication checks. Each unavailable STOP yields unknown. Visa STOP12
   non-applicability now also depends on that STOP's current availability.
   Own paired R5 controls prove a wrong source pin cannot bypass these checks
   abroad, and rejection of STOP12 does not erase a known expired-stay trigger.

4. **A literal manual regime could be hidden with an extra narrowing guard.**
   The builder raised this during final self-review of the extracted shared
   validator. Source inspection confirms the retained draft's non-catalog
   literal VR lists are disjoint from the executable VF lists, and catalog
   special-regime guards are exact. The original retained bundle therefore
   does not demonstrate this bypass by itself.

   This reviewer created a separate synthetic source variant adding RUS to
   `KG.VR.SIMPLIFIED_ALL`, retaining its literal country list and using normal
   import/review/publication APIs. The initial full regime assessment correctly
   sees that manual regime as met and requires a specialist. Adding an unrelated
   `permanent_residence_in USA` predicate to the manual guard, then constructing
   the new server policy and refreshing its factual pin, is accepted by R5 and
   returns VF not-triggered. Thus a structured source country conflict can be
   erased by policy interpretation despite complete ID/hash coverage. This is
   not an unauthenticated-client exploit or a claim of any real approval.

   Required bounded correction: non-catalog manual units with a literal country
   list admit the exact country guard alone or with the supported ordinary
   document guard. Reject other narrowing predicates; preserve catalog equality
   and the separately approved GENERAL partition. R6 implements that exact
   bounded rule; the original repro is kept and rerun unchanged. A separate
   positive control tests country-only manual guards on the original full
   source-shaped fixture and must retain observed headroom4.

## Independent runtime evidence

Command in each own archive:
`python -X utf8 -m pytest tests/test_review_current_stay.py -q --basetemp <own-temp> --junitxml=<artifact> -p no:cacheprovider`.

| Snapshot/artifact | Actual result | Scope |
|---|---|---|
| R2 `review-first.xml`, `.pytest-review-first` | 4 FAIL, 92.82 s | Three visa/history bypasses and ignored typed interview history; each first establishes a valid positive baseline |
| R3 `review-corrected.xml`, `.pytest-review-corrected` | 6 PASS, 140.958 s | Original four repros, refreshed history pin still cannot hide a basis conflict, known expired actual permission retained while VF authority unknown, independent approved synthetic source with both entry/exit counting disabled |
| R5 `review-delta.xml`, `.pytest-review-delta` | 2 PASS, 47.796 s | Valid abroad baseline then wrong source hash yields all unknown; actual visa with expired permission and rejected STOP12 retains expiry trigger while VF becomes unknown |
| R5 `review-manual.xml`, `.pytest-review-manual` | 1 FAIL, 21.91 s | Separate normal-import synthetic overlapping VR/VF source; additional manual residence guard incorrectly changes specialist uncertainty to not-triggered |
| R6 `review-manual.xml`, `.pytest-review-manual` | 2 PASS, 47.02 s | Same overlapping-source repro now refuses narrowing; original full source-shaped positive retains headroom4 with exact country-only manual guards |

Failed R2 evidence remains preserved. The R3 tests do not alter runtime or old
arithmetic. The additional counting test creates a separate synthetic source
variant before normal import/review/publication, explicitly approves its exact
source/counting hashes and compares observed headroom with projected scenario
headroom. This is not a mutation of the retained supplied draft or an approval
of actual counting rules.

R5 delta command uses `tests/test_review_current_stay_delta.py`; all other
flags match the command above. The R5/R6 manual-guard suites use
`tests/test_review_manual_guard.py` with the same flags. XML counts were
independently parsed, including the preserved failures. Final own corrective
evidence is **10 PASS** over explicitly mapped R3, R5 and R6 paths; original
four R2 failures and one R5 manual-guard failure remain preserved.
Both-counting-false evidence checks
observed usage86/headroom4 versus hypothetical scenario headroom5, with
`days_until_exit=None` and unchanged review-only arithmetic.

## Builder and separate-auditor evidence mapping

Builder XMLs read and parsed independently; test source inspected:

| Artifact | Actual result | What it establishes and limit |
|---|---|---|
| `runs/e6-29b-r2/runs/e629b-r2.xml` | 38 PASS, 501.947 s | Original pure/calendar and domain boundaries before the review corrections; this alone is not final-runtime approval |
| `runs/e6-29b-r3/runs/e629b-r3-pg.xml` | 5 PASS, 127.245 s | Actual isolated PostgreSQL reader-held profile/history/publication locks, writer-first profile correction, and clock sampled after a real case-lock wait |
| `runs/e6-29b-r4/runs/e629b-r4-focused-compat.xml` | 43 PASS, 635.047 s | 8 pure calendar controls, 33 corrected current-stay controls and 2 old connected-assessment positive/authority regressions |
| `runs/e6-29b-r5/runs/e629b-r5-source-delta.xml` | 2 PASS, 46.080 s | Final-runtime abroad fact/applicability and independently attested visa with initially missing history |
| `runs/e6-29b-r6/runs/e629b-r6-guard-compat.xml` | 3 PASS, 96.637 s | New manual-narrowing authority negative plus old connected-assessment positive/no-writes and authority-boundary compatibility |
| `runs/e6-29b-audit-r5/runs/e629b-audit-r5.xml` | 3 PASS, 102.870 s | Separate auditor's actual PG: paired abroad source withdrawal, authority/current-source/full-regime and relevant-unknown controls, actual history/profile/source corruption with recovery and no writes |
| `runs/e6-29b-audit-r6/runs/e629b-audit-r6.xml` | 1 PASS, 37.814 s | Separate auditor's actual PG overlap control: allowed country-only/ordinary guards retain conflict; additional residence and nonordinary narrowing is refused |

The PG test source checks `pg_stat_activity.wait_event_type='Lock'`, not merely
thread delays. The after-read mutations invalidate the next result; a profile
writer committed first is visible to the waiting reader. Crossing local
midnight while blocked produces the next date and requires current profile
confirmation. R5 does not change this locking/time path. This reviewer did not
independently run PG; separate audit provides additional actual-PG controls.
The auditor's final XML was independently parsed (raw SHA256
`e02190bb1f0e5eb451da66aada3a6e771d4f12ae9f08ec3417d5bb5afd97c8f9`).
His original R4 artifact remains 1 PASS/2 FAIL: the genuine abroad-source
failure plus a separately explained oracle error that expected an irrelevant
foreign-visa inventory unknown to block a definitively false country guard.
The corrected R5 audit retains that case as a positive control and tests a
relevant unknown instead. It is not represented as two runtime defects.
R4 focused/compatibility XML raw SHA256 is
`f15b99b18b9584aad306472f6f9dd8ca2f0e45ba13e8424ccab8f821a9affb00`.
R6 guard/compatibility XML raw SHA256 is
`63d582886260b8d5e986b2e603d131d38eae9940259ffd2a0379002bc6ed3d49`.
Both were independently parsed, with zero failures, errors or skipped tests.
The auditor's R6 XML was also parsed, raw SHA256
`5dc28ef955b5eb07ec00e17d5667bc92e5e28a2f527e8906bf1c77c22a9cab79`.

## Acceptance assessment and remaining scope

- Actual permission-end semantics are explicit server attestation provenance,
  not visa validity, planned departure, registration expiry or a government
  calculation. Unknown/mismatched authority cannot supply a deadline.
- Calendar checks bind full calendar content and explicit endpoints/strict
  threshold, retain draft status, scan at most366 days and can prove a lower
  bound of five without inventing an exact later total.
- VF checks require the full approved source-shaped applicability set,
  separately approved counting matching exact source values, current complete
  same-passport personal history and one current open interval. Observed usage
  comes from `reported_history_days`; no hypothetical exit day is subtracted.
- Results have fixed `current_stay_stops_only` scope, per-check state,
  `permission_to_remain=None`, no eligibility, quote or delivery. Other legal/
  dialogue stops must still be evaluated by a future consumer.
- Same-session case/applicant/publication lock order and post-lock clock were
  inspected and mapped to the actual five-case PG artifact above.
- The shared `assessment_rules.validate_regimes` extraction preserves the
  previous authority checks and their ordering: complete source regime/route
  sets and hashes remain required before per-regime guard semantics; counting
  checks remain in the old assessment validator. The two R4 old-assessment
  regressions pass; R6 adds the narrow manual-guard constraint described above,
  with its own independent paired correction and repeated compatibility evidence.
- No endpoint, native UI, incoming-message orchestration, normal typed-answer
  dispatch or delivery is added. UI/browser testing is N/A for this helper;
  the preserved unrelated UI overlay does not change that assessment.
- No real authority, calendar approval, policy, source approval or factual
  attestation is installed. Server attestation provenance is not a signature
  or independent government verification. Production activation is not reviewed.
- Full E6-29/H02 remains UNKNOWN: these three current-stay checks must later be
  connected to the remaining dialogue/stop handling and prove the complete
  incoming flow. This component receives no standalone fixed-criterion points.
