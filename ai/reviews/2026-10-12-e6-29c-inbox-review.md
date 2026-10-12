# E6-29C — independent focused inbox review

**Final scoped verdict: APPROVE for the R11 incoming-inbox seam, based on source review and independent synthetic SQLite/native checks. R8 was FIX_REQUIRED.** The confirmed mutable-projection and displayed-phone defects are corrected. This review covers incoming-text persistence and its consent/identity/recovery boundaries only. It does not approve the whole C integration, H02, deployment, actual retention authority or external delivery. Actual PostgreSQL concurrency/recovery and the separate final audit remain requirements of the broader C integration.

Reviewer: `/root/publication_review`, independent of implementation. Requirements and actual code examined before builder test conclusions. Task: `ai/tasks/2026-10-12-e6-29c-incoming-dialogue.md`; acceptance: the inbox addendum in `ai/reviews/2026-10-12-e6-29-pre-audit.md`.

## Identity and environment

Frozen `runs/e6-29c-r8`, base `6775d30be496335fc0aad10f6d18e6debc98da25`,38 LF-normalized overlays all independently verified. Manifest raw SHA256: `332a1aca5a02e2278c86a9772ca239dd510d2785932b73f7e5f9060fbf2ca484`. Own clean archive: `runs/e629c-inbox-review-r8`, constructed from `git archive` of that exact base plus verified overlays, with no `.env`. Runtime/source/test originals and the builder archive were not modified.

Key R8 source identities:

| File | LF SHA256 |
|---|---|
| `app/domain/dialogue_inbox.py` | `b9eb3404d073ad29cd9849d638691550b04419c97403795db607a352122b1302` |
| `app/domain/dialogue_sessions.py` | `bec7192c4b26ab576fddf666eb2ec3e39e0451c2d4316e8d896109b2dcb760db` |
| `app/domain/dialogue_journal.py` | `e446dd9fa16c6edeb42b0cd2a817e3b4899ef3726e7de1074c4188b869aea2b8` |
| `app/core/kg_dialogue.py` | `9fbcddc781abc24748da2bd3399c353c381b0f6b1c2eac2f905a23a2ff8c3410` |

No PostgreSQL suite, provider call, production connection, actual message or real source/privacy approval was used by this focused review. Tests use synthetic authorities and the repository network guard; connected tests use an in-process mock HTTP provider.

## Confirmed source finding

**P1 — mutable inbox availability blocks retained privacy processing.** `dialogue_journal.history:298–299` always calls `dialogue_inbox.verify`. The latter raises when a recorded message or its conversation is missing, changed or moved. `receive:177` calls this history before its privacy branch, and `_stop` calls it again. Thus removal of a display-only raw row prevents appending the operational withdrawal and C terminal event, although the immutable interview/session chain remains valid. The managed hook consumes the error and prevents legacy advice; that does **not** establish that interview collection was blocked. Historical retry, read and outcome recording inherit the same unnecessary dependency.

The requirement expressly allows a missing display projection without reconstructing raw text and prohibits making permanent raw retention necessary for C history validity. R11 retains strict C receipt/chain validation while exposing projection availability separately. It never backfills the original raw message on retry. Current raw-insert identity validation remains, while missing mutable content no longer supplies authority for the retained privacy operation. The combined independent R11 probe below confirms modified and deleted raw content and a deleted conversation do not prevent privacy, history, native read or exact retry.

## Additional findings and their R11 disposition

- R8 saves non-privacy text whenever `_collection` passes, even for non-text/voice or unsupported control text subsequently routed to a specialist. R11 restricts retention to plain text, no voice/failed voice, at most2048 characters and no unsupported Unicode control categories; it retains only a reason otherwise. The independent NUL-body probe confirms a durable specialist stop and exact retry with no raw row and no delivery claim. A PostgreSQL NUL reproduction was not run; the corrected input never reaches raw SQL insertion.
- **P2, independently reproduced and corrected:** R8 does not compare `Conversation.phone`, although the existing panel card prefers it as the displayed identity. `test_foreign_display_phone_is_not_accepted_as_bound_inbox` fails: a real permitted input bound to synthetic recipient `996700000001` is saved and read through `PostgresConversationStore` with displayed phone `19999999999`. R11 rejects mismatched identity into a minimal specialist stop. It also narrowly translates a malformed stored phone/chat recipient to that conflict. The final own probe covers a malformed phone through the real composer and subsequent privacy processing.
- C writes SQL inbox tables; the actual visible panel defaults to memory. R11 explicitly requires `panel_backend=postgres` for ordinary collection admission. The own final test reads the real configured `get_conversation_store` and later removes that backend before requesting privacy: the retained operational hold still commits. No memory fallback is presented as durable persistence.
- R11's immutable turn validator requires a privacy interrupt to carry the exact minimal non-retained receipt. Physical raw availability remains separate from this semantic check. Code inspection PASS; no extra forged-row probe was claimed here.

