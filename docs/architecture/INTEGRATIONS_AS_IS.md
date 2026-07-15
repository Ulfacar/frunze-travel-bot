# INTEGRATIONS AS-IS — Provisional

> Status: PROVISIONAL AS-IS
> Repository baseline: a4edd5a824db6842b668f61e50f418f75b555f99
> Production snapshot: 2026-07-15T23:25–23:28Z
> Production image: sha256:1be488a9ca8e…
> Exact production source commit: UNKNOWN
> This document describes current state and does not approve target implementation.

Runtime status reflects flags/env observed at the snapshot; it does not claim message delivery.

| Integration | Direction | Runtime status | Authentication | Dedup | Idempotency | Timeout | Retry | Failure handling |
|---|---|---|---|---|---|---|---|---|
| Wappi inbound | in | active channel (`/webhook/wappi` receives traffic) `[RUNTIME-CONFIRMED]` | `?s=<secret>`/header; **empty secret → verification off** | in-memory `raw["id"]` (OrderedDict cap 2000) | n/a | — | — | filter/`continue`; silent on drop |
| Wappi outbound | out | credentials present `[RUNTIME-CONFIRMED]` | account token | provider_msg_id / idempotency_key columns | **no durable idempotency** | 20s | **none** | `record_failure("send")`, message `failed` |
| Telegram | in/out | 2 sandbox bots configured; **0 webhook events in window** `[RUNTIME-CONFIRMED]` (may run via polling) | webhook secret header | none explicit | n/a | — | none | fallback |
| Bitrix Open Lines | in/out | **inactive as inbound** (`/webhook/bitrix` = 0 in window) `[RUNTIME-CONFIRMED]`; bots carry no bitrix mapping | webhook secret | **none** | n/a | 20s (send) | none | 200/log |
| Bitrix CRM mirror | out (one-way) | **enabled** (`bitrix_mirror_enabled=true`); add_note activity observed `[RUNTIME-CONFIRMED]` | webhook URL | phone (`findbycomm`) + per-key lock | n/a | httpx client | **none** (fire-and-forget) | log warning only |
| TourVisor | out | credentials present `[RUNTIME-CONFIRMED]`; call volume not measurable from logs | login/pass in query | requestid | n/a | search 30s / poll 20s | 1 functional (over-budget re-search) | friendly fallback string |
| OpenRouter | out | key present; `llm_usage` lines observed `[RUNTIME-CONFIRMED]`; models overridden | API key | — | n/a | 60s | **none** | `LLM_ERROR_FALLBACK` reply |

## Mandatory clarifications

- **Wappi webhook requests ≠ user messages.** `POST /webhook/wappi` counts include echoes, delivery-status events, group/reaction events, and retries — not one-per-client-message `[CODE-CONFIRMED]`.
- **Wappi dedup is in-memory** (`_seen_wappi_ids`, cap 2000, lost on restart) `[CODE-CONFIRMED]`.
- **Bitrix Open Lines dedup is absent** — a re-delivered `/webhook/bitrix` event would be reprocessed `[CODE-CONFIRMED]`.
- **No durable outbound idempotency** — an `idempotency_key` column exists but there is no durable send-once guarantee across restarts `[CODE-CONFIRMED]`.
- **No durable outbox** — outbound is a direct channel call plus a manual resend button `[CODE-CONFIRMED]`.
- **Successful Wappi/TourVisor operations are not fully measured** — success paths are not log-instrumented per call, so call volumes/success rates are not derivable from logs `[CODE-CONFIRMED]`.
- **Zero matching failure log lines does not prove zero actual failures** — it means no matching lines were found in the observed window `[RUNTIME-CONFIRMED]`.
- **Bitrix mirror is one-directional** (bot → Bitrix Lead + timeline comments) `[CODE-CONFIRMED]`.
- **CRM won/lost are not read back** — there is no Bitrix ingestion path `[CODE-CONFIRMED]` + `[RUNTIME-CONFIRMED, 0 inbound]`.
