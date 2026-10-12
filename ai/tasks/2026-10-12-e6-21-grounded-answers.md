# E6-21 — approved knowledge answers with source/version and fallback

- Date: 2026-10-12. Parent: fixed PDF requirements, currently 90/100.
- CLASS: CRITICAL — presentation of approved immigration-related knowledge.
- Mode: solo. Completion target: reviewed local change; no release.
- Base: `fix/tours-search-quality`, `f06f5eacef734bfde625813c663bc91815fe01bc`.
- Builder: root agent. Independent reviewer: `/root/e621_review`; separate auditor: `/root/e621_audit`.

## Goal and current behavior

H03 requires grounded approved knowledge answers with source/version and fallback.
Existing `runtime_knowledge` validates publication and individual source reviews,
but no user-facing answer adapter consumes it. The PDF search displays drafts.
Implement a deterministic RU/EN internal answer adapter and accessible native
full-admin screen. Only exact requested, currently published facts can appear.
Source facts do not establish a person's eligibility or calculate dates/prices.

## Scope and authorization

User requested continuing implementation on 12 October. Continue locally with
synthetic checks. No deployment, production access, client messages, source/legal
approval, new permissions, migrations, or actual personal data. Preserve unrelated
untracked files. No new publishing or privacy policy is invented.

## Acceptance

| ID | Scenario | Expected |
|---|---|---|
| AC1 | Select up to three exact source rules, RU or EN | Deterministic readable source facts; retain every value field, scope/conditions and citation/version |
| AC2 | Unpublished, expired, rejected, conflicting, withdrawn or policy-mismatched rule | Explicit specialist fallback; no blocked value, no stale cache |
| AC3 | Mixed available/unavailable rules | Only approved facts shown, unanswered part explicit; no whole-answer approval claim |
| AC4 | Changed publication or review between requests | Fresh runtime check, current version/provenance; no request-supplied authority |
| AC5 | Unauthorized actor, disabled pilot, malformed/duplicate parameters | Denied before sensitive source access; no storage writes/sends |
| AC6 | Native page, empty/errors, hostile source markup, mobile/no-JS | Usable labelled form, escaped content, no-store, no external calls |
| AC7 | Unsupported or incomplete answer semantics | Withhold that rule and explain fallback; never silently omit qualifiers |

## Risk pre-audit and plan

Main failures: selective omission of exceptions/anchors, presenting a general
source as personal advice, mixing versions, stale availability after withdrawal,
source text treated as instructions, broadening access or leaking unpublished
values. Use existing runtime validation, bounded literal formatting, explicit
scope, fresh reads and escaping. Include negative tests for these failures.
The change is read-only; recovery is removing the adapter/link. Existing journal
and source rows remain unchanged. Inspect publication dependencies for defects
affecting this path; record other review gaps separately.

## Completion evidence

Run env-free synthetic SQLite domain/native tests and relevant publication
regression. Add real local PostgreSQL checks if available. Required independent
review and final audit examine task and actual snapshot before builder verdicts.
Record exact files/hashes and commands. H03 points only if full acceptance is
demonstrated; other fixed definitions and business gates remain unchanged.
Handoff: `ai/handoffs/2026-10-12-1200-e6-21-grounded-answers.md`.

## Completion

DONE for reviewed local H03; full parent PDF remains PARTIALLY_READY, **92/100**.
Code `c73745744b46f5b3b8029baba201c2506e4c4a06`, exact final r5 source identity.
43 focused PASS including7 actual PostgreSQL and2 browser cases;42 final shell
PASS. Earlier165 related checks are supporting r2 evidence with identical
publication runtime, not a new full suite. Independent APPROVE and separate GO;
13 changed source files match reviewed snapshot and code commit. Initial failures,
fixture corrections and semantic issues are retained in the evidence/reviews.
Temporary local PostgreSQL stopped. No deployment, real source approval or send.
Real client dialogue, personal eligibility and all other criteria remain outside
this bounded answer path. Recovery is source rollback; read-only path has no data
migration or persistent changes to restore. No approval gate was bypassed.
