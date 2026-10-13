# E6-22A independent final audit

- Auditor: `/root/e622_audit`; builder and publication reviewer are separate contexts.
- Date: 2026-10-12. CRITICAL / solo. Target: reviewed local correction, no release.
- Requirement: `ai/tasks/2026-10-12-e6-22a-publication-recovery.md`, read from root because the task card is not included in the frozen archive.
- Final source candidate: `runs/e6-22a-r5`, based on `8062f80e89f60c9b42ec74457fd6275bd038e3bd` plus 17 recorded overlays. No environment files. All 17 normalized file hashes independently verified.
- Final snapshot manifest SHA-256: `19cd5114dea64f5533f40b52388454ae69389b750357d937657de778e0004fdf`.
- Verdict: **GO — reviewed local E6-22A publication recovery correction.** No confirmed unresolved defect remains within this scope. This is not a production release approval or whole-PDF completion.

## Findings and resolution

1. Pre-audit found that a publication `review` could still pin a future decision after clock rollback, poisoning historical manifest replay. R2 checks every selected decision against the timestamp sampled under the publication locks, including the `review` action. Independent SQLite and actual PostgreSQL regression checks passed.
2. Pre-audit found decision retry could be rejected by current-date validation before the original receipt lookup. R2 validates shape before I/O and time after duplicate lookup under the locks. Independent SQLite and actual PostgreSQL checks passed, including rollback across the verified date.
3. Pre-audit found native withdrawal could not handle a domain publication above 100 units. The bounded native selection now pins the entire lifecycle manifest by signed hash and CAS; the domain resolves the full list under its write lock. A real 101-unit native withdrawal and immediate retry passed on SQLite and PostgreSQL in R2.
4. **Confirmed R2 defect, fixed in R3:** original native withdrawal returned 409 after a later review replaced the same version's manifest. The auditor's own reproduction produced `303 -> replacement review revision 5 -> exact retry 409`, with the journal remaining at revision 5. The native precheck ran before domain duplicate lookup. R3 permits `unit_ids=None` only for withdrawal; the domain derives IDs from the immutable original command before comparing the complete command hash. New withdrawals derive IDs from the current lifecycle manifest under the same lock. The auditor's R3 test now passes after replacement and reactivation, preserving the new active subset.
5. **R4 browser evidence correction, fixed in R5:** files named `390-dark` initially showed the light theme because system preference alone did not activate the application's new theme. The auditor inspected the images and reported this gap. R5 enables the actual application theme and asserts computed background channels. The corrected dark phone, light desktop and final print images were independently inspected; this issue was with the claimed evidence, not withdrawal behavior.

There are no unresolved source defects identified in the bounded correction after the R3 examination. The separate reviewer's actual PostgreSQL probes described below close the concurrency evidence item.

## Independent checks actually run

Environment: Windows Python 3.12, env-free frozen archives, synthetic SQLite and isolated PostgreSQL 16 on loopback port 55971. PostgreSQL tests use the explicitly validated private temporary connection file and unique synthetic databases; no connection values are recorded here.

| Snapshot | Command/scenario | Result |
|---|---|---|
| R2 | `python -m pytest tests/test_publication_recovery.py tests/test_publication_recovery_migration.py tests/test_admin_publication_recovery.py tests/test_knowledge_publication.py tests/test_admin_kg_knowledge_publication.py -q --basetemp=C:/Users/alanb/AppData/Local/Temp/e622a-audit-r2-tests` | **51 PASS**, 1 dependency deprecation warning, 207.31 s |
| R2 | `python -m pytest tests/test_publication_recovery_postgres.py -q --basetemp=C:/Users/alanb/AppData/Local/Temp/e622a-audit-r2-pg --tb=short`, with `FRUNZE_LOCAL_PG_CONNECTION` pointing only to the isolated local fixture | **10 PASS**, 1 dependency deprecation warning, 169.06 s |
| R2 | Auditor-created inline synthetic native scenario: activate both units, save signed withdrawal, withdraw, review one-unit replacement, retry original signed form | **FAIL reproduced**, 409 instead of original-receipt 303; no extra event |
| R3 | `python -m pytest tests/test_admin_publication_recovery.py::test_original_native_withdrawal_retry_after_manifest_replacement tests/test_admin_publication_recovery.py::test_native_withdrawal_at_capacity_and_exact_retry tests/test_admin_kg_knowledge_publication.py::test_auth_off_write_policy_change_csrf_and_pinned_selection tests/test_knowledge_publication.py::test_concurrent_identical_requests_have_one_receipt tests/test_publication_recovery.py::test_existing_full_history_has_one_terminal_withdrawal -q --basetemp=C:/Users/alanb/AppData/Local/Temp/e622a-audit-r3-narrow --tb=short` | **6 PASS**, 1 dependency deprecation warning, 21.05 s |
| R3 | Manifest recomputation with SHA-256 after CRLF normalization | **14/14 match**; no environment files |
| Contract bound | Independent standard-library construction of a withdrawal envelope with 5,000 maximum-length 120-character IDs, maximum-width database IDs and policy fields | **2,272,560 bytes**, below the 4,194,304-byte reserve; this is an envelope-size check, not a 5,000-unit integration benchmark |

