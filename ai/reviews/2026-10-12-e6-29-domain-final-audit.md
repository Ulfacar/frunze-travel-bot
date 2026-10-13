# E6-29A — separate final audit of atomic dialogue interruption

Auditor `/root/e622_audit`, separate from builder `/root` and reviewer
`/root/calculation_review`. 2026-10-12, CRITICAL / solo, reviewed local component.
**Final: GO for the exact R6 reviewed local E6-29A component.** The separate
review is APPROVE and all component acceptance gates below have evidence.
No full H02 or production approval follows from this component.

## Requirement and exact candidate

Read parent `ai/tasks/2026-10-12-e6-29-dialogue-escalation.md`, source-first
`ai/reviews/2026-10-12-e6-29-pre-audit.md` including its normal-turn and
calendar/observed-history addendum, then actual runtime/model/migration/native
code before reviewer conclusions. The later explicit component card
`ai/tasks/2026-10-12-e6-29a-atomic-interruption.md` accurately narrows this
completion target without changing H02. Relevant supplied-PDF requirements
are section4 stops, section17's 57 exception rows and Appendix Б.6; the
pre-audit's full parent coverage matrix remains required for later H02 work.

Final candidate `runs/e6-29-r6`, base
`b10012e8b5a9f50989c725fc77c270b64b045dce`, **18/18 normalized-LF overlay
hashes verified**. Raw manifest SHA-256
`4d13308c746a3565c09488dffbf2474b2eb321b4dbc99e77e4351d67b67e8d3e`.
The only R5→R6 delta is `tests/browser_kg_dialogue_stops.py`; all runtime is
identical. **14/14 scoped root files matched R6** at final identity inspection.
Pre-audit documentation and unrelated `base.html`, `boards.html` and
`test_admin_new_look.py` overlays are recorded but not approved as changes here.

Auditor execution used a separate Git archive of the base plus all verified
R5 overlays, `runs/e6-29-audit-r5`; no `.env`. R5 raw manifest SHA-256
`c76847b9faf1f7be27771944f14c310ee8a64f312993a085ed06f90a27bd6301`.
These executions map to unchanged R6 runtime; they are not labeled R6 reruns.
Identity and XML evidence are in
`runs/e6-29-audit-r5/runs/final-identities-r6.json`.

## Source-first findings

- **Authority and subject:** immutable `DialoguePolicy/1` supplies one exact
  route/case/applicant/interview/Dialog assignment, pinned header and retained
  interview/channel policy hashes, actor, provenance and dates. Route uniqueness,
  strict IDs and current full-admin/operator checks prevent payer-based person
  inference. No client-facing policy injection or real assignment is installed.
  The receipt stores only its delegated assignment and original deployed-policy
  digest; proof strings are server provenance, not independently verified legal
  signatures.
- **Atomicity and chronology:** route writer lock → global registry capacity →
  case → Dialog order is reused. The timestamp after Dialog waits is used for
  the new event/latch/cause and policy is checked again. Interview interrupt,
  existing permanent latch and cause share one transaction. No provider callback
  occurs inside the writer. A send already admitted first may finish once;
  stop-first prevents subsequent provider invocation. No retraction is promised.
- **Retained semantics:** active/paused receives the retained interrupt action;
  pending/ACKed retains its frozen card. The original v1 channel validator is
  unchanged: the new latch observes the already-pending interrupt event, while
  old manual binds still observe active/paused and append generic handoff.
  Historic `channel_suppression=not_integrated` remains untouched.
- **Privacy and uncertainty:** arbitrary unrecognized input is not admitted as
  an ordinary answer. RU/EN exception labels are possible review topics, not
  established facts. Complete collection-stop detection now precedes voice,
  control-character and soft text-length guards. Ambiguous/unsupported privacy
  text records a possible privacy hold and blocks collection, without claiming
  legal revocation or deletion. The domain input has a separate hard 65,536
  character bound; invalid envelopes raise rather than authorizing fallthrough.
- **Historical versus current:** duplicate provider key and unchanged body return
  the original immutable receipt; changed body conflicts. The original receipt's
  collection flag is historical, not current collection permission. After a
  committed first cause, stored delegation permits only the reserved later
  withdrawal even if policy is expired/removed; current access still applies.
  Full validated interview state determines current collection permission.
- **Bounds and integrity:** maximum128 initially represented routes and256 cause
  rows, at most two per route; each canonical row ≤64KiB and aggregate ≤16MiB.
  One second receipt is reserved for later collection stop, and existing interview
  terminal reserves remain. SQL size/count checks precede cause decoding. Full
  chain, exact delegated subject, retained interview replay, event/actor/time,
  stop anchor, previous hash and revision2 withdrawal semantics are checked.
  Corruption remains an error. The separate permanent latch independently
  suppresses sends if its anchors remain valid.
- **Migration/native:**0036 adds one constrained table, subject composite FK,
  event/stop/previous references, revision/request uniqueness and ORM immutable
  guards. Empty downgrade is supported; populated/offline downgrade refuses
  before dropping evidence. Existing protected native page adds validated causes,
  escaped labels, possible-source row references and explicit no-ACK/no-deletion
  wording. Raw incoming message text is not stored/displayed in this new journal.

## Auditor's own actual PostgreSQL checks

One serial process, guarded loopback fixture using
`FRUNZE_LOCAL_PG_CONNECTION` and uniquely named disposable migrated synthetic
databases. No credential value was printed, no real data used. Command in the
own archive:

```text
python -m pytest tests/test_auditor_dialogue_component.py -q --tb=short --junitxml=runs/e629-audit-pg.xml --basetemp=C:/Users/alanb/AppData/Local/Temp/e629-audit-r5
```

**6 PASS, 30.82s, exit0; no failures/errors/skips, one existing dependency
deprecation warning.** JUnit SHA-256
`92b547cbc27135f2de2deda4b29bae24e649030d8a7dd296adc73a0f8d946003`.

1. Loaded the complete actual `entry_channel_stops.py` from Git b10012e as an
   archived module and used its old manual writer to save a real receipt.
   Current code reads it and retries it unchanged with removed policy. A new
   criminal-topic cause uses that same latch and retains the original card;
   ACK followed by unsupported voice collection-stop creates the reserved second
   cause, blocks collection and preserves the frozen card. Old exact retry still
   returns the identical receipt, and the archived v1 validator still accepts the
   registry. One stop/two causes, no automated callback.
2. Four parametrized raw corruption probes recompute the outer receipt hash after
   changing delegated actor, effect, reason or second-row previous hash. Each is
   rejected despite the recomputed hash; native GET returns controlled no-store503
   without rendering causes. Existing latch suppresses. Restoring the original
   document/hash restores both exact receipts and current collection block.
3. Oversized valid JSON cause is refused by the SQL registry bound before the
   cause decode/validation path is reached. Original retry works after restoration;
   the existing latch continues to suppress throughout.

No auditor test process remains; the PostgreSQL slot has been released.

## Compatibility, separate evidence and preserved original failure

Independent byte comparison confirms unchanged retained interview module/reducer,
channel policy, guard, orchestrator and outbound sender. Whole-function AST
comparison of channel service identifies exactly three modified functions:
`_context` (optional timestamp, default unchanged), `list_stops` (validated cause
display), `bind_stop` (delegates its final block), plus the extracted save helper.
Registry validation, public receipt/command/payload and send algorithms are
unchanged. The actual archived-writer test above covers real historical records,
not a synthetic result relabeled as old runtime.

The separate reviewer reproduced a genuine R2 P1: oversized/voice/control-text
withdrawal after ACK was classified as ordinary uncertainty, left collection
unblocked and permitted an actual owner personal-data correction. Original
4PASS/3FAIL and additional1PASS/1FAIL artifacts remain visible. An intermediate
correction still missed collection-stop phrases without generic privacy keywords;
that source finding is also retained. Final R5 moves complete detection before
guards. The reviewer's corrected **17 PASS/41.24s** includes all original failures,
additional invisible/non-keyword cases, blocked owner correction, expiry after
Dialog wait, actual policy-expiry withdrawal, changed-body retry, unrelated
corrupt-cause negative lookup and combined interview/cause terminal reserve.

Builder evidence independently read in source and parsed from actual XML,
separately attributed rather than counted as auditor runs:

| Frozen artifact | Result and meaning |
|---|---|
| R5 `runs/e629-r5-domain-native.xml` | **134 PASS/73.56s**, pure RU/EN interruption, domain/native and old channel controls. |
| R5 `runs/e629-r5-pg.xml` | **14 PASS/60.45s**, actual PG both send/stop lock orders, retained card/withdrawal, all-three-write rollback, corruption recovery, reserve, migrated metadata/constraints and populated downgrade, before/after-commit lost-ACK exact retry. |
| R6 `runs/e629-r6-browser.xml` | **2 PASS/19.14s**, actual Chromium390px and1365px/no-JavaScript native causes with possible privacy hold, no raw message, overflow check and real PDF text/pages. |

These runs have zero failures/errors/skips. Earlier R2/R3 checks are historical
support, not replacements for final evidence or a whole-repository green claim.
Overlapping checks are not summed. Exact XML hashes are in the identity artifact.

The auditor independently viewed both screen artifacts and all four PDF page
rasters, and parsed the PDFs directly: each has **two nonblank pages**. Small-screen
labels, cause text, unchanged latch, possible-privacy/no-deletion caveats and
scope are readable; no clipping observed. This is independent artifact inspection,
not an auditor browser run. PDF hashes/text counts are recorded in
`runs/e6-29-audit-r5/runs/browser-pdf-inspection.json`. The existing page is RU-only;
these checks do not establish the parent's future RU/EN incoming conversation.

## Final gate and remaining parent scope

Final separate independent review is **APPROVE** in
`ai/reviews/2026-10-12-e6-29-domain-independent-review.md`, read after the
auditor's source assessment and independently verified at normalized-LF
SHA-256 `6cec190a29fe51bd7421396ce07afb144bf737b130a8be9a5c8b8a0e6bffde49`.
Its scope and evidence match the frozen R6 component and unchanged R5 runtime.
No confirmed component defect or required evidence remains open. **GO / DONE
for the agreed reviewed local E6-29A component**, with the parent's acceptance
explicitly retained below. This audit does not edit the score ledger.

**H02 remains UNKNOWN / PARTIALLY_READY.** There is no installed incoming hook,
meaningful normal typed-answer sequence, current lawful-until/calendar evaluator
or observed current-stay STOP12 bridge here. Returning `None` for an unassigned
route or closed greeting is not permission for generic LLM advice or collection.
Full H02 requires the unchanged parent task/pre-audit acceptance; this component
earns no H02 points. J01/J02/J03/J05, real assignments/privacy/legal/source/calendar
approval, shared-phone policy and production release remain outside this audit.
No deployment, live migration, channel activation or external message occurred.
