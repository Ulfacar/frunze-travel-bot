# E6-12 independent CRITICAL implementation review

Latest verdict: **APPROVE for the reviewed local synthetic r3 scope**, identified in the final section. The earlier FIX_REQUIRED verdicts and their evidence below are preserved for r1/r2. This is not production release authorization or approval of unimplemented channel integration.

Verdict: **FIX_REQUIRED** for frozen r1. This is an independent implementation review, not release authorization or the separate final audit.

## Reviewed target and independence

- Base: `8575f1f278659cc0d92c8342dbf25262afce5dc7`.
- Immutable target: `runs/e6-12-review-r1`.
- Manifest: `ai/reviews/2026-10-11-e6-12-snapshot-r1.json`, SHA-256 `ebd7402f5b9767ae8339016119762065758bfc4a8523f9853a434b3333bfb7f8`.
- Independently verified all 19 manifest entries against LF-normalized archive files: PASS.
- Read task and source PDF-derived sections 3.1–3.4, 4.1, 17, Appendix B before implementation source. Reviewed catalog, rules, policy, journal, native UI/template, models/migration and relevant tests before builder test conclusions. First source assessment was sent to the builder before this review's tests. Builder subsequently disclosed planned fixes; none were substituted into r1 or counted as evidence.
- All verification used synthetic local SQLite, loopback browsers or the guarded local PostgreSQL harness. No production access, real policies, customer data, deployment or external messages. Frozen source was not edited; only ignored test artifacts/probes were added.

## Required fixes

### F1 — P1: a new active catalog version makes existing cards and retries unreadable

`app/domain/entry_interview_policy.py:41` requires the stored policy hash to equal the currently imported `catalog.digest()`. `app/domain/entry_interviews.py:87` independently compares the persisted catalog with `catalog.document()`. Replay also resolves all fields and rules through the current global catalog.

Reproduction: create an interview, hand it off, acknowledge it, retain its original command and card; change only the active catalog version string. Reading with `policy=None` raises `invalid_interview_policy`. This reproduced on SQLite and actual PostgreSQL. The failure occurs before exact retry and pending acknowledgement can recover through their normal shared history path. Changing only the active collection policy, with the catalog unchanged, is a passing negative control: the old card stays readable and collection is disabled.

Required: retain immutable catalog versions and their supported reducer/decoder versions; resolve historical policy, fields, conditions, replay and display from the persisted accepted version. Validate new starts against the current active version separately. Merely removing the hash check would permit reinterpretation and is not a fix. Acceptance must exercise old read, retry and pending ACK after a genuine active-version change plus new starts under the new supported version.

### F2 — P1: consent withdrawal cannot be persisted while a card awaits acknowledgement

`app/domain/entry_interviews.py:143` rejects every `interrupt` once phase is `pending` or `acked`. The other answer/correction paths also reject pending updates. A person can withdraw consent while the manager is considering the handoff, but the explicit `consent_withdrawn` operation then raises `interview_handoff_already_exists`. The state remains `collection_blocked=False`, and a later owner ACK enables manual collection again. The UI exposes no withdrawal action in this phase either. Reproduced independently on SQLite and PostgreSQL.

Required: allow a minimal durable withdrawal event in pending and acknowledged states, while leaving the original handoff/card/hash unchanged. It must stop subsequent collection, remain possible when collection policy is absent/expired, retain actor/scope/CAS/idempotency enforcement and have a native form. Repeated withdrawal must not consume unbounded history. Reserve count and bytes for this event in addition to any remaining handoff/ACK steps, and verify races with ACK and owner correction. This does not require inventing retention/deletion policy or changing existing bot behavior.

### F3 — P2: history replay does not enforce the writer's terminal reserve

The writer at `app/domain/entry_interviews.py:205` reserves two maximum events for ordinary operations and one for handoff. The reader at lines 219/239 checks only the absolute journal count/bytes. A structurally valid ordinary event in a terminally reserved position is accepted during semantic replay even though the public writer would reject it.

Independent reduced-bound reproduction: create five ordinary events while the count bound is eight; validate the same history under a bound of six, where ordinary writes may only reach four. Read incorrectly succeeds. The corresponding valid sequence at the boundary — ordinary writes, then handoff, then owner ACK — passes. This is a replay/integrity gap rather than a demonstrated public-writer overflow. The analogous byte comparison is visible in the source; it was not separately reproduced in this review.

Required: one action-aware capacity rule used by both append and every replay prefix, including cumulative bytes and any new withdrawal reserve. Preserve readable valid terminal histories and exact old retries at the bound.

### F4 — P2: policy authorization and persisted event time can cross a validity boundary

