# Independent review — knowledge import and publication boundary

Date: 2026-10-12. Reviewer: `/root/publication_review`, separate agent context.
Risk: CRITICAL. Target: reviewed local implementation; no release authorization.
Final verdict: **APPROVE** for the local D01–D05 source/publication boundary at the verified r3 snapshot below. The initial base and r2 findings are retained as evidence; all confirmed findings were corrected and independently rechecked. This is not an approval of legal source facts, the unfinished E6-22 qualifier, or a production release.

## Scope and independence

Reviewed `docs/pdf-engineering-criteria.json` D01–D05, relevant E5-02 import/review/projection contracts, actual import, decision, publication, projection, source-validation and immutable-model code, native review/publication authorization and their focused tests. No builder handoffs, old reviewer reports or builder verdicts were read before this assessment.

Base: Git `8062f80`. Frozen clean tracked snapshot: `runs/publication-review-20261012/base.zip`, extracted to `runs/publication-review-20261012/source`. The archive contains no local `.env`. Existing working-tree UI edits are outside this review. New E6-22 changes and runtime extraction are not covered by this initial assessment.

Archive SHA-256: `115767ca1a1f7d8fa2a101e7846f4110844ee13c784facef448b46706b572d2b`.

## Confirmed initial findings — corrected in final r3

### P1 — A backdated review permanently invalidates unrelated publication history

Location: `app/domain/knowledge_decisions.py`, `record_knowledge_decision`, assignment of `_now()` to the new row; `app/domain/knowledge_publication.py`, `_Context.manifest`, `_Context.availability` and `_history` historical filtering.

Trigger: activate a valid synthetic publication with two independently approved units; after the system clock steps backwards, submit a rejection of one unit with `created_at` preceding an existing publication event. The public domain command commits the new review. The same problem exists for equality with a publication timestamp, because historical filtering uses `<=`.

Consequence: replay now includes the later-inserted review in the older publication manifest. All runtime reads, publication previews and withdrawal commands fail with `publication_history_integrity_failed`, including the unrelated approved unit. Normal correction through the publication API is unavailable because each command first replays the corrupted history. This is fail-closed but violates per-unit invalidation and recoverable publication behavior.

Evidence: independent synthetic SQLite probe `test_backdated_review_after_activation_must_not_poison_publication` in `runs/publication-review-20261012/source/tests/reviewer_publication_probes.py` failed after the rejection committed, at `runtime(release)` with that exact error.

Required correction: prevent new decision records from preceding their existing decision chain and require their timestamp to be strictly later than the latest publication event for the set, under the existing set lock; or use a different historical association that cannot be rewritten by later insertion timestamps. Preserve exact retries and do not rewrite old evidence. Add regression coverage for earlier and equal instants, and a normal later rejection that leaves unrelated units available.

Additional independently reproduced inverse case: a publication `review` action could itself predate its pinned latest decision. This action has no availability approval gate, so it committed a manifest that its own next replay could not reproduce. `test_publication_review_cannot_predate_pinned_decision` failed on the frozen base in 7.54 seconds. Non-withdrawal lifecycle writes also need to reject selected decision timestamps later than their sampled publication time.

### P2 — The bounded lifecycle can exhaust its ability to withdraw an active publication

Location: `app/domain/knowledge_publication.py`, `MAX_REVISIONS`, `MAX_BYTES`, command validation and the append-size check; `app/admin/kg_knowledge_publication.py`, `_render` form gating.

Trigger: ordinary review/approval/activation/rollback operations use all 250 lifecycle slots or the byte budget while a version remains active. No terminal slot or bytes are reserved.

Consequence: withdrawal is rejected by `invalid_publication_command` or the history-size guard; the native UI also removes its form at the revision cap. The active version remains usable until a separate policy or source gate disables it. Changing global configuration is not a durable withdrawal receipt.

Evidence: independent synthetic SQLite probe `test_withdrawal_is_available_at_history_capacity` sets the limit to the three existing review/approve/activate events and confirms that withdrawal is rejected. The same code applies to the production-sized 250 cap. Static inspection confirms the analogous byte-cap issue.

Required correction: reserve a bounded final withdrawal slot and enough bytes while admitting nonterminal operations, expose the remaining safe terminal action in the native UI, and preserve exact retries at capacity. Keep the database constraint and maximum replay bounds; do not delete history or silently raise the cap as a substitute for recovery behavior.

## Evidence actually run by this reviewer

Environment: Windows, Python 3.12, env-free Git archive, temporary synthetic SQLite databases. No live channels, customer messages, production database, deployment or credentials were used.

1. `python -m pytest tests/test_knowledge_import.py tests/test_knowledge_review.py tests/test_knowledge_projection.py tests/test_knowledge_decisions.py tests/test_knowledge_publication.py tests/test_admin_kg_knowledge_decisions.py tests/test_admin_kg_knowledge_publication.py -q --basetemp=../pytest-temp`
   - **PASS:** 178 tests, 123.86 seconds.
   - **SKIP:** 2 real-PDF import/review tests require the original local PDF, which is absent from the tracked archive. These are not counted as source-verification evidence.