R2-to-R3 identity mapping was checked independently: only the publication domain service, native publication controller, native recovery tests and PostgreSQL recovery tests differ. Decision validation, models, migration 0034 and remaining recovery/migration tests are identical. R3 changes were examined as actual code, and the changed retry/withdrawal behavior was independently executed in the six final checks. The R2 suite is not presented as a complete R3 suite.

R3 manifest SHA-256 is `6e0a8d6d0563135b13da4b994ccb963835252b641cd9799a5c62f8dc24616d3d`; R4 is `0f6e71e1dc67edc0905188cfd2cdfbe906e95e03fe21f52ee8b870ba84281048`. The auditor inspected the R3-to-R4 delta: explicit whole-publication withdrawal confirmation with the rule count, command-pin regression, browser test and migration-test fixture adjustment. Runtime source files are unchanged. The migration test seeds through current schema, then downgrades to 0023 before checking the same constraints; this is appropriate because current decision code also reads the publication table. Authorship of that pre-existing test edit was not established, and no claim of authorship is made. R4-to-R5 changes only the browser test. All final source identities were checked.

Additional evidence supplied by others, kept separate from the auditor's 67 own test executions:

- The independent publication review records its 100-test R2 compatibility suite, including grounded answers, plus final R3 regression and actual PostgreSQL concurrency checks. See `ai/reviews/2026-10-12-publication-independent-review.md`; the auditor read its actual concurrency probes and verified source identity as described below.
- Builder's final R4 delta: 7 PASS in 48.21 s, including the legacy-light browser cases and five nonbrowser checks. Builder's final PostgreSQL checks: 3 PASS in 65.45 s for delayed native retry, 101-unit server-resolved withdrawal and migration/downgrade preservation. These are builder-reported executions, not auditor runs.
- Builder's final R5 command: `python -m pytest tests/browser_publication_recovery.py -q --junitxml=runs/e622a-browser-r5.xml`, executed in `runs/e6-22a-r5`: **2 PASS**, 3 dependency deprecation warnings, 25.31 s. JUnit: `runs/e6-22a-r5/runs/e622a-browser-r5.xml`. The auditor independently inspected `before-390-dark.png`, `after-390-dark.png`, `before-1365-light.png` and `print-1.png` under `runs/e6-22a-r5/runs/publication-recovery-browser`. Actual dark mode, readable confirmation and action text, retired state, history and print are visible; browser assertions also cover page overflow and the no-JavaScript desktop submission.
- The auditor parsed that final JUnit independently: 2 tests, 0 failures, 0 errors, 0 skips, 25.303 s recorded suite time. Artifact SHA-256: `5ae1fd560a8e98c5fc667cf07c8ec344ef13b46913b5327dba12ad6f3e859262`.

## Critical acceptance and recovery

