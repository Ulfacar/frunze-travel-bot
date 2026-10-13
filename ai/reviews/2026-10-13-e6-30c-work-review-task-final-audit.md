# E630C conditional work-review reminder: separate final audit

Auditor: `/root/e622_audit`; 2026-10-13. CRITICAL / solo, reviewed-local target.
**Final verdict: GO / DONE for the reviewed-local conditional reminder adapter,
exact R44 / 26-file staged scope.** All confirmed scoped findings have corrective
evidence. Own actual PostgreSQL temporal/concurrency, real count/byte limits and
exact reserved cancellation checks pass; independent domain/native reviews and
exact-final fresh recovery pass. No open scoped defect or required evidence gap
remains. Whole-C acceptance, J points, source/calendar/pilot approval and release
authorization are outside this verdict.

## Source-first requirement and scope

Read C task and `2026-10-13-e6-30c-deadline-task-pre-audit.md`, original-source
distinctions, actual domain/native/policy/schema code before independent review
conclusions. The already inspected original PDF SHA256 is
`141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`.
Section 19.11 / the UZ source scenario names ten working days before an actual
visa-free permission end. The original deadline unit remains null. Separate
delegation supplies its interpretation and explicit calendar; it does not turn
the conditional result into an official filing date or permission to work/stay.

This component binds that conditional calculation to an explicitly confirmed
internal review reminder for the same person's unified-permit application.
The helper retains `requires_specialist=True`, `operational_action_allowed=False`
and unknown work/stay permissions. Existing generic CalendarTask lifecycle is
reused with a distinct immutable receipt and separate default-empty authority.
The UI must expose current stops, stale/unknown evidence and operator-driven
reconciliation. Reading alone does not promise automatic revocation/cancellation.

Reviewed runtime scope: migration0041; `EntryWorkReviewEvent` and immutable
guards; `work_review_policy`, `work_review_evidence`, `work_review_tasks`;
same-session `work_deadlines` extraction; default-empty config;
`kg_work_review`, its template/application link, and the existing generic
calendar guard's new binding lookup. Unrelated aftercare, base-shell UI,
source-product/golden work and older router behavior remain outside this scope.

## Isolation and snapshots

Own archives are Git archive plus hash-verified frozen overlays; no root app
imports or `.env`, no production, private real data or external provider.
Original R35 base `7b0475b536592f6d254d607fb4baf3619a6e7fff`, 34 overlays,
manifest LF SHA256
`5759454022885c82200f1812198f53c1fd71cecfee80532d877d5dbaa042ea3b`.
R36 base is recorded by its manifest, 32 overlays, manifest LF SHA256
`6b49633c112f9592b25cea01fd48827f5ed308c11236480c636a1aa13262cc2e`.
Own archives: `runs/e6-30c-work-task-audit-r35` and `...-r36`; identity artifacts
`runs/audit-identity.json` and R36 `runs/scoped-hashes.json`.

Own final runtime candidate under audit is R40, base
`0398bfdd372ecc9e946787913f5b849535075034`, 32 overlays, manifest LF SHA256
`3d37dff31339b61b9dc08449e7eec371ac3788824cdc57ed759b1aefdced0b39`.
Own R40 archive and all overlays are independently verified. R36-to-R40 actual
task-service diff adds only per-row immutable calendar binding validation;
the other runtime change is the scoped R38 link contrast correction.

Final staged candidate is now **R44**, with exactly the same 11 runtime/schema
files as R40. Independently verified the exact 26-file Git index set against
the R44 manifest and `runs/e630c-work-review-staged.json`: 11 runtime/schema,
five builder tests and ten promoted independent test/browser files. Every
LF hash matches and `git diff --cached --check` passes. R44 manifest LF SHA256
`122637da5368c31ba2f0376626a5df866347fb9f0c80e616914ae8e7377df40c`;
scope manifest LF SHA256
`96199cee9bcdfdd0e28574625e2fbd9127e334a8f44f33d0bf2b56deb8b9ab50`.
Own identity artifacts: R40 `runs/audit-final-mapping.json` (11 runtime files,
R32/R36/R38/R40/R44 differences and XML hashes) and
`runs/audit-staged-identity.json` (all 26 exact staged files). Later unstaged
actual-anchor/model/config work and unrelated shell UI are explicitly excluded.

