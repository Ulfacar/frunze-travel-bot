# E6-29C journal construction checkpoint

Auditor: `/root/e622_audit`. Date: 2026-10-12. Risk: CRITICAL / solo.
Target: source-first construction review before final connected composition,
not runtime approval. HEAD: `6775d30be496335fc0aad10f6d18e6debc98da25`;
the reviewed C files are uncommitted and were changing during this review.
There is no frozen acceptance candidate for this checkpoint.

**PARTIALLY_READY / final verification UNKNOWN.** Several concrete design gaps
were reported while the builder was implementing. Corrections to some are now
visible in source; none has been runtime-tested by this auditor. No PG, provider,
network, root environment, migration or application write was performed. Only
this report was written. H02 and the full C completion gate remain UNKNOWN.

## Basis and scope

Read the C task and the final incoming/reconciliation pre-audit, including the
new first-privacy-after-expiry addendum, then actual source. Relevant files:

- `app/domain/dialogue_journal.py`, `dialogue_session_policy.py`,
  `dialogue_reconciliation.py`, session/event models and migration0037;
- `app/knowledge/dialogue_reconciliation.py`, question renderer/parser and the
  retained interview reducer/catalogue;
- `current_stay_stops.py`'s new internal dialogue path and unchanged public
  exact-head path;
- newly appearing `dialogue_authority.py` and `dialogue_sessions.py` to check
  whether the proposed journal contracts were actually usable by composition;
- existing channel-stop/cause validators and interview terminal reserves.

The separate question-adapter APPROVE was not used as proof of this journal.
The journal explicitly does not grant current collection/send admission; this
review does not demand that historical records alone grant it. The findings
below concern the integrity and recovery claims made by those records and the
operations their contract must support.

## Findings and source corrections

### F1 — a rendered prompt was not tied to the real displayed drafts

Initial `history()` only regenerated the stored question renderer. A valid
renderer document for another allowed field, a subset of the full batch, or a
different language could pass that check for the named interview head. A
correct body hash does not prove that this was the real complete current batch.
The retained answer reducer eventually checks `operation.displayed`, but this
does not protect a stored prompt/claim before a subsequent answer exists.

Requested: link the prompt's exact head to the retained snapshot, require its
active/nonblocked phase, exact language and complete ordered draft paths, then
regenerate the exact body/options/labels. Keep the separate fresh admission
check immediately before provider invocation.

**SOURCE_CORRECTION_OBSERVED:** `history()` now performs these snapshot checks.
Runtime evidence remains UNKNOWN. Future negative controls: omit/reorder a
draft, change language, use another valid catalogue field, rehash the event;
reading/admission must refuse. The untouched complete batch must pass.

### F2 — terminal flags and optional IDs lacked causal validation

Initially a stop only checked scalar ID shapes and a nondecreasing head
revision. It could assert `collection_blocked=True` without checking the real
interview snapshot, or carry a foreign stop/cause ID. This was a durable
provenance gap even though the new journal was not yet a live send gate.

The separate expiry addendum correctly permits a C terminal suppressor without
creating an expired A latch. Null optional IDs are legitimate; they must not be
presented as evidence that an old latch exists.

**SOURCE_CORRECTION_OBSERVED:** the stop now declares
`suppression='persistent_session_terminal'`, records `observed` and `effect`,
and checks the actual retained interrupt's predecessor/operation/actor/time,
or the retained existing handoff, plus the actual collection flag. Provided
old stop/cause IDs are looked up and checked for the same route/interview.
The header also now retains channel authority/identity; the builder reports
the explicit retained privacy grant being added in this same work stream.

Still require the final causal schema and tests: raw triage, typed answer,
current-check and context failure must be distinguishable; their reason and
input/evidence links must be validated. A hash of arbitrary JSON must not make
it an authentic current-check packet. Rehashed false collection flags,
different actual before/after heads, foreign optional links and mismatched
trigger evidence must be refused. This checkpoint does not certify that the
whole evolving causal format is complete.

