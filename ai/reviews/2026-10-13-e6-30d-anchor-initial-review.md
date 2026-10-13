# E630D — initial anchor stream and pure deadline contracts

Independent source-first CRITICAL component review, `calculation_review`, 2026-10-13.

**R2 correction verdict: APPROVE for the bounded anchor domain component under the demonstrated SQLite scope.** R1 was **FIX_REQUIRED**; its genuine failures remain below. No confirmed anchor-stream defect remains after the corrective checks. Conditional receipt/task integration, configuration and native UI do not yet exist in this snapshot; this is not a whole-D gate. Migration execution, real PostgreSQL, recovery and the final whole-task audit remain pending, not waived by this component verdict.

Requirements read first: `ai/tasks/2026-10-13-e6-30d-actual-anchors.md`, the preceding source-first pre-audit, original §13.2 / §19.9–19.12 PDF. Actual code inspected before builder results: `entry_anchor_rules.py`, `entry_anchors.py`, `conditional_deadline_rules.py`, `EntryAnchorEvent` and migration0042; adjacent profile/application/document/issued semantics.

Frozen target: `runs/e6-30d-r1`, base `0398bfdd372ecc9e946787913f5b849535075034`, 47 overlays. Own verified env-free Git archive: `runs/e6-30d-anchor-review-r1`; manifest LF SHA256 `df01a7b86e861a66b98dc4dedacd6db400ee2742504be56b1c194944abcf82e8`. Root runtime was not changed or imported; no private environment, PostgreSQL or external service was used.

## Confirmed failures

### A1 — actual passport replacement does not invalidate the old period

Record a genuine own REG period with passport reference `b…`, then record the same application's actual `passport_change` from `b…` to `f…` on the following date. Both observations remain `usable=True`. The current view verifies profile/application and quarantine but does not reconcile active period passport identity with recorded passport-change facts.

The paired cross-application variant also fails: another person's REG passport change correctly leaves the subject's EP period usable, but the **same person's separate REG** passport change also leaves the EP period usable. Since passport-change anchors are supported only under registration, a same-stream-only correction would miss EP/RES periods. Preserve own-person scope and make later reviewed period recovery explicit; withdrawing the change must not silently prove the old passport current again.

This is actual current evidence inconsistency, not only missing coverage. Old exact receipts must remain unchanged when the current overlay becomes unusable.

### A2 — pre-lock date validation can commit an unreadable future observation

The public writer normalizes against `apps._today()` before locking, then captures `_now()` under the lock without repeating normalization against that captured local date. Inject a one-day clock reversal between those reads, with all actual source rows already created: a future `operation.data.on` is committed. Historical validation normalizes against the persisted earlier `created_at`, so this admitted event cannot satisfy the reader's own invariant.

Independent negative expected precommit refusal and failed because the writer returned successfully. Revalidate against the captured post-lock date before mutation; preserve exact historical retry behavior before applying fresh current-policy gates.

### A3 — an already-existing equal-time profile successor can be omitted from historical evidence

Create profiles1 and2 before the anchor, both with the same timestamp as the anchor. Normal write correctly selects profile2. Rewrite only the anchor command/evidence to profile1 and recompute its request/payload hashes. The history reader accepts the semantically stale source selection because `selected()` rejects only successors with `created_at < at`.

The current view separately reports `profile_changed`, so this is a historical provenance failure, **not a demonstrated currently usable-date bypass**. A correction must also preserve a genuine later-source/same-clock original receipt: blindly changing `<` to `<=` risks invalidating a legitimate historical receipt after a later transaction. Parent is implementing an independently retained scope-bound source pin.

## Independent execution evidence

| Artifact in own R1 archive | Actual result | Meaning |
|---|---|---|
| `runs/reviewer-anchors-r1.xml` | 3 FAIL / 12.04s | A1 and A2 genuine; third failed during attempted ORM corruption injection because immutable bulk-write protection correctly blocked the harness. That third result is not evidence of A3. |
| `runs/reviewer-equal-time-r1.xml` | 1 FAIL / 7.09s | Corrected raw-connection injection; genuine A3 with ordinary positive write/read control before tampering. |
| `runs/reviewer-person-passport-r1.xml` | 1 FAIL / 7.70s | A1 same-person cross-application failure after the other-person positive control. |
| `runs/reviewer-anchor-reserves-r1.xml` | 2 PASS / 17.76s | Actual count and byte reserves, described below. |

Capacity checks use declared production limits, not reduced monkeypatched limits:

- Real64 records on one active key → ordinary record65 refused → withdrawal65 succeeds with `policy=None`; original record retry and withdrawal retry remain exact.
- Real serialized-byte exhaustion with all16 active keys and a valid20-operator authority happens before64 records. Every one of the16 remaining keys can then be withdrawn with no current policy, and the current view contains only withdrawn observations.

These PASS results support the initial reserve design only. They do not erase A1–A3 or prove final corrected model/migration/PG integration.

