# E6-19 — deadline-task review and lifecycle corrections

DONE for the reviewed local G03/G04 scope, CRITICAL / solo. Code `dc474d8`
saved/pushed only to `origin fix/tours-search-quality`. No deployment, migration
rollout, scheduler activation, new worker identity or real data/date policy.

Independent source-first review and separate audit of the original E6-06 scope
found five defects. Corrected r2 binds explicit restore consent to the current
source/owner; distinguishes JSON types in consumed binding/action evidence;
refreshes and locks the task before existing calendar/card authority checks;
refuses inconsistent missing task links instead of creating duplicates; and
reserves one terminal receipt after ordinary action capacity. Both installed
calendar writers refuse claimed bound tasks. Legitimate waiting placeholders,
ordinary unbound calendar actions and old exact action retries remain valid.

Frozen `runs/e6-19-review-r2`, base d1c9a38 plus five manifest files. Manifest
`ai/reviews/2026-10-11-e6-19-snapshot-r2.json` raw CRLF SHA256
`5efce2f48f4da2aacf3d9981b90682cd7cb3680cc8e45c56a8091db0307d467e`;
LF manifest SHA256 `2f7a3b267c3b0fcbef0475b360803d07e7e596c108008cd5e51726a7d38026d7`.
Source file hashes use LF normalization. All five root/archive/commit hashes
match. All committed files outside ai/ and docs/ also match the frozen full-suite
execution tree; runtime evidence records the exact counts and method separately
from the independent frozen-copy identities.

Builder commands in exact r2 (first enables only the guarded local PG fixture):

```text
python -m pytest tests/test_entry_deadline_task_integrity.py tests/test_entry_deadline_task_integrity_postgres.py tests/test_entry_deadline_tasks.py tests/test_admin_kg_deadline_tasks.py tests/test_entry_deadline_tasks_migration.py -q --tb=short --basetemp=runs/deadline-r2-tmp --junitxml=runs/deadline-r2.xml
70 PASS /1 existing warning /216.07s, including21 actual PostgreSQL checks.

python -m pytest tests/test_calendar_tasks.py tests/test_calendar_admin.py tests/test_calendar_brief.py tests/browser_kg_deadline_tasks.py -q --tb=short --basetemp=runs/calendar-browser-r2-tmp --junitxml=runs/calendar-browser-r2.xml
46 PASS /3 existing warnings /66.82s.
```

No skips/failures/errors in these116 builder checks. Mobile390, desktop1365 with
JavaScript disabled, and the sole printed page were visually inspected. AST,
credential-pattern scan, three cold imports, whitespace and protocol checks PASS.
Exact XML hashes/counters: `ai/reviews/2026-10-11-e6-19-runtime-evidence.json`.

Independent review `ai/reviews/2026-10-11-e6-19-independent-review.md` APPROVE:
65 named core cases covered after correcting a reviewer-only `.acquired` typo
to the actual `.claimed` field; original63 PASS/2 probe failures remain recorded,
affected four cases then PASS. Separate21 actualPG and2 browser PASS. Original
negative probes remain byte-identical. Actual old-module receipts read/retry
after source growth and JSON key reorder. Both installed writers wait on real
PG row locks and recheck changed owner/claim after commit.

Separate audit `ai/reviews/2026-10-11-e6-19-final-audit.md` GO:39 own passing
acceptance checks. The original default250 action limit, active NULL binding,
waiting placeholders and terminal retry/overflow controls pass. Actual migration
constraints/populated downgrade refusal and Binary COPY restoration of all56
tables/19 populated pass, with FK checks, sequences, old retry, native conflict
restoration and a new generation. Independent competing enables return one task.
An auditor-only cached activity-monitor snapshot was corrected and rerun; its
original failure is retained. Reviewer/auditor/builder counts overlap.

This closes the old E6-06 independent review/audit gap for existing G03/G04.
Their review fields become PASS, without new points or definition changes.
Overall90/100 and J03 UNKNOWN remain. Native pg_dump/production recovery,
remaining older critical gates and owner/source decisions are not approved.

The final merged whole suite is still running at this handoff on exact r2;
it is separate evidence and is not yet PASS. The earlier merged r1 and E6-18
broader partial runs were deliberately interrupted to test the newer code.
No final Telegram has been sent at this checkpoint.
