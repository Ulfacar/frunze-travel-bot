# E6-16 — persistent internal notification drafts

DONE for reviewed local synthetic target. CRITICAL / solo. Code
`4fcf694d8d7586ec969126e411359d43c345c63d`, saved and pushed only to
`origin fix/tours-search-quality`. User forbids deployment; no actual message,
recipient, real source/storage policy, live migration or activation occurred.

The source's13 templates now have a separate immutable application-scoped draft
journal, additive migration0032, explicit default-empty storage authority,
retained versioned renderer/catalog, exact source/event pins, CAS and request-key
dedup. Native preview/confirmation/save/history/print preserve manual-unverified,
source blockers, unresolved placeholders and false publication/send flags.
Expired/removed policy and a later current renderer cannot destroy old receipts
or exact retries. Later application events change the current readiness overlay,
not the historical draft. This is internal draft storage, not an outbound queue.

## Evidence

Frozen `runs/e6-16-review-r3`, basefca93ad;23-file LF manifest
`ai/reviews/2026-10-11-e6-16-snapshot-r3.json`, SHA256
`627f6bf0079f85b381ca5eb1b7ef3c6ee5aa8b0713af71d2e810db04470d5253`.
All23 root/archive/commit identities, AST parsing, four cold imports, scoped
secret-shape scan and staged whitespace checks PASS. Environment-free Windows
Python3.12, synthetic FK SQLite, Chromium and isolated loopback PostgreSQL16.15.

Builder combined command in the frozen tree, with the guarded private local PG
fixture configured (connection values never recorded):

```text
python -m pytest tests/test_entry_notifications.py tests/test_admin_kg_notifications.py tests/test_entry_notification_migration.py tests/test_entry_notification_postgres.py tests/browser_kg_notifications.py tests/test_kg_template_preview.py tests/test_admin_kg_templates.py -q --tb=short --basetemp=runs/notification-r3-tmp --junitxml=runs/notification-r3.xml
137 PASS /3 deprecation warnings /456.83s; no skips or failures.
```

JUnit hash/counters: `ai/reviews/2026-10-11-e6-16-runtime-evidence.json`.
The earlier r1/r2 failures remain preserved: valid long Unicode could fail native
confirmation, SQL escaped-text limits disagreed with canonical UTF-8 append
limits, and intermediate print pages lost draft/source context. All three were
fixed and retested with the original independent probes. The SQL materialization
guard is now a separate conservative character bound, followed by exact canonical
byte limits. Valid Unicode accepted writes stay readable; the next over-limit
write is refused before commit. Native CSS page-margin context repeats on every
page, with space reserved for it.

Independent implementation review APPROVE:
`ai/reviews/2026-10-11-e6-16-independent-review.md`;106 core,30 actualPG,
four original/default-limit/live-v2 probes and three browser/print checks PASS.
Separate final audit GO: `ai/reviews/2026-10-11-e6-16-final-audit.md`;
147 ownPASS (106 core +33 actualPG +8 own/native/browser). Counts overlap with
builder/reviewer suites and are not additive project coverage.

Actual binary COPY recovery into a fresh Alembic schema covers56 tables,
16 populated, restored old receipts/exact retry/new revision/native read and FK/
sequence checks. Native pg_dump remains blocked by Windows App Control4551;
this is not PITR or production-backup proof. No security settings were changed.

Builder visually inspected all four pages of the final one-page A06 and
three-page long A07 PDFs plus mobile390 and desktop1365/no-JS states. Independent
auditor also inspected all four pages of its own long print. A separate LIGHT
label-only polish `b8114c3` replaces the chooser's `none` caption with the existing
source title. Two unchanged native browser cases PASS/35.02s in the env-free
`runs/e616-label-polish` copy (base214d88f); final mobile screenshot inspected.
This one-line cosmetic delta is separate from the critical r3 manifest.

Additional regression was interrupted once for memory pressure; that interruption
is not PASS. Replacement exact-r3 regression completed252PASS/2 optional generic
PostgreSQL SKIP/1 warning/591.35s. The notification actual-PG tests above did run.
Command: `python -m pytest tests/test_entry_quotes.py tests/test_admin_kg_quotes.py
tests/test_entry_applications.py tests/test_admin_kg_applications.py
tests/test_alembic_domain_migration.py tests/test_service_cases.py
tests/test_knowledge_publication.py tests/test_entry_interviews.py -q --tb=short
--basetemp=runs/notification-r3-regression2-tmp
--junitxml=runs/notification-r3-regression2.xml`. No whole-final-code full-suite
green claim.

## Score and next action

I02 earns1point after exact-source identity, independent APPROVE and GO:90/100
technical points,10 remaining; frozen criterion definitions are unchanged.
Remaining C05/H02/H03/J01/J02/J03/J05 concern approved-rule qualification/answers,
complete dialogue and connected source scenarios, remaining critical reviews and
owner acceptance. Real source text, prices, privacy/storage authority and pilot
approval remain separate. Continue E6-17/E6-18 integrity checks and final local
regression/report; save and send only the user's authorized final Telegram status.

Five-page report `docs/reports/frunze-pdf-progress-2026-10-11-notification-drafts.pdf`
was inspected on all five pages:26 source sections,90/10 fixed score, exact code
and check limitations. SHA256
`93929a7226da299b6396128c6c216454256fc3574b144bf2e472ffed79c6a020`.
It records the current checkpoint; later completed checks belong to later evidence.