2. `python -m pytest tests/reviewer_publication_probes.py -q --basetemp=../probe-temp`
   - **FAIL:** 2 reviewer probes, 11.02 seconds; findings above.
   - Extended repeat with `--basetemp=../probe-time-equality --tb=short`: **FAIL**, 3 probes, 14.14 seconds. Earlier and exactly equal publication timestamps both reproduce P1; terminal-capacity probe reproduces P2.
3. PostgreSQL locking/concurrency: **UNKNOWN** at this initial assessment. Requested safe local runtime details from the parent; no assumption that SQLite proves PostgreSQL lock behavior.
   - Prepared seven probes in `runs/publication-review-20261012/source/tests/reviewer_publication_postgres.py`: four read/write order combinations with real database lock-wait observation, lifecycle rollback, atomic failure and lost acknowledgment.
   - First explicit localhost run: **SETUP ERROR**, 7 errors, 10.32 seconds. The validated private connection file targeted only `127.0.0.1:55971`, but the server refused connections before any test database was created. This is an environment failure, not a product failure or passing PG evidence.
   - Second attempt after a reported restart: **SETUP ERROR**, 9 errors, 13.77 seconds. Parent then corrected the listener port. Neither failed setup is included in passing evidence.
   - Once the listener was verified: `FRUNZE_LOCAL_PG_CONNECTION` set to the private local file, `python -m pytest tests/reviewer_publication_postgres.py -q --basetemp=../postgres-port-fixed --tb=short`: **PASS**, 9 tests, 45.36 seconds. Four source-lock order cases asserted a real `pg_stat_activity.wait_event_type='Lock'` waiter scoped to each unique test database, then checked source visibility before/after release. Also exercised version rollback, publication atomic failure, lost acknowledgment, import deduplication and partial-import rollback/rejected journaling. No credentials printed.

## Other assessed boundaries

- Import validates source hash, normalized bundle and projection before atomically storing the draft, units, projection and accepted journal. Existing drafts are reused only after snapshot/projection consistency checks. Rejected journaling follows rollback, and unknown commit outcomes remain explicit.
- Diff preserves missing versus null and Boolean versus numeric values, imported evidence and per-field changes. Projection is re-derived and verified before exposing candidates.
- Trusted named full-admin authorization precedes storage/file access. Native forms bind actor, source, action, revision, policy and manifest using server-issued signatures and CSRF; policy and write gates are checked on the server.
- Runtime and decision/publication writers use the same `KnowledgeSet` lock: runtime `FOR SHARE`, writers `FOR UPDATE`, then version locks. Static inspection found no supported API mutation race through a cached decision tail under that lock order. This observation is not a substitute for PostgreSQL testing.
- An available runtime unit is a published source fact, not independent approval of the attached draft condition mapping or proof of complete qualification alternatives. Callers must retain their additional semantic/condition gates.
- Actual business-source approvals, owner policy, legal truth and pilot acceptance are outside technical review; synthetic fixture approvals do not establish any of them.

## Initial assessment before correction

| Criterion | Independent local review | Evidence or limitation |
|---|---|---|
| D01 — atomic versioned import | PASS | Focused import/projection failure, retry, rollback and snapshot tests; PostgreSQL and original-PDF verification remain separate. |
| D02 — review index/diff | PASS | Source/projection consistency, exact-field diff, provenance and affected-case code/test inspection. |
| D03 — recorded decisions | FAIL | P1 admits a later-inserted backdated review that invalidates historical publication evidence. |
| D04 — publication lifecycle and rollback | FAIL | P1 prevents recovery through the API; P2 consumes terminal withdrawal capacity. |
| D05 — runtime refusal and isolation | FAIL | Existing stale/conflict/draft guards pass, but P1 turns one-unit invalidation into whole-set integrity failure. |

D01–D02 initially had a scoped independent review with the evidence above; D03–D05 initially required the corrections below. The final assessment superseding that initial verdict is recorded at the end.

## Correction review — E6-22A

Requirements read from `ai/tasks/2026-10-12-e6-22a-publication-recovery.md`. Frozen correction `runs/e6-22a-r2` was verified against all 14 SHA-256 entries in `snapshot.json`, normalizing CRLF to LF as the manifest does, and copied into reviewer-owned `runs/publication-review-20261012/fixed-r2`. It is based on the same Git revision and contains no `.env`.

Actual correction inspected: guarded decision timestamps and sampled-date normalization after receipt lookup; future-decision guard on lifecycle writes; reserved ordinary capacity plus one strictly bounded legacy terminal withdrawal; native capacity forms; local migration `e6_publication_withdraw_0034`; extraction of the existing runtime body into internal transaction-composition helpers. The external runtime actor and selection gates remain in place.

Reviewer-run r2 evidence:

