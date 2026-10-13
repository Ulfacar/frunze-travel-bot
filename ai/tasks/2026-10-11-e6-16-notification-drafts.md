# E6-16 — policy-gated persistent notification drafts

CRITICAL / solo. Completion target: independently reviewed LOCAL synthetic
draft persistence, not outbound delivery. Parent overnight scope/no-deploy
authorization and08:00 Asia/Almaty deadline apply. Candidate I02 only; no points yet.

## Gap and bounded proposal for pre-audit

Appendix A currently has a typed, source-pinned read-only template preview.
An operator cannot preserve a draft with an exact application, source version,
explicit authority and deduplicated confirmation. Add a separate immutable
notification-draft journal. Do not enqueue into the existing sending outbox,
call adapters, choose a recipient, mark a message sent, or invent release policy.

- Existing full-admin/KG/workday/write gates and application/applicant/case scope.
  Server-side draft-storage policy defaults empty: explicit operators, finite
  validity, catalog digest, privacy/source proof references, permitted templates.
  This grants storage of a draft only, never legal/text approval or sending.
- Native application page: select a source template, fill existing typed slots,
  preview and explicitly save. Unknown/conditional placeholders and blocked
  source marks remain visible. Text is always escaped and never interpreted.
  No freeform destination, arbitrary template body, attachments, payment or FX.
- An additive immutable table stores case/applicant/application, source/template
  pins and retained catalog rendering version, exact typed command/result,
  policy snapshot, creator and server timestamp. Strict bounded JSON and total
  per-application history prevent unbounded reads. Full history validation and
  semantic reproduction detect corruption; no claim against complete DB forgery.
- CAS revisions and per-application request-key identity; exact lost-commit retry
  returns original receipt after policy expiry/removal but still checks current
  full-admin authority. Same-key changed input or identity fails. Serialization
  under the existing case/application lock precedes limit/policy/day checks.
- New rows never modify source, interview, quote, application decision, money,
  message/outbox or task state. The journal is a draft artifact, not an automatic
  bridge or notification worker. Later text changes create new revisions.
- Retain old catalog/rendering semantics for historical reads and exact retries.
  Current source/policy mismatch blocks new saves, not old valid receipts.
  Explicitly render current authority/source readiness separately from history.

## Required evidence

Independent pre-audit before runtime implementation, review and separate final
audit. Domain/native negative checks: current identity/scope/policy, stale preview,
source drift, invalid/duplicate/oversize/Unicode form fields, wrong applicant,
immutable history, semantic tamper, bounded reads, policy/day change during lock,
atomic rollback, before/after-commit ambiguity, concurrent same/different requests.
Actual local PostgreSQL schema/FKs/concurrency/recovery; SQLite/model parity and
safe empty migration cycle/populated refusal. Browser mobile/no-JS/all print pages.
Verify no provider/network/message/outbox side effects and default OFF behavior.

## Status

Independent pre-audit GO: `ai/reviews/2026-10-11-e6-16-pre-audit.md`.
Implementation exists in an uncommitted local snapshot. Preliminary development
SQLite/domain/native/legacy-template checks:103 PASS/1 dependency warning.
Actual PostgreSQL, browser and frozen-snapshot independent review/audit pending.
No I02 credit yet. Actual source/privacy approval, recipients, releases and
message transmission remain owner decisions.

Independent r1 findings: Unicode envelope expansion made a valid preview
unsavable; long print middle pages lost draft/source context; escaped SQL JSON
capacity accounting could make successful appends unreadable. Root fixes preserve
Unicode in signed values, use repeated print margin context, and separate the
conservative serialized-text prefetch guard from exact canonical UTF-8 budgets.
Original failure evidence remains preserved. Targeted Unicode native2 PASS,
capacity SQLite+actualPG2 PASS, long no-JS browser/every-page markers1 PASS before
the final r3 freeze. Full final checks and independent re-review/audit still needed.