`start_interview` authorizes against `_today()` at line 258, then constructs a later `_now()` at line 264. The action writer has the same split at lines 291/294. At local midnight after `review_due_on`, a write can commit outside the pinned policy validity period and then fail its own replay check.

Independent probe fixes the authorization day to 2027-01-01 and the event timestamp to 2027-01-01 18:00:00.001 UTC (next day in Bishkek); the policy ending 2027-01-01 is accepted and the interview is committed. A final probe with only the expected domain/permission exceptions also fails, so the result is not masked by a broad exception assertion.

Required: validate authorization against the exact timestamp that will be persisted, after acquiring the relevant transaction state. Add a midnight-boundary rejection/rollback check for start and append. Keep minimal operational handoff/ACK/revocation availability separate from collection-policy validity. Also preserve chronological replay; the builder reported a follow-up for monotonic timestamps, which has not been reviewed in r1.

### C1 — test portability: recovery evidence output assumes an existing directory

The PostgreSQL recovery test initially failed only at `tests/test_entry_interview_postgres.py:151`, writing `runs/interview-postgres-recovery.json` into a missing directory. All preceding restore/read/retry/new-write assertions had succeeded. Creating only the ignored output directory and rerunning produced PASS. Make the test create its own artifact directory to support clean archives. This is not classified as a storage-recovery defect.

## Independent evidence

| Verification | Exact command/scenario | Result |
|---|---|---|
| Snapshot identity | Manifest hash and all 19 LF-normalized file hashes | PASS |
| Rules, domain, native HTTP, migration, shared regression | In r1: `python -m pytest -q tests/test_kg_interview_rules.py tests/test_entry_interviews.py tests/test_admin_kg_interviews.py tests/test_entry_interview_migration.py tests/test_alembic_domain_migration.py tests/test_service_cases.py` | 153 PASS, 2 SKIP (opt-in PostgreSQL checks; PG exercised separately) |
| Real PostgreSQL implementation tests | Root: `python runs/e610_legacy_pg_probe.py runs/e6-12-review-r1 tests/test_entry_interview_postgres.py` | 12 PASS; recovery test artifact-directory FAIL described in C1 |
| Recovery rerun after creating ignored output directory | Same harness with `tests/test_entry_interview_postgres.py::test_binary_copy_recovery_frozen_card_ack_old_retry_native_read_and_new_write --tb=short` | 1 PASS; all 13 distinct PG cases therefore exercised successfully |
| Actual browsers | In r1: `python -m pytest -q tests/browser_kg_interviews.py` | 2 PASS: 390px mobile and desktop without JavaScript; lost commit ACK plus unavailable reread, exact native retry, handoff, owner ACK and correction |
| Independent adversarial SQLite probes | In r1: `python -m pytest -q ../../runs/e612_independent_adversarial.py` | 4 FAIL (F1–F4), 2 PASS (valid terminal capacity and changed-policy historical-read controls) |
| Tightened midnight probe | Same probe module, `::test_policy_authorized_day_is_the_actual_persisted_day --tb=short` | FAIL: invalid-date write still accepted |
| Independent adversarial PostgreSQL probes | Root: `python runs/e610_legacy_pg_probe.py runs/e6-12-review-r1 ../../runs/e612_independent_pg.py --tb=short` | 2 FAIL (F1/F2), 1 PASS (valid terminal reserve control) |
| Visual inspection | Own browser-produced mobile question screenshot and rasterized first page of `runs/e6-12-review-r1/runs/e6-12-interview-browser/interview-demo.pdf` | PASS for readable layout; 3 PDF pages, all contain text; first page inspected visually |

The recovery evidence is application-level PostgreSQL binary COPY into a fresh migrated guarded UUID database, including sequence restoration and post-restore behavior. It is not a native `pg_dump` recovery claim. The only recurring warnings were dependency deprecations.

## Positive source assessment and limits

The 57 A–H source codes have individually typed fields and RU/EN question text. Own-applicant minor/family fields exist even with zero companions. Unknown, false, zero, empty choice lists and proven not-applicable remain distinct. Dependency contexts retain stale evidence rather than silently replacing it; changing prerequisite values back does not revive old dependent answers. Batches are bounded to three questions. Manual work/family/investor branches retain facts without generating legal arithmetic or invented prices.

Current trusted full-admin enforcement precedes database access; historical actors must belong to the pinned operator/authority set. The unique applicant subject, composite scope/previous-event constraints, shared case lock, exact command hash and expected revision support isolation, duplicate recovery and races. Rehashed altered handoff cards fail semantic replay. Empty migration round trips, populated downgrade refusal, metadata agreement, commit uncertainty and two-part start rollback have meaningful checks. Signed native forms bind actor/session, route scope, target, revision, action, request key, displayed paths and policy/card identity; typed values remain intended operator input.

