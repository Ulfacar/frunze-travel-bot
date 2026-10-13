# HANDOFF: 2026-10-12-1915 — publication withdrawal and historical integrity

- STATUS: DONE for reviewed local E6-22A; full PDF remains PARTIALLY_READY.
- CLASS / MODE: CRITICAL / solo.
- Task: `ai/tasks/2026-10-12-e6-22a-publication-recovery.md`.
- Branch / code: `fix/tours-search-quality`, `87ad9e759aae223258742d286310aba2155f112d`.
- Completion target: reviewed local correction, no release.

## Outcome and files

Independent review of the existing publication boundary found that a new backdated/equal-time decision could invalidate historical approval manifests, and a full journal prevented withdrawal. Corrected both time directions under the existing set/version locks, preserving original receipts before current-time validation. New normal histories reserve one event and 4MiB for withdrawal; valid old 250-record/16MiB histories can append one bounded terminal withdrawal. Reader and database bounds enforce the recovery limit.

Native withdrawal keeps a bounded selection while signing the entire manifest. The domain resolves the original immutable list before retry comparison, so a delayed retry after a later reactivation preserves that new active publication. The form explicitly confirms withdrawal of the entire publication, including publications above 100 rules. Migration0034 extends only the publication revision constraint; populated downgrade refuses before mutation.

Runtime extraction into internal session helpers preserves the public knowledge adapter and enables the pending coherent per-person qualifier. No actual rule or source was approved. Real policies remain empty.

## Evidence

Frozen final source: `runs/e6-22a-r5`, base8062f80 plus17 overlays; manifest SHA256 `19cd5114dea64f5533f40b52388454ae69389b750357d937657de778e0004fdf`. The 12 scoped source/test files match root, staged content and final code commit after CRLF normalization; durable map `ai/reviews/2026-10-12-e6-22a-snapshot.json`. The other overlays are preserved UI/config/context work, not part of this correction's commit or approval. No environment file was copied.

| Check | Environment / snapshot | Result and limit |
|---|---|---|
| `python -m pytest tests/test_publication_recovery.py tests/test_admin_publication_recovery.py tests/test_publication_recovery_migration.py tests/test_knowledge_publication.py tests/test_knowledge_decisions.py tests/test_admin_kg_knowledge_publication.py tests/test_knowledge_answers.py tests/test_knowledge_publication_migration.py -q --junitxml=runs/e622a-core-r3.xml` | env-free Windows Python3.12 / synthetic SQLite / r3 | 100 PASS,260.81s. Windows WMI allocation warning at import under parallel test load; Python continued and exited0. Subsequent cold imports passed. |
| Focused correction / actual PostgreSQL | r2, same final decision/model/migration source | 16 SQLite/native/migration PASS;10 actualPG PASS. This is not a full final suite. |
| `python -m pytest tests/browser_publication_recovery.py tests/test_publication_recovery.py::test_server_manifest_resolution_keeps_command_and_scope_pins tests/test_admin_publication_recovery.py::test_native_withdraws_full_101_unit_manifest_using_bounded_selection tests/test_knowledge_decisions_migration.py -q --junitxml=runs/e622a-final-delta-r4.xml` | r4 / SQLite/native/browser | 7 PASS,48.21s. The2 browser cases here used the legacy light appearance despite one dark-system preference; no dark-theme claim from r4. |
| `python -m pytest tests/test_publication_recovery_postgres.py::test_native_delayed_retry tests/test_publication_recovery_postgres.py::test_native_large_publication tests/test_publication_recovery_postgres.py::test_migration_empty_cycle_and_populated_downgrade_refusal -q --junitxml=runs/e622a-pg-final-r4.xml` | r4 / actual isolated PostgreSQL16.15 | 3 PASS,65.45s; final native server-resolved IDs, late retry,101-rule withdrawal and migration preservation. |
| `python -m pytest tests/browser_publication_recovery.py -q --junitxml=runs/e622a-browser-r5.xml` | r5 / loopback Playwright | 2 PASS,25.31s. Actual dark phone390 and light desktop1365 without JS, computed background assertions, no overflow, full-scope confirmation and sole print page visually inspected. |
| Cold imports, compilation, scoped staged whitespace and source identities | env-free r5 / final root and commit | PASS. |

Original evidence retained: independent clock/capacity failures in the review report; builder r1 89PASS/1 failed test assertion (stale revision correctly returned conflict, revised expectation); independent r2 delayed native retry409 reproduced and corrected in r3. Counts overlap; they are not added into a whole-project total.

## Review and remaining gates

- Independent reviewer `/root/publication_review`: APPROVE, `ai/reviews/2026-10-12-publication-independent-review.md`. Own final4 actualPG after-lock clock/CAS probes and5 original/native reproductions passed; earlier scoped import/projection and runtime suites mapped explicitly. D01–D05 now have scoped independent review PASS.
- Separate final auditor `/root/e622_audit`: GO at r5, `ai/reviews/2026-10-12-e6-22a-final-audit.md`. Own51 SQLite/compat+10 actualPG+6 final retry checks PASS; independently verified17/17 snapshot hashes and visually inspected final browser/print. Reviewer concurrency evidence is identified separately.
- Production, actual legal/source approvals and owner acceptance remain UNKNOWN. No deployment, live migration, remote push or message. The earlier permission to save the working branch was used for this local code commit.

## Limits and preserved work

Already-corrupt historical journals are not silently rewritten; a repair would need separate scoped authorization. Migration recovery is synthetic local evidence, not a production backup claim. All208 actual source units remain draft. C05/H02/J01/J02/J03/J05 remain unresolved; closing5 earlier review gaps does not add technical points. The score remains92/100 once this correction is recorded, with16 earlier PASS criteria still lacking a completed review.

The root migration-test adaptation was encountered as an existing unstaged edit of unknown authorship; neither review agent authored it. It was preserved, independently inspected and verified: seed through the current schema required by the new clock guard, downgrade to0023, then retain all original constraint assertions. Adopted into the correction after those checks. Existing uncommitted UI readability/button changes and unfinished qualification policy/config are separate. No full repository suite was rerun.

## Next action

Continue `ai/tasks/2026-10-12-e6-22-approved-qualification.md`. Its pre-audit establishes that a candidate route without individual stay-history arithmetic cannot close C05. Existing contact/payer history must not be reused as applicant evidence. E6-23 independent C01–C03 review is running under `calculation_review`; it has its own task. Keep local PostgreSQL127.0.0.1:55971 running for those synthetic checks, then stop it when no test uses it. Private connection file remains in Temp; never copy credentials. Keep the existing CRM demo at127.0.0.1:8765 available; do not replace its data with these test databases.
