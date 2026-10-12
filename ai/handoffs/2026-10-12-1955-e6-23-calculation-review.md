# HANDOFF: E6-23 — calculation and retained arithmetic review

- STATUS: DONE for reviewed local C01/C02/C03; full PDF remains PARTIALLY_READY.
- CLASS / MODE: CRITICAL / solo. Task: `ai/tasks/2026-10-12-e6-23-calculation-review.md`.
- Branch: fix/tours-search-quality. Source identity87ad9e759aae223258742d286310aba2155f112d; arithmetic/storage unchanged from8062f80. No runtime changes were required.
- Completion target: reviewed local behavior, without release or real legal approval.

Independent reviewer `/root/calculation_review` ran246 scoped arithmetic/calendar/storage/migration checks, one120-case open-history oracle, and31 actual local PostgreSQL checks:278PASS. Separate final auditor `/root/publication_review` ran12 bounded SQLite/oracle checks (including64 closed-history vectors and40 work-calendar vectors) and5 actual PostgreSQL cases:17PASS. These are separate, overlapping evidence sets, not a new whole-repository suite.

The auditor verified14 relevant files unchanged across8062f80/87ad/current source and11 relevant model/hook sections, original94-page PDF SHA-256 and four source-fragment hashes. Detailed commands, identities, original archive locations and limits are in:

- `ai/reviews/2026-10-12-calculation-independent-review.md` — APPROVE.
- `ai/reviews/2026-10-12-calculation-final-audit.md` — GO.

Evidence covers rolling-window interval union, incomplete/uncertain history, custom work calendars, immutable source/history/calendar pins, CAS/idempotency, rollback, lost commit acknowledgment and retained arithmetic replay. All runtime data was synthetic in env-free archives; PostgreSQL16 was explicitly confined to127.0.0.1:55971 and disposable fixture databases.

C01/C02/C03 review fields are nowPASS in the fixed50-criterion ledger. Definitions and engineering points are unchanged. The remaining individual-applicant history/qualification bridge is outside this review. Actual source/calendar/counting policies, production recovery, deployment and pilot acceptance remain unapproved. No remote push, production operation or external message occurred.

Next: continue E6-22 qualification boundary and E6-24 independent source/profile review. A later confirmed intake numeric-count defect belongs to E6-24; it does not modify these arithmetic files or their scopedGO.