The stored handoff is a snapshot of observed facts, gaps and reasons. Later owner correction does not rewrite that card. Legal qualification, price and confidence remain explicitly unknown where approved evidence is absent. The UI explicitly discloses that installed bot replies/reminders are not controlled by this interview. H04 and real channel stop/escalation behavior are therefore not approved or claimed by this review. Calendar-dependent near-expiry thresholds, approved source/privacy/consent/offer policies, real personal-data collection and production acceptance remain UNKNOWN/outside this synthetic target.

Re-review is required for the corrected immutable snapshot, particularly F1/F2 and changed terminal capacity. No r2 source or tests have been approved by this report.

## Re-review of corrected r2

Verdict: **FIX_REQUIRED for r2**, because of the additional confirmed F5 below. Original F1–F4 and C1 are addressed in this snapshot. The r1 observations/evidence above remain historical and have not been rewritten.

Target: `runs/e6-12-review-r2`, unchanged base `8575f1f278659cc0d92c8342dbf25262afce5dc7`; 22-file manifest `ai/reviews/2026-10-11-e6-12-snapshot-r2.json`, SHA-256 `9cff719c1c841bc45e65d0dc0b312293869e1df9c4b0f8286fc694794251d972`.

The reviewer examined the actual source delta before receiving builder result claims. A separate ignored execution copy, `runs/e6-12-reviewer-r2`, matched all 22 LF-normalized file hashes. Tests, browser output and recovery evidence below belong to that independent copy, not the shared builder/auditor output directory. Both the frozen target and reviewer copy still matched all manifest entries after testing.

### Closure of r1 findings

- **F1 addressed:** historical policy and header resolve an explicitly retained catalog digest, domain rules and native rendering receive the pinned document, and commands select the retained reducer version. The Docker image includes the immutable JSON catalog. Independent probes narrowed a new catalog's name-field maximum while leaving the old catalog retained: old long answers, old card/retry/ACK and later owner correction remained valid; new starts enforced the new maximum. Changing a valid signed form's catalog hash to another supported digest was rejected with HTTP 403; the unchanged original form and its exact retry succeeded. Existing unsupported-reducer checks reject new writes atomically. Future semantic engine changes must continue retaining their older implementation; a registry alone is not permission to reinterpret prior facts.
- **F2 addressed:** minimal withdrawal is durable in all four phases, leaves an existing frozen card untouched and blocks subsequent collection. Current/historical operator and CAS gates still apply. Both ACK-versus-withdrawal and owner-correction-versus-withdrawal were independently raced in both submission orders on SQLite and actual PostgreSQL. Exactly one original CAS command won; completing the remaining withdrawal/ACK retained the card, permanently blocked collection and rejected later corrections. Exact withdrawal retry returned its original result.
- **F3 addressed:** append and every replay prefix call the same state-aware count/byte capacity function. A third reserved event accommodates withdrawal after ACK, with dynamic reserve reduction after collection becomes permanently blocked. Independent probes rejected histories beyond either ordinary count or cumulative byte reserve, accepted the exact final handoff/ACK/withdrawal sequence and rejected a fresh-key repeated withdrawal without growing history. Builder-authored boundary tests were independently executed as well.
- **F4 addressed:** both fresh start and append authorize the exact timestamp they persist; append/replay also reject backwards time. Independently executed midnight and monotonic-time checks pass. Operational handoff/ACK/withdrawal remain available without a current collection policy.
- **C1 addressed:** the recovery test creates its output parent directory before writing evidence. The PostgreSQL recovery test passes in the reviewer's isolated execution copy.

### F5 — P2: repeating an unchanged fresh consent answer falsely withdraws consent

This additional issue was first reported by the separate auditor; the reviewer then wrote and ran an independent reproduction against exact r2. In `app/knowledge/interview_rules.py`, `apply_answers` unconditionally replaces an answer with the new revision/context even when its canonical value is identical and its existing context remains fresh. Repeating `correct(consent.given=True)` after consent date/reference/hash are complete therefore invalidates those dependent records. The domain interprets the resulting loss of complete consent as withdrawal, creates a handoff and permanently blocks collection.

