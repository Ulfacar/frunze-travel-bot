# E6-30 — preserve the case from intake through recorded contract

CRITICAL / solo. Parent: full local PDF/CRM completion, fixed J01/J02 remain open.
Completion target: independently reviewed local change, not release. Builder root;
independent source-first pre-audit by publication_review completed. Implementation
is active; E6-29C saved as exact reviewed codee08338b, excluding all E630 changes.

## Problem and observable outcome

PDF section19 begins with intake and qualification before quotation and contract.
Current native intake requires a service case; the conversation contract form
creates a new case. A manager needs to explicitly open an unsigned case for a
chosen commercial product, record intake on the actual same applicant/case, and
later record an already signed contract against that same case without duplicating
the case, applicant, contract event or initial task. Choosing the commercial
product must not imply an approved immigration classification or published fee.

E6-28 already computes a bounded connected NO_VISA assessment from interview,
profile, history and published source authority. It is read-only, does not grant
quotation authority, and refers unsupported business/work/family scenarios. This
task does not manufacture wider eligibility or source approvals and alone cannot
close all section19/B8 acceptance.

## Required design checks before code

- Read `ai/reviews/2026-10-13-e6-30-pre-audit.md` when complete. Inspect current
  ownership, immutable workflow, signing and money readers; preserve old callers.
- Separate original open and signing command identities. Delayed retries must
  compare immutable operation evidence, including after later assignment or money
  correction. Global key collisions cannot disclose another manager's case.
- Explicit contact/product/case/actor scope and server-enforced current rights;
  database serialization plus exact expected revision for a fresh existing-case
  signing operation. No inferred client consent, signature, payment or approval.
- Preserve the original case/applicant and pinned workflow across later workflow
  publication. Define task creation from that workflow explicitly; do not silently
  lose the initial task because the unsigned case advanced to another stage.
- Preserve decimal/unknown-money semantics and existing contract event payload
  consumed by finance/process readers. No automatic payment, invoice or offer fact.
- Native no-JS forms use existing CSRF/signature/feature-flag conventions, display
  unsigned versus signed status truthfully, handle uncertain commit/retry, and link
  directly to the intake and existing-case signing flows.

## Acceptance / evidence

Actual native open→saved/reloaded intake→recorded signature on the same case;
exact replay after lost response; conflicting command; wrong owner/contact/product;
revoked access; stale revision; double open/sign races; existing signed-case deny;
later money correction and reassignment retry; preserved workflow/task/event;
rollback leaves no partial operation. SQLite and isolated local PostgreSQL,
relevant native/browser checks, compatibility tests, independent review and final
audit. If a schema change is needed, additive migration and recovery evidence.

Keep unknown quotation/classification and remaining work/regularization SOP gaps
explicit. No production, live clients, source/business approvals or deployment.
Do not read root `.env`; use env-free frozen archives. No J01/J02 point merely for
this preparatory card or a partial implementation.

## Initial implementation checkpoint — 12 October 18:55 UTC

Bounded visa-direction explicit opening only. Separate immutable one-per-case
`ServiceCaseOpening` receipt0038 retains original opening command/result; existing
signature key and legacy `sign_contract` behavior unchanged. New same-case signature
keeps a versioned original command in compatible `contract_signed` payload and
requires the pinned commercial first stage for first signature. No classification,
payment, collection consent or source approval is inferred.

Native forms now open a preliminary case from its existing conversation and record
an explicitly confirmed signature on that same case. HMAC/CSRF bind actor/action/
target/key/revision/original owner; current access rechecked. GET is read-only and
503 preserves the original form. Existing applicant/intake card link remains.

R1domain16PASS/1fixtureFAIL5.31s: admin tried another manager's ordinary payment,
which the established money API correctly rejects. Fixture changed to current
owner; no permission weakened. R2domain17PASS4.94s, R3native/domain24PASS16.47s.
All are synthetic SQLite in env-free archives. Real PostgreSQL races/recovery,
browser and independent review/final audit still pending. No criterion awarded.

## Final verification checkpoint — 12 October 19:12 UTC

Exact R11 candidate,16 scoped files, independent final verdicts pending. Real
native applicant/application creation, individual profile save/reload, internal
quote save and same-case signature now exercised with preserved IDs and receipts.
R10 core/native/10actualPG45PASS48.75s includes fresh-schema full-table binaryCOPY
recovery with sequences, legacy records and later writes. Final R11 canonical
identity/integrity/native18PASS20.27s. R7 mobile390dark/desktop1365light noJS and
recorded-contract state have six root-inspected PASS screenshots.

Reviewer and auditor reproduced historical retry, malformed evidence, impossible
revision/owner and noncanonical actor defects. Fixes are mapped by exact snapshot;
original failures remain evidence. After repeated evidence-validation findings,
root reassessed the command/event contract as a whole: canonical actor is required
before any write; original opening revision/workflow/stage and signature result
revision are deterministic; current mutable owner/price remain separate. This
avoids altering legacy signing or rejecting legitimate historical price changes.
One builder NULL-versus-empty reason regression was caught and corrected; the
original case_opened reason remains NULL. No stored history is rewritten.

Handoff `ai/handoffs/2026-10-12-1910-e6-30-precontract-case.md`; evidence
`ai/reviews/2026-10-13-e6-30-snapshot-evidence.json`. E630B pre-audit is separate.
All four remaining PDF criteria and real owner/pilot gates remain open.

## Final acceptance

DONE for reviewed local E630A. Code `d57cb059bbe78ca832478eee52cc83cc8738c597`, exact16 R12/root/index/commit
identities. Independent APPROVE and separate GO; final evidence/handoff above.
R11 final18PASS and legacyactualPG4PASS; reviewer13PASS; auditor6+5PASS with
separate run attribution. No criterion points awarded. Continue E630B task.
