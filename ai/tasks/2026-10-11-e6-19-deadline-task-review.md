# E6-19 — close the bounded E6-06 deadline-task review gap

CRITICAL / solo. Target: independently reviewed local synthetic G03/G04 scope,
not new points, new worker authority, scheduler activation or production release.
Parent overnight deadline03:00 UTC applies, reserve final15minutes. Initial work
is independent review of the existing implementation, not speculative edits.

Requirement: original task `2026-10-10-e6-06-deadline-tasks.md` and handoff
`../handoffs/2026-10-10-0545-e6-06-deadline-tasks.md`. Read actual task binding,
source/deadline hooks, CalendarTask lifecycle, native actions and migration.
Scope includes internal owner assignment, complete/cancel/escalate, idempotent
latest-source reconciliation, bounded batch recovery, external manual/claimed
task conflict, scope/authority gates and additive migration. No client sends,
new worker identity, legal date approval or real-data use.

Review actual source before builder conclusions. Reproduce material defects
against a fixed environment-free source snapshot before changing code. Any
correction requires a risk assessment, meaningful negative/ordinary tests,
independent re-review and separate final audit. Never count an unavailable
review as PASS or promote this slice to all-project J03 approval.

Use synthetic FK SQLite, native Chromium and guarded isolated PostgreSQL where
applicable. Verify source identities, named scenario outcomes, rollback/retry,
concurrency and relevant populated migration protections. Existing production
configuration and unrelated files stay outside scope. Initial status: source
review preparation; exact merged execution snapshot follows E6-18 checks.

Reviewed r1 is `runs/overnight-final-r1`, merged runtime now committed d1c9a38.
Independent reviewer and auditor reproduced five problems before any patch:
stale restore consent omits current desired source/owner; audit identity uses
Python bool/int equality; generic calendar action can resurrect an atomically
cancelled task (actual PostgreSQL race); cleared task pointer permits a duplicate;
ordinary action capacity prevents completion/cancellation (also default250).
Original failures remain in their separate ignored r1 copies/reports.

Independent source pre-assessment approves narrow corrective work: source-aware
tokens checked under existing locks without disturbing historical retries;
canonical consumed audit/receipt identities; missing pointer/date invariant;
one bounded terminal receipt beyond ordinary capacity; fresh locked calendar
task fetch, then current authorization/terminal checks for installed writers.
Claimed bound tasks retain the existing refusal boundary. No new authority,
source/date policy, scheduler, recipient, migration or historical repair.
Test original negative cases, current-owner and claim races, exact retry at
capacity, no-task waiting placeholders, normal calendar behavior and actualPG.
