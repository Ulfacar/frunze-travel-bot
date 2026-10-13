# TASK — E6-02C issued-document verification and actual delivery/travel facts

- CRITICAL / solo; local implementation/checks plus independent-review packet.
- Base `8e9ab4f`; parent70-point goal remains ACTIVE (42/100 technical points).
- Source PDF §§16.1–16.5,17 (passport change/error),18. Criterion E07.
- Reuse registered applicants/application attempts and metadata-only evidence.
  No real files/names/numbers, client sending, legal decisions or financial policy.

## Observable acceptance

An approved visa attempt has separate immutable issued-file versions, explicit
12-field comparison against passport/order/route, error/correction records,
actual delivery through each channel, copy/pamphlet evidence and client receipt.
Receipt is never inferred from sending. Replacement/passport changes invalidate
old verification without rewriting past facts. Actual entry/exit needs dated
stamp/official-record evidence; planned dates cannot become actual events. Facts
remain recordable even if the traveler acted before internal checks were complete;
the system shows missing verification rather than falsifying travel history.
None of these facts alone grants legal travel permission or completes the service.

Native per-application forms/history/print, same full-admin/OFF/write gates;
strict typed input, CAS, exact retry and atomic append. No silent cross-case links.
Existing intake/checklist events are not overwritten by post-issue facts.

## Risk pre-audit

- Wrong person/attempt: composite scope FKs, locked application, existing event
  chain validation; file and passport fingerprints bound to each review.
- Stale verification: current file version and passport binding required; new
  contents/changed passport cannot inherit old approval or delivery readiness.
- False completion: separate reviewed/delivered/received/actual-travel facts;
  no automatic ServiceCase, money, client messaging or legal permission changes.
- Fraud/integrity: source fingerprint and actual dates, explicit confirmation,
  hash/semantic replay, immutable bounded history, default refusal on corruption.
- Ordering/retry: CAS, request-content identity, duplicate proof detection;
  factual travel backfill must not invent chronology or infer a missing event.
- Migration: additive table only; scoped constraints and populated/offline
  downgrade refusal; no production backfill or destructive experiments.
- UI: server checks before writes, actor/session/action/version-bound signature,
  no sensitive logging, recovery from uncertain commit, mobile/no-JS/print.

Independent critical review/audit and PostgreSQL verification remain required.
Without them local slice stays PARTIALLY_READY. Continue useful goal work; do not
self-certify a release or call42 points70.