Actual PG uses the explicitly validated private loopback connection file and
fresh isolated migrated scratch databases, with safe teardown. Credentials are
not printed or copied into reports. The single PG slot was explicitly reserved
for this audit. No root runtime/config/source changes were made.

## Source assessment

- Separate policy validates typed work/current/fact/qualification/publication
  grants and exact digest relationships, owns a copied calendar and limits
  operators. Server configuration is empty by default; POST does not supply
  authority. The existing public helper still rejects malformed scope/actor
  before storage and delegates to the same-session implementation.
- The receipt binds actor/request/revision, same case/person/EP application,
  immutable previous id/hash, full calculation/source/calendar evidence,
  separately validated historical authority and the mutable calendar projection.
  Historical checks use retained heads and source manifest decisions, not
  today's active grant. Later equal-time independent revisions preserve the
  pinned historical serial observation while fresh evaluation sees new state.
- New enable/reconcile uses case, application, person and current publication
  locks in one transaction. Existing task lock precedes current computation;
  generic calendar mutation only takes that task lock, without an inverse case
  acquisition. Real races are tested separately; inspection alone is not proof.
- Exact original retry is resolved before mutable projection/current authority
  recomputation. Different command/actor under the retained key conflicts.
  Semantic identity survives an unknown refresh; restoring unchanged authority
  cannot reopen a completed/cancelled generation.
- Every retained receipt is validated against its own immutable
  `work_review_bound` event before an original retry can return. The bounded
  event set must match receipt count, actor, task, receipt id/hash and same
  application/person; detail is limited to 1024 bytes. The current calendar
  projection additionally checks its exact latest binding and own scope.
  Date conflicts require explicit eligible restore. Claimed work is refused by
  the new writer and both generic native writers' shared binding guard.
- Read limits precede JSON loading. Normal history is capped at 64 rows and
  4 MiB with 8192 bytes reserved; one terminal cancellation may use row65.
  Cancellation inherits verified operators/semantic identity and avoids another
  full personal evidence copy. Actual count/byte executions are recorded below.
- Migration is additive, with own-subject and previous-scope composite FKs,
  per-application revision and per-case request uniqueness. Offline downgrade
  refuses; live downgrade takes a barrier and refuses populated history.
- Task text describes conditional internal review and contains case/person
  identifiers rather than raw passport/history/proof contents. Created tasks
  have no channel user and no exact send time. The adapter has no sending call;
  existing manager calendar/brief behavior remains governed by its own flags,
  so this is not a promise that no downstream internal notification is possible.

## WRA-01: confirmed future application head commits unreadable receipt

R35 original actual-PG test:
`tests/test_audit_work_review_pg.py::test_future_application_event_cannot_create_unreadable_receipt`
in the own R35 archive. Actual normal application submission is recorded at
16:00; the helper's current observation is 15:00 and the reminder receipt is
sampled at 15:00:01 on the same day. No storage tampering occurs. R35 commits
the task/receipt, but immediate read fails
`work_review_evidence_integrity_failed`: retained verification rejects the
application event after `current_stay.checked_at`.

Original command:

```text
python -X utf8 -m pytest tests/test_audit_work_review_pg.py -q --tb=short --junitxml=runs/audit-future-application-r35.xml
```

Result: **1 genuine FAIL / 43.92 s**, exit1, one dependency warning. Preserved
test/XML stay in R35. This is an ordinary temporal data-integrity defect,
not a fixture failure or a claimed unauthenticated write.

R36 `_current` now checks application identity and latest event creation time
against the actual observation, refusing fresh eligibility when either is in
the future. Retained cancellation remains available. The corrective probe
accepts the guard's actual fail-closed `PermissionDenied` as well as storage
invalid/conflict, asserts no task/receipt, then moves the observation to the
exact event timestamp and confirms a readable positive and identical retry.
No source/business condition was relaxed. This is PASS in the final seven-case
own R36 suite below. The original failing R35 oracle/XML remain untouched.

## Own PostgreSQL concurrency and temporal evidence

Command in the env-free R36 archive:

```text
python -X utf8 -m pytest tests/test_audit_work_review_pg.py -q --tb=short --junitxml=runs/audit-work-review-r36.xml
```

**7 PASS / 333.87 s**, exit0, one dependency warning; own execution. Cases:

1. WRA-01 future application refusal without task/receipt, exact-time positive
   recovery, readable result and original retry.
2. Actual profile writer holds scope lock; stale task enable is observed waiting
   in `pg_stat_activity`, then conflicts after profile commit, without writing.
