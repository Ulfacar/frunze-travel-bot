# STATE OWNERSHIP MATRIX — Provisional

> Status: PROVISIONAL AS-IS
> Repository baseline: a4edd5a824db6842b668f61e50f418f75b555f99
> Production snapshot: 2026-07-15T23:25–23:28Z
> Production image: sha256:1be488a9ca8e…
> Exact production source commit: UNKNOWN
> This document describes current state and does not approve target implementation.

Stores: **DS** = DialogState (Redis, 7-day TTL) · **CV** = Conversation (Postgres panel) · **DEAL** = Deal (Postgres) · **BX** = Bitrix (external, write-only). All `[CODE-CONFIRMED]` unless noted.

| State | Store(s) | Writers (file) | Readers | Manual override behavior | Restart behavior | Multi-worker risk |
|---|---|---|---|---|---|---|
| stage | DS (authoritative) + CV + DEAL | runner (DS), `_sync_card` orchestrator.py:367 (CV), `set_stage` router.py:946 (CV only) | orchestrator, board | **drag writes CV only; bot re-syncs DS→CV → overwrites drag** | DS survives (Redis 7d); CV survives (PG) | in-proc lock only → cross-worker race |
| intercepted | DS + CV | `set_intercept` intercept.py:8, auto-handoff orchestrator.py:271 | `_run_turn` gate | manual takeover sets it; not a business-status change | survives | set on one worker invisible to another |
| assigned_to | CV | `takeover`/`send`/`buyers_claim` router.py | board, filters | takeover/send set unconditionally; only claim() is atomic | survives | two managers can stomp (except claim path) |
| outcome | CV | `set_outcome` router.py:959 (manual), `_auto_outcome` (auto in `_sync_card`) | analytics, board | manual won/lost protected from auto-downgrade | survives | low |
| outcome_inferred | CV | `outcome_infer` job | analytics | never overwrites manual outcome | survives | double LLM spend if scaled |
| readiness_tier | CV | `compute_readiness` (sync), `rescore` job | buyers/morning | — | survives | double rescore if scaled |
| manager_next_step | CV | `build_manager_brief` via `_sync_card` | chat card | — | survives | low |
| escalation_reason | CV | `build_manager_brief` via `_sync_card` | chat card | — | survives | low |
| followup_count | CV | `followup` job | followup gate | — | survives (DB-backed) | double followup if scaled |
| last_message_at | CV | `add_message` (explicit) | activity/analytics | no onupdate (sweeps don't bump) | survives | low |
| qualification | DS + CV | runner (DS), `_sync_card` (CV) | prompt facts, card | overwritten by new topic on same key | survives | race |
| funnel | DS + CV + DEAL | bot scenario → DS, `_sync_card` → CV | routing, board | fixed per bot; overwritten by new topic | survives | low |

## Proven problem — Kanban drag overwrite `[CODE-CONFIRMED]`

```text
Kanban drag  (POST /conversation/{id}/stage → set_stage, router.py:946)
→ Conversation.stage updated   (update_meta(stage=target) — PANEL store only)
→ DialogState.stage unchanged  (Redis authoritative value untouched)
→ next inbound message
→ _sync_card copies DialogState.stage  (orchestrator.py:372: update_meta(stage=state.stage, ...))
→ manual Conversation.stage overwritten
```

- `set_stage` writes only the panel `Conversation.stage` (+ audit); it does not touch `DialogState.stage`.
- On the next bot turn, `_sync_card` writes `DialogState.stage` back into `Conversation.stage`, replacing the manual value.
- There is no optimistic lock or transactional protection across the two stores.
- This document does **not** propose a fix.

## Flag resolution — RESOLVED `[CODE-CONFIRMED]`

Function: `Orchestrator._bots_on` (`app/core/orchestrator.py:108-118`).

```text
global_on = get_flag("bots_enabled", True)          # code default True
if bot_id:
    return get_flag(f"bots_enabled:{bot_id}", global_on)   # per-bot key overrides; falls back to global
return global_on
```

- Precedence is **proven**: a per-bot `bots_enabled:<bot_id>` value takes priority; if that key is absent, the bot inherits the global `bots_enabled`.
- Applied to runtime flags `[RUNTIME-CONFIRMED, 2026-07-15T23:25Z]` (global `bots_enabled=false`):
  - `frunze_tours` → per-bot `true` ⇒ auto-reply ON
  - `frunze_tours_sezim` → per-bot `false` ⇒ OFF
  - `getvisa` → per-bot `false` ⇒ OFF
  - `frunze_tours_tg` → per-bot `true` ⇒ ON
  - `getvisa_tg` → per-bot `true` ⇒ ON
- Note: this reflects the flag gate only. Whether a given bot delivers messages also depends on channel wiring and other runtime conditions not asserted here.
