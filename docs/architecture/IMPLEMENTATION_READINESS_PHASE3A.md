# IMPLEMENTATION READINESS — Phase 3A

> Status: PHASE 3A IMPLEMENTATION READINESS — ACCEPTED
> IMPLEMENTATION NOT APPROVED
> Approved design baseline: 1630571f37b376077b107e390c6f8e58d867e2db (Phase 2 target design — architecturally approved)
> As-is code baseline: app/ is unchanged by the docs commits (identical to a4edd5a824db6842b668f61e50f418f75b555f99)
> Read-only analysis. No code, SQL, migrations, timelines, or rollout instructions. Implementation waits on team validation + owner/GPT-5.6 go.

Evidence tags: **[CODE-CONFIRMED]** read in code · **[RUNTIME-CONFIRMED]** production snapshot 2026-07-15 (earlier phases; not re-taken here) · **[VALIDATED-FACT]** confirmed team/owner fact · **[OWNER-DECISION-REQUIRED]** · **[OPEN]** awaiting team validation.

---

## Team facts (closed)
- Emergency **full-admin reassignment**: **Алан and Гриша** only (reason + immutable audit). `[VALIDATED-FACT]`
- Tour managers' move to Bitrix is **gradual** (not big-bang). `[VALIDATED-FACT]`
- Tour managers use **separate WhatsApp/Wappi numbers** (per-manager attribution feasible for tours). `[VALIDATED-FACT]`
- Visa direction uses **one shared number/bot** (two visa managers). Per-manager attribution on that number is not automatic — see Gap F / WP3. `[VALIDATED-FACT]`
- **Peer takeover forbidden**; only the pinned manager or a full-admin may return the bot. `[VALIDATED-FACT]`
- Visa managers reply **only in Bitrix**; FAQ/prices/visa terms published **only by Алан + Гриша**. `[VALIDATED-FACT]`

## Open team blockers (must close before Phase 3 implementation is approved)
1. Visa managers: **separate or shared Bitrix account?** (drives per-manager identity/authorization). `[OPEN]`
2. **Distribution rule** for a new visa client (who gets pinned, how). `[OPEN]`
3. **A separate test Bitrix Open Line** for safe contract testing. `[OPEN]`

## Owner-decision required (not team-validation blockers)
- **STT limits** (max duration / file size / languages). `[OWNER-DECISION-REQUIRED]`
- **Follow-up quiet hours** exact rules. `[OWNER-DECISION-REQUIRED]`

---

## 1. Current chat flows (actual code)

| Flow | Entry point | Functions / modules | DB/Redis state | External call | Missing step | Risk |
|---|---|---|---|---|---|---|
| WA inbound | `POST /webhook/wappi` `main.py:240` | `_verify_webhook:76` → `_seen_before:94` → `WappiAdapter.parse` → `orchestrator.handle:120` → `_log_in:314` → `store.add_message` → funnel | DialogState (Redis), Conversation+ConvMessage (PG) | — | durable inbox; Bitrix chat ingest | in-mem dedup, lost on restart |
| Bot outbound | `runner.run_turn:121` | LLM loop ≤6 → `validate_reply:165` (`validator.py:156`) → `_sync_card:367` → `_reply:338` → `outbound.send_to_client` → `bitrix_mirror.fire:356` | Conversation.stage/outcome via `_sync_card` | Wappi send; Bitrix `add_note` | post into Bitrix Open Line chat; blocking gate | validator mostly log-only |
| Admin outbound | `POST /admin/conversation/{id}/send` `router.py:859` | `require_admin` → `_require_visible_conversation` → auto-intercept `:869` → `store.add_message` → `outbound.send_to_client` → `mark_own` | Conversation, intercepted, assigned_to | Wappi send | Bitrix reflect; owner-vs-assignment check | assigned_to set unconditionally |
| Bitrix in/out | `POST /webhook/bitrix` `main.py:213` | `nest_form`→`bot_id_from_event`→`registry.by_bitrix_bot_id`→`BitrixOpenLinesAdapter.parse`→`handle`; out `bitrix_openlines.send` | — | Bitrix imbot | inbound inactive (bots lack `bitrix_bot_id`); no CRM won/lost ingest; no dedup | one-way only |
| Bitrix CRM mirror | `bitrix_mirror.fire:80` | `mirror_message:63`→`create_lead:46`/`add_note:83` | `Conversation.bitrix_lead_id` | Bitrix REST (Lead + comment) | two-way; retry; Open Line chat | fire-and-forget, no retry |
| Native WA manager echo | `_handle_manager_echo` `main.py:138` | `_seen_before`+`is_own`→`outgoing_echo_phone/text`→`add_message("manager")`→`assigned_to="whatsapp"`→`set_intercept(True)` | Conversation, intercepted | Bitrix mirror | manager identity = sentinel `"whatsapp"`, not a person | shared visa number → who sent? |