- **Clock integrity — PASS:** decisions sample time after set/version lock acquisition and duplicate lookup, reject earlier-than-own-history and at/before-publication timestamps, then revalidate decision dates. Publication review refuses selected future decisions. Legacy immutable commands and old receipts are preserved.
- **Recovery capacity — PASS:** new ordinary publication events stop at 249 and reserve 4 MiB from the 16 MiB ordinary journal budget. A valid old 250-event or 16 MiB journal can append one bounded withdrawal. Replay permits overflow only for the final withdrawal, with previous size at most 16 MiB and event size at most 4 MiB. Reader count is bounded at 251; it does not accept another event after overflow. Both ordinary and recovery writes remain atomic.
- **Native authorization and retry — PASS:** current actor/policy, feature/write gates, CSRF, signed manifest and revision are retained. The small visible selection cannot change the withdrawal's full manifest. Exact retry after a later reactivation returns the old receipt without withdrawing the new publication.
- **Native boundary display — PASS:** final confirmation explicitly states that withdrawal affects the entire active publication and shows its full rule count. Final dark-phone and light no-JavaScript desktop flows complete at capacity; the withdrawal result and four-event history are readable. Print was independently inspected.
- **Migration and recovery — PASS:** actual PostgreSQL migration head/metadata and revision 251 were checked. SQLite populated upgrade preserved publication event/link rows and foreign-key integrity. Empty downgrade/upgrade cycles passed. A populated downgrade refuses before constraint changes; the still-valid runtime could subsequently withdraw. SQLite migration with foreign keys enabled refuses without mutation. This is local synthetic recovery evidence, not a production backup/restore claim.
- **Actual PostgreSQL lock timing and competing withdrawal CAS — PASS, separate reviewer evidence:** `/root/publication_review` reported 4 PASS in 38.21 s for `python -m pytest tests/reviewer_clock_cas_r3.py -q --basetemp=../fixed-r3-pg-clock-cas --tb=short` in `runs/publication-review-20261012/fixed-r3`. The auditor read the actual probes and verified that all 14 source overlay hashes match R3. Probe SHA-256: `d34a5109cfff9fd895709dfbc9f68257f52c22f5ba9a7b88d82fa7e0695bd200`. The probes observe a database-specific `pg_stat_activity` lock wait, prove the decision clock has not been sampled while waiting, then reject earlier/equal timestamps without a decision insert or publication damage. Distinct withdrawal keys yield one receipt and one CAS conflict; the same key yields two identical receipts with one database event. These four tests were run by the separate reviewer, not by this auditor.

## Limits

This audit covers the E6-22A publication recovery correction. It does not certify the whole repository, unrelated preserved UI/config work, approved qualification C05, actual legal/source decisions or production release. Already-corrupt publication journals are not silently rewritten; they still fail closed and need a separate scoped repair decision. Downgrade over any populated publication history intentionally refuses to avoid installing an older reader over byte-overflow recovery data. No production deployment, real source approval or customer messaging was performed.

---

# Separate final audit — committed target (second auditor context)

- Date: 2026-10-12. CRITICAL / solo. Completion target: reviewed local change; no release, no deploy, no commits by the auditor.
- Base `8062f80`. The task was handed over as an uncommitted working tree; during this audit commit `87ad9e7` ("Keep knowledge withdrawal and history safe at clock and capacity boundaries") appeared. All ten in-scope files were checked with `git hash-object` against `HEAD:<path>`: **identical**, and their mtimes (19:00) predate this audit, so every check below ran on content equal to `87ad9e7`. The commit also carries `app/admin/templates/kg_knowledge_publication.html` (confirmation text only, Jinja-escaped) and `tests/browser_publication_recovery.py` (not run here).
- SHA-256 (working tree = HEAD 87ad9e7): `app/domain/knowledge_publication.py` e62422b3857843bb2816413bbca3b55fd18fd14cacb63403dffebffd499f3b6a; `app/domain/knowledge_decisions.py` 6b1381e18de87cf985a1e6e3d2b8191e3aa87694ae1b91f3e05f701f2185894e; `app/domain/models.py` 33ab3fe058dc64668120c22a89fa45a2fbc549149697fae8f4096e076368fbb8; `app/admin/kg_knowledge_publication.py` 852bd95985b68d1d35c129a941c395af2948a073b7a091f1887d3dd4e182d01b; `alembic/versions/e6_publication_withdraw_0034.py` 1a0e4ab906ff03b17ed8d2481001e36c1b5fd96c4bedb650a4438c5e4db1d017.
- `ai/STATE.md` and `ai/handoffs/*` were not read. The section above (first auditor) was read only after this verdict was formed; nothing from it is inherited.
- **Verdict: GO — reviewed local E6-22A correction at `87ad9e7`.** Not a release approval.

