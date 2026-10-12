# TASK: E6-22 — qualification from approved rules

- ID / date: E6-22 / 2026-10-12
- Project/scope: inbound PDF, C05 and the interview-to-qualification boundary
- CLASS: CRITICAL — a product/regime recommendation must not misstate eligibility or use draft legal rules.
- Mode: solo
- Completion target: reviewed local change; no production release
- Base: `fix/tours-search-quality` at `8062f80`, plus preserved uncommitted UI changes documented in STATE.
- Builder: root; independent reviewer and separate auditor to be assigned.
- Bounded candidate adapter: DONE at locald847a254acfd54ec8aeecef529c2885f6ba39bbe, independent APPROVE and separateGO. Handoff `ai/handoffs/2026-10-12-2002-e6-22-route-candidate.md`. Full C05 remains open: personal history/calculation, registration and typed-interview reconciliation are not delivered by this slice.

## Goal and current behavior

User said “делай” after the 92/100 PDF status and remaining requirements were explained. Continue the authorized local work. The existing qualifier deliberately always returns a draft review. The publication runtime and per-applicant profile journal already exist but are not connected to an approved product/regime recommendation.

## Scope and boundaries

- Select only an unambiguous applicable regime and product route using the current approved publication and an explicit, version-bound qualification policy. Preserve unanswered facts and unsupported conditions as uncertainty.
- Read the exact latest individual profile, with case/applicant scope and current source checks; preserve historical draft replay contracts.
- Expose the result in the existing protected native CRM flow, including RU/EN, source/version, missing facts and specialist fallback.
- Connect the typed interview where its facts can be mapped without inventing answers; examine source stop/interrupt coverage separately.
- Actual legal rules, privacy, prices, product routing and pilot policies remain owner decisions. Positive tests use unmistakably synthetic policies and data.
- No deployment, customer messages, production database changes, real source approval or production activation.
- Parent J01/J02/J03/J05 and earlier review gaps remain open until separately evidenced; no automatic points from this task card.

## Acceptance and evidence

| ID | Preconditions/action | Expected behavior | Verification |
|---|---|---|---|
| AC1 | Complete synthetic ordinary profile, one applicable published regime, exact approved routing policy | Bounded recommendation with immutable profile/source/policy identities; no entry guarantee or invented dates/prices | Domain and native tests |
| AC2 | Draft, withdrawn, stale, conflicting, changed or partially published relevant rules | No selected regime/product; specific reason and specialist fallback | Negative tests |
| AC3 | Missing/unknown facts, multiple citizenships, multiple matching regimes, unsupported conditions | No guessed choice, at most three questions; explicit unresolved facts | Golden/adversarial tests |
| AC4 | Wrong actor/case/applicant, malformed input, obsolete profile | Existing access and scope enforcement; no mutation | Domain/native tests |
| AC5 | Publication/profile changes during evaluation, actual PostgreSQL | Coherent current snapshot or conservative rejection; no mixed-version recommendation | Actual PG checks |
| AC6 | Existing saved qualification/profile receipts | Historical replay remains unchanged | Compatibility tests |
| AC7 | CRM desktop/mobile/light/dark/no-JS | Readable recommendation and fallback, native navigation and print | Browser evidence |

## Plan and risk

Read source requirements and current contracts; independent risk pre-audit; define the conservative executable-policy contract; implement domain/native flow; verify synthetic positive/negative/concurrency scenarios in an env-free snapshot; independent review and separate final audit. No destructive migration is planned, so recovery is removal of the local code/config addition; existing source/profile records remain unchanged.

## Completion requirements

- Relevant pure/domain/native/browser tests and real PostgreSQL where concurrency semantics apply.
- Independent CRITICAL review plus separate final audit on identified source snapshot; fix confirmed defects.
- Whole repository suite is not assumed green from older runs.
- Handoff: `ai/handoffs/2026-10-12-e6-22-approved-qualification.md` (final time and evidence added at completion).
- Remaining owner gate: concrete approval of actual source/policy decisions and pilot; prepare reviewable packet after technical work.
