# E6-29A atomic interruption component — independent APPROVE

Reviewer `/root/calculation_review`, 2026-10-12. CRITICAL / solo.
Final verdict: **APPROVE** for frozen R5 runtime/migration exactly mapped to R6
and current root. R2 was FIX_REQUIRED; all original privacy failures and added
controls now pass. No confirmed runtime defect remains after R5. This approves
the reviewed local E6-29A component, with separate final audit still a distinct
protocol gate.
This is not full H02 approval. No incoming orchestrator hook, normal-answer
adapter or current-stay/calendar evaluator is approved by this review.

## Requirement and source-first scope

Read the E6-29 task, independent risk pre-audit and design addendum, protocol,
project boundary and actual new implementation before builder conclusions.
Inspected `dialogue_interrupts.py`, `dialogue_policy.py`, `dialogue_stops.py`,
the new `EntryDialogueStopCause` model/migration0036 and the extracted channel
save helper. Also read retained interview reducers/history/capacity and the
existing channel registry, locks, context, binding and send contract.
The later explicit component card is
`ai/tasks/2026-10-12-e6-29a-atomic-interruption.md`; its separation of component
completion from unchanged full H02 acceptance is appropriate.

R2 snapshot is `runs/e6-29-r2/snapshot.json`, base
`b10012e8b5a9f50989c725fc77c270b64b045dce`, 12 overlays. Own env-free archive is
`runs/e6-29-review-r2`; all overlay LF hashes were checked during creation.
Root runtime was read-only. Own probes use synthetic SQLite through existing
domain APIs; no `.env`, real data, live service, external message or PG used.

The slice composes one accepted interruption with the retained interview,
existing permanent exact-route latch and a new bounded immutable cause. It
explicitly does not admit ordinary answers or send messages. Trusted server
delegation pins route/case/person/interview/Dialog and existing operator;
payer/contact identity is not used to select an applicant.

## Confirmed P1: privacy request discarded by input guards

Frozen R2 `triage` returns `uncertain_answer` before examining privacy wording
when a text exceeds 2048 characters, is marked voice, or contains a control
character. After the first connected handoff and owner ACK, `record_interrupt`
treats this as an ordinary already-stopped message and returns the earlier
cause, whose `collection_blocked` remains false. No consent withdrawal is
appended. An actual subsequent owner personal-data correction succeeds.

Independent ordinary-flow reproductions:

1. Start interview, bind a raw manager interruption, ACK.
2. Submit `I revoke consent to storing my data` with either a long synthetic
   explanation, `voice=True`, or a trailing NUL.
3. All three leave collection unblocked. The same short plain text is a
   positive control and correctly blocks it.
4. Separate end-to-end probe submits an oversized `Delete my data...` message
   and then successfully saves owner `applicant.age=31`; expected collection
   rejection does not occur. This establishes a real collection effect, not
   merely an old receipt display.

Original evidence is preserved in own `tests/test_review_dialogue_domain.py`,
`review-domain.xml` and `review-extra.xml`. Root accepted the finding. An
intermediate uncommitted correction moved only generic privacy-topic matching
before guards. A further independent pure probe found that explicit phrases
without those keywords, including `Do not store this`, `Stop collecting
information about me`, `Не храните информацию обо мне`, `Не собирайте ничего
больше` and `Revoke permission to process these records`, still changed from
plain `consent_withdrawn` to voice/oversize `uncertain_answer`. This was the same
guard-precedence defect, not a separate downstream issue.

R5 moves complete withdrawal and consent-question recognition before the input
guards, strips invisible controls for detection and records unsupported privacy
instructions as `possible_privacy_stop`. It does not admit them as ordinary
answers or claim legal revocation/deletion. Original connected repros, additional
non-keyword/invisible-control cases and actual denied owner correction now PASS.

## Independent runtime evidence

Both commands ran sequentially in the own R2 archive:

| Command/scenario | Actual result | Interpretation |
|---|---|---|
| `python -X utf8 -m pytest tests/test_review_dialogue_domain.py -q --basetemp .pytest-review-domain --junitxml=review-domain.xml -p no:cacheprovider` | 4 PASS / 3 FAIL, 17.64 s | Plain privacy positive; unrelated corrupt-cause negative lookup/recovery; post-Dialog-lock expiry rollback; terminal reserve after actual clock expiry PASS. Three privacy guard failures above. |
| Same test file, `-k 'actual_owner or combined_interview'`, `.pytest-review-extra`, `review-extra.xml` | 1 PASS / 1 FAIL, 10.38 s | Combined terminal reserve PASS; actual post-refusal owner collection is the confirmed failure. |
| Own R5 archive, same file, `.pytest-review-corrected`, `review-corrected.xml` | 17 PASS, 41.24 s | All original controls, seven connected privacy shapes, actual blocked owner collection, five pure unsupported/consent-question controls, corruption/recovery, clock crossing and both reserve controls. |

Combined reserve uses `MAX_EVENTS=4`, `MAX_CAUSES=2` and actual
start→interrupt→ACK→withdrawal writes; it reaches four interview events and two
causes, preserves the first exact receipt and still suppresses sends. The
expiry control advances the clock to 2027-01-02, beyond both original policies,
then successfully records terminal withdrawal using stored delegation, checks
exact retries and rejects changed content under the terminal message ID.

The clock-crossing control keeps initial service time valid but advances the
clock sampled after acquiring the Dialog to expiry; all attempted writes roll
back and the interview remains active. A corrupted cause also prevents an
unassigned negative route lookup until the original hash is restored.

Own corrected archive `runs/e6-29-review-r5` preserves base b10012e and all 17
verified R5 overlays. R5 manifest LF SHA256 is
`7bfc7ea176796d1636b480d3ba1ad0942dfd6b92c69471d080e94a4ec8112e2b`.
No own test process remains. The original failed R2 artifacts were not replaced.

R6 adds a browser test only; its runtime and migration hashes are identical to
R5 and independently match current root. Its 18-file manifest LF SHA256 is
`536520f3b988b78976c7dcd4ccf5fc2f2803580fbda29ecb27c6cbcc76e3bfc4`.

Byte comparison confirms unchanged base versions of `entry_interviews.py`,
`interview_rules.py`, `entry_channel_policy.py` and `kg_channel_guard.py` in R2;
R2 channel AST changes are limited to `_context`, `bind_stop` and the new
`_save_stop_in_session`. R5 additionally reads validated cause history for the
existing protected native channel page. Its reason text is operator review
context, not a client fact or manager acceptance. Existing RU-only page evidence
does not establish the full parent's RU/EN incoming-dialogue requirement.

## Inspected builder evidence

The following are completed builder executions, independently parsed as XML
and inspected against actual test source; they are not reviewer executions:

| Artifact | Actual result | Scope |
|---|---|---|
| `runs/e6-29-r5/runs/e629-r5-domain-native.xml` | 134 PASS, 73.559 s; zero errors/skips | Pure triage, connected domain and native cause controls |
| `runs/e6-29-r5/runs/e629-r5-pg.xml` | 14 PASS, 60.444 s; zero errors/skips | Actual synthetic PostgreSQL, both send/stop linearizations, three-write rollback, exact retry, terminal reserve, corruption/restore, real migrated schema/FK/parity/populated-downgrade protection, lost before/after commit acknowledgement |
| `runs/e6-29-r3/runs/e629-r3-migration-native.xml` | 29 PASS / 2 SKIP, 46.101 s | Additive SQLite migration/parity and old protected native page compatibility; two optional prior PG-tier tests explicitly skipped |
| `runs/e6-29-r3/runs/e629-r3-pg.xml` | 11 PASS, 45.486 s | Earlier actual PG domain/linearization evidence; final R5 PG supersedes it for those paths |
| `runs/e6-29-r6/runs/e629-r6-browser.xml` | 2 PASS, 19.138 s; zero errors/skips | Actual Chromium 390px and 1365px/no-JS, two cause records including ambiguous privacy hold, no raw message exposure, no horizontal overflow and print text preservation |

The R5 PG test observes real `pg_stat_activity` lock waits. Send-first permits
the one callback admitted before the writer, then suppresses the next; stop-first
holds the sender until commit and never invokes its callback. This is the actual
linearization contract, not a claim that an already admitted provider request
can be retracted. No real provider is called.

