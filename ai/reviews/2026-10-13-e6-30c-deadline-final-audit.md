# E630C — separate final audit of the bounded work-deadline helper

Auditor: `calculation_review`. Date 2026-10-13. CRITICAL / solo / reviewed-local target. **Scoped GO on frozen R9:** the read-only, separately delegated, conditional ten-working-day EP filing-date helper. No remaining confirmed defect within this contract. This is separate from my work-process implementation review and from `publication_review`'s deadline implementation review. No whole-E630C verdict or J01/J02/J03/J05 points are awarded.

## Independent basis and exact scope

Before reading the deadline review conclusions, independently read the original source, actual helper/policy, same-session current-stay dependencies, profile/history/interview/publication readers, and calendar arithmetic. Original PDF SHA256 `141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`; §19.9/19.11 and Б.8 examined directly on physical pages 83–84 and 90. Also checked the ten-working-day source row in §13.2 on physical page 61. These are historical requested-source facts, not a finding that current law or real authority is approved.

Own env-free archive: `runs/e6-30c-deadline-audit-r9`, reconstructed from base `d57a0f0a8ea91358edb6e8df654d623fde06264e` and exact R9 overlays. **17/17 overlay LF hashes verified.** Manifest LF SHA256 `a4b15d55cebf541dc7563d39f36327ac079fae99c9589eaba4cfc2fc3b700abb`. Own identity map `audit-deadline-identities.json`, SHA256 `9d7ee14c9c39b39609d1a5f1075a0462a8b499e43ab70dde723b4c1cc8bb2093`.

The approved component is `app/domain/work_deadlines.py`, LF SHA256 `63cad5cf5d8ec36aefd739187fcbd8c8bea73fa9741b41cd28814a3146e6d0ec`, and its supplied test (`9573d686f3eb0733725cf63d4f96f438207876db6f9780fc1b4e2743d1bcd392`). Broader process, model, migration, scenario and recovery overlays are not approved through this deadline verdict. All application imports ran inside the own archive; no root `.env`, real data, production, provider, messages, root runtime edits or PostgreSQL were used. SQLite fixtures retain their foreign-key/network protections.

## Contract assessment

- The original `KG.DL.EP_BEFORE_VISA_FREE_END` row remains `value=null`, `needs_verification`, with its unresolved mapping preserved. A separate typed server authority pins source/bundle/projection/catalog hashes and the exact complete rule hash, explicitly selecting the ten-working-day interpretation, actual-permission-end anchor, calendar, anchor-day convention and deadline-day inclusivity. Default missing authority supplies no date. This is an explicit conditional interpretation; it neither publishes the null row nor supplies a real approval.
- Evaluation first establishes case/person access and uses the existing locked same-session current-stay reader. Exact current profile/history/interview/attestation/source pins, complete competing-regime and counting authority, and current publication availability are required. The extra work scope is ordinary single-citizenship UZB, currently in KG, visa-free, `work_hire`. When an interview exists, its validated current answer must also be known `work_hire`; absent, unknown or contrary purpose is not silently accepted. Without an interview, the separately attested profile/fact contract remains explicit.
- A date is derived from the attested actual permission end, not planned exit, visa validity or the threshold reader's lower-bound count. Calendar hash, completeness and delegated coverage must cover every scanned date, including an excluded anchor. Year absence and provisional data do not fall back to a normal week. The existing bounded arithmetic visits each calendar date and counts exactly ten approved working dates.
- `within_filing_deadline` is only a date comparison under the explicitly selected boundary. A current STOP may remain visible while the conditional date is calculated. Top-level `requires_specialist=True`, `operational_action_allowed=False`, null stay/work permissions, `eligibility_evaluated=False`, `may_quote=False` and `delivery='not_sent'` prevent this component from presenting a readiness or permission decision. In particular a future attested permission end does not erase an observed visa-free overstay/low-headroom stop.
- The helper performs no SQL mutation, timer/task creation, persisted receipt, quote, official submission or message. It adds no incoming/native activation. Retrying this read recomputes current evidence; historical command/replay promises are not invented for a nonpersistent component. All real policy/calendar/source approval remains outside this audit.

## Own exact-R9 execution

Independently authored tests: `runs/e6-30c-deadline-audit-r9/tests/test_auditor_work_deadlines.py`. Existing connected fixture builders supply actual imported source, source review/publication, own profile/history and typed interview APIs; expected outcomes and the calendar trace below were independently specified.

