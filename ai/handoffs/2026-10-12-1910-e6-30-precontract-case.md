# HANDOFF: 2026-10-12 19:10 UTC — preliminary case and same-case contract

- STATUS: DONE — independent APPROVE and separate GO.
- CLASS / MODE: CRITICAL / solo.
- Task: `ai/tasks/2026-10-13-e6-30-precontract-case.md`.
- Branch: `fix/tours-search-quality`; base `7b45f6c56c22adef80a3f4e79aa1aae8d7a3fe0d`.
- Target: reviewed local change; exact code `d57cb059bbe78ca832478eee52cc83cc8738c597`,16 scoped files matching reviewed R12/index. Not release.

## Outcome

A visa conversation can explicitly open an unsigned commercial case, create its
own applicant/application, save and reload the person's intake, save an internal
estimate, then record an already signed contract in the same case. No duplicate
case/person/task is created by an exact retry. No legal clearance, consent,
client-facing offer, invoice or payment is inferred from these operations.

The additive0038 `ServiceCaseOpening` receipt preserves the opening command and
original workflow/event. Existing signing keys and legacy `sign_contract` are
unchanged. The new signature retains a separate immutable command/result in a
compatible `contract_signed` payload. It requires the original commercial first
stage, exact current revision, current access and an active product. Historical
exact retries survive workflow replacement, owner and price correction, later
stage movement and product archive without reverting those current facts.

Native forms bind actor/session/action/target/key/revision/owner through existing
HMAC/CSRF conventions. Controlled errors preserve the original command; current
route/case rights remain required. Saved contracts show their actual reference and
current agreed money instead of an empty disabled form. Canonical actor identity
is explicitly required before writes, consistent with the native auth adapter.

## Evidence

All commands ran in env-free Git archives on Windows/Python3.12 with synthetic
SQLite or isolated PostgreSQL16.15 loopback55971; no root `.env` imports. Runs
overlap and are separately mapped in
`ai/reviews/2026-10-13-e6-30-snapshot-evidence.json`, not one whole-project suite.

| Scenario / command | Snapshot | Result and limits |
| --- | --- | --- |
| New domain/native plus actual PG concurrent open/sign, sign vs owner/stage/money and migration | R4 |33PASS33.57s |
| Legacy contract/service/money/workday plus new native continuity | R5 |305PASS,4optionalPGSKIP,1FAIL142.58s. Static migration inventory omitted three already-existing C tables and new0038 table; corrected explicit inventory passes R7. |
| Actual loopback browser390dark/1365light, both noJS | R5 |1PASS18.57s, but visual inspection identified confusing empty signed form; corrected R7. |
| Three original independent repros and new domain/native/PG | R6 |39PASS,1FAIL48.73s. COPY restore assertions succeeded but test artifact write lacked runs directory; fixed fixture R7, original FAIL retained. |
| Corrected recovery, migration inventory, actual native own applicant/profile save/reload/internal quote→same-case signature, original repros and browser | R7 |16PASS41.98s. All six final screenshots visually inspected by root: PASS. Form printing N/A: this scope has no export/report action. |
| Revised owner/revision evidence and native/domain | R8 |33PASS25.55s |
| Opening-receipt invariant extension | R9 |20FAIL15PASS28.10s: builder incorrectly expected empty reason on original case_opened, whose established value is NULL. Corrected to NULL; no existing event rewrite. |
| Final opening/domain/native +10actualPG including full binaryCOPY recovery | R10 |45PASS48.75s |
| Final canonical actor rejection + integrity/native controls | R11 |18PASS20.27s |
| Four formerly skipped legacy contract PG races/migration | R11 |4PASS6.20s, isolated scratch DB and test-owned schemas; all four prior skipped identities executed. |

Recovery is explicitly all-public-table binary COPY plus fresh Alembic schema,
FK-enabled restore and sequence restoration, not native pg_dump. It verified
legacy contract preservation, exact opening/signature retries and a new write
after restoration. Populated downgrade is refused; empty0038 downgrade/upgrade
and model/table parity pass. No live migration or production backup is claimed.

Independent original findings are retained: stale owner lookup blocked an exact
historical open; corrupt signed payload produced500; altered event stage was
accepted; rehashed impossible signature revision/owner shape was accepted; a
noncanonical caller actor could commit unusable opening evidence. Fixes have
targeted positive and negative controls; review reports identify their own runs.

## Reviews and remaining gates

Independent reviewer `calculation_review` returned APPROVE; separate auditor
`e622_audit` returned GO for exact R12/index. Reports:
`ai/reviews/2026-10-13-e6-30-independent-review.md` and
`ai/reviews/2026-10-13-e6-30-final-audit.md`. Own reviewer13PASS; auditor6PASS
including3actualPG plus final5PASS. R12 differs from tested R11 only by one test
EOF blank-line removal; all16 root/index/commit identities verified. Full PDF
remains96/100 with J01/J02/J03/J05 UNKNOWN; E630A alone does not close those criteria.

No deployment, remote push, live client message, source/tariff approval or pilot.
Preserved unrelated UI base/boards/readability changes and untracked user files;
the old CRM8765 preview remains unchanged. Browser snapshots include the user's
preserved styling as context, excluded from the16-file implementation scope.

## Next action

E630A is saved as the exact reviewed local commit. Continue E630B connecting explicitly
authorized specialist decisions to the same person's internal quote; its separate
source-first pre-audit is complete at `ai/reviews/2026-10-13-e6-30b-pre-audit.md`,
with task `ai/tasks/2026-10-13-e6-30b-specialist-quote.md`. Remaining fourteen SOP and three exact Б.8
examples must exercise actual entry points before J01/J02 can be assessed. Real
business/source approvals and authorized pilot remain owner gates.