3. Same actual wait/commit/refusal for current stay-history withdrawal.
4. Same actual wait/commit/refusal for current source-publication withdrawal.
5. Generic task claim wins first: cancellation waits, then refuses the claimed
   task; the generic native mutation guard refuses it too. Release permits a
   fresh cancellation.
6. Cancellation wins first: competing generic claim waits and returns false;
   original cancellation retry is identical.
7. Receipt clock moves behind the current observation after task mutation:
   transaction rejects and rolls back task/receipt; restored clock allows the
   same request and exact retry.

No races are inferred merely from concurrent futures: the tests observe scoped
database `Lock` waits before releasing the winning transaction. R36-to-R40
mapping retains these lock, current-source, temporal and transaction paths;
R40 capacity checks independently execute the new per-row history gate.

## Own production-limit capacity evidence

The original R40 64-full-authority-copy loop was intentionally interrupted
before a completed oracle; 27 actual receipts had been observed. This attempt
is **UNKNOWN**, not PASS and not a demonstrated runtime failure. Its original
harness and interruption note remain under own R40 `runs/`. Repeated identical
full evidence caused growing history-validation cost. No runtime was changed.

The replacement count scenario uses the same public writer and exact production
limits: one authorized create, 62 legitimate no-authority reconciliations,
an explicitly new delegated-policy generation at row64, then reserved row65
cancellation. It covers two task generations and every retained binding.
The separate 4-MiB scenario retains large valid calendar authority documents,
fills the real byte budget, then verifies compact cancellation and original
retry. Constants, validators, writer, storage and migration are unmodified.

Command in own env-free R40 archive:

```text
python -X utf8 -m pytest tests/test_audit_work_review_capacity.py -q --tb=short --junitxml=runs/audit-capacity-r40.xml
```

**2 PASS / 737.08 s**, exit0, one dependency warning; own actual PostgreSQL.
Exact production constants: 64 ordinary rows, 1,048,576 bytes per event,
4,194,304 total bytes, 8,192 reserved cancellation bytes. Count result:
64 ordinary receipts / 141,339 bytes, two task generations, followed by actual
revision65 cancellation / 1,179 bytes; full history and both exact retries pass.
Byte result: seven ordinary receipts / 3,907,096 bytes; next 558,165-byte receipt
is refused and transaction rolls back; cancellation / 1,175 bytes, history and
both exact retries pass. Artifacts `runs/audit-capacity-count.json` and
`runs/audit-capacity-bytes.json` retain exact dimensions.

The seven-event case proves the actual next-event budget refusal, but leaves a
279,016-byte ordinary tail. A separate stronger public-writer-only control fills
that tail exactly with valid unused-year calendar text and consumes the reserved
region. It does not lower constants or mutate persisted receipts.

```text
python -X utf8 -m pytest tests/test_audit_work_review_exact_bytes.py -q --tb=short --junitxml=runs/audit-exact-byte-reserve-r40.xml
```

**1 PASS / 231.05 s**, exit0, one dependency warning; own actual PostgreSQL.
Eight ordinary records total **4,186,112 bytes**, exactly 4 MiB minus 8 KiB.
The last ordinary event is 279,016 bytes; another normal append is refused.
Actual cancellation consumes **1,175 reserved bytes**, total **4,187,287**,
below 4,194,304. Full history, oldest original retry and cancellation retry
remain readable/equal. Artifact `runs/audit-exact-byte-reserve.json` records
exact dimensions. Thus the reserve is actually consumed, rather than inferred
from a failed large append with unused ordinary space.

## Independent review and remaining gates

After own source assessment, read the domain review
`2026-10-13-e6-30c-work-review-task-review.md` and native review
`2026-10-13-e6-30c-work-review-ui-review.md`. Their original failures remain
evidence, not discarded history. Domain findings include semantic loss on
unknown refresh, wrong same-case projection capture, false historical source
metadata, forged retained operators, wrapper validation regression, nested
calendar/type gaps, equal-time source recovery, and exact-time terminal
projection recovery. A final ninth finding showed that a fully rehashed old
task pointer bypassed the current-only binding check on an exact retry. Its R36
original FAIL / 38.03 s is retained; R40 validates each original receipt's own
immutable calendar audit before duplicate return.