Command in that archive:

`python -X utf8 -m pytest tests/test_auditor_work_deadlines.py -q --basetemp .pytest-audit-deadlines --junitxml=audit-deadlines-r9.xml -p no:cacheprovider`

**3 PASS / 111.539 s, process exit 0, zero failures/errors/skips.** One pre-existing Starlette deprecation warning. Artifact `runs/e6-30c-deadline-audit-r9/audit-deadlines-r9.xml`, SHA256 `3038c3f8571aa33ba712a2c25d9c39bdabbde1218c15a168b11420294895e18d`. No own process remains active.

1. **Original null authority, exact calendar and no writes.** With an explicitly attested Sunday 2026-10-25 anchor, both anchor-counting choices produce 2026-10-08. Expected ten dates are Oct 23/22/21/20/19/16/15/14, the synthetic working Saturday Oct 10, and Oct 8; synthetic nonworking Oct 9/12/13 are skipped. Current filing comparison is late while the attested stay-expiry check is not triggered and STOP12 remains triggered. All non-actionability fields remain explicit. Missing work authority, wrong rule hash, missing current-stay authority and removed publication authority all suppress the date. Original rule hash/value remains unchanged. Actual SQL statement capture observes no INSERT/UPDATE/DELETE/REPLACE/CREATE/ALTER/DROP during these evaluations. Integer booleans and duplicate operators are rejected.
2. **Actual current publication withdrawal.** Positive current date 2026-10-16 → real publication `withdraw` operation → unknown/no date with nested `no_active_publication`. This exercises current state, not a mocked runtime response.
3. **Actual purpose/currentness/privacy.** Real interview start/owner ACK and exact current pin: absent purpose → unknown; recorded tourism purpose → unknown; correcting to work while retaining the old head → unknown; fresh exact work head → positive date; actual consent-withdrawal interruption then owner ACK and fresh pin → collection remains blocked, no date. No runtime or stored rows are forged.

## Implementation-review reconciliation

After the independent source/code assessment, read `ai/reviews/2026-10-13-e6-30c-deadline-review.md` and inspected its test source/artifacts. Its scoped APPROVE is supported. Original WD-01 correctly identifies R4's missing current-interview purpose comparison; R9 adds only that work-specific check and explicit top-level non-actionability. Independently compared R4→R9 helper diff and verified nine called dependency/test files are unchanged, including current-stay, profile/history, interview/publication and date/calendar mechanics.

Independently parsed these reviewer XML files:

| Artifact | Actual result | Interpretation |
| --- | --- | --- |
| `runs/e630c-deadline-review-r4/runs/reviewer-deadlines-r4.xml` | 6 PASS, 1 harness failure / 270.057 s | Passing year crossing, inclusivity equality, missing-year, exact scope/calendar coverage, no-write and authority controls map to unchanged calculation paths. The probe corrected before an initial required ACK; preserve as a harness error. |
| `.../reviewer-purpose-r4.xml` | 1 genuine FAIL / 37.523 s | Actual known tourism interview still yielded a work date; WD-01. |
| `runs/e630c-deadline-review-r9/runs/reviewer-correction-r9.xml` | 1 PASS, 1 harness failure / 85.479 s | Unchanged original purpose reproduction passes. Follow-up used a nonexistent privacy action; preserve separately. |
| `.../reviewer-followup-r9.xml` | 1 PASS / 51.027 s | Correct real privacy interrupt/ACK and purpose/head controls pass. |

Mapped R4 passing controls are not misreported as rerun on R9. Own exact-R9 suite independently exercises the decisive correction, retained privacy, current source withdrawal and conditional non-actionability.

## Gate and limits

**GO only for this bounded reviewed-local helper at the exact R9 identity.** No open confirmed audit finding. PostgreSQL was not run by this auditor: the slot belongs to the separate work-process auditor, and this component adds no writer/schema/lock algorithm; actual current-stay lock behavior is an unchanged dependency, not newly certified here. A consumer that persists a date, creates a timer, exposes an actionable button or sends a reminder needs its own scope, atomic/current evidence checks and acceptance. Native work flow, COPY recovery, full source SOP/golden acceptance and owner/pilot decisions remain separate. This audit changes no fixed criterion scope or score.
