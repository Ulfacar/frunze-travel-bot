# TASK — E6-01C versioned draft process checks

- STANDARD / solo; target: local change and reviewable process draft, not publication/release.
- Base `735eaf3`, branch `fix/tours-search-quality`; builder/reviewer Codex SELF_REVIEW.
- User requested continued PDF/CRM work; working-branch commits/push already authorized.

## Goal

PDF §§14.2–14.6/p63–66 define V/W/R/U stages, branches and exceptions. Current CRM
records generic application facts but has no source-coded procedural transition
checks. Add a versioned source catalog and deterministic dry-run evaluator, plus
a full-admin CRM review screen, without changing applications or service stages.

## Acceptance

1. Catalog retains all87 source codes (V25/X15/W22/WX4/R8/RX2/U9/UX2), original
   labels/provenance and distinctions between normal stages, exceptions and flags.
2. Explicit draft edges carry named required facts; unknown/false differs from true.
   No truthy strings, stage jumping, cross-process transitions or stale versions.
3. Corrections return within one attempt; refusal retry describes a NEW linked
   application, not a transition that rewrites a refused attempt. U's L-vs-registration
   branch must not imply that a registration produces an L visa.
4. Documents/consent, verified issue/delivery/entry and declared prerequisites are
   checked in synthetic scenarios. These are draft checks, not evidence from live
   CRM, actual payment authority, legal eligibility or a complete operational workflow.
5. Every result explicitly remains non-executable/unpublished. Numerical deadlines,
   tariffs/refunds, client messages, document storage and publication decisions stay
   with existing owners; input cannot enable them. No new policies or access rights.
6. Native admin preview behind existing KG-OFF/workday/full-admin gates, source
   references, missing/failed facts, malformed/stale inputs, no SQL writes or PII entry.
7. Tests, mobile/desktop/no-JS/print, source coverage, report, handoff and commits.

## Risk / boundaries

Existing ServiceCase workflow is a commercial published process; do not seed draft
KG stages there or falsely attach whole employer/workflow stages to one document.
Preview facts are user-supplied hypothetical values and are never loaded from or
saved onto applicants. Preserving source claims is not legal verification/publication.
Draft edges without explicit source successors are labelled implementation proposals.
Unknown branch/workflow policy remains blocked or a linked-procedure notice.

No schema, env, deploy, messages, new personal records or permission expansion.
STANDARD solo requires separate SELF_REVIEW. Previous CRITICAL review/PG gates
remain open. Relevant focused regression and isolated-browser checks; full suite
only if an unresolved regression warrants it. Whole PDF remains incomplete.

## Completion

DONE for this STANDARD local scope at code
`6af101f5b6482d8db7073d25d2975273f9ebeee4`:87 source codes,71 draft edge variants,
native preview and print, final related130 tests PASS, separate SELF_REVIEW PASS.
Evidence/report: `ai/handoffs/2026-10-10-0225-e6-01c-process-preview.md`.
No real transition execution/publication or production acceptance claimed.
