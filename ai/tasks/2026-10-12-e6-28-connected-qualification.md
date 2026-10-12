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
tourism/transit profile, explicitly complete current same-passport stay evidence,
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

Pre-audit pending before implementation. Review actual source schemas,
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

Status: DESIGN. E6-27 final review/audit complete, code
`643c455bf690e14a4b8e48f557e3fe2f7541d77f`, mapped to frozenR6. E6-28 independent
pre-audit in progress; no runtime code exists and no fixed point has been claimed.
