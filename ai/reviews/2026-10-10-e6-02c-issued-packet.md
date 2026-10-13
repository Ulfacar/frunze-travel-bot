# E6-02C — SELF_REVIEW and independent-review packet

- CRITICAL / solo; task `ai/tasks/2026-10-10-e6-02c-issued-documents.md`.
- Builder and SELF_REVIEW are the same context. Independent review/final audit
  remain **UNKNOWN**. Local implementation is **PARTIALLY_READY**, no release.
- Source §§16.1–16.5/17:12 comparisons, correction, delivery, receipt, actual travel.

## Actual change reviewed

One additive immutable `EntryIssuedRevision` ledger and migration `e6_issued_0019`,
pure strict reducer, owned transaction service and native per-application forms.
Writes require the existing named full-admin boundary and an approved visa/exit-visa
attempt backed by portal/official-document evidence. Other document procedures are
not silently assigned a visa checklist. Actual files/personal identifiers are absent.

Checklist version/source PDF hash and fields are stored with snapshots. File/passport
fingerprints, exact versions and passport epochs bind verification. Verified fields
are operator attestations, not automated OCR or legal eligibility. No case completion,
financial charge, portal submission or external client message is performed.

## Adversarial review

- Changed-back passport cannot resurrect a previous check. File replacement cannot
  undo the established current passport; check date cannot predate that binding.
  A new file clears old checks and current delivery/receipt while preserving history.
- All12 fields must be compared. Unknown/false fails complete verification; only
  explicitly optional passport dates support “not present”. A correction remains
  pending until a different official file is registered; rechecking the erroneous
  file cannot clear it. False-alarm correction reversal is not implemented.
- Delivery has separate messenger/email/CRM evidence and pamphlet fingerprint.
  Receipt is explicit, and unknown client name/passport check remains unknown.
  Delivery does not fabricate receipt. Rechecking records changes the generation
  against which current delivery completeness is assessed.
- Actual travel requires past/current dated stamp or official-record evidence.
  Late actual facts can be recorded before internal file/review work, with no
  invented permission; duplicate proof/fact is rejected and ordering not guessed.
- Composite FKs bind application/case/predecessor/approval event. Full chain/hash
  and semantic replay before read/write; bounded history; no ORM/bulk mutation.
  This does not protect against a privileged DB administrator replacing all history.
- Parent lock, CAS and original request identity handle duplicate/concurrent writes.
  Lost commit acknowledgement offers the exact signed request and hides new mutation
  forms until recovery. Auth/KG/write gates precede writes; strict fields/body/query.
- Additive migration; no backfill. Empty-only locked downgrade, populated/offline
  downgrade refused. Actual SQLite FK/model parity checked; PG runtime UNKNOWN.

## Evidence before final committed snapshot

Initial domain12 PASS. Domain/migration/native HTTP26 PASS /40.50s after current
passport/date/receipt separation; browser2 PASS /30.24s (mobile390 and desktop1365
without JavaScript). Two-page synthetic print inspected, actual facts/source checks
and history present. Additional history-bound cases2 PASS /8.92s.
Later explicit source-definition pin, recovery-form guard and wrong-approval FK
challenge are included in the final exact-commit regression, not assumed passed here.

Final revision/checks/manifest belong in the following handoff. Keep older full-suite
results separate: `5feb4e0` had3732 PASS/3 FAIL/13 SKIP; baseline shell lists corrected
in8e9ab4f, known tour-date fixture still FAIL. No new full-suite/PG/deploy claim here.

Independent reviewer should start from the source requirement/diff and challenge
passport rollback, mixed file/approval links, missed acknowledgement, unknown receipt,
backfilled travel and downgrade recovery. Consent/source/access approvals remain open.
Continue the active70-point goal after this slice; do not declare the PDF complete.
