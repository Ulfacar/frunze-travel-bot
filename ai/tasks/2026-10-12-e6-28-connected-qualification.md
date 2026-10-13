# E6-28 — connected personal qualification

CRITICAL / solo. Parent: full inbound PDF/CRM continuation. Target: reviewed
local implementation for C05, with explicit evidence coverage before changing
that fixed criterion. Production, actual source approval, legal/business policy
decisions, quote authorization and outbound delivery remain outside this task.

## Problem and intended behavior

E6-22 only proposes a source-bound route. E6-27 supplies personal stay evidence,
but the route, that history, arithmetic, registration rules and typed interview
are not yet one coherent result. The payer/contact calculator cannot bridge the
gap. A saved candidate or arithmetic scenario must not become entry eligibility.

Build a current case/applicant qualification read under one transaction, with
case, applicant and publication locks in their existing order. Use the exact
approved source, latest profile and validated personal history IDs/hashes.
Keep the existing route-only API/receipts and all old arithmetic/interview
algorithms readable. Preserve source/profile stop conditions and unsupported
routes as a clear specialist fallback rather than guessing policy.

The intended positive path is a complete current ordinary-passport individual
adult tourism profile, explicitly complete current same-passport stay evidence,
an unambiguous approved route and sufficient explicit server-owned authority for
counting and registration interpretation. Evaluate the entire planned trip, not
only its first day. Report internal route/product, source references, history
pin and calculation findings separately. Other purposes, special documents,
changed/unknown passports, missing dates/unknown basis and conflicting sources
must retain bounded questions or specialist review. No client permission to
cross a border, charge, quote or message follows from this result.

Registration exemption, registration period and submission deadline are distinct
source concepts. Do not turn a registration term into an exemption, a visa-free
allowance into registration permission, or a planned entry into an actual date.
Unapproved calendar/counting interpretations cannot produce an authoritative
deadline. Retain the already reviewed pure arithmetic as a labeled scenario;
any stronger selection requires separately pinned explicit authority, never a
form checkbox or a draft source value silently promoted to approval.

Typed interviews need an explicit reconciliation contract: validate their whole
journals, current policy, current answer dependency stamps, consent and stop/
handoff state, and compare mapped facts to the exact profile/history. New or
unmapped material answers cannot be ignored. No interview is distinct from an
incomplete/paused/stopped interview. Keep fail-closed reconciliation until every
used field has an explicit mapping and freshness rule. Prefer a narrow complete
supported path with visible fallback to an invented broad interpretation.

## Risk pre-audit and acceptance

Pre-audit completed in `ai/reviews/2026-10-12-e6-28-pre-audit.md`. Review actual source schemas,
qualification/publication policies, arithmetic and interview reducers and propose
the smallest coherent contract, including whether a separate approval document
is necessary and which original source concepts remain unsupported. Any final
C05 claim needs requirement/evidence coverage and independent approval.

Verify same-person isolation, zero payer-history inheritance, whole-trip source
and policy validity, stale/withdrawn history, exact pinned source/profile changes,
conflicting registration sets, complete/unknown histories, closed overlaps,
changed passport, actual/planned-date separation, interview stop/consent/conflict,
corruption and transaction consistency. Synthetic approved fixtures are test
authority only. Include real loopback PostgreSQL writer/read locks and protected
native RU/EN/mobile/no-JS/print behavior. Old profile/route/replay behavior is a
compatibility requirement. Independent review and separate final audit required.

Status: DONE for reviewed local C05. Code
`9bd6e926d4649b4d57152e0ce07491353767bc7f`, exact15 R9/root/index/commit identities.
Independent APPROVE and separate GO explicitly evaluated the unchanged fixed
C05 matrix. Handoff `ai/handoffs/2026-10-12-2212-e6-28-connected-qualification.md`.
54 core/compatibility PASS, five actual PG locks PASS, five native/browser PASS;
11 reviewer controls and five distinct auditor actualPG scenarios PASS, scoped
and mapped separately. Source/business/production approvals remain absent.

Chosen C05 matrix: substantive internal NO_VISA regime selection for a current,
adult, ordinary-passport, single-entry, individual tourism plan abroad, with
complete ACKed interview, current same-passport personal history, whole-trip
counting and registration exemption. Empty and nonempty histories and another
window require positives against the full 18-regime source structure. USA
45-day overflow, <=3-day margin, registration obligations/conflicts, business,
work, family, in-KG and special regimes need explicit justified referral.
Business B selection is not implemented by this matrix and remains part of
later all-product/golden-scenario coverage; no business automation claim follows.