> No flow is asserted as production-working on code alone. Snapshot 2026-07-15: `/webhook/wappi` active, `/webhook/bitrix` = 0, mirror ON (1071 add_note) `[RUNTIME-CONFIRMED, not re-taken]`.

## 2. Exact sync gaps (code-level)

- **Gap A — bot message in WA+admin but not in Bitrix chat.** `bitrix_mirror.mirror_message:75` writes `add_note` (timeline comment on the LEAD), not the Open Line chat; `Bitrix24Crm.send` (imbot.message.add, `bitrix24.py:92`) is a stub. Fire-and-forget, no retry. Target: two-way sync into Open Line chat (§3/R3). **Severity HIGH** ("bot not visible").
- **Gap B — manager replies in Bitrix → client gets WA, admin blind.** 0 Bitrix inbound (bots lack `bitrix_bot_id`, `bots.py:17`); `_handle_manager_echo` is Wappi-only. No Bitrix operator ingestion. Target: R2. **Severity HIGH.**
- **Gap C — Bitrix has comment, not full Open Lines history.** add_note vs imbot.message.add(stub). **Severity MEDIUM.**
- **Gap D — one message reprocessed.** in-mem `_seen_wappi_ids` (`main.py:90-103`), Bitrix path has no `_seen_before`, per-process. Target: durable inbox (§12/R4). **Severity MEDIUM-HIGH.**
- **Gap E — bot state vs card status diverge.** `stage` in DialogState (bot authority) + Conversation; `_sync_card:367` writes state.stage→Conversation each turn; drag `set_stage:946` writes only Conversation → next turn overwrites. Target: single authority + manual>bot. **Severity HIGH.**
- **Gap F — shared visa number identity.** Visa `[VALIDATED-FACT]` shared number + pinned-ownership requires per-manager identity inside Bitrix (separate Bitrix accounts). Without it: team-level attribution + post-hoc audit only (finding M-a). **Severity HIGH for the pinning rule.** Depends on open blocker #1.

## 3. As-is → target component map

| Current component | Current responsibility | Target responsibility | Reuse/adapt/replace | Main risk |
|---|---|---|---|---|
| `Conversation` (`db.py:52`) | lead+chat+one funnel in one row | split into Contact / Request / Dialog | adapt | ambiguous Request derive |
| `DialogState` (`state.py`) | bot state + history | bot/dialog mode (not business state) | reuse+narrow | keep business status out of Redis |
| `assigned_to`/`intercepted` | soft ownership | Assignment (hard, versioned, history) | replace | migrate owners without loss |
| local `Deal` (`db.py:32`) | near-unused mirror | external Bitrix Deal mapping (ref) | replace | don't trust old Deal |
| message storage (`ConvMessage`) | panel log | canonical message hub | adapt+extend | source/idempotency fields |
| dedup (`_seen_wappi_ids`) | in-mem, Wappi-only | durable inbox | replace | cover Bitrix+restart+workers |
| direct outbound (`outbound.send_to_client`) | direct call | durable outbox + idempotency | wrap/replace | double send on retry |
| one-way mirror (`bitrix_mirror.py`) | Lead+comments | bidirectional sync (Open Line chat) | replace | loops/echo |
| validator (`validator.py:156`) | mostly log, 2 block rules | blocking fact-safety gate | adapt→enforce | don't rewrite manager |
| `_handle_manager_echo` (`main.py:138`) | Wappi echo → sentinel owner | authorized manager ingest (identity) | adapt | shared-number identity |

