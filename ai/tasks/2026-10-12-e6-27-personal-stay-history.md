# E6-27 — individual stay-history evidence for approved qualification

CRITICAL / solo. Parent: continue full inbound PDF/CRM implementation under the
existing local-only authorization. Completion target: reviewed local change.
No production migration, real personal records, owner-policy approval or sending.

## Confirmed gap

C05 cannot close from the E6-22 candidate alone. The stay arithmetic and immutable
contact history are already reviewed, but a payer/contact history is not evidence
about each applicant. Existing typed interview history contains dates and country,
not confirmed stay basis, passport continuity or a complete-history declaration.
Do not copy contact history or infer those missing answers.

## Planned bounded change

- Add an immutable, bounded case/applicant stay-history journal with composite
  scope/predecessor constraints, idempotent commands and compare-and-swap revision.
  Reuse the existing strict history schema and semantic normalizer. Keep opaque
  passport references; accept no raw passport number or uploaded document bytes.
- Preserve explicit history completeness, evidential basis and confirmation.
  Prevent future as-of dates and contradictory dates; incomplete/unknown data
  stays visible. A newer profile or different passport must never silently
  become continuity with the previous passport.
- Add a protected native operator flow for reading, editing, saving and inspecting
  historical versions. Signed scope/revision, existing full-admin/feature/workday
  gates, strict fields, clear errors, RU/EN where the parent profile selects it.
- Expose an internal same-session reader for later approved qualification. No
  selected regime, eligibility, money or source approval follows from saving
  history. Subsequent calculation/registration/interview integration is still
  required for full C05.

## Pre-audit and verification

Risk: cross-person evidence leakage, payer inheritance, ambiguous passport
continuity, invented completeness, stale/concurrent writes, broken immutable
history, future/backfilled dates and oversized journals. Lock in existing order:
case then applicant; use exact participant scope and validate the entire bounded
history before deriving current evidence. Keep old contact/profile tables and
receipts unchanged. Additive local migration; downgrade refuses populated new
history. No destructive repair or real-data backfill.

Observable acceptance: two people in one case retain separate histories; wrong
case/person/actor is denied; exact retry returns original receipt after later
edits; conflicting retry/CAS is refused; a failed transaction leaves no partial
snapshot; unknown/unchecked/client-statement evidence cannot become confirmed
eligibility; current and historical native views are readable and explicit.
Verify SQLite foreign keys, actual loopback PostgreSQL concurrency and migration,
old-data preservation, browser mobile/no-JS/print and relevant regression only.
Independent requirement/code review and separate final audit are required.

Status: PREPARED, not implemented. E6-25/E6-26 corrections finish first.
