# SELF_REVIEW — E6-01B group overview

- STANDARD / solo, local-change target. Reviewer: Codex, same author and context,
  separate review pass. This is not independent CRITICAL approval.
- Base `6d74465`; task `ai/tasks/2026-10-10-e6-01b-group-overview.md`.
- Reviewed source §14.1/p63, actual new domain loader/aggregation, existing event
  validator extraction, route, template, tests, report builder and coverage.
- Exact final revision/results: handoff linked from `ai/STATE.md`.

## Findings and resolution

1. Aggregate must use all stored attempts, not the current register page. Loader
   selects the whole case under explicit bounds;22-person test crosses both page
   boundaries, keeps total22 and shows2 on page2. Six SELECT, no N+1 per application.
2. A historical refusal must not count twice after a linked retry; independent roots
   must not disappear. Validate every event/hash/reference and same-subject predecessor,
   then take only leaves; keep explicit historic counters and links. Mixed fixture
   includes two independent visa roots for one person plus a registration.
3. No-person/no-application group cannot become an all-approved state. Those states
   are distinct, totals remain visible under filters, approval labels explicitly
   exclude delivery, travel readiness and service completion. Missing expected
   procedures are not inferred from the existing registry.
4. A group read can otherwise mix application events from concurrent commits.
   PostgreSQL: case shared lock, all application shared locks ordered by ID, then
   batch events/references. Creation uses exclusive case first; fact writes lock
   their application. SQLite keeps explicit physical BEGIN. Concurrent SQLite
   read/write scenario exercises full hash/reference validation; PG runtime UNKNOWN.
5. Oversize/corrupt/unavailable snapshot must not display partial success. Limits
   checked before aggregation; routes return503 with no summary data. Old event and
   reference corruption covered; foreign direction/resource and auth-before-storage
   checks retained. No SQL mutation or new permission policy.
6. Initial corrupt-hash fixtures violated DB length checks before exercising the
   reader. Corrected only fixtures to a wrong64-character hash; DB constraints and
   application validation unchanged. Initial HTTP assertion included the existing
   shared-shell logout POST. Corrected to check this view's GET filter, absence of
   mutation envelope and actual zero SQL writes; logout remains intact.
7. Initial print split a process card across pages and left a sparse third page.
   Compact print spacing/columns and keep individual cards together. Preserve
   visible filter/page scope and add snapshot UTC time. Mobile screenshot now
   scrolls to top after its focus check so sticky shell is captured at correct position.
8. Source uses **U01–U09** for regularization, while L is an exit-visa type. Corrected
   current coverage wording to V/W/R/U; historical handoffs/reports remain unchanged.

## Verification boundaries

Initial isolated run: **111 passed /4 failed /3 warnings /175.29s**; failures were
three fixture setup constraints and one overbroad shared-shell assertion above.
Both new browser widths and previous application browser flows passed in that run.
Final corrected checks, visual inspection and immutable Git-copy identity are
recorded in the final handoff. Python compilation, whitespace and protocol structure
checked separately. No new dependency, model, migration, client message or env change.

Approval of this local STANDARD view does not approve E6-01A storage for production.
Existing independent review/audit/PG16 gates, business access/privacy decisions and
full V/W/R/U workflows remain outstanding. Full suite/traps/build not rerun solely
for this view; known date baseline is not converted to PASS.

## Final local verdict

**SELF_REVIEW PASS for STANDARD local target**, not independent approval. Corrected
feature49 passed /75.28s. Final code f923a446449bc8010a4a78d09a192d0156315d71:
related regression **120 passed /3 warnings /184.11s**. Cold imports all exit0;
Git/worktree/copy16/16 hashes match. All4 final synthetic print pages and mobile
screen inspected; five-page progress PDF inspected and26 headings verified.
No application-code changes after this final run. Remaining gates above unchanged.