## 4. Implementation work packages (conceptual; no code/timelines)

| Package | Goal | Depends on | Existing code affected | Acceptance invariants | Main risks | Team/owner decision | Size |
|---|---|---|---|---|---|---|---|
| **WP0** Observability + test/network guard | correlation-id, durable usage/health, test socket-guard | — | `observ.py`, `main.py`, `tests/` | no network in tests; every reply traceable | low | — | S |
| **WP1** Contact/Request/Dialog/Assignment foundation | new entities beside old | WP0 | `db.py`, `store.py`, `state.py` | one active Request per Contact+direction; Contact≠bot_id | derive ambiguity | visa distribution rule (open #2) | L |
| **WP2** Canonical messages + durable inbox/outbox | single message hub, at-most-once | WP1 | `main.py`, `store.py`, `outbound.py` | duplicate inbound once; no retry-dup | message migration | — | L |
| **WP3** Assignment authorization | pre-send auth on all surfaces | WP1 | `admin/router.py`, `main.py`, `intercept.py` | wrong manager can't send; old manager can't send after reassign | shared-number identity | separate Bitrix accounts (open #1); full-admin = Алан+Гриша (closed) | M |
| **WP6** Blocking fact-safety gate | block unverified facts | WP2 | `validator.py`, `runner.py` | unverified price blocked; FAQ passes contract; manager untouched | false blocks | price truth sources | M |
| **WP4** Bitrix bidirectional chat sync | Open Line imbot in/out, anti-loop | WP2, WP3 | `bitrix_openlines.py`, `bitrix_mirror.py`, `main.py`, Bitrix portal | msg from any surface visible in 3; echo not looped | loops; portal event shape | test Open Line (open #3); gradual tour move (closed) | XL |
| **WP5** Deal ingestion + confirmed sales | read won/lost back, correlation | WP1, WP4 | `bitrix24.py`, new ingest | Deal won once; won≠visa/payment | late/dup/manual events | Bitrix mapping field | L |
| **WP7** Follow-up engine | 2 touches + refusal detector | WP1, WP3 | `followup.py`, `leadstate.py`, `branding.py` | ≤2 follow-ups; refusal stops | detector quality | quiet hours (OWNER-DECISION-REQUIRED) | M |
| **WP8** Attribution | touch-history, confidence, raw payload | WP1, WP5 | `wappi.py`, `store.py` | keyword not over verified; conversion after Deal | live CTWA format | schema discovery | M |
| **WP9** STT | separate one-shot STT, untrusted | WP2 | `orchestrator.py` non-text, new service | low-confidence can't change status; ≤1 transcription | limits/cost | limits (OWNER-DECISION-REQUIRED) | M |
| **WP10** Admin UX | dialog owner, manual status, confirmations | WP1, WP3 | `admin/router.py`, templates | drag not overwritten; owner visible | retraining | workplace #1 | L |

## 5. Recommended dependency order (safe, additive; no rollout plan)

Principle: current bot keeps working; observability + new structures first; no data deletion; feature-flagged; Bitrix sync verified on a test line; gradual; rollback = flag off; no big-bang.

**WP0 → WP1 → WP2 → WP3 → WP6 → WP4 → WP5**, then **WP7 / WP8 / WP9 / WP10** by the owner-approved priorities (decision #10: CTWA + STT prioritized; scaling deferred).

- **WP6 before WP4:** the blocking fact-safety gate is applied to outbound in the hub before the two-way Bitrix chat sync widens the surfaces on which bot messages appear.
- **WP5 may be prepared architecturally in parallel with WP4** once a stable **Request↔Bitrix Deal mapping** exists (the mapping is the shared prerequisite; Deal ingestion logic can be built while the chat sync stabilizes).
- Each WP: feature flag, backward compatible, rollback = disable flag. `Conversation/DialogState/Deal` are extended, not deleted.

## 6. Acceptance test catalog

- **Unit:** one active Request per Contact+direction; manual status not overwritten by AI; ≤2 follow-ups; refusal stops follow-up; unverified price blocked; deterministic FAQ passes outbound safety contract; low-confidence STT cannot change business state; wrong-manager rejected (where pre-send available).
- **Integration:** duplicate WA webhook once; bot message → WA+admin+Bitrix; admin reply → Bitrix+WA; old manager can't send after reassignment; Deal won recorded once.
- **Contract:** Bitrix manager reply → admin+WA (Open Line imbot shape); Bitrix echo not looped; Deal event dedup/idempotency; Wappi CTWA payload schema.
- **End-to-end:** visa+tour Request coexist; full cross-surface round-trip; Deal won ≠ visa approved / full payment surfaced correctly.
- **Migration:** Contact from phone; Request from funnel; assigned_to→Assignment; bitrix_lead_id→external ref; ambiguous rows quarantined.
- **Failure-injection:** Bitrix/Wappi/OpenRouter/TourVisor/Redis/PG unavailable; restart (pending outbox survives); reassignment during send; Deal-won-before-mapping; ambiguous Contact; simultaneous bot/manager send; provider send OK but ack lost.

≈ 30+ tests; priority on the 6 contract + failure-injection cases.

## 7. Data migration inventory (no migrations created)

| Current data | Target entity | Confidence | Ambiguity | Manual review |
|---|---|---|---|---|
| `Conversation.phone`/`user_id` | Contact (normalized phone) | High | missing country / dupes | on merge |
| `Conversation.funnel`+`bot_id` | Request.direction + initial Request | Medium | empty/changed funnel | yes if empty |
| `ConvMessage.*` | canonical Message | High | empty provider_msg_id on old rows | no |
| `assigned_to`/`intercepted` | Assignment + bot/dialog mode | Medium | sentinel `"whatsapp"` ≠ person | yes |
| `bitrix_lead_id` (364/1074) | external Bitrix Lead ref | High | empty for ~66% | no |
| local `Deal` (135) | NOT a trusted source | Low | near-unused | do not migrate as truth |
| two funnels for one phone | 2 Requests (visa+tour) | High | one row currently overwritten | yes on direction conflict |
| prod image older than HEAD | baseline risk | — | what actually runs in prod | verify by markers |

## 8. Open questions summary
See **Open team blockers** (3) and **Owner-decision required** (2) at the top. No assumptions were made in place of a team answer.

## 9. Final report
- **Inspected commit:** `1630571…` (app/ identical to `a4edd5a`).
- **Inspected modules:** `main.py`, `orchestrator.py`, `runner.py`, `validator.py`, `intercept.py`, `wappi.py`, `bitrix_openlines.py`, `bitrix_mirror.py`, `bitrix24.py`, `state.py`, `store.py`, `db.py`, `followup.py`.
- **Chat flows:** 6 documented. **Top gaps:** A/B/E/F HIGH, D MED-HIGH, C MED.
- **Work packages:** WP0–WP10 (S–XL). **Order:** WP0→WP1→WP2→WP3→WP6→WP4→WP5, then WP7-10.
- **Acceptance tests:** ≈30+ in 6 categories. **Migration ambiguities:** Request derive, sentinel-owner, funnel overwrite, old Deal.
- **Team-validation blockers:** 3 open (Bitrix accounts, distribution, test Open Line). **Owner decisions:** STT limits, quiet hours.
- **Assumptions made:** none.

This is an accepted readiness analysis. It is NOT an implementation plan and NOT approval to write code, migrate, or roll out. Implementation waits on team validation (#1/#4/#8), the open blockers above, and an explicit owner/GPT-5.6 go.