### F3 — the ordinary reserve also blocked first nonprivacy interruption

Original `append()` reserved six events for every nonprivacy turn. At the
ordinary limit `MAX_EVENTS-6`, the first urgent nonprivacy interrupt could not
append its input turn, although the reserve was meant to preserve a first stop
and later privacy recovery. The same issue applied to the byte reserve.

**SOURCE_CORRECTION_OBSERVED:** ordinary events retain six slots; nonprivacy
interrupt turns retain four; privacy turns retain one; stop/outcome events can
consume the reserve. This supports the intended interrupt-turn/stop pair while
retaining room for later privacy and an outstanding outcome. Actual count and
byte-limit sequences remain UNKNOWN until exercised through the composer.

Also test the boundary immediately after a prepared prompt and before claim:
the last ordinary slot must not leave an unresolvable partial send preparation.
Capacity failure must never cause legacy fallback, resend, or a false terminal
success receipt. All effect/receipt writes need one transaction.

An initial concern about the union of manual stop routes and session routes was
explicitly narrowed after the expiry addendum: reserving old latch/cause slots
is necessary only if composition depends on creating them. C's own durable
terminal suppressor can make those optional. Do not impose an unnecessary old
registry reservation, and do not silently promise that an optional old latch
was created at capacity.

### F4 — privacy after a native head advance initially failed CAS

The newly written composer exposed a concrete source sequence:

1. A C stop records the interview's pending head.
2. The native owner ACK advances that interview head.
3. A later first privacy withdrawal uses the actual ACK head as `turn.before`.
4. The journal reducer requires `turn.before == flow.head`, still the earlier
   pending head, so the transaction fails before the privacy effect is saved.

The same mismatch follows an out-of-band correction/refresh while enrolled.
Ordinary reconciliation must refuse those changes, but this must not erase an
operational withdrawal.

**SOURCE_CORRECTION_OBSERVED:** an interrupt input turn now names the unchanged
last reconciled flow head; the distinct stop `observed` names the actual native
head and `head` names its verified effect. This does not pretend the native
event is an ordinary answer from this session. Required runtime controls:
pending -> ACK -> privacy; native correction -> privacy; active/paused/already
blocked variants; missing/expired current collection policy; exact retry; the
original handoff remains intact and no current actor revocation is bypassed.

### F5 — early terminal paths dropped incoming idempotency evidence

The observed `receive()` called `_stop()` directly on native-head drift and
current-check/collection failure before adding a `turn`. Consequently the
triggering provider message key and full envelope hash were absent from
`flow.turns` and the terminal evidence. A repeated packet did not identify its
original causal receipt; changing text/voice/media under that same provider ID
could take the stopped-session shortcut instead of conflicting.

**FIX_REQUIRED at the last inspected implementation of these branches.** The
builder acknowledged it and is adding a shared terminal-input helper. Every
input-triggered terminal path must retain the original key and envelope hash
exactly once. Internal/no-input stops need an explicit separate form. After
stopping, replay of any original key must still check its original input hash;
new unrelated packets must not consume unbounded terminal capacity. No retest
or completed correction is claimed here.

### F6 — retain the referenced check evidence, not just a free hash

The inspected header stores six `baseline_check` hashes; prompt/claim records
contain a `check_hash`. The header cross-checks fact/profile/history/head pins,
but `evidence_hash` and `source_hash` have no retained canonical baseline result
against which to verify the claim. The new reconciliation result includes an
explicit original/current head and tail proof, so its immutable reference also
needs to remain inspectable after the original call returns.

Requested: a bounded versioned check packet, or a validated immutable reference
to one, for baseline/prompt/admission evidence. Bind result status, authority,
source/profile/history/fact/head and reconciliation pins. If a compact packet
omits arithmetic, make its separate digest/meaning explicit and keep the
original calculation digest and inputs traceable. A bare 64-character string
must not be displayed or validated as proof that baseline checks succeeded.
This is an evidence-contract follow-up, not a claim of an observed live
collection bypass. Implementation and recovery tests remain UNKNOWN.

