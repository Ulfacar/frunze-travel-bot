# RUNTIME SNAPSHOT — 2026-07-15 (Provisional)

> Status: PROVISIONAL AS-IS
> Repository baseline: a4edd5a824db6842b668f61e50f418f75b555f99
> Production snapshot: 2026-07-15T23:25–23:28Z
> Production image: sha256:1be488a9ca8e…
> Exact production source commit: UNKNOWN
> This document describes current state and does not approve target implementation.

All facts here are `[RUNTIME-CONFIRMED]` at the snapshot unless marked otherwise. Method: read-only SSH (`docker inspect`/`logs`, `psql` SELECT aggregates, `redis-cli INFO`/`DBSIZE`/`--scan|wc`, env classification). No secret values, phones, texts, or referral values were read.

## Containers / image

- App image built `2026-07-11T20:53:59Z`; container started `2026-07-11T20:54:02Z`; uptime ~4 days; health `healthy`.
- App containers: **1**. uvicorn command: `uvicorn app.main:app --host 0.0.0.0 --port 8000` (no `--workers`).
- Postgres `16.14` (up ~11 days); Redis `7.4.9` AOF enabled (up ~11 days).

## Database (aggregate counts, no rows read)

| Table | Count |
|---|---|
| conversations | 1074 |
| messages | 9337 |
| deals | 135 |
| audit_log | 797 |
| faq_entries | 20 |
| app_flags | 9 |

- FK: `messages → conversations`. Index counts: conversations 3, faq_entries 4, deals/audit_log/messages 2, app_flags 1.
- `conversations` with `bitrix_lead_id` set: **364 / 1074**.
- Manual `outcome` distribution: won **2**, office 35, manager 55, in_progress 359, none 623.
  - Note: `outcome` is an internal system field, set by managers inconsistently and rarely. `won=2` must **not** be read as a conversion rate, and the field is **not a reliable measure of actual sales**. Real outcomes may be recorded outside this system, including in Bitrix. `[RUNTIME-CONFIRMED]` / `[BUSINESS-UNCONFIRMED]`
- Advisory `outcome_inferred` (flag ON): active 539, none 464, ghosted 33, lost 31, won 7.
- intercepted 196; assigned 196; archived 586.

## Redis

- DBSIZE (total keys): **104**. `frunze:dialog:*` key count: **101** (values not read).

## App flags (key = value)

- bots_enabled = false (global); bots_enabled:frunze_tours = true; bots_enabled:frunze_tours_sezim = false; bots_enabled:getvisa = false; bots_enabled:frunze_tours_tg = true; bots_enabled:getvisa_tg = true.
- bitrix_mirror_enabled = true; outcome_infer_enabled = true; followup_enabled = false.
- Absent (⇒ code defaults): dozhim_enabled (false), morning_brief_enabled (false), alerts_enabled (true), readiness_rescore_enabled (true).

## Bot registry (no secret mapping values)

- 3 bots: `frunze_tours` (tours), `frunze_tours_sezim` (tours), `getvisa` (visa) — each has a Wappi mapping present, Bitrix mapping absent.
- 2 Telegram sandbox bots: `frunze_tours_tg` (tours), `getvisa_tg` (visa).
- Managers: 6 (1 admin).

## Integration log counts

- Observation window: **2026-07-11T20:54:12Z → 2026-07-15T23:28:50Z** (~4.1 days).
- Source: container `docker` json-file logs (since container start; older lines may be rotated). Lines: 38,536.

| Metric | Count |
|---|---|
| Wappi webhook HTTP requests (`POST /webhook/wappi`) | 5062 |
| Bitrix webhook HTTP requests (`POST /webhook/bitrix`) | 0 |
| Telegram webhook HTTP requests | 0 |
| OpenRouter calls (`llm_usage` lines) | 2223 |
| Bitrix mirror `add_note` attempts | 1071 |
| Bitrix mirror matching failure log lines | 1 |
| TourVisor warning/error log lines | 0 |
| OpenRouter matching failure log lines | 0 |
| Outbound send matching failure log lines | 0 |

- Note: `Wappi webhook HTTP requests` are not equal to `Wappi client messages`.
- Note: `No matching failure log lines found` is not the same as `zero actual failures`.

## CTWA (Click-to-WhatsApp) evidence

```text
No successful referral capture was found.
Four referral-miss diagnostics were observed.
The cause is not established.
Possible causes include parser mismatch, provider transformation,
missing upstream referral data, or non-CTWA diagnostic triggers.
```

- No captured referral metadata was found for the 1074 Conversation records.

## Limitations

- Successful Wappi/TourVisor operations are not per-call log-instrumented → volumes/success rates not derivable.
- Log window bounded to current container lifetime.
- Secret values, LLM model values, and any PII were intentionally not read.