Promotable tests: `tests/test_reviewer_actual_anchors.py` and `tests/test_reviewer_anchor_reserves.py` in the own archive. The original first harness is retained separately as `runs/reviewer_actual_anchors_initial.py`; all failure XMLs remain intact.

## Source-contract caution for the next integration

`KG.DL.EXIT_AFTER_EP_END` retains the §13.2 meaning “departure after termination of the EP.” Its initial pure mapping uses `employment_ended`, the WX1 dismissal observation. Actual dismissal, a request to annul and effective EP termination must not become interchangeable facts. Either use a distinct actual permit-termination anchor for the retained unit, or give conditional WX1 planning its own explicitly pinned SOP identity. Do not promote the resulting internal reminder into legal departure permission/deadline. This is an early mapping concern; there is no connected consumer exploit in R1 yet.

The remainder of the closed rule definitions preserves original null source units and separate internal-clause identities. Final integration must prove exact publication/source/calendar/currentness enforcement, actual EAEU period classification without manufacturing a duration, earliest concurrent-change handling, and actual absence review-trigger semantics. The pure helper alone cannot satisfy those gates.

## R2 correction and exact identity

R2 adds an independent immutable `EntryAnchorPin` retaining the original receipt hash and scope-bound profile/application-event/issued IDs, with composite FKs; a single rehashed receipt cannot silently change those identities. It repeats operation-date validation against the captured post-lock time and defers fresh cutoff checks until after an exact old retry is resolved. Current passport observations validate same-person histories across applications, exclude another person, require a fresh period with the latest replacement identity, and preserve uncertainty after withdrawal of a later replacement.

The source caution is addressed structurally: `KG.DL.EXIT_AFTER_EP_END` now requires distinct `permit_terminated`, while `KG.DL.INTERNAL_DISMISSAL_EXIT_PLAN` explicitly describes the conditional WX1 employment-dismissal planning calculation. Connected applicability of both remains an integration gate.

Own final archive: `runs/e6-30d-anchor-review-r2`, same base, all47 overlays verified. Manifest LF SHA256 `08e90bc373d71a005783c2192b88900fe718bd531d437d0dffab53d62d234eb3`.

| Scoped file / portion | LF SHA256 |
|---|---|
| `app/domain/entry_anchor_rules.py` | `7d12b4bce8e2130892e47e817cf0b6b1b620cc9d1a734b3df86fd79b7e330406` |
| `app/domain/entry_anchors.py` | `0a996ac3770b53e202ff7e3b57bbcaa5fd9b6a23bc4066a03d3f83f7a1da064c` |
| `app/domain/conditional_deadline_rules.py` — pure source contract inspected, connected consumer not yet present | `dab1c2600ec07bb7db9c5611713899419dce9df6f728dfa8f48ad76fc541208f` |
| `app/domain/models.py` — only `EntryAnchorEvent`, `EntryAnchorPin`, immutable registration | `02e9fe10f9b0b18db7d708c0d5928038df9ee4a28c3a6ecd11c2fefc76b53039` |
| `alembic/versions/e6_actual_anchor_events_0042.py` — source inspection, execution pending | `c59b21ce71dc6a87f5d996506f5cb6601c8bef686fdb6d700c5a66139f93d9c8` |

`runs/reviewer-anchors-r2-corrected.xml`: **8 PASS**,0 failures/errors/skips,32.271s; SHA256 `45c296742a06d888657a6a85309b184b7aa7a0f16b5a554a7da77a2d7124b1c3`. All4 original negative test identities pass unchanged. Additional controls prove a genuine later same-timestamp profile preserves original exact retry and permits new confirmation; old-passport re-confirmation fails, new-passport period succeeds, and a later withdrawn replacement does not restore the stale period. Both genuine count/byte reserve controls pass with the new pins.

`runs/reviewer-anchor-atomicity-r2-corrected.xml`: **1 PASS**,0 failures/errors/skips,7.909s; SHA256 `c62f67e552b586a19c26ff65b62f74affbb1e85c5528dc905bb902b805fca894`. Inject failure at the actual SQL pin INSERT, after the event INSERT: both tables remain empty, and the same command subsequently creates exactly one event+pin and exact retry succeeds. The initial run `runs/reviewer-anchor-atomicity-r2.xml` is preserved as **one reviewer oracle error**: it expected the injected RuntimeError rather than the existing storage wrapper's intentional `EntryStorageUnavailable`. No runtime defect was inferred from that failed oracle.

All evidence above was independently executed in the env-free archive. No PG or reviewer process is active. Promotable R2 files additionally include `tests/test_reviewer_anchor_correction_controls.py` and `tests/test_reviewer_anchor_atomicity.py`.

## Next gate

Continue source-first review of conditional integration/native, then required schema/PG/recovery and separate final audit. Pure arithmetic has not by itself established source applicability or current publication authority. No whole-D, whole-C, legal/source or production approval is given here.