## Invariants vs actual code

| Pre-audit invariant | Code location | Result |
|---|---|---|
| Normal publication never uses the recovery slot or byte reserve | `publish_knowledge`: non-withdraw `count_limit = MAX_REVISIONS-1`, `size_limit = MAX_BYTES-MAX_EVENT_BYTES`; any event above `MAX_EVENT_BYTES` refused | PASS (probes a6, a9; `test_normal_commands_preserve_recovery_slot`) |
| No second overflow event | write refuses all at `rows >= 251` or `size > MAX_BYTES`; replay admits overflow only for a withdraw that is the last row, with previous size <= 16 MiB and event <= 4 MiB; reader caps at 251; DB check `revision BETWEEN 1 AND 251 AND (revision <= 250 OR action = 'withdraw')` | PASS (probes a1, a3, a4; PG direct inserts rev 251 rollback / 252 / 0 -> IntegrityError) |
| Limits enforced in write AND replay | as above | PASS (probe a2: well-formed rollback beyond cap rejected on replay with `publication_history_limit`) |
| Formerly valid records still replay | new replay branch fires only when revision > 250 or size > 16 MiB, never for a history the old reader accepted | PASS (code; `test_real_250_event_history_withdraws_at_251`; 237-test compatibility suite) |
| Exact retry at full journal returns original receipt | duplicate lookup precedes CAS, limits and clock; `unit_ids=None` resolves from the immutable old command | PASS (probe a5: old activate retry after terminal withdrawal = original receipt; same key, other data -> Conflict; no write) |
| Clock validation after duplicate lookup, before insert | decisions: shape-only normalize before I/O; `_now()` after lookup and CAS; refuse `< previous decision` or `<= latest publication`; then date revalidation. Publication: `_now()` after lookup/CAS/manifest, then history and selected-decision future checks | PASS (code; reviewer PG clock/CAS probes re-run) |
| UI never offers approve/activate beyond normal capacity | `_render` filters forms by `normal_capacity_available` / `withdrawal_capacity_available` | PASS (probe a6: no review/approve/activate/rollback forms at cap; stale signed activate POST -> 422, no write) |
| Lock order set-before-version | `decisions._version` locks set then version; runtime set FOR SHARE first; new publication-event read is under the set lock | PASS (code; frozen reviewer PG lock-waiter probes re-run: 9 + 4) |
| Actor/policy/CSRF gates unchanged | diff only filters forms and passes `ids=None` for withdraw; `require_full_admin`, `_gate(write=True)`, `authorize_publisher`, `_form` CSRF/HMAC, policy hash check untouched | PASS (diff; `test_admin_kg_knowledge_publication.py` in suite) |
| Migration recovery | `_change`: row count checked before any DDL; offline downgrade and offline SQLite refused; SQLite requires FK OFF and `foreign_key_check` before/after | PASS (commands 6-7) |

## Commands actually run by this auditor (repo root, synthetic databases only)