## Positive source assessment

The narrow helper reuses existing `Conversation/ConvMessage` and only performs SQL operations; it does not invoke legacy `_log_in`, mirror bridges, autoassignment, provider calls or notification code. It flushes through the caller's transaction. Current route→case→Dialog locks are acquired before inbox insertion. C's exact incoming key includes the captured full route and provider ID; the dedicated namespace has no other runtime writer. Original turn dedup occurs before save, so the serialized C path does not rely on the legacy non-unique idempotency index for concurrent admission. An orphan/foreign projection conflicts instead of being adopted. Long provider display IDs become empty, while the full identity remains hashed; there is no identity truncation.

New ordinary inbox rows correctly remain client/incoming records; they do not claim an answer or provider acceptance. Privacy raw is omitted. Save plus turn/interview append shares one transaction, giving a coherent rollback boundary. Actual PostgreSQL race evidence remains for the broader independent C review; source inspection is not presented as such evidence.

## Completed R8 verification and R11 correction target

Completed in the clean R8 archive: `python -m pytest tests/test_reviewer_inbox_seam.py tests/test_dialogue_sessions.py::test_inbox_and_turn_commit_together_no_retry_backfill_and_no_orphan_on_failure tests/test_kg_dialogue_connected.py -q --disable-warnings --maxfail=3 --junitxml=runs/reviewer-inbox-r8.xml` — **8 PASS / 1 FAIL**,1106.09s. Persistent result: `runs/e629c-inbox-review-r8/runs/reviewer-inbox-r8.xml`. The sole failure is the mismatched displayed phone above, not a harness failure.

Own passing probes cover a read through the existing panel store, wrong-chat/channel atomic rejection, changed-body conflict and duplicate after privacy, and route-scoped incoming identity. Selected existing checks pass for fault rollback/long provider ID and actual installed RU/EN webhook flows with mocked provider responses. These are exact R8 results, not a claim that the later whole C runtime passed this suite.

R11 final correction target: `runs/e6-29c-r11`, same base,40 overlays independently verified. Manifest raw SHA256 `45eee047fa8265550f0c529dbf52937f0a4b884ca5244f468a72a7456c3e056f`; own env-free Git archive `runs/e629c-inbox-review-r11`. Source-first review confirms: mutable raw availability is read separately from immutable history; privacy requires a non-retained receipt; raw retention excludes media/voice/failed voice/control/oversize input; ordinary authority requires the persistent panel backend; mismatched or malformed stored inbox identity produces a minimal stop. Existing C receipt and raw insertion remain atomic. The broader causal/time/guard corrections in R11 are outside this focused approval.

Completed serially after R8: `python -m pytest tests/test_reviewer_inbox_correction.py -q --disable-warnings --junitxml=runs/reviewer-inbox-r11.xml` — **2 PASS**,204.23s; no failures, errors or skips. Persistent result: `runs/e629c-inbox-review-r11/runs/reviewer-inbox-r11.xml`. The first combines the configured panel reader, modified/deleted raw rows and conversation, malformed display phone, backend/authority removal, retained privacy and native history/read/retry without backfill. The second confirms NUL text commits only a minimal cause with no raw or delivery. These are two multi-step scenarios, not an inflated sum of assertions.

R11 source identities independently rechecked after testing:

| File | LF SHA256 |
|---|---|
| `app/domain/dialogue_inbox.py` | `1a4f8667409b85f70f1e203bbc31dd60dde91704e90d619c586fd5d56b4f5934` |
| `app/domain/dialogue_sessions.py` | `ab535369b3bdcecbf0b9979afb28ce0ed0bf5d4a1b96975a42909b8894441bf2` |
| `app/domain/dialogue_journal.py` | `3664ead734cc030d11673a492a53140cbfd154d138b4296d8cdfbb5aff5b6d93` |
| `app/core/kg_dialogue.py` | `5a77e1f2cda9d4f0a534931d6aca65fd54d1fe9b197f0d7a7f9569305114cbaf` |

Evidence index: `runs/e629c-inbox-review-r11/review-evidence.json`, SHA256 `1d7f886ae85bfcd6c02b1169c7a68ff514f230e93284c317bea2752fbfbf54c8`. It records both JUnit identities, exact case IDs, own probe identity and all40 unchanged runtime-overlay checks. Earlier R8 passing outcomes are retained as baseline evidence; they are not relabeled as a complete R11 run. The broader R11 causal/time/transport-error changes, actual PostgreSQL races, browser rendering and owner source/privacy decisions are outside this focused verdict.
