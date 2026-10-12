# HANDOFF: 2026-10-12 22:12 — connected personal qualification

- STATUS: DONE for reviewed local E6-28 / fixed C05 technical scope.
- CLASS / MODE: CRITICAL / solo; target: reviewed local change.
- Task: `ai/tasks/2026-10-12-e6-28-connected-qualification.md`.
- Branch: `fix/tours-search-quality`; base `30b12b1097ddbd8c74a2d54bf38cec1a98647553`.
- Candidate: `runs/e6-28-r9`, 15 scoped runtime/test files. Code revision
  `9bd6e926d4649b4d57152e0ce07491353767bc7f`; all 15 root/index/commit identities
  equal R9. Evidence: `ai/reviews/2026-10-12-e6-28-snapshot-evidence.json`.

## Outcome

Added a protected read-only RU/EN assessment for an individual applicant. It
combines the current profile, same-passport personal stay history, complete
ACKed interview, all 18 competing source regimes, registration and whole-trip
arithmetic under one locked transaction. A separately approved versioned server
policy can select NO_VISA for the supported adult ordinary-passport individual
tourism plan abroad. Unknown/manual applicability, unsafe facts, registration
obligations, overflow, small margin, stale inputs or withdrawn authority return
explicit specialist reasons. Real policies remain empty.

The original route-candidate APIs, interview receipts and pure arithmetic are
unchanged. Publication's internal read only gains an optional already-sampled
timestamp; its default behavior is preserved. No calculation is saved against
the payer, no admission guarantee/quote/actual registration deadline follows.
The native page rejects client-supplied authority and distinguishes internal
counts from permission to enter or charge. General CRM UI changes are preserved
outside the 15-file scope.

## Evidence

Windows Python3.12, env-free Git archives, synthetic approved source-shaped
fixtures and synthetic records; actual loopback PostgreSQL16.15 and Chromium.
The real 208 draft units were not approved. Commands and exact per-test outcomes
are retained in the snapshot evidence and the independent reports.

| Scope / command | Result | Exact mapping / limit |
|---|---|---|
| R8 `python -m pytest tests/test_connected_qualification.py tests/test_approved_qualification.py tests/test_approved_qualification_conditions.py tests/test_approved_qualification_source_integrity.py tests/test_approved_qualification_legacy.py -q --junitxml=runs/e628-r8-core-compat.xml` | 54 PASS, 601.34s | R8/R9 runtime identical; includes 17 connected cases and 37 old-route/condition/source/legacy cases. |
| R7 `tests/test_connected_qualification_postgres.py` in combined native/PG run | 5 actual PG PASS | Observed real writer lock waits for profile/history/interview/publication withdrawal/review. R8 adds only earlier specific registration refusal on other branches. |
| R9 `python -m pytest tests/test_admin_kg_assessment.py tests/browser_kg_assessment.py -x -q --junitxml=runs/e628-r9-native-browser.xml` | 5 PASS, 127.27s | Native access, no-store error, schema mapping; actual RU390 dark and EN1365 light no-JS flows, keyboard/overflow/contrast >=4.5, publication withdrawal; both PDFs exactly one page and visually checked. |
| Independent reviewer R7 controls + R8 registration + R8 complete in-KG | 7 + 3 + 1 PASS | Separate own executions. Adverse personal histories, correction/restore/withdrawal, material profile facts, blocked MDA exemption/default UZB obligation; complete in-KG profile gets scope referral. |
| Separate auditor actual PG | 5 distinct scenarios PASS | Full authority/manual coverage, default publication clock/no writes, mid-trip source expiry, exact margin4/3, raw corruption and restoration. Own initial harness failure preserved. |

These overlapping runs are not summed or represented as a final whole-project
suite. R5/R6 earlier builder10+10 passes remain scoped to their snapshots. R1–R4
fixture failures occurred before assessment. R7 combined run had 5PASS/1FAIL:
the native assertion incorrectly rejected the shared logout form; the corrected
assertion inspects main content, and R9 passes. Reviewer reproduced genuine
purpose-detail and nested-ban-date false positives in R5; explicit pinned
profile mapping fixes them and independent controls pass. Auditor initially
reused a case-scoped interview key; only its fixture was corrected before the
two-case narrow passing rerun.

## Review and criterion boundary

Independent `/root/calculation_review` APPROVE:
`ai/reviews/2026-10-12-connected-qualification-independent-review.md`.
Separate final `/root/e622_audit` report:
`ai/reviews/2026-10-12-e6-28-final-audit.md`: GO, exact 15 root/R9 identities
independently rechecked and final independent APPROVE reconciled.
Pre-audit: `ai/reviews/2026-10-12-e6-28-pre-audit.md`.

The reviewer explicitly evaluated unchanged fixed C05 against the chosen
matrix: this is substantive regime selection after full competing applicability,
not a renamed candidate or always-referral service. C05 technical acceptance
is closed with the separate final audit. It does not require automatic
selection of every visa product. B selection, USA45 alternative-product
selection and all B.8/J01/J02 golden workflows remain open. In-KG cases receive
specialist referral; this does not implement actual-entry deadline approval.

## Remaining work and resume

Continue E6-29/H02 under its independent pre-audit, then J01/J02/J03 and concrete
owner acceptance J05. No production deployment, real source/business approval,
channel activation, remote push or outbound message happened in E6-28.
Local PostgreSQL55971 remains running for isolated checks. The old synthetic
CRM preview8765 is preserved; this task did not replace its DB/server.
