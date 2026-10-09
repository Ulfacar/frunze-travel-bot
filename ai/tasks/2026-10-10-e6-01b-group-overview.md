# TASK — E6-01B group overview

- STANDARD / solo; target: local change, not release.
- Base `6d74465` on `fix/tours-search-quality`; builder/reviewer Codex (separate SELF_REVIEW pass).
- User authorized continued PDF/CRM work and working-branch commits/push.

## Goal and evidence source

PDF §14.1, physical63, verified directly against original SHA256
`141b9e1e570c916aab65f3dc40e927cc61ef182e1d155b997a5123091e36cca2`:
the service must show aggregate progress across separate people/documents. Current
register has paginated attempts but no complete group view; an old refusal and its
linked retry appear as separate rows without a current group summary.

## Acceptance

1. Read-only overview includes every registered person and every application chain,
   independent of register pagination; independent roots for one document stay separate.
2. Only verified leaf attempts contribute to current progress. Earlier linked attempts
   remain counted as history. Refusal, closure and requested corrections stay visible.
3. People with no applications are explicit. All approvals never imply document
   verification/delivery, travel readiness, a complete document set or service completion.
4. Whole-service totals and four process-family counts remain whole-service totals when
   filtering/paging people. Print states its filter/page scope and preserves results.
5. Coherent bounded database read, full existing hash/event/reference validation,
   no SQL writes; oversized/corrupt/unavailable data produces no misleading partial result.
6. Existing named full-admin, KG-OFF/workday gates and resource scope; no role expansion,
   new tables, real-data use, automatic tasks/messages or legal/financial decisions.
7. Synthetic domain/HTTP/concurrency cases, desktop/mobile/no-JS/print, source coverage,
   updated PDF checkpoint, handoff and commits.

## Risk and boundaries

Presentation/aggregation of existing authorized data only. No changed access,
persistence, retention, submission or commercial workflow behavior. Aggregate labels
describe the common manual journal, not publication of V/W/R/U workflows or approved
business rules. Missing current application evidence cannot become a ready state.
Read locks follow existing case → application order; capped reads fail explicitly.
Pure event validation can be extracted for batch reuse without changing its rules.

Existing independent CRITICAL review/PG runtime gates for E6-01A remain open; this
STANDARD local view cannot certify them. No production authorization requested/used.

## Completion checks

Focused existing/new domain and HTTP regression, synthetic browser checks, compilation,
whitespace, protocol structure; separate SELF_REVIEW. Full suite only if unresolved
regression warrants it; previous full run has one reproduced date baseline after the
migration-list correction. No CI configured; release/real customer acceptance N/A to
local target. Save exact results/revision and next action in a dated handoff/STATE.

## Outcome

**DONE for local STANDARD scope**. Code `f923a446449bc8010a4a78d09a192d0156315d71`.
Corrected new tests49 passed; exact-code related regression120 passed /3 warnings /
184.11s. Git/worktree/copy16/16 identity, cold imports, static/protocol checks PASS.
Separate SELF_REVIEW passed for local scope; five-page PDF and all26 headings checked.
Handoff `ai/handoffs/2026-10-10-0113-e6-01b-group-overview.md` records limits/baseline.
No whole-PDF or production completion claim; inherited CRITICAL gates remain open.