1. Frozen reviewer probes against current code, via `python -c` wrapping `pytest.main` with `runs/publication-review-20261012/source/tests/reviewer_publication_probes.py -q -p no:cacheprovider --import-mode=append -o addopts= --basetemp=%TEMP%/e622a-audit/probes` -> **4 passed**, 14.46 s. After the run, the printed module origins for `app`, `app.domain.knowledge_publication` and `app.domain.knowledge_decisions` were the repo root, not `runs/`. The loaded `conftest` was the frozen copy, which is byte-identical to `tests/conftest.py`.
2. SQLite compatibility: `python -m pytest tests/test_publication_recovery.py tests/test_admin_publication_recovery.py tests/test_publication_recovery_migration.py tests/test_knowledge_decisions.py tests/test_knowledge_decisions_migration.py tests/test_knowledge_publication.py tests/test_knowledge_publication_migration.py tests/test_knowledge_answers.py tests/test_admin_kg_knowledge_publication.py tests/test_admin_kg_knowledge_decisions.py tests/test_knowledge_import.py tests/test_knowledge_review.py tests/test_knowledge_projection.py tests/test_knowledge_migration.py tests/test_knowledge_projection_migration.py -q -p no:cacheprovider` -> **237 passed**, 296.47 s.
3. Actual PostgreSQL 16 (isolated loopback; `FRUNZE_LOCAL_PG_CONNECTION` = private temp file, values not printed): `python -m pytest tests/test_publication_recovery_postgres.py tests/test_knowledge_answers_postgres.py -q` -> **18 passed**, 185.81 s.
4. Frozen reviewer PostgreSQL probes against current code: `runs/publication-review-20261012/source/tests/reviewer_publication_postgres.py` -> **9 passed**, 52.69 s; `runs/publication-review-20261012/reviewer_clock_cas_r3.py` -> **4 passed**, 29.22 s. Module origin verified as the repo root.
5. Auditor adversarial probes (scratch, outside the repo, 9 tests):
   - a1: an event after a count-terminal withdrawal is rejected on replay.
   - a2: a non-withdraw event beyond the cap is rejected on replay.
   - a3: an event after a byte-terminal withdrawal is rejected on replay.
   - a4: an oversized terminal event is rejected on replay.
   - a5: at a terminal journal, an old request returns its original receipt, a reused key conflicts, and nothing is written.
   - a6: native forms are absent at capacity, and a stale signed form gets 422.
   - a7: a server-resolved withdraw of a non-active version is refused without a write.
   - a8: `unit_ids=None` is refused for every non-withdraw action.
   - a9: in a new history, normal events stop at MAX-1, withdraw takes MAX, and nothing follows.
   Result: **9 passed**, 28.94 s. Two earlier runs failed only because my own a5 expected `history_limit`. The code instead refused with `invalid_publication_command` / `publication_revision_changed`; both are correct and nothing was written.
6. Auditor PostgreSQL probe: a populated `command.downgrade(cfg, 'e6_deadline_clear_0033')` raised RuntimeError `preserve populated`. `pg_get_constraintdef`, `alembic_version` and all event rows were identical before and after. Direct inserts at revision 251 (rollback), 252 and 0 raised IntegrityError. Runtime still returned 2 available units. **1 passed**, 16.99 s.
7. Offline migration: `alembic -x dburl=postgresql://... downgrade e6_publication_withdraw_0034:e6_deadline_clear_0033 --sql` raised RuntimeError `offline migration cannot verify publication history`. Offline SQLite upgrade was refused the same way. Offline PostgreSQL upgrade emits only `LOCK TABLE ... ACCESS EXCLUSIVE` plus drop and recreate of the one check.

Own final executions: 4 + 237 + 18 + 9 + 4 + 9 + 1 = 282 tests, 0 failures.

## Remarks (not blockers)

1. `normal_capacity_available` tests `size < MAX_BYTES - MAX_EVENT_BYTES`, while the write needs `size + event <= MAX_BYTES - MAX_EVENT_BYTES`. Near the byte bound the UI can show a form that the server then refuses with 422. The server is authoritative and the reserve stays intact, so this is cosmetic.
2. The reserve is enforced only on write. Replay cannot tell a legacy event at revision 250, or one in the 12-16 MiB range, from a new one. That follows from preserving formerly valid records; the hard bounds (251, withdraw-only overflow, 4 MiB terminal) are enforced on replay.
3. The decision clock guard is set-wide (latest publication of the whole set), which is stricter than needed. Under clock skew it fails closed with an explicit error and writes nothing.
4. Downgrade below 0034 refuses over any populated history. An older reader (`8062f80`) over a 251-row journal fails closed with `publication_history_limit`. Rollback after migration therefore means fixing forward, not downgrading the schema.

## NEEDS_HUMAN_DECISION (does not block the local change)

- Once a journal reaches 249 normal events, or uses its terminal withdrawal, the `kg_entry` set can never publish again. The freeze existed before (at 250). How to recover — a new set, archiving, or a repair procedure — is a product decision for Alan.

## Not verified

- I did not run `tests/browser_publication_recovery.py`.
- Production data, backup and restore are out of scope. Whether the publication tables exist on production is UNKNOWN.
- No 5,000-unit integration run. The claim that the terminal event fits in 4 MiB rests on code arithmetic (an envelope of about 2.2 MB), not on a measurement.
- No builder or reviewer PASS is inherited; only the commands above count as this audit's evidence.
