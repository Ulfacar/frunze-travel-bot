# E6-06 review packet — internal deadline tasks

CRITICAL / solo, local synthetic implementation. Required independent reviewer and final auditor: UNKNOWN. This packet is not approval. Parent70-point goal remains ACTIVE.

## Requirement and implementation to inspect first

PDF sections13/14/19: preserve assigned deadline work, completion/cancellation/escalation, retries and change handling. Only a manual evidence-backed operational date creates a task; unknown/draft arithmetic never schedules a guessed date. Assignee is the current ServiceCase owner; escalation raises priority for that same person with a typed reason. No invented supervisor hierarchy, client messages, production scheduler or service identity.

Inspect `app/domain/entry_deadline_tasks.py`, model `EntryDeadlineTask`, additive migration0022, source hooks in `entry_deadlines`, `entry_issued`, `entry_applications`, native `kg_deadline_tasks` and tests. CalendarTask/CalendarTaskEvent remain the lifecycle/audit engine; bindings do not duplicate an immutable task-event journal.

## Important invariants / adversarial review

- Named full admin before engine/payload; existing KG-OFF/workday/write gates and actor/session/case/application/rule/action/binding/token HMAC. No expanded manager access.
- Owned atomic case→application→task locks; source hooks share the source transaction and only reconcile explicitly enabled bindings. No task table means the older source-journal capability has no enabled tracks; explicit task APIs never hide a missing migration/storage error. Older populated migration tests exercise this compatibility.
- Latest verified deadline/actual anchor under lock; stable source and owner fingerprints. A requested future revision waits. An old job always consumes latest state; duplicates cannot create parallel tasks.
- Calendar task contact/case/direction/kind and the last authoritative binding audit must agree. Changed task date/exact time is a manual conflict, never silently overwritten; explicit restoration uses current token. Claimed outcome remains uncertain and blocks mutation/duplication. Source facts are retained even when tasks need attention or exhaust generations.
- Terminal same-source task stays closed even after owner changes. New source generation retains old task/owner/history. Missing owner pauses work; restored owner can receive a new generation. Source withdrawal cancels active work; later explicit source evidence can create new work.
- Manual actions use bounded receipts in CalendarTaskEvent with exact command/actor/request identity. A lost acknowledgement can be retried without duplicate completion. Stale forms cannot operate on a newer source/generation. No outside message or I/O inside a transaction.
- Case worker scans stable first-generation cursors in bounded pages; each track owns a transaction and records failed/retry cursors. Repeated sweeps from zero cover owner/anchor changes without new deadline rows. Native admin can invoke and continue a sweep. Automatic production scheduling and role policy remain unapproved.
- Migration is additive/no backfill. Populated/offline downgrade refuses; SQLite and PostgreSQL DDL checked separately. PostgreSQL runtime/recovery is UNKNOWN; no available local daemon/DSN, no live migration.

## Evidence and limitations

Development checks and exact-revision verification are recorded in the matching handoff/snapshot after code commit. Initial task tests exposed a seeded generic calendar task in the fixture; assertions now count only bound deadline tasks, preserving unrelated tasks. The HTTP fixture used a nonexistent flag name; corrected to existing `service_cases_enabled`, without changing its production gate. Print inspection found a blank second page from base html/body height; explicit print height now follows the existing deadline page convention.

Inspect failure paths, action receipt tampering, two people/rules, owner changes, actual event hooks, partial success, before/after-commit crash, concurrent processors, mobile/no-JS and real FK enforcement. These synthetic checks cannot establish legal source validity, approved production operations, pilot acceptance, or independent review. All208 source units remain drafts;22 deadline values remain NULL.

Known unrelated full-suite tour-date fixture failure persists from the earlier baseline. Do not claim a clean full suite, PostgreSQL runtime, independent audit, deployment or whole PDF completion.
