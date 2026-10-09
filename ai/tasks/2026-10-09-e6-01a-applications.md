# TASK — E6-01A applicant/application register

- CRITICAL / solo; target: local implementation + review packet, not release.
- Base `208a04d95a54ca0da9535bdeab5a81fdfcc7b15f`, branch `fix/tours-search-quality`.
- Builder Codex; independent reviewer/final auditor UNKNOWN.
- Authorization: continue PDF/CRM, working-branch commits/push already requested.

## Goal / acceptance

PDF §§14.1, 14.3, 18.3, 18.8: separate each person, document/procedure and submission
attempt. Current contact interview cannot do this. Add a full-admin manual register:

1. Numbered applicant records scoped to one visa case (group role only, no names,
   passport numbers/scans or imported personal profiles until DEC-06 is resolved).
2. Separate application records for visa, unified permit, resident card, registration,
   violation protocol and exit visa, labelled with the four PDF process families.
3. Manual fact journal: draft, submitted, returned for revision, approved, refused,
   closed without completion. Record actual date/source and operator confirmation;
   no portal automation, commercial/legal decisions, deadlines or customer messages.
4. Resubmission after requested correction stays on the same attempt; retry after
   refusal/closure creates a linked new attempt for the same applicant/procedure.
   Another independent procedure can start separately. One outcome never completes
   other applications or the existing service case.
5. Existing full-admin/OFF/workday/write gates, signed native forms, bounded payload,
   resource scope, CAS, idempotency, owned transactions, immutable audit and recovery.
6. Additive migration tested only in synthetic local SQLite; PostgreSQL DDL inspected.
   Downgrade refuses populated tables. No production/environment/migration execution.
7. Native mobile/desktop/no-JS flow, error recovery, tests, source coverage and handoff.

## Risk pre-audit / boundaries

Application references and dates are sensitive even with numbered placeholders.
Existing rights only; no real-data use before privacy/access/release decisions.
Full workflow/SLA/payment/document guards remain future work: these are manually
recorded processing facts, not publication of the four executable workflows.
Do not infer applicant identity from the shared contact/family array, copy their
qualification/history to every person, overwrite older events or auto-close the case.
Creation identity and every status revision must remain attributable, source-labelled
and recoverable after a lost commit acknowledgement. Unknown dates/sources are not
fabricated. No financial side effects from refusal or closure.

## Checks / remaining gates

Domain, migration/parity, native HTTP, malicious/foreign input, stale forms, duplicates,
concurrent revisions, lost acknowledgement, corrupted history and browser flows.
Separate SELF_REVIEW packet; independent CRITICAL review/audit/PG runtime UNKNOWN
means PARTIALLY_READY. Formal manager/access/privacy decisions remain pending.

## Outcome

Code `91a43fa0202fbacfe62ee337c188bb156276a4df`; local feature implemented,
**PARTIALLY_READY** pending independent review/audit and PG runtime. Initial related
checks70 passed, final browser2 passed after print correction. Full copy: 3562 passed /2 failed /13 skipped. Migration-test list corrected in `478598a819c63d317451a932dc6ee68da1c528e1`; final focused copy **131 passed /2 PG skips /135.77s**. Tour-date failure reproduced on prior code. Exact full regression and report recorded in `ai/handoffs/2026-10-10-0005-e6-01a-applications.md`.
Existing pilot gates retained; no production migration, real data or outgoing messages.
