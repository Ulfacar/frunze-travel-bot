# E6-15 — connected source SOP and Appendix B.8 scenarios

STANDARD / solo. Completion target: local synthetic acceptance tests and evidence,
with a separate SELF_REVIEW. Parent overnight deadline:08:00 Asia/Almaty.
No deployment, actual client data, network delivery or business/source approval.

## Intended result

Exercise the existing storage and service functions together for the PDF §19
procedures and the three specific Appendix B.8 intake situations. Keep a single
case/applicant identity through each scenario. Verify persisted revisions,
handoff/owner acknowledgement, quote uncertainty, real package/payment/application
dependencies, portal confirmation and post-issue consequences where applicable.
Source examples are historical acceptance inputs, never current legal advice.

J01/J02 are candidates only. Preserve their fixed definitions and weights;
unavailable approved classification must remain UNKNOWN rather than be simulated
as production approval. Test fixture policies authorize only synthetic tests.
Report any missing connected step explicitly, even if that prevents scoring.

## Acceptance and failure paths

- Whole connected visa scenario and the work/registration/regularization branches
  from source §19; actual functions and storage, not success-returning service mocks.
- Exact US tourism45days, India business10days, Uzbekistan garment-work in-country
  situations from B.8, with source provenance and expected uncertainty/handoff.
- Negative checks for incomplete/conflicting facts, wrong person or stale source,
  unconfirmed portal messages, duplicate operations and changed authoritative facts.
- SQLite and relevant isolated local PostgreSQL checks; no external adapters invoked.
- Separate self-review, exact commands/results, saved handoff and updated coverage.

Runtime changes are outside the initial test-only scope. A discovered defect in
money, authorization, personal-data storage or irreversible behavior reclassifies
its fix as CRITICAL and requires independent review/final audit under the protocol.

Research established two missing product links: intake currently requires an
existing service case, while contract signing creates a new case; the complete
typed interview also does not persist an approved qualification automatically.
Do not hide those gaps with a test-only bridge or call an operator attestation an
approved automatic result. Broader work/regularization paths remain the existing
E6-10 evidence, not newly claimed full source-SOP coverage.

The concrete additional test slice is therefore visa V25 and registration R08
after an existing contract, same-subject handoff/quote/package/payment/portal and
post-issue calls, plus the three exact B.8 situations with retained uncertainty.
It strengthens evidence but deliberately earns **no J01/J02 points**; whole source
acceptance remains PARTIALLY_READY until the missing product links are implemented.
Current status: final SQLite and isolated PostgreSQL verification pending.
