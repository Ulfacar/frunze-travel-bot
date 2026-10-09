# Review packet — E5-04B

- CRITICAL / solo, local target; base `ccc6e038b75448750f23681261e2b3a6d015881b`.
- Target: E5-04B uncommitted snapshot, branch `fix/tours-search-quality`.
- Independent reviewer / final auditor UNKNOWN. Builder SELF_REVIEW below is not approval.

Read `ai/tasks/2026-10-09-e5-04b-review-card.md` and actual diff before builder findings.
Inspect `app/domain/qualification_card.py`, `app/admin/kg_review_card.py`, route in
`kg_entry.py`, both KG templates, new HTTP/domain tests and browser extension.
Sources: original PDF physical p29 §3.4 and p88 Б.4, directly re-read in this turn;
derived §Б.6 is context, new escalation computation is not in this change.

## Challenge the implementation

- Named full-admin before DB both via HTTP and direct domain call. Verify a normal visa
  owner is still denied; query/body/source ids do not grant access.
- Join case/product, visa direction, contact binding to selected qualification; absence
  does not silently switch to latest. Corrupt snapshots, sources/import/history fail closed.
- Older answers/report are pinned, current case owner is explicitly current. Latest
  notice is observational at read time, not a lock against future changes.
- No domain INSERT/UPDATE/DELETE during read/reload. No tasks/messages/assignments.
- All facts escaped. No dynamic exception text in response/log. No-store and no-referrer.
- Missing/unknown/false/NA, partial lists of specialist documents, conditional F1,
  B8/D3/D4 gaps, unresolved legal calculations. No unsupported readiness assertion.
- Mobile/desktop native navigation without JS, print hides shell and preserves caveats.

Permitted: read-only review and isolated local synthetic tests. No production/data
transfers/messages/paid services. New permission policy is pending the owner's answer.

## Builder SELF_REVIEW — same author/context

Separate pass over requirements, new domain/HTTP code, formatting and actual template.
No independent verdict claimed. Findings addressed:

1. Partial profile completeness is not full PDF 3.4 completeness: A5/G1 and specialist
   decision remain, F1 is conditional; no "handoff completed" status is inferred.
2. Existing specialist facts must be visible, not only a "present" label: read-only
   human labels show lists and their completeness, unknown/null and false separately.
3. Shared contact profile remains explicit; route provides case context, not persisted
   applicant association. Current owner does not pretend to be historic snapshot owner.
4. First new test failed because substring `F1` matched the global color `#F1F5F9`;
   changed assertion to the actual requirement label `(F1)`, without changing behavior.
5. Initial printed demo used 3 pages with a mostly empty final page; compact print-only
   spacing gives 2 pages for this fixture. Both final PDF pages visually inspected.

Evidence pointers: task/handoff E5-04B. Relevant suite 170 passed before the final
specialist-facts display addition; final new tests 30 passed, final browser 1 passed.
PG runtime, independent review/audit remain UNKNOWN. Full suite/traps not rerun in this
read-only slice; prior failure baselines must not be represented as current green gates.