The PG migration test downgrades an empty synthetic database to 0035, upgrades
through 0036, compares real schema metadata, rejects invalid subject/event/stop
references and revision/previous links, refuses populated downgrade, then
replays the exact receipt and verifies suppression. SQLite cycles additionally
preserve a sentinel contact and existing table definitions. The two optional
skips are not converted to PASS; the explicit R5 actual PG evidence establishes
the newly affected migration behavior.

R5 domain/native XML SHA256:
`a98affab09098a856d395639f0d6bf73831e292bae821ab207ac54833d588477`.
R5 PG XML SHA256:
`a2c4540bb7c92abd3061ff5df8ac69786d2f2ff2cf7114e40d76d696c298907f`.

R6 browser XML SHA256:
`0d1f9c02d3d4737a9d3fd4fafeeafe1b09ede5091e4361d83dbbcd3e88aad212`.
Reviewer independently viewed `runs/e6-29-r6/runs/e629-browser/causes-390.png`
and both `print-390-1.png` / `print-390-2.png`: clear reason/collection-stop
labels, no clipped card text and explicit no-deletion/no-ACK implications.
PyMuPDF independently confirms both generated PDFs have exactly two nonblank
pages (text lengths 1231 and 292), preserving whole cause cards. The second page
is intentional card preservation, not a claimed one-page result. No quantitative
contrast audit or new English page is claimed by this browser evidence.

## Source observations and component acceptance

- Existing route/capacity/case/Dialog lock order is reused. New events and cause
  use the post-Dialog-lock timestamp. PostgreSQL concurrency is not established
  by the SQLite controls; it is established separately by the actual PG
  evidence above. Reviewer did not run a duplicate PG suite.
- Exact stored message key/body hash retries return frozen receipts; changed
  body conflicts. Returning an old cause is historical evidence, not a fresh
  statement that consent collection is allowed; later integration must honor
  the retained current interview block.
- Two cause revisions per route and half-registry admission reserve a later
  withdrawal. Existing interview terminal reserves remain intact. The new
  migration adds constraints and refuses populated downgrade; independent
  inspection of actual migration/PG evidence is complete.
- Cause validation checks bounded journal, hash chain, exact delegated subject,
  stop anchor, complete interview replay, event/actor/time links and terminal
  second-revision semantics. Existing channel v1 anchors and frozen handoff
  remain unchanged. Corruption must stay an error, not a fallback admission.
- Corrected frozen controls, source inspection and final migration/PG/native/
  browser identity mapping are complete. Separate final audit remains a
  distinct gate. Full H02 remains UNKNOWN after this component approval.

| E6-29A requirement | Review conclusion |
|---|---|
| Exact trusted route/person/operator authority | Explicit immutable policy pins subject, header and existing operator; wrong assignment/current access negatives pass. No payer-to-applicant inference or real assignment installed. |
| Atomic raw interruption, retained handoff, permanent stop and cause | Normal connected controls, all-three-write rollback, lost commit recovery and both actual PG send linearizations pass. No provider invocation inside writer. |
| Historical card/retry and terminal collection refusal | Pending/paused/ACKed card controls pass; exact first receipt remains immutable. Original privacy failure is fixed including unsupported input. Actual owner collection is rejected. Count/byte reserves and unchanged old reducers preserve terminal handling. |
| Integrity, time and recovery | Full cause/interview replay and anchors are validated; corruption and negative lookup fail closed; restoration/exact retry pass. Post-Dialog-lock policy crossing rolls back. Stored delegation permits a terminal stop after actual expiry. |
| Additive storage and protected operator view | Migrated PG schema/FK/parity and populated downgrade refusal pass; SQLite migration preserves unrelated data. Protected native compatibility and rendered mobile/no-JS/print pass; no raw message or fabricated manager acceptance/deletion is displayed. |

Boundary retained: first cause plus one terminal collection cause is the
bounded durable journal; subsequent messages on an already stopped route do
not become a new general-purpose message history. A frozen receipt flag is not
current permission to collect. Failures/capacity rejection must not become
normal-answer admission in any future incoming adapter.

No incoming orchestrator hook, meaningful normal typed-answer path, approved
current-calendar threshold or observed-stay STOP12 evaluation exists in this
component. No H02 points, all-source dialogue completion, live activation,
production migration, real policy/privacy approval or external delivery follows.
Final disposition: **APPROVE reviewed local E6-29A; full E6-29/H02 remains
IMPLEMENTING / UNKNOWN; separate final audit required.**