Reproduction: start interview; save affirmative consent; save date/reference/hash; verify `consent_complete=True`; explicitly correct the already-fresh affirmative consent to the same `True`. `collection_blocked` unexpectedly becomes `True`. Own probe `runs/e612_r2_independent.py::test_identical_fresh_consent_is_not_withdrawal`: **FAIL**. Evidence `runs/e6-12-reviewer-r2/runs/reviewer-noop.xml` has SHA-256 `3d70b9ca50c9288174f22196d08683c26d9164dc7b1910e2b0db1a53928c1055`.

Required: preserve lineage when an existing answer is both fresh and canonically identical; preserve the explicit ability to reconfirm a stale answer with the same value and a new dependency context. Do not weaken real value-change invalidation, actual withdrawal, or historical replay. Verify these distinctions through domain and native forms; the final verdict belongs to the next exact snapshot.

### Independently executed r2 checks

All relative test paths below were executed from `runs/e6-12-reviewer-r2` unless prefixed with the guarded root PostgreSQL helper. Unique `--basetemp` and `--junitxml` arguments were used.

| Check | Result and reviewer artifact |
|---|---|
| Same six-module rules/domain/native/migration/shared regression command listed for r1 | **171 PASS, 2 SKIP**, 279.50s; `runs/reviewer-unit.xml` |
| `tests/test_entry_interview_postgres.py` through `python runs/e610_legacy_pg_probe.py runs/e6-12-reviewer-r2 ...` | **18 PASS**, 97.09s; `runs/reviewer-pg2.xml` |
| `tests/browser_kg_interviews.py` | **2 PASS**, 46.46s; `runs/reviewer-browser.xml`; resulting PDF has 3 nonempty pages |
| Own `../../runs/e612_r2_independent.py` before the later F5 probe was appended | **8 PASS**, 28.33s; `runs/reviewer-adversarial.xml` |
| Own `../../runs/e612_r2_independent_pg.py` through the guarded PostgreSQL helper | **8 PASS**, 60.89s; `runs/reviewer-adversarial-pg.xml` |
| Separately selected new identical-consent probe | **1 FAIL** as described in F5; `runs/reviewer-noop.xml` |

The first PostgreSQL invocation with a reviewer-selected nested `--basetemp` failed during fixture setup because that parent directory did not yet exist. No product test body executed; `reviewer-pg.xml` retains the 18 setup errors. A separate invocation after the parent existed produced the 18 PASS results in `reviewer-pg2.xml`. This reviewer command setup error is not hidden as a product pass and is separate from the resolved r1 C1 defect.

Independent recovery evidence: `runs/e6-12-reviewer-r2/runs/interview-postgres-recovery.json`, SHA-256 `f483447e4e0b40ca89142d1181f47ac3db494ec4b6b5af772fbaa8079ddb32e8`. It records unchanged card/ACK/history, exact old ACK retry, native read HTTP 200 and a successful subsequent owner answer after binary COPY recovery. The same local synthetic/production limitations as the r1 review apply. H04 and real external policies/channels remain unapproved. No r3 implementation has been reviewed in this section.

## Final independent re-review of r3

Verdict: **APPROVE for reviewed local synthetic scope**. There are no remaining identified implementation blockers within the typed local interview/journal/handoff scope. This does not supply the separate final audit, authorize deployment or approve real collection policies, qualification rules, prices or installed bot behavior.

Exact target: `runs/e6-12-review-r3`, base `8575f1f278659cc0d92c8342dbf25262afce5dc7`; manifest `ai/reviews/2026-10-11-e6-12-snapshot-r3.json`, SHA-256 `12a95658fb1518800249c097618dd0425847b2407f358d20af7d6b726431bf55`, 22 files. Independent execution copy: `runs/e6-12-reviewer-r3`. All 22 normalized file hashes matched in both the frozen target and review copy before/after verification.

The actual r2-to-r3 delta is five files: the answer reducer, its pure/domain/PostgreSQL tests, and the feature contract. The production-code delta validates the supplied value and applicability first, then skips reassignment only when the existing answer is fresh and canonically identical. Thus a boolean-like integer cannot bypass type checks; canonical country-list order changes do not invalidate dependent passport facts; a stale identical answer still receives a new revision/context and must be explicitly reconfirmed. Commands continue to be journaled and exact retries remain unchanged. F5 is closed by independent reproduction and negative controls. F1–F4/C1 closures were rechecked through the affected boundary tests and PostgreSQL suite.

### Exact r3 verification

The five connected domain intake goldens already exercised in r2 were deliberately excluded from this targeted rerun; they are not reported as fresh r3 results. The reducer's complete pure-rule module, all other domain/native tests and newly authored boundary probes were rerun. This avoids treating the old broad result as an exact-r3 run while focusing verification on the changed behavior.