- `python -m pytest tests/reviewer_publication_probes.py tests/test_publication_recovery.py tests/test_admin_publication_recovery.py tests/test_publication_recovery_migration.py tests/test_knowledge_decisions.py tests/test_knowledge_publication.py tests/test_knowledge_answers.py tests/test_admin_kg_knowledge_publication.py -q --basetemp=../fixed-r2-pytest --tb=short` — **PASS**, 100 tests, 284.55 seconds. Includes all four independently constructed original defect probes.
- `python -m pytest tests/reviewer_publication_postgres.py tests/test_publication_recovery_postgres.py -q --basetemp=../fixed-r2-pg --tb=short` with the explicit private localhost connection file — **PASS**, 19 tests, 244.22 seconds. Fresh uniquely named databases migrated to head per the validated fixture; includes actual revision-251 withdrawal, metadata parity, migration cycle/populated downgrade refusal and native 101-unit withdrawal.
- Additional reviewer native regression: withdrawing a manifest, reactivating a different subset of the same version, then retrying the original signed withdrawal returned 409 instead of the original receipt. `tests/reviewer_publication_native_retry.py` — **FAIL**, 1 test, 20.18 seconds. Independently reproduced the same issue reported by the separate auditor. This blocks approval of r2's native retry change.

Frozen r3 copied and independently hash-verified at `runs/publication-review-20261012/fixed-r3`. The inspected delta resolves `unit_ids=None` only for withdrawal, using an existing immutable command before retry comparison or the current manifest under the set lock for a new operation. All original command fields still participate in request-hash comparison. Native code no longer performs the premature current-manifest check. The r2 passing checks map to unchanged decision/migration/model/runtime code and unchanged behavior for explicit ID selections; the changed withdrawal path was rechecked on r3.

## Final r3 verification and verdict

Target identity: base `8062f80e89f60c9b42ec74457fd6275bd038e3bd` plus `runs/e6-22a-r3/snapshot.json`, whose raw SHA-256 is `6e0a8d6d0563135b13da4b994ccb963835252b641cd9799a5c62f8dc24616d3d`. Every overlay entry was verified using LF-normalized content hashes before tests. Reviewer-owned tests remain under `runs/publication-review-20261012`; they were not inserted into the shared source tree.

1. From `runs/publication-review-20261012/fixed-r3`, with `FRUNZE_LOCAL_PG_CONNECTION` explicitly pointing to the private local rehearsal file:
   `python -m pytest tests/reviewer_clock_cas_r3.py -q --basetemp=../fixed-r3-pg-clock-cas --tb=short`
   — **PASS**, 4 tests, 38.21 seconds, actual isolated PostgreSQL.
   - Paused activation while holding the publication set lock. A competing review produced an actual scoped database lock waiter, and its `_now` sampler had not run. After activation committed and the review acquired the lock, the sampler ran exactly once; earlier and equal timestamps were rejected without a new decision. Both approved units remained readable, and a later withdrawal succeeded.
   - Two distinct withdrawal request keys with one expected revision yielded one receipt and one CAS conflict. Two identical keys yielded the same receipt twice. In each scenario only one withdrawal row was stored. These calls use the new `unit_ids=None` path.
2. `python -m pytest tests/reviewer_publication_probes.py tests/reviewer_publication_native_retry.py -q --basetemp=../fixed-r3-repros --tb=short`
   — **PASS**, 5 tests, 18.97 seconds, synthetic SQLite/native HTTP. Earlier/equal decision timestamps, inverse publication-before-decision time, full-history terminal withdrawal, and the independently reproduced delayed native retry all pass. Retrying the old withdrawal preserves the newly activated subset.

| Criterion | Final independent review | Evidence |
|---|---|---|
| D01 — atomic versioned import | PASS | Baseline import/projection tests plus actual PG deduplication and partial-write rollback/journaling; unchanged implementation. |
| D02 — review index/diff | PASS | Focused snapshot/projection/diff checks and source/dependency inspection; unchanged implementation. |
| D03 — recorded decisions | PASS | Corrected timestamp validation, receipt ordering and sampled-date checks; own earlier/equal reproductions and after-lock PG checks pass. |
| D04 — atomic lifecycle, pin and rollback | PASS | Reserved capacity, bounded legacy terminal event, real 250-to-251 history, migration preservation/refusal, rollback, lost acknowledgment, native delayed receipt and concurrent withdrawal checks. |
| D05 — runtime source gate | PASS | Existing draft/stale/conflict/policy and projection checks remain; corrected histories replay, unrelated approved facts remain available, and PG reader/writer lock ordering is observed directly. |

**APPROVE — reviewed local correction and scoped D01–D05 boundary.** No confirmed open defect remains within this reviewed target. Separate final audit and any production release authorization remain distinct responsibilities. Original local PDF round-trip checks were skipped in the env-free base archive; this review does not assert independent verification of its legal content or approve the 208 real draft units. The change prevents new malformed chronology and supports valid full legacy journals; it does not claim to repair already corrupted historical evidence. Later source changes require another scoped review.
