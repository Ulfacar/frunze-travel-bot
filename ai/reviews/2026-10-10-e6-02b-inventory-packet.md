# E6-02B — review packet / SELF_REVIEW

- Requirement: source PDF §§5/6/14/18/19; task
  `ai/tasks/2026-10-10-e6-02b-document-inventory.md`.
- CRITICAL / solo. Completion target: local implementation and review packet.
- Builder and this reviewer are the same context. Independent review and final
  audit are **UNKNOWN**. Local slice **PARTIALLY_READY**; no production release.

## Actual change inspected

`EntryDocumentRevision`, additive `e6_documents_0018`, pure metadata reducer,
owned transaction service and native case/application forms. No files or actual
personal data. Existing full-admin/OFF/write gates remain. Source definitions
are pinned per inventory; they remain draft and incomplete for whole-package use.

## Challenges and outcome

- Receipt must not mean approval: received/checked/correction/withdrawn separated;
  summary always says package not accepted and submission not allowed.
- Stale acceptance: version+SHA256 and passport epoch bind review. Replacement
  clears own check and passport changes invalidate earlier checks across items.
  Historical revisions remain unchanged and readable without today's catalog.
- Scope/permission: authorization precedes data access; composite FKs bind case,
  application and predecessor; URL/form identifiers and actor/session are signed.
- Atomicity: application parent locks serialize writes and shared read validation;
  SQLite begins a physical transaction. CAS and same-key payload identity prevent
  duplicates. Actual committed-but-unacknowledged HTTP retry is tested.
- Audit: complete bounded chain and hashes plus semantic reducer replay. Tests
  reject both raw corruption and a forged snapshot with a recomputed snapshot hash.
  This is not cryptographic protection against a database administrator replacing
  the entire command chain or deleting its suffix.
- Migration: populated and offline downgrade refused; real SQLite FK constraints
  tested. PostgreSQL DDL only; local Docker engine unavailable, runtime UNKNOWN.
- UI: mobile390/desktop1365 without JavaScript, print3 pages, GET performs no SQL
  mutations, bounded strict POST/query fields, accessible labels/focus and safe
  error recovery. SELF_REVIEW found passport reason reset on validation error:
  fixed selected option preservation and added a regression scenario.

## Observed precommit evidence

- Working snapshot `runs/e6-02b-inventory-worktree` (base archive `f0d9efa` with
  explicit changed files; env absent): domain14 PASS; migration/HTTP/foundation
  73 PASS /2 PG SKIP; browser2 PASS. Additional negative domain4 PASS.
- Mobile screenshot and all3 printed pages visually inspected. Text extraction
  preserves not-accepted, recheck, revision, history and checksum labels.
- Final exact-commit related regression and snapshot identity are recorded in the
  ensuing handoff; this packet does not invent their outcome in advance.

## Remaining gates

Independent critical review/audit and PostgreSQL concurrency/recovery remain
UNKNOWN. Real-data policy DEC-06 and approved executable checklist/process rules
remain unresolved. Full supplements, package evidence, file adapter and downstream
workflow are separate work. No tests here establish legal/portal acceptance.

Next reviewer should inspect requirement and diff, then challenge corruption,
transaction ordering, duplicate/uncertain commits and schema downgrade. Continue
the active70-point goal after this checkpoint; do not call the whole PDF complete.
