# REVIEW: E6-22A publication recovery (P1 clock rewrite, P2 terminal withdrawal)

- Task: ai/tasks/2026-10-12-e6-22a-publication-recovery.md (requirements: confirmed P1/P2 in ai/reviews/2026-10-12-publication-independent-review.md)
- Base / target snapshot: git 8062f80 + uncommitted working tree. Reviewed: app/domain/knowledge_decisions.py, knowledge_publication.py, models.py constraint line, app/admin/kg_knowledge_publication.py, untracked alembic/versions/e6_publication_withdraw_0034.py, tests/test_publication_recovery*.py, tests/test_admin_publication_recovery.py, modified tests/test_knowledge_decisions_migration.py. Out-of-scope files ignored. The snapshot is the live working tree, not a frozen archive.
- Reviewer / builder: independent Claude reviewer context (read-only except this file) / root + Codex
- Independence: INDEPENDENT (separate context, same working tree, not a different provider)
- First assessment without builder conclusions: YES. ai/STATE.md, ai/handoffs/* and builder summaries were not read. Only the task and the prior review (requirement source) were read before the verdict.

## Findings
No blocker or major finding. Confirmed bugs: none.

| Severity | Location | Trigger / problem / consequence | Evidence | Suggested correction |
|---|---|---|---|---|
| minor (theoretical) | knowledge_publication.py write(): event_size > MAX_EVENT_BYTES also applies to withdraw; _history applies it to the over-cap terminal | A legacy active publication whose event exceeds 4 MiB could never be withdrawn. Not reachable: manifest capped at 5000 units, unit_id <=120 chars, entry about 290 B and command ids about 125 B each, so an event is about 2.1 MiB. | Static estimate from _identifiers/_unit_id limits; not measured on a real 5000-unit event. | Optional: test with a 5000-unit synthetic manifest asserting event size < MAX_EVENT_BYTES, or exempt the manifest-copy withdraw from the per-event cap. |
| nit | publication_preview normal_capacity_available | Size test is size < MAX_BYTES-MAX_EVENT_BYTES, optimistic against write (size + event_size <= that). A form can be offered and rejected 422. Server stays authoritative, no state damage. | Code reading | Acceptable. |
| nit | admin publication_submit | For withdraw _ids(units) is still parsed before being discarded (ids=None); hidden _kp_units for withdraw is the user selection, not the active manifest. Harmless: the signature binds the field and the manifest hash binds the real list. | Code reading | Optional comment. |

## Answers to the review questions
- P1 write path: the decision timestamp is sampled after receipt lookup and revision check, under the set lock (set-then-version order unchanged in decisions._version). It must be >= the unit previous decision and strictly > the set latest publication event; rejected without a row. Exact retries return the original receipt before any clock check. Decision dates are re-validated against the sampled local day (cutoff=None precedence is correct). The only KnowledgeDecision insert in app/ is this one (grep). Non-withdraw publication writes reject any selected unit whose decision is later than the sampled publication time (publication_clock_before_review), closing the inverse case. Replay is unchanged and strict (historical manifest equality, <= filter), so formerly valid histories replay as before.
- P2: new histories: normal actions stop at revision 249 (len>=249 reject) and 12 MiB total, each event <=4 MiB; withdraw is allowed up to revision 251 and 20 MiB total. A normal action cannot consume the reserve. Second overflow event: after a terminal withdraw there is no active version, so _transition forbids another withdraw and normal actions are capped; write rejects len>=251 and size>MAX_BYTES; replay rejects any event beyond 250 or over 16 MiB unless it is the last row, a withdraw, previous size <=16 MiB, event <=4 MiB. Exact retries at a full journal pass because _history replays a full journal and receipt lookup precedes limit checks (tested at 251 rows and byte-full).
- Preview flags match write predicates (len<249, len<=250, size). Native form: normal actions need normal_capacity_available, withdraw needs withdrawal_capacity_available; old current_revision < MAX_REVISIONS gate removed.
- Native withdraw with unit_ids=None: resolved under the set write lock from the original event (retry) or the version current lifecycle manifest; signed manifest hash, expected revision, policy, actor, version and action still enter the request-hash/manifest comparison, so substitution gives conflict (tested: changed hash, revision, version). None is accepted only for withdraw.
- Migration 0034: same structure as precedent 0033 (ACCESS EXCLUSIVE lock on PG; SQLite requires FK OFF, BEGIN IMMEDIATE or write-lock touch, FK check before and after, batch recreate; offline allowed only for PG upgrade). Any populated downgrade is refused before changes (conservative, also covers byte-only terminal). Model constraint equals migration text; the DB enforces revision<=250 OR action=withdraw.
- Runtime refactor: _runtime_context/_runtime_in_session is a verbatim extraction; sole caller is runtime_knowledge; its signature and actor gate are unchanged; knowledge_answers tests pass.
- test_knowledge_decisions_migration.py change: legitimate. record_knowledge_decision now queries knowledge_publication_events (created in 0024), so a 0023-only schema cannot run it. The test now writes at head, downgrades to 0023 and still asserts all 0023 constraints and the populated-downgrade refusal. No assertion weakened. Residual: between migrations 0023 and 0024 the decision writer would fail; irrelevant as migrations run to head together.
- Legacy edge (events >4 MiB): see minor finding; unreachable under current limits.

## Acceptance coverage
| Criterion | PASS / FAIL / UNKNOWN / N/A | Evidence or N/A reason |
|---|---|---|
| 1 Review clock guard, retry, date revalidation | PASS | Code + test_publication_recovery (earlier/equal, retry after clock rollback, inverse future-decision) |
| 2 Reserved slot/bytes, terminal withdraw for full 250/16MiB, replay validation | PASS | Code + tests incl. seeded real 250-event history, byte-full history |
| 3 Native form at boundary, ordinary cannot consume recovery capacity | PASS | Admin recovery tests, preview flags match write predicates |
| 4 Constraint 251 only, populated downgrade refusal, real PG | PASS (local) | Migration tests, 11 PG tests on isolated local PostgreSQL |
| 5 Defect reproductions and compatibility checks | PASS | 106 + 11 tests below |
| Concurrency/lock ordering probed independently by me | UNKNOWN | Code reading only (same set-before-version path); builder PG tests passed; I wrote no lock-wait probes |
| 5000-unit manifest under 4 MiB event cap | UNKNOWN | Estimated, not measured |

## Checks actually performed
| Command/scenario | Environment | Result | Limitation |
|---|---|---|---|
| pytest of tests/test_publication_recovery.py, test_admin_publication_recovery.py, test_publication_recovery_migration.py, test_knowledge_decisions_migration.py, test_knowledge_decisions.py, test_knowledge_publication.py, test_knowledge_answers.py, test_admin_kg_knowledge_publication.py, test_admin_kg_knowledge_decisions.py (-q -p no:cacheprovider, basetemp under TEMP) | Windows, synthetic SQLite | 106 passed, 244.56 s | Builder tests; I added no new probes |
| pytest tests/test_publication_recovery_postgres.py with FRUNZE_LOCAL_PG_CONNECTION set to the local connection file | isolated local PostgreSQL 127.0.0.1:55971 | 11 passed, 143.89 s | Local only; no production |
| Static review of full diff and surrounding functions (_history, publish_knowledge, publication_preview, decisions._version/_history, admin render/submit, migration 0034 vs 0033) | working tree | done | Working tree is not frozen; later edits void this review |

## Verdict
APPROVE

Scope: reviewed local correction of P1 and P2 in the listed files. No blocking defect; only a theoretical legacy-size note and nits. The independent-review requirement for CRITICAL is met by a separate context; the separate final audit and any release decision remain outside this review. Not asserted: production backups, legal source facts, real data, own PG lock-order probes.