| Command / environment | Result |
|---|---|
| From reviewer r3 copy: `python -m pytest -q tests/test_kg_interview_rules.py tests/test_entry_interviews.py tests/test_admin_kg_interviews.py ../../runs/e612_r2_independent.py ../../runs/e612_r3_delta.py --ignore-glob=none -k "not connected_golden_journal" --basetemp=runs/reviewer-core-tmp --junitxml=runs/reviewer-core.xml --tb=short` | **116 PASS**, 5 explicitly deselected, 168.45s |
| From root: `python runs/e610_legacy_pg_probe.py runs/e6-12-reviewer-r3 tests/test_entry_interview_postgres.py ../../runs/e612_r2_independent_pg.py ../../runs/e612_r3_delta_pg.py --basetemp=runs/reviewer-pg-tmp --junitxml=runs/reviewer-pg.xml --tb=short` | **28 PASS**, 157.77s; guarded local PostgreSQL only |
| Post-run manifest verification of frozen r3 and reviewer copy | **PASS**, no mismatches |

The 116-test run includes the previously failing independently authored unchanged-consent scenario, canonical reordering versus real parent changes, explicit stale-value reconfirmation, real native POST reaffirmation and exact retry, integer-for-boolean rejection without a write, and genuine false-consent withdrawal. The PostgreSQL run includes the native reaffirmation/withdrawal probe plus both CAS races, count/byte reserve replay, changed active catalog with preserved old types, signed catalog tamper, rollback/unknown commit, schema checks and recovery.

Independent r3 artifacts under `runs/e6-12-reviewer-r3/runs/`:

- `reviewer-core.xml`: SHA-256 `7425269894b2d1ee8a4477f2652023f7a9d1e63426cb72d6e177d1ae6ad445f7`.
- `reviewer-pg.xml`: SHA-256 `06cd737d1e866cc7488358e9531a5757735a684e35dbc2df770f592de6a2dab0`.
- `interview-postgres-recovery.json`: SHA-256 `0721d0466b5364a1d97cc6e76354cc365b46b2d17c065096cb8e6479f653b199`; unchanged card/ACK/history, original ACK retry, native read HTTP 200 and new owner answer after recovery all passed.

The no-JavaScript/mobile browser and print artifacts reported above belong to r2; those UI/template sources are identical in r3. Native HTTP and the changed consent behavior were tested again on exact r3. No Docker build, production backup certification, production operation or real customer acceptance is claimed.

### Criteria opinion requested by builder

This opinion uses the unchanged acceptance wording in `docs/pdf-engineering-criteria.json`, not a rewritten definition chosen to earn points. It is separate from approval of this bounded local feature.

| Criterion | Opinion for engineering evidence |
|---|---|
| **B03** — complete conditional A–H and specialist/family/employer branches | **PASS within local typed intake scope**: actual fields, own-applicant versus companions, conditions/staleness, typed native writes, source-code coverage and connected synthetic branch collection are demonstrated. It does not mean legal source/privacy approval. |
| **H01** — stateful RU/EN adapter, bounded questions, save/resume and revisions | **PASS within local adapter scope**: persisted native/domain flow, maximum three questions, language switching, pause/resume, revisions and retry are demonstrated. No claim that legacy chat dispatch already uses it. |
| **B04** — durable handoff plus automation stop | **UNKNOWN / partial evidence**: frozen facts/gaps/owner/ACK are demonstrated, but installed automation is not stopped. The acceptance includes that missing component. |
| **H02** — interrupts, stop factors and specialist escalation in dialogue flow | **UNKNOWN / partial evidence**: explicit typed interrupts and the implemented stop factors work in this adapter, but a connected client dialogue path covering the source section 4/17/Appendix B.6 triggers is not demonstrated. Calendar-dependent urgency and arbitrary client interruptions should not be promoted from manual controls to full dialogue-flow evidence. |
| **J02** — golden intake/qualification scenarios and adversarial uncertainty, Appendix B.8 | **UNKNOWN / partial evidence**: the five connected generic intake goldens and uncertainty probes are valuable, but the specific Appendix B.8 US-tourism-45-day, India-business-10-day and Uzbekistan-garment-work intake/qualification flows are not demonstrated here. Unapproved legal/price outputs correctly remain unknown. Do not treat generic intake completion alone as full source-scenario qualification coverage. |
| **H04** — manager ACK plus suppression of autonomous client replies | **UNKNOWN / unimplemented channel portion**, explicitly unscored. |

Real external source/privacy/consent/offer policy, retention/deletion decisions, channel enrollment/suppression, business acceptance and production remain UNKNOWN or outside this local target. The reviewed implementation leaves those gates explicit rather than inventing policy or enabling live operation.
