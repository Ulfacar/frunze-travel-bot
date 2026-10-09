# E6-05 — SELF_REVIEW and independent-review packet

- CRITICAL / solo; local implementation target PARTIALLY_READY. Independent review and final audit UNKNOWN. Task `ai/tasks/2026-10-10-e6-05-application-deadlines.md`.
- ScopeG01/G02: actual-event/source/calendar binding and immutable manual correction/recalculation history. No task worker, automatic notification, publication, legal deadline approval or production change is claimed.

## Actual change

One additive `EntryDeadlineRevision` table (`e6_deadlines_0021`), strict source/operation adapter, owned transaction journal, native scoped CRM forms/history/print. Source rules/calendar versions are pinned and integrity-checked. Proposed arithmetic reuses DeadlineReview; a candidate date never becomes an operational date automatically. All22 real PDF deadline units still lack approved typed interpretation; missing values remain unknown.

Actual anchors come from verified application events or issued-document travel entries. The caller cannot provide an actual date directly. Supported semantics are submission_date/return_date/approval_date and actual entry_date/exit_date. Other anchor names and hour-based rules without exact timestamps remain unresolved. This does not pretend to cover birth, employment termination, passport issue, permit expiry or quota facts that are not yet in the factual registry.

Manual dates require dated portal/official-document fingerprint, explicit operator confirmation and reason. They are internal control facts, not legal source approval. Clearing/recalculation preserves history and removes the prior manual date. A newer anchor makes the old date non-operational without erasing it; manual reconfirmation requires recalculation. Old source/calendar calculations replay against their historical facts after newer events/calendar versions appear.

## Risk review

- Full-admin/OFF/workday/write gates; strict form/body/query allowlist and actor/session/case/application/rule/action/revision signature. Foreign person/application/event access refused.
- Scoped application, predecessor and two anchor FKs. Parent lock, per-rule CAS/idempotency; one concurrent successor. Immutable ORM model and bounded250 revisions/4MiB per rule,64 rules/application. No source or prior facts are mutated.
- Hashes, pinned bundle/rule/calendar/anchor evidence, manual-operation replay and runtime-pinned arithmetic replay. Corrupt history fails closed. Privileged replacement of a complete forged database history is outside hash guarantees.
- Unknown dates remain unknown; no fallback to calendar days, planned trips or another applicant's stay history. A changed calendar version produces a new snapshot; old calculations remain reproducible.
- Lost commit acknowledgement preserves the exact original form, including multi-selected calendars, and hides fresh mutation forms until recovery. Fixed an error classification bug: DomainError inherits ValueError, so EntryStorageUnavailable must be caught before ordinary form ValueError.
- Additive schema, no backfill. Locked empty-only downgrade; populated/offline downgrade refused. SQLite migration/FK/model parity exercised; PostgreSQL DDL only, runtime/recovery UNKNOWN.

## Evidence before final committed snapshot

- Source adapter4 PASS/10.60s after correcting a fixture's calendar import return shape.
- Initial journal5 PASS/13.94s; source+journal with replay9 PASS/21.01s.
- HTTP8 PASS/19.25s after fixing uncertain-commit handling. Recovery fixture corrected to reflect HTML wire semantics: empty multi-select sends no key; a separate multi-calendar recovery test checks every hidden input and duplicate-free retry.
- Migration and mobile390/desktop1365 without JS browser5 PASS/3 warnings/29.54s after correcting a synthetic reference to the required8-character format.
- Extended domain11 PASS/1 invalid fixture/18.76s; fixture for unknown value needed preserved blocked evidence. Corrected imported-unknown case1 PASS/8.34s without relaxing import validation. Final combined rerun required.
- Mobile and one-page print inspected. Cold imports deadline UI/application UI/main exit0. Later source-label/runtime pin and result screenshot additions are included in final snapshot checks, not assumed from earlier evidence.

Final exact-commit checks/snapshot identity belong in the handoff. Source, calendar, owner/privacy and release decisions remain unapproved. Synthetic generic VisaUSA case is a test scaffold, not an approved inbound product. Continue parent70-point goal after this slice.
