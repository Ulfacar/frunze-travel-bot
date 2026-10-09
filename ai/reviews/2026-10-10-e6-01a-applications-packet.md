# REVIEW PACKET — E6-01A applications

- Base `208a04d95a54ca0da9535bdeab5a81fdfcc7b15f`, `fix/tours-search-quality`.
- CRITICAL / solo; local implementation + review packet, **PARTIALLY_READY**.
- Codex builder and same-context **SELF_REVIEW**. Independent reviewer/auditor UNKNOWN.
- Assessment before builder conclusions: NO. This packet is not independent approval.
- Final code commit, exact Git-copy evidence and report: handoff linked from `ai/STATE.md`.

Read task `ai/tasks/2026-10-09-e6-01a-applications.md`, original PDF §§14.1/14.3/18.3/18.8
and contract `docs/e6-01a-applications.md` before builder conclusions. Review actual
models, migration, domain operations, form envelope, route and template; no real data
or external services are needed. Do not infer a published workflow from shared statuses.

## Challenge criteria

1. Contact/payer is not automatically an applicant. Applicant belongs to case; attempt
   belongs to the same case/person/procedure as its previous attempt. DB composite FKs,
   API checks and guessed-ID denials must agree, including two cases of one contact.
2. Correction returns to submitted on the SAME attempt. Retry after refusal/CRM closure
   creates a NEW linked attempt, never a branch or a continuation after approval.
   An independent new procedure starts its own attempt chain. Other cases, applicants,
   applications, qualification snapshots and commercial service state do not change.
3. Actor is a named full administrator; gates precede domain access. No role expansion.
   CSRF/HMAC bind session, actor, case, action, target, revision and nonce. Wrong form,
   cross-session/case, duplicate keys, unknown fields and excessive body are rejected.
4. Actual dates cannot move backward after first recorded fact or into the future.
   Draft creation date does not prohibit historical factual capture. Operator source
   and explicit confirmation are required; a client statement cannot approve a visa.
5. Eight-character e-Visa reference is globally unique and immutable for an attempt.
   Resubmission preserves it; new attempt cannot silently inherit/reuse it. Cross-case
   collision error does not expose another applicant/application identifier.
6. Transactions own commit/rollback. Retry returns original operation result before
   checking stale revision; changed same-key payload conflicts. CAS/unique constraints
   protect simultaneous changes. Lost commit acknowledgement preserves same form/key.
7. Immutable metadata/events and reference projection are verified on reads. ORM and
   bulk mutation rejected; corruption cannot produce a claimed clean status or append.
   GET emits no SQL write, bounded pagination does not silently truncate applications.
8. Additive migration matches models and enforces composite FKs/uniqueness. Empty
   downgrade cycle preserves old tables, populated downgrade refuses before any drop,
   writers held out across empty check/drop. Offline downgrade refuses. PG execution
   still requires separate runtime evidence; compiled DDL is not that evidence.
9. Native mobile390/desktop1365 without JS, errors/empty/retry states, focus, print.
   Print must include people even if their on-screen details element is collapsed.
10. No names, passport numbers/scans, live imports, payment/refund effects, portal
    submission, automatic deadline, customer messages or publication of V/W/R/L rules.

## Findings / fixes — SELF_REVIEW

| Finding | Fix / evidence |
|---|---|
| Concurrent duplicate first submission could read old events and then a newly committed reference | Explicit SQLite BEGIN before reads; PostgreSQL shared/exclusive parent locks. Duplicate/conflicting writes and concurrent read/write tests pass |
| Previous test fixture did not enable SQLite FK enforcement | New domain tests enable foreign_keys on connections; migration test runs real operations with FK ON; raw negative FK/unique tests include two cases sharing one contact |
| Empty downgrade count check alone could race with an insertion | Hold PostgreSQL table locks / SQLite write reservation across check and drops. Local empty/populated tests pass; PG runtime remains UNKNOWN |
| Legacy exact schema list did not include the four new tables | Added their exact names, retaining equality and all previous table checks; new migration parity/constraint tests independently cover them |
| Approval label implied possession of the issued document | Changed to «Одобрено»; interface explicitly leaves document review/delivery unconfirmed |
| Printing hid forms but left empty section headings | Hide whole action sections in print |
| Closed details contents remained hidden by Chromium in print despite CSS | Dedicated print-only applicant list, screen-reader-safe display:none in screen CSS; browser verifies both people in print |

Initial domain run: 33 pass / 1 concurrency fail. After transaction fix domain/migration
37 pass. Native HTTP28 pass. Combined domain/migration/HTTP/browser70 pass before final
FK/downgrade/print refinements. Subsequent foundation/FK/browser run52 pass/2 PG skips/
1 print failure; final print fix and final committed-copy evidence are recorded in
handoff. Do not report these worktree snapshots as an all-green final repository suite.

## Release boundary / known gaps

Numbered placeholders only: no approved privacy policy, real person identity, role
correction/merge, applicant-specific qualification/history, reference correction,
full source exception reasons, aggregate case status or all procedural guards.
Common manual facts do not implement four complete workflows. Independent critical
review/final audit, PG16 concurrency and explicit production release remain open.
Working-branch commit/push is authorized; production migrations/env/real data/messages
are not performed. Existing full-suite date failure/traps baseline is historical until
the final run is recorded; never label unknown verification as passed.
