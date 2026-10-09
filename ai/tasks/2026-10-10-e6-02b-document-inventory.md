# TASK — E6-02B persisted document inventory

- CRITICAL / solo; local implementation/checks and independent-review packet.
- Base `f0d9efa`; parent goal `ai/tasks/2026-10-10-pdf-to70.md` remains active.
- Requirement: PDF §§5/14/18/19 requires documents per applicant/application,
  distinct receipt/review/correction, current versions and passport-change invalidation.

## Observable scope

Persist an explicit checklist definition per application and append immutable
metadata events: received version fingerprint, checked/correction/revocation,
requiredness/applicability and passport revision. Same-key retry returns original
result; changed retry or stale revision conflicts. Foreign case/application/item
IDs, unauthenticated/non-admin actors, corrupt histories and stale evidence fail.
Reads return full history under bounds; summary never calls mere receipt accepted.
Native forms behind existing OFF/full-admin/write gates; CSRF/HMAC bind actor,
case, application, action, expected revision and nonce. Mobile/no-JS/print/errors.

No file content, personal names/numbers, storage/deletion policy or actual portal
submission. Metadata feature is local/synthetic only pending DEC-06 and review.
No production migration. A draft source checklist is not a complete approved pack;
receipt/review events cannot publish rules or authorize submission by themselves.

## Risk pre-audit

- Scope confusion: composite FKs and domain checks bind every record to its case
  and application; reused applicants from another case fail even with same payer.
- Stale documents: immutable content fingerprint/version; checking old content
  cannot accept a new version. Passport generation is pinned to checks and changing
  it invalidates dependent checks without erasing prior facts.
- False acceptance: explicit review, source evidence and operator confirmation;
  missing/conditional/unknown definitions remain visible and block complete status.
- Concurrency: serialize through application lock; atomic append, CAS, request-key
  dedup before stale checks; no partial writes or newly accepted state on retry error.
- Audit integrity: event-chain hashes, bounded reads, immutable ORM/bulk guards;
  corruption fails before new writes. No secrets or unneeded free text in records.
- Migration: additive schema, constraints tested with FK enforcement; empty-only
  downgrade under lock; populated/ offline downgrade refused. PG runtime not inferred.
- UI: strict allowed fields/types/body limits and safe retry after uncertain commit;
  never expand manager permissions or auto-enable flags.

Independent review and final audit required; same-context SELF_REVIEW is not approval.
If unavailable, local slice remains PARTIALLY_READY while goal work continues.