Domain reviewer final **scoped APPROVE R40**, report LF SHA256
`e0a1a1d24890d8580b99ddcf7bfefa3847ce6e70b346894c142e3e2720abcdd7`.
Final own reviewer correction suite: **4 PASS / 210.96 s**,
`runs/e630c-review-adapter-r40/runs/reviewer-corrective-r40.xml`; reviewer
evidence, not auditor execution. Earlier R34 five corrective cases also pass.

Native findings include hidden triggered/past-date stops, a restore action that
cancelled under missing authority, and R35 light-theme link contrast below4.5.
All three are closed by the separate native reviewer. Final **scoped APPROVE
R38**, report LF SHA256
`bf5b0e9884dd6628e22a65311c326fa838f60aa5ff8145dce2fe8e7896d5f200`.
Final same-oracle themed browser: **1 PASS / 73.973 s**, XML
`runs/e6-30c-work-ui-review-r38/review-work-ui-browser-r38.xml`.
The auditor independently viewed mobile RU dark, desktop EN light, withdrawn
authority, unavailable reader and the one-page print image. Visible button and
link text is readable, current triggered/past-date stops and conditional scope
are clear, mobile fits, errors remove unsafe forms, and printed history fits.
The reviewer executed computed contrast >=4.5, focus, no-JS signed POST,
overflow and print checks. No whole-shell redesign approval is inferred.

Independently inspected builder R32 actual-PG XML: **5 PASS / 258.764 s** for
same/different request races with actual lock waits, bound-audit rollback,
schema parity/empty cycle/populated refusal, and fresh binary COPY recovery.
The recovery source verifies table hashes/counts, live FKs, restored sequences,
equal view/original retry and a new cancellation after restore. This is builder
evidence, not own execution. Inspected R32-to-final mapping identifies later
temporal, terminal and source-prefix corrections; the original R32 run is not
called exact-final coverage.
The original recovery includes all 63 public data tables at migration0041.
Exact-final R44 recovery has now completed, independently parsed XML
`runs/e6-30c-r44/runs/work-review-recovery-final-r44.xml`: **1 PASS / 61.062 s**,
exit0 confirmed by builder. The current per-row immutable binding validator
passes after fresh-schema binary COPY with all 63 public data tables, live FKs
and restored sequences. Saved history and original no-current-authority retry
are equal; a new cancellation succeeds at revision2. Final report
`runs/e6-30c-r44/runs/work-review-recovery.json`, dump SHA256
`af6a5bc4f718f2fa0b540fe3f6c94d0757a3c0b834e8329512ecb55f0abacb41`.
This is independently inspected builder execution, not an auditor-run restore.

Independently parsed builder R44 consolidated XML
`runs/e6-30c-r44/runs/work-review-promoted-r44.xml`: **23 PASS / 843.638 s**,
no errors, failures or skips. This contains two core flows, promoted domain and
native original/corrective scenarios, and two schema controls. It exercises the
R40 history gate through original retries and direct historical-evidence
negatives. This overlaps reviewer evidence and is not summed as 23 new distinct
scenarios. The standalone final browser remains the independently reviewed R38
execution mapped to byte-identical R44 native files.

## Final gate and exact scope

After the exact-tail test completed, independently re-ran the exact 26-file
index/R44 manifest comparison and cached whitespace check: **PASS**. The
runtime tested in own R40 is byte-identical to those 11 staged runtime/schema
files. Current working-tree model/config or other actual-anchor additions are
not substituted for the reviewed index. Source/schema hashes and all test/report
provenance are retained in own R40 `runs/audit-final-evidence.json` and
`runs/audit-staged-identity.json`; the collector parses actual JUnit totals and
asserts the exact count and byte limits before writing its result.

Own final actual-PG executions are seven R36 cases, two R40 count/coarse-byte
cases and one exact-byte-reserve case. Their scopes overlap intentionally;
they are not described as one invented ten-case final suite. The genuine R35
failure and interrupted first capacity attempt remain separately visible.
Builder and reviewer executions are explicitly attributed above. All auditor
processes have ended and the exclusive PG slot is released.

**GO for the reviewed local 26-file adapter change.** The component supports
explicitly delegated conditional internal review reminders, safe current
reconciliation, bounded historical replay and recovery. It does not establish
official filing dates, work/stay permission, actual source/calendar/operator
approval, unattended revocation, other source anchors, all SOPs, J01/J02 or
whole-PDF/CRM completion. No deployment, activation, live data mutation or
external messaging was performed or authorized by this audit.