## Structural assessment of reconciliation and storage

The inspected ordinary reconciliation has the right basic separation: it
retains the original fact and baseline, reads the actual interview chain,
requires the current flow head to equal the real latest event, rejects stopped
flows, reconstructs fresh consent/typed analysis and exact drafts, requires
every post-baseline event to be an ordinary answer backed by this session's
own turn, and checks full tail cardinality. The explicit material/nonmaterial
map rejects unclassified fields; its catalogue/map hashes are separately
authorized. The original public E629B path still requires an exact current
attestation head. No copied attestation or caller-supplied reconciled boolean
was found in these inspected paths.

These are source observations, not PASS evidence. Verify missing/extra or
foreign turns, altered retained actor/time/operation, valid native answers
without a session receipt, baseline outside ancestry, changed profile/history,
stale dependency stamps, unknown catalogue/map and actual in-KG positive
progress. One receipt per exact full displayed batch must stay necessary.

Models and migration0037 have matching session/event fields, unique route and
interview binding, a composite subject FK, per-session revision/request-key
uniqueness, bounded revision checks, and inclusion in ORM immutability guards.
The ordinary predecessor FK is supplemented by the runtime exact same-session
chain check. Populated downgrade is designed to refuse under a write lock;
offline downgrade refuses. Actual SQLite/PG constraint parity, migration,
rollback/recovery and populated downgrade remain UNKNOWN; no DB was opened.

The entire bounded header registry is validated before lookup. The requested
session's bounded event chain is validated separately; do not load every
16-MiB chain for each send. Verify oversized JSON before decode and the actual
UTF-8 serialized-byte limits, corruption on negative lookups, and coherent
route/capacity/case/applicant/publication lock order in final composition.

## Revision and evidence limits

Read-only commands were `Get-Content`, `rg`, Git status/history/diff and
`Get-FileHash`. A moving-tree checkpoint captured these raw SHA256 values:

| File | Raw SHA256 |
|---|---|
| `dialogue_journal.py` | `e8c8d836d9d0a06c255964ef2691f0d3aa9488b5c86f3bfa278fd0121d45ae8e` |
| `dialogue_session_policy.py` | `f551e41bf5fe4c805b4ff1ff2d590c3e4583232ca10911e2272fedaa25ede6d4` |
| domain `dialogue_reconciliation.py` | `37d49842e5a3fc2593cce0ff9dc08cb4f28277256373b7d05391a09f65e2a282` |
| knowledge `dialogue_reconciliation.py` | `209887e53f6ff91634b448d2b79f6ea46f0ea4107ffd1f6458f382fcea1fae83` |
| `dialogue_authority.py` | `98867c6b42caad7e52d6d24636ab710f23cca37a9e5d8557f05b71b08a1ddeb4` |
| `dialogue_sessions.py` | `809ab6fbb0bb9516239d4f61ac50436316f1e4dd14927c7f4da0fb9f05e328b9` |
| `current_stay_stops.py` | `223ec5c6912aa4970b48b5decffa40bca0f2834490e1b67fce94ccd47019926f` |
| `models.py` | `b0a2e371002f4de838c90a1a9cc0e400e83eebe53ea4a908de94a91b175790a0` |
| migration0037 | `f2e56160dba0dbc0633a753a625b703bded9050d770535471e6abb46bb193eaf` |

These hashes identify source observations during ongoing edits, not an atomic
snapshot or final candidate. Original findings above predate some of these
hashes; they are retained as construction findings, not invented failing test
results. A later frozen candidate requires its own exact identity manifest,
adversarial checks, independent review and separate final audit. No GO, H02
points, legal/source/privacy approval, deployment or real message is granted.
