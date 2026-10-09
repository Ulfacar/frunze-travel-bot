# TASK — durable internal deadline tasks

- CRITICAL / solo, local implementation/checks and review packet. Parent70-point goal stays ACTIVE. BuildG03 and assessG04 against actual completed worker behavior; do not award worker points for a plan or a task-claim helper alone.
- Reuse CalendarTask/CalendarTaskEvent and current ServiceCase owner. Do not introduce new manager permissions, fictitious service accounts, external messages, an escalation recipient hierarchy, or production scheduler configuration.
- Observable acceptance: an application/rule's currently supported manual control date can create one durable task for the existing case owner; journal/source/anchor changes update or invalidate that task without duplication. Unknown/unconfirmed candidates never schedule a guessed deadline. Completed/cancelled history remains intact; a new source generation requiring work is explicit. Native task status, completion, cancellation, manual escalation to high priority for the same owner, and reconciliation are reviewable.
- A bounded reconciliation processor must own atomic transactions and consume the latest verified revision under locks. Repeated/out-of-order batches cannot regress dates or create duplicate tasks; partially failed batches can resume. No external action occurs inside this processor. Autonomous production scheduling/worker-role policy is not implied by a local processor or native manual trigger.

## Risk pre-audit and design constraints

- Lock order case→application→task; validate application/rule/case/source-row/task scope before mutation. Task contact, direction and service_case_id must match the case. Foreign link or corrupted history fails closed.
- Pin consumed source revision/hash and desired date/owner. Existing task assignment follows current case owner, not an invented supervisor. Missing owner/date yields an explicit waiting state.
- Reuse existing task lifecycle events; keep cancelled/completed generations and actor attribution. Manual escalation changes internal priority only, with reason; no automatic client/supervisor messages or guessed reminder cadence.
- A claimed task has an uncertain execution outcome: do not blindly cancel, reschedule or duplicate it. Expose reconciliation instead. Existing manually changed task scheduling must not be silently overwritten by a stale worker; detect and surface the conflict.
- Per-rule task binding/generation records and idempotent target fingerprints prevent duplicates after lost commit acknowledgement and competing processors. Process latest state even when an old job arrives; a requested future revision must wait.
- Atomic creation/update and source-consumption markers; resume bounded batches safely after partial failure. Existing business records and source snapshots are untouched.
- Additive migration only; local synthetic SQLite, scoped FK/negative tests, PG DDL, safe populated/offline downgrade behavior. Independent critical review/audit and PG runtime remain required and UNKNOWN until evidenced.

Acceptance scenarios: two applications/same payer; two rules/same application; no source date; verified manual date; recalculation clears date; later anchor invalidation; case reassignment; complete/cancel/escalate; repeated/concurrent/out-of-order jobs; crash before/after commit; partial batch recovery; claimed-task/manual-schedule conflict; native full-admin/OFF/write/CSRF gates; mobile/no-JS.
