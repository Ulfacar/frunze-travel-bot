# TASK — E5-04D: actual stay history in CRM

- Base `54a6e9d94c8fde5a8b602b49646702dc91633f83`, branch `fix/tours-search-quality`.
- CRITICAL / solo, local target + review packet; independent review/auditor UNKNOWN.
- User: continue PDF/CRM, commits/push already authorized; prefers no interim messages.
- PDF §§2.9, 3.3 D1/D2/D5 and B8, 18.4/18.5, Б.4: recorded actual entries/exits,
  completeness and provenance for specialist review; no legal allowance inferred.

## Acceptance

1. Full-admin visa-case form shows/saves historical trips via existing immutable
   StayHistory service, with explicit completeness/verification and open interval.
2. No new access policy, migrations, real data, passport numbers/scans or retention
   policy. Preserve opaque existing passport refs; never expose them as editable IDs.
3. Signed case/contact/base binding, CSRF, bounded native form, CAS, idempotent retry,
   lost-commit recovery, stale/foreign/corrupt denial and no SQL writes on GET.
4. View previous versions without modifying them; editing creates a new full snapshot.
   Trip removal changes only next revision, not historical records.
5. Explicitly choose saved history for a NEW qualification; old report/card stays pinned.
   Display pinned trips in review/print, so a specialist can inspect actual source facts.
6. Relevant domain/HTTP/browser checks including mobile/no-JS, unknown vs empty,
   invalid/future dates, duplicate/overlap/open semantics, unsupported source failures.

## Risk pre-audit / boundaries

Travel history is personal data despite absent names/passport numbers. Reuse existing
full-admin/default-OFF/workday/write gates and storage semantics. Do not publish legal
rules or calculate exact remaining days here. Do not silently attach newest history,
drop out-of-view trips, infer confirmed from client statement, or rewrite old snapshots.
Unknown exit dates must not be represented as a known ongoing stay. No deployment.
Separate self-review and review packet required; critical final status remains
PARTIALLY_READY when independent review/PG gates are still UNKNOWN.

## Outcome / evidence

Code `f851f635688ad92d202034a4a3eb605452e21421`, **PARTIALLY_READY**.
Acceptance implemented locally: existing immutable service, native version editor,
explicit source attachment and pinned print facts. No deployment or migration.
Related regression301 and corrected browser3 PASS before final banner refinement;
final Git-copy HTTP/shared-shell/browser **134 passed / 167.19s**. Exact commands/limits and report in
`ai/handoffs/2026-10-09-2318-e5-04d-history-crm.md`.
Review packet is **SELF_REVIEW**; independent reviewer/audit/PG remain UNKNOWN.
